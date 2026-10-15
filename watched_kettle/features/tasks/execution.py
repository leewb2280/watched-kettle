"""Queue-owned turn execution with durable reservation and no blind retries."""

from __future__ import annotations

import time

from PySide6.QtCore import QObject, QTimer, Signal

from watched_kettle.features.tasks.completion import (
    evaluate_completion,
    verify_artifacts,
    Verdict,
)
from watched_kettle.features.tasks.models import TaskState, source_version
from watched_kettle.features.tasks.history import HistoryReader
from watched_kettle.features.tasks.scheduling import (
    allocate,
    ExecutionScope,
    resolve_lock_keys,
)


class QueueExecutor(QObject):
    changed = Signal()
    user_request = Signal(object)
    scope_refresh_requested = Signal()

    def __init__(
        self,
        repository,
        client,
        parent=None,
        *,
        clock=time.monotonic,
        history_reader=None,
    ):
        super().__init__(parent)
        self.repository, self.client, self.clock = repository, client, clock
        self.enabled_batches = set()
        self.continuous_projects = set()
        self.continuous_excluded = set()
        self.paused_projects = set()
        self.paused = True
        self.limit = 2
        self.scope = ExecutionScope(False, 0)
        self.scope_at = 0.0
        self.last_served = {}
        self.pending = {}
        self.requests = {}
        self.request_details = {}
        self.reasons = {}
        self.terminal_turns = {}
        self.expected_turns: dict[str, set[str]] = {}
        self.dispatch_versions = {}
        self.connection_epoch = 0
        self._dispatching = set()
        self.early_requests = []
        self.stop_requested = set()
        self.interrupt_retries = set()
        self.history_reader = (
            HistoryReader(client, self) if history_reader is None else history_reader
        )
        self.history_queue = []
        self.history_current = None
        self.history_serial = 0
        self.waiting_preflights = {}
        self.recovery_required = False
        if self.history_reader:
            self.history_reader.completed.connect(self._history_complete)
            self.history_reader.failed.connect(self._history_failed)
        client.response_received.connect(self.response)
        client.notification_received.connect(self.notification)
        client.ready_changed.connect(self.connection_changed)
        client.server_request_received.connect(self.server_request)

    def connection_changed(self, _ready):
        self.connection_epoch += 1
        self.paused = True
        self.scope = ExecutionScope(False, 0)
        self.pending.clear()
        self.requests.clear()
        self.request_details.clear()
        self._dispatching.clear()
        self.early_requests.clear()
        self.terminal_turns.clear()
        self.expected_turns.clear()
        self.dispatch_versions.clear()
        self.enabled_batches.clear()
        self.continuous_projects.clear()
        self.continuous_excluded.clear()
        self.stop_requested.clear()
        self.interrupt_retries.clear()
        self.history_queue.clear()
        self.history_current = None
        self.waiting_preflights.clear()
        self.recovery_required = True
        if self.history_reader:
            self.history_reader.cancel()
        if self.repository.account_key:
            self.repository.mark_interrupted()
        self.changed.emit()

    def _save_session(self):
        if self.recovery_required:
            return
        preferences = self.repository.preferences()
        preferences["execution_session"] = {
            "batches": sorted(self.enabled_batches),
            "continuous_projects": sorted(self.continuous_projects),
            "excluded": sorted(self.continuous_excluded),
            "limit": self.limit,
        }
        self.repository.save_preferences(preferences)

    def _restore_session(self):
        items = self.repository.list_items()
        if any(i.state in {TaskState.STARTING, TaskState.RECONCILING} for i in items):
            raise ValueError("reconciliation_required")
        value = self.repository.preferences().get("execution_session", {})
        available = {
            i.batch_id
            for i in items
            if i.batch_id
            and i.state != TaskState.COMPLETE
            and i.reason != "dismissed_by_user"
        }
        self.enabled_batches = set(value.get("batches", ())) & available
        self.continuous_projects = set(value.get("continuous_projects", ()))
        self.continuous_excluded = set(value.get("excluded", ()))
        self.limit = max(1, min(4, int(value.get("limit", 2))))
        self._restore_baselines(items)
        self.recovery_required = False

    def _restore_baselines(self, items):
        for predecessor in items:
            if not predecessor.attempt_id:
                continue
            receipt = self.repository.receipt(predecessor.attempt_id)
            context = receipt.get("execution_context", {})
            if not context:
                continue
            self.dispatch_versions[predecessor.attempt_id] = context.get(
                "dispatch_version", ""
            )
            self.expected_turns.setdefault(predecessor.id, set()).update(
                context.get("excluded_turns", ())
            )
            if predecessor.state != TaskState.COMPLETE or not receipt.get("turn_id"):
                continue
            for item in items:
                if (
                    item.state == TaskState.QUEUED
                    and item.spec
                    and item.spec.thread_id == receipt.get("thread_id")
                    and item.spec.source_version
                    in {context.get("source_version"), context.get("dispatch_version")}
                ):
                    self.expected_turns.setdefault(item.id, set()).update(
                        [receipt["turn_id"], *context.get("excluded_turns", ())]
                    )

    def observe_scope(self, scope: ExecutionScope, *, observed_at=None):
        self.scope = scope
        self.scope_at = self.clock() if observed_at is None else observed_at
        if scope.reliable:
            waiting, self.waiting_preflights = self.waiting_preflights, {}
            for identity, (thread, locks, at) in waiting.items():
                if self.clock() - at <= 3:
                    self._preflight(identity, thread, locks)
                else:
                    self._request(
                        "preflight",
                        identity,
                        "thread/read",
                        {"threadId": thread["id"], "includeTurns": True},
                        locks,
                    )
        if not self.paused:
            self.pump()

    def start_batch(
        self, identities: list[str], *, continuous: bool = False, limit: int = 2
    ):
        if (
            not self.client.ready
            or not self.scope.reliable
            or self.clock() - self.scope_at > 3
        ):
            raise ValueError("execution_scope_unverified")
        if not 1 <= limit <= 4:
            raise ValueError("execution_limit_invalid")
        self.limit = limit
        self.recovery_required = False
        batch = self.repository.create_batch(identities)
        self.enabled_batches.add(batch)
        if continuous:
            self.continuous_excluded.update(
                item.id
                for item in self.repository.list_items()
                if item.id not in identities
            )
            for identity in identities:
                spec = self.repository.require(identity).spec
                if spec:
                    self.continuous_projects.add(spec.project_id or spec.cwd)
        self.paused = False
        self._save_session()
        self.pump()
        return batch

    def pump(self):
        if self.paused or not self.client.ready or self._dispatching:
            return
        if self.continuous_projects:
            additions = [
                item.id
                for item in self.repository.list_items()
                if item.id not in self.continuous_excluded
                and item.state == TaskState.QUEUED
                and not item.batch_id
                and item.spec
                and (item.spec.project_id or item.spec.cwd) in self.continuous_projects
            ]
            if additions:
                self.enabled_batches.add(self.repository.create_batch(additions))
                self._save_session()
        scope = self.scope
        if self.clock() - self.scope_at > 3:
            scope = ExecutionScope(False, scope.active_main_tasks)
        allocations, self.reasons = allocate(
            self.repository.list_items(),
            self.enabled_batches,
            self.paused_projects,
            scope,
            limit=self.limit,
            last_served=self.last_served,
        )
        for allocation in allocations:
            item = self.repository.require(allocation.task_id)
            if item.spec is None:
                continue
            self._dispatching.add(item.id)
            self._request(
                "preflight",
                item.id,
                "thread/read",
                {"threadId": item.spec.thread_id, "includeTurns": True},
                allocation.lock_keys,
            )
        self.changed.emit()

    def _request(self, kind, identity, method, params, extra=None):
        if self.history_reader and kind in {
            "preflight",
            "reconcile",
            "interrupt_check",
            "resume_check",
        }:
            entry = (kind, identity, extra)
            if entry != self.history_current and entry not in self.history_queue:
                self.history_queue.append(entry)
                self._drain_history()
            return
        rid = self.client.request(method, params)
        if rid is None:
            self._uncertain(identity, kind)
        else:
            self.pending[rid] = (self.connection_epoch, kind, identity, extra)

    def _drain_history(self):
        if not self.history_reader or self.history_current or not self.history_queue:
            return
        self.history_current = self.history_queue.pop(0)
        kind, identity, _extra = self.history_current
        item = (
            self.repository.get(identity)
            if kind == "preflight"
            else next(
                (i for i in self.repository.list_items() if i.attempt_id == identity),
                None,
            )
        )
        if item is None or item.spec is None:
            self._history_failed("", "execution_target_unavailable")
            return
        receipt = self.repository.receipt(identity) if kind != "preflight" else {}
        self.history_reader.start(
            item.spec.thread_id,
            excluded_turns=self.expected_turns.get(item.id, ()),
            evidence_turn_id=receipt.get("turn_id", ""),
            command_targets=[
                (c.target, item.spec.cwd)
                for c in item.spec.checks
                if c.kind == "command"
            ],
        )

    def _history_complete(self, thread):
        entry, self.history_current = self.history_current, None
        if entry is None:
            return
        kind, identity, extra = entry
        self.history_serial += 1
        token = ("history", self.history_serial)
        self.pending[token] = (self.connection_epoch, kind, identity, extra)
        thread["turns"] = (
            [thread["executionTurn"]] if thread.get("executionTurn") else []
        )
        self.response(token, "thread/read", {}, {"thread": thread}, None)
        QTimer.singleShot(0, self._drain_history)

    def _history_failed(self, _thread, _reason):
        entry, self.history_current = self.history_current, None
        if entry:
            self._uncertain(entry[1], entry[0])
            if entry[0] == "preflight":
                self.reasons[entry[1]] = "history_verification_failed"
            else:
                self.repository.update_attempt(
                    entry[1],
                    TaskState.NEEDS_REVIEW,
                    reason="history_verification_failed",
                )
            self.changed.emit()
        QTimer.singleShot(0, self._drain_history)

    def _uncertain(self, identity, kind):
        self.paused = True
        if kind == "preflight":
            self.reasons[identity] = "connection_unavailable"
            self._dispatching.discard(identity)
        else:
            try:
                self.repository.update_attempt(
                    identity, TaskState.RECONCILING, reason="execution_response_unknown"
                )
            except ValueError:
                pass
        self.changed.emit()

    def response(self, rid, _method, _params, result, error):
        pending = self.pending.pop(rid, None)
        if pending is None or pending[0] != self.connection_epoch:
            return
        _, kind, identity, extra = pending
        if kind != "preflight" and not any(
            i.attempt_id == identity
            and i.state
            in {
                TaskState.STARTING,
                TaskState.RUNNING,
                TaskState.RECONCILING,
                TaskState.NEEDS_REVIEW,
            }
            for i in self.repository.list_items()
        ):
            return
        if error or not isinstance(result, dict):
            self._uncertain(identity, kind)
            if (
                kind == "interrupt"
                and isinstance(error, dict)
                and error.get("code") == -32600
                and error.get("message") == "no active turn to interrupt"
                and identity not in self.interrupt_retries
            ):
                self.interrupt_retries.add(identity)
                epoch = self.connection_epoch
                QTimer.singleShot(500, lambda: self._retry_interrupt(identity, epoch))
            return
        if kind == "preflight":
            self._preflight(identity, result.get("thread"), extra)
        elif kind in {"resume", "resume_check"}:
            if kind == "resume" and self.history_reader:
                self._request("resume_check", identity, "thread/read", {})
                return
            item = next(
                (i for i in self.repository.list_items() if i.attempt_id == identity),
                None,
            )
            thread = result.get("thread")
            if (
                item is None
                or item.spec is None
                or not isinstance(thread, dict)
                or thread.get("id") != item.spec.thread_id
                or thread.get("canAcceptDirectInput") is not True
                or thread.get("cwd") != item.spec.cwd
                or (thread.get("projectId") or "") != item.spec.project_id
                or not isinstance(thread.get("status"), dict)
                or thread["status"].get("type") != "idle"
                or not isinstance(thread.get("turns"), list)
                or any(not isinstance(t, dict) for t in thread["turns"])
                or (
                    thread.get("baselineVersion")
                    or source_version(
                        [
                            t
                            for t in thread["turns"]
                            if t.get("id")
                            not in self.expected_turns.get(item.id, set())
                        ]
                    )
                )
                != item.spec.source_version
            ):
                self._uncertain(identity, kind)
                return
            current_locks = self._current_locks(item.spec.cwd)
            if (
                self.paused
                or not self.scope.reliable
                or self.clock() - self.scope_at > 3
                or self.scope.active_main_tasks >= self.limit
                or (item.spec.project_id or item.spec.cwd) in self.scope.active_projects
                or current_locks is None
                or set(current_locks or ()).intersection(self.scope.busy_lock_keys)
            ):
                # Reservation exists, but no turn/start has been sent. Keep it reviewable.
                self.repository.update_attempt(
                    identity, TaskState.NEEDS_REVIEW, reason="paused_before_send"
                )
                self.changed.emit()
                return
            self._request(
                "start",
                identity,
                "turn/start",
                {
                    "threadId": item.spec.thread_id,
                    "input": [{"type": "text", "text": item.spec.execution_prompt()}],
                    "clientUserMessageId": identity,
                },
            )
        elif kind == "start":
            turn = result.get("turn")
            if not isinstance(turn, dict) or not turn.get("id"):
                self._uncertain(identity, kind)
                return
            self.repository.update_attempt(
                identity, TaskState.RUNNING, turn_id=str(turn["id"])
            )
            early, self.early_requests = self.early_requests, []
            for request in early:
                self.server_request(*request)
            item = next(
                i for i in self.repository.list_items() if i.attempt_id == identity
            )
            self._dispatching.discard(item.id)
            self.scope = ExecutionScope(
                self.scope.reliable,
                self.scope.active_main_tasks + 1,
                self.scope.busy_lock_keys,
                self.scope.active_projects | {item.spec.project_id or item.spec.cwd}
                if item.spec
                else self.scope.active_projects,
            )
            self.changed.emit()
            self.reconcile(identity)
            if identity in self.stop_requested:
                self.interrupt(identity)
        elif kind in {"reconcile", "interrupt_check"}:
            thread = result.get("thread")
            receipt = self.repository.receipt(identity)
            if (
                not isinstance(thread, dict)
                or thread.get("id") != receipt["thread_id"]
                or not receipt["turn_id"]
            ):
                self._uncertain(identity, kind)
                return
            turn = next(
                (
                    t
                    for t in (thread.get("turns") or [])
                    if isinstance(t, dict) and t.get("id") == receipt["turn_id"]
                ),
                None,
            )
            if turn is None:
                self._uncertain(identity, kind)
            elif turn.get("status") in {"completed", "failed", "interrupted"}:
                self._completed(identity, turn)
            else:
                self.repository.update_attempt(identity, TaskState.RUNNING)
                self.changed.emit()
        elif kind == "interrupt":
            self.reconcile(identity)

    def _preflight(self, identity, thread, locks):
        self._dispatching.discard(identity)
        item = self.repository.get(identity)
        if item is None:
            self.reasons.pop(identity, None)
            return
        spec = item.spec
        current_locks = self._current_locks(spec.cwd) if spec else None
        reason = ""
        if (
            spec is None
            or not isinstance(thread, dict)
            or not isinstance(thread.get("status"), dict)
            or not isinstance(thread.get("turns"), list)
            or any(not isinstance(t, dict) for t in thread.get("turns", []))
        ):
            reason = "execution_target_unavailable"
        elif self.paused:
            reason = "execution_scope_unverified"
        elif not self.scope.reliable or self.clock() - self.scope_at > 3:
            self.waiting_preflights[identity] = (thread, locks, self.clock())
            self._dispatching.add(identity)
            self.scope_refresh_requested.emit()
            return
        elif (spec.project_id or spec.cwd) in self.scope.active_projects:
            reason = "project_busy"
        elif set(locks).intersection(self.scope.busy_lock_keys):
            reason = "repository_busy"
        elif current_locks is None or set(locks) != set(current_locks):
            reason = "execution_target_changed"
        elif self.scope.active_main_tasks >= self.limit:
            reason = "concurrency_limit"
        elif (
            thread.get("id") != spec.thread_id
            or (thread.get("projectId") or "") != spec.project_id
            or thread.get("cwd") != spec.cwd
        ):
            reason = "execution_target_changed"
        elif (thread.get("status") or {}).get("type") != "idle" or thread.get(
            "canAcceptDirectInput"
        ) is not True:
            reason = "conversation_busy"
        elif (
            thread.get("baselineVersion")
            or source_version(
                [
                    t
                    for t in thread.get("turns", [])
                    if t.get("id") not in self.expected_turns.get(item.id, set())
                ]
            )
        ) != spec.source_version:
            reason = "source_changed"
        if reason:
            self.reasons[identity] = reason
            if spec:
                self.paused_projects.add(spec.project_id or spec.cwd)
            self.changed.emit()
            return
        try:
            attempt = self.repository.reserve(
                identity,
                item.revision,
                tuple(locks),
                limit=self.limit,
                context={
                    "source_version": spec.source_version,
                    "dispatch_version": thread.get("sourceVersion")
                    or source_version(thread["turns"]),
                    "excluded_turns": sorted(self.expected_turns.get(identity, ())),
                },
            )
        except ValueError as error:
            self.reasons[identity] = str(error)
            self.changed.emit()
            return
        self.last_served[spec.project_id or spec.cwd] = self.clock()
        self.dispatch_versions[attempt] = thread.get("sourceVersion") or source_version(
            thread["turns"]
        )
        self._dispatching.add(identity)
        self._request("resume", attempt, "thread/resume", {"threadId": spec.thread_id})

    @staticmethod
    def _current_locks(cwd):
        try:
            return resolve_lock_keys(cwd)
        except (OSError, ValueError):
            return None

    def notification(self, method, params):
        if method == "serverRequest/resolved" and isinstance(params, dict):
            self.resolve_request(params.get("requestId"))
            self.changed.emit()
            return
        if method != "turn/completed" or not isinstance(params, dict):
            return
        turn = params.get("turn")
        if not isinstance(turn, dict):
            return
        for item in self.repository.list_items():
            if not item.attempt_id or item.state not in {
                TaskState.RUNNING,
                TaskState.RECONCILING,
                TaskState.NEEDS_REVIEW,
            }:
                continue
            receipt = self.repository.receipt(item.attempt_id)
            if receipt["turn_id"] == turn.get("id") and receipt[
                "thread_id"
            ] == params.get("threadId"):
                # Read the persisted full turn, rather than trusting an abbreviated notification.
                self.reconcile(item.attempt_id)

    def reconcile(self, attempt):
        receipt = self.repository.receipt(attempt)
        self._request(
            "reconcile",
            attempt,
            "thread/read",
            {"threadId": receipt["thread_id"], "includeTurns": True},
        )

    def _completed(self, attempt, turn, *, manual_confirmed=False):
        item = next(
            (i for i in self.repository.list_items() if i.attempt_id == attempt), None
        )
        if (
            item is None
            or item.spec is None
            or item.state in {TaskState.COMPLETE, TaskState.FAILED, TaskState.STOPPED}
        ):
            return
        verdict = evaluate_completion(
            item.spec,
            turn,
            self.repository.receipt(attempt)["turn_id"],
            manual_confirmed=manual_confirmed,
            artifact_results=verify_artifacts(item.spec),
        )
        project = item.spec.project_id or item.spec.cwd
        context = self.repository.receipt(attempt).get("execution_context", {})
        if context:
            self.dispatch_versions[attempt] = context.get("dispatch_version", "")
        if verdict.verdict == Verdict.PASSED:
            self.repository.update_attempt(
                attempt, TaskState.COMPLETE, terminal_verified=True
            )
            baselines = {item.spec.source_version, self.dispatch_versions.get(attempt)}
            for successor in self.repository.list_items():
                if (
                    successor.state == TaskState.QUEUED
                    and successor.spec
                    and successor.spec.thread_id == item.spec.thread_id
                    and successor.spec.source_version in baselines
                ):
                    self.expected_turns.setdefault(successor.id, set()).add(turn["id"])
            self.expected_turns.pop(item.id, None)
            self.dispatch_versions.pop(attempt, None)
            self.terminal_turns.pop(attempt, None)
            self.paused_projects.discard(project)
            remaining = {
                i.batch_id
                for i in self.repository.list_items()
                if i.state != TaskState.COMPLETE and i.reason != "dismissed_by_user"
            }
            self.enabled_batches.intersection_update(remaining)
            if not self.enabled_batches and not self.continuous_projects:
                self.paused = True
        elif verdict.verdict == Verdict.FAILED:
            state = (
                TaskState.STOPPED
                if turn.get("status") == "interrupted"
                else TaskState.FAILED
            )
            self.repository.update_attempt(
                attempt, state, reason=verdict.reasons[0], terminal_verified=True
            )
            self.paused_projects.add(project)
        else:
            self.repository.update_attempt(
                attempt, TaskState.NEEDS_REVIEW, reason=verdict.reasons[0]
            )
            self.terminal_turns[attempt] = turn
            self.paused_projects.add(project)
        self.scope = ExecutionScope(False, self.scope.active_main_tasks)
        self._save_session()
        self.changed.emit()
        self.scope_refresh_requested.emit()

    def pause(self):
        self.paused = True
        self.changed.emit()

    def resume(self):
        if not self.scope.reliable or self.clock() - self.scope_at > 3:
            raise ValueError("execution_scope_unverified")
        if self.recovery_required or not self.enabled_batches:
            self._restore_session()
        self.paused = False
        self._save_session()
        self.pump()

    def confirm_result(self, attempt):
        turn = self.terminal_turns.get(attempt)
        if turn is None:
            raise ValueError("terminal_evidence_required")
        self._completed(attempt, turn, manual_confirmed=True)

    def resume_project(self, identity):
        item = self.repository.require(identity)
        if item.spec is None:
            raise ValueError("execution_target_unavailable")
        if not self.scope.reliable or self.clock() - self.scope_at > 3:
            raise ValueError("execution_scope_unverified")
        if self.recovery_required:
            self._restore_session()
        if item.batch_id:
            self.enabled_batches.add(item.batch_id)
        self.paused_projects.discard(item.spec.project_id or item.spec.cwd)
        self.paused = False
        self._save_session()
        self.pump()

    def server_request(self, identity, method, params):
        if not isinstance(params, dict):
            return
        for item in self.repository.list_items():
            if (
                not item.attempt_id
                or item.spec is None
                or item.state
                not in {
                    TaskState.STARTING,
                    TaskState.RUNNING,
                    TaskState.RECONCILING,
                    TaskState.NEEDS_REVIEW,
                }
            ):
                continue
            receipt = self.repository.receipt(item.attempt_id)
            if (
                params.get("threadId") == receipt["thread_id"]
                and receipt["turn_id"]
                and params.get("turnId") == receipt["turn_id"]
            ):
                self.paused_projects.add(item.spec.project_id or item.spec.cwd)
                self.repository.update_attempt(
                    item.attempt_id,
                    TaskState.NEEDS_REVIEW,
                    reason="user_input_required",
                )
                self.requests[identity] = item.attempt_id
                self.request_details[identity] = {
                    "id": identity,
                    "method": method,
                    "params": params,
                    "task_id": item.id,
                    "epoch": self.connection_epoch,
                }
                self.user_request.emit(self.request_details[identity])
                self.changed.emit()
                return
        if len(self.early_requests) < 32 and any(
            i.state == TaskState.STARTING for i in self.repository.list_items()
        ):
            self.early_requests.append((identity, method, params))

    def answer_request(self, identity, response):
        if identity not in self.requests:
            raise ValueError("request_expired")
        if not self.client.answer_server_request(identity, response):
            raise ValueError("request_response_unknown")
        self.resolve_request(identity)
        self.changed.emit()

    def resolve_request(self, identity):
        attempt = self.requests.pop(identity, None)
        self.request_details.pop(identity, None)
        if attempt and attempt not in self.requests.values():
            item = next(
                (i for i in self.repository.list_items() if i.attempt_id == attempt),
                None,
            )
            if (
                item
                and item.state == TaskState.NEEDS_REVIEW
                and item.reason == "user_input_required"
            ):
                self.repository.update_attempt(attempt, TaskState.RUNNING)

    def interrupt(self, attempt):
        self.stop_requested.add(attempt)
        receipt = self.repository.receipt(attempt)
        if not receipt["turn_id"]:
            self.changed.emit()
            return
        self._request(
            "interrupt",
            attempt,
            "turn/interrupt",
            {"threadId": receipt["thread_id"], "turnId": receipt["turn_id"]},
        )

    def _retry_interrupt(self, attempt, epoch):
        """Retry one rejected stop, never a turn start or a different connection."""
        if epoch != self.connection_epoch or attempt not in self.stop_requested:
            return
        if any(
            item.attempt_id == attempt
            and item.state in {TaskState.RUNNING, TaskState.RECONCILING}
            for item in self.repository.list_items()
        ):
            self.interrupt(attempt)

    def emergency_stop(self):
        self.paused = True
        self.continuous_projects.clear()
        for item in self.repository.list_items():
            if item.attempt_id and item.state in {
                TaskState.STARTING,
                TaskState.RUNNING,
                TaskState.RECONCILING,
                TaskState.NEEDS_REVIEW,
            }:
                try:
                    self.interrupt(item.attempt_id)
                except ValueError:
                    self.reasons[item.id] = "turn_identity_unknown"
        self.changed.emit()
