"""Bounded, read-only metadata worker independent of usage collection."""

from collections import OrderedDict
import json
import ntpath
from pathlib import Path, PureWindowsPath
import time

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal, Slot

from watched_kettle.activity_diagnostics import (
    MAX_DIAGNOSTIC_KEYS,
    DiagnosticRecorder,
    diagnostic_guard,
    diagnostic_ref,
    diagnostic_thread_ref,
)

from watched_kettle.integrations.codex_app_server import CodexAppServerClient
from watched_kettle.integrations.codex_paths import codex_home
from watched_kettle.features.project_activity.service import (
    ThreadMetadata,
    safe_label,
    conversation_title,
)


MAX_DESKTOP_STATE_BYTES = 16 * 1024 * 1024


def _normalized_project_path(value):
    if not isinstance(value, str) or not value or "\x00" in value:
        return ""
    if not PureWindowsPath(value).is_absolute():
        return ""
    return ntpath.normcase(ntpath.normpath(value))


def _read_desktop_project_index(path):
    """Read only the desktop project relations; fail closed on schema changes."""
    path = Path(path)
    try:
        if not path.is_file() or path.stat().st_size > MAX_DESKTOP_STATE_BYTES:
            return {}, set(), {}, {}
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError):
        return {}, set(), {}, {}
    if not isinstance(payload, dict):
        return {}, set(), {}, {}

    assignments = {}
    raw_assignments = payload.get("thread-project-assignments")
    if isinstance(raw_assignments, dict):
        for thread_id, assignment in raw_assignments.items():
            if not isinstance(thread_id, str) or not isinstance(assignment, dict):
                continue
            project_id = assignment.get("projectId")
            if isinstance(project_id, str) and project_id:
                assignments[thread_id] = project_id

    raw_projectless = payload.get("projectless-thread-ids")
    projectless = (
        {
            thread_id
            for thread_id in raw_projectless
            if isinstance(thread_id, str) and thread_id
        }
        if isinstance(raw_projectless, list)
        else set()
    )
    projects = {}
    roots: dict[str, set[str]] = {}
    raw_projects = payload.get("local-projects")
    if isinstance(raw_projects, dict):
        for fallback_id, project in raw_projects.items():
            if not isinstance(project, dict):
                continue
            project_id = project.get("id", fallback_id)
            if isinstance(project_id, str) and project_id:
                projects[project_id] = safe_label(project.get("name"), "Codex 작업")
                raw_roots = project.get("rootPaths")
                if isinstance(raw_roots, list):
                    for value in raw_roots:
                        root = _normalized_project_path(value)
                        if root:
                            roots.setdefault(root, set()).add(project_id)
    return assignments, projectless, projects, roots


class _MetadataWorker(QObject):
    diagnostic_event = Signal(str, object)
    result = Signal(object, int)
    reset = Signal()
    delivered = Signal(object, int, int, int)
    relation = Signal(str, object, str, int, int, int)
    connection_changed = Signal(int)
    status = Signal(str)
    timing = Signal(str, str, float, int, int, int)

    def __init__(self, factory, desktop_state_path=None):
        super().__init__()
        self.factory = factory
        self.desktop_state_path = Path(
            desktop_state_path or codex_home() / ".codex-global-state.json"
        )
        self.client = None
        self.generation = 0
        self.queue: OrderedDict[str, int] = OrderedDict()
        self.pending = {}
        self.control_requests = {}
        self.cursors = set()
        self.projects = {}
        self.desktop_assignments = {}
        self.desktop_projectless = set()
        self.desktop_projects = {}
        self.desktop_roots = {}
        self.desktop_state_mtime = None
        self.account = None
        self.poll = None
        self.last_account_check = 0.0
        self.clock = time.monotonic
        self.targets: dict[str, int] = {}
        self.due: dict[str, float] = {}
        self.failures: dict[str, int] = {}
        self.stamps = {}
        self.epoch = 0
        self.account_verified = True  # start/ready gate real transports
        self._relation_cache = {}
        self._api_projects = {}
        self._thread_cwds = {}
        self._local_checked = 0.0
        self._serial = 0
        self._policies = {}
        self._resolved = set()
        self._maintenance = set()
        self.activity_diagnostics = DiagnosticRecorder()
        self._diagnostic_requests = OrderedDict()
        self.activity_diagnostics.callback = (
            lambda event, **fields: self.diagnostic_event.emit(event, fields)
        )

    @Slot()
    def start(self):
        self.account_verified = False
        self.client = self.factory(parent=self)
        self.client.ready_changed.connect(self.ready)
        self.client.response_received.connect(self.response)
        self.client.notification_received.connect(self.notification)
        self.poll = QTimer(self)
        self.poll.setInterval(250)
        self.poll.timeout.connect(self.pump)
        self.poll.start()
        self.client.start()

    @Slot(object, int)
    def sync_targets(self, targets, generation):
        if generation != self.generation:
            return
        for thread in set(self.targets) - set(targets):
            self._remove_target(thread)
        for thread, value in targets.items():
            version, priority, interval = (
                value if isinstance(value, tuple) else (value, 1, 3)
            )
            if self.targets.get(thread) != version:
                self._remove_target(thread)
                self.targets[thread] = version
                self._diagnose("metadata_target_registered", thread)
                self.due[thread] = self.clock()
                self.publish_relation(thread)
            previous = self._policies.get(thread)
            self._policies[thread] = (priority, interval)
            if previous is not None and previous != (priority, interval):
                self.due[thread] = min(self.due.get(thread, 0), self.clock() + interval)
        self.pump()

    def _remove_target(self, thread):
        if thread in self.targets:
            self._diagnose("metadata_target_removed", thread)
        self._forget_diagnostics(
            thread, "metadata_resolved", "metadata_failed", "metadata_relation"
        )
        for mapping in (
            self.targets,
            self.due,
            self.failures,
            self.queue,
            self._relation_cache,
            self._api_projects,
            self._thread_cwds,
            self._policies,
        ):
            mapping.pop(thread, None)
        self._resolved.discard(thread)
        # Keep transport slots occupied until their response/timeout arrives.
        # The registration stamp makes those responses inapplicable.

    @Slot(str, int)
    def request(self, thread, generation):
        if generation != self.generation:
            return
        if thread not in self.targets:
            self._serial += 1
            self.targets[thread] = self._serial
            self.due[thread] = self.clock()
        self.queue.setdefault(thread, generation)
        while len(self.queue) > 512:
            self.queue.popitem(last=False)

    @Slot(int)
    def invalidate(self, generation):
        self.activity_diagnostics.emit(
            "metadata_invalidated", generation=generation, epoch=self.epoch
        )
        self.activity_diagnostics.states.clear()
        self.generation = generation
        self.targets.clear()
        self.queue.clear()
        self.pending.clear()
        self.stamps.clear()
        self.due.clear()
        self.failures.clear()
        self._relation_cache.clear()
        self._api_projects.clear()
        self._thread_cwds.clear()
        self._policies.clear()
        self._resolved.clear()
        self._maintenance.clear()
        self.projects.clear()
        self.desktop_assignments.clear()
        self.desktop_projectless.clear()
        self.desktop_projects.clear()
        self.desktop_roots.clear()
        self.desktop_state_mtime = None
        self.control_requests.clear()
        self.cursors.clear()
        if self.client is not None and self.client.ready:
            self.account_verified = False
            self.control_request("account/read", {})
            self.control_request("project/list", {})

    def control_request(self, method, params):
        if self.client is None:
            return
        rid = self.client.request(method, params)
        if rid is not None:
            self.control_requests[rid] = self.generation

    def ready(self, ready):
        if self.client is None:
            return
        self.epoch += 1
        self.activity_diagnostics.emit(
            "metadata_connection",
            epoch=self.epoch,
            generation=self.generation,
            ready=ready,
        )
        self.connection_changed.emit(self.epoch)
        self.pending.clear()
        self._maintenance.clear()
        self.stamps.clear()
        self.control_requests.clear()
        self.cursors.clear()
        self.account_verified = False
        if ready:
            self.control_request("account/read", {})
            self.control_request("project/list", {})
            self.status.emit("메타데이터 연결됨")
        else:
            self.status.emit("메타데이터 연결 끊김")

    def notification(self, method, _params):
        if method == "account/updated" and self.client is not None:
            self.account_verified = False
            self.control_request("account/read", {})

    def refresh_desktop_project_index(self):
        try:
            mtime = self.desktop_state_path.stat().st_mtime_ns
        except OSError:
            mtime = None
        if mtime == self.desktop_state_mtime:
            return
        self.desktop_state_mtime = mtime
        (
            self.desktop_assignments,
            self.desktop_projectless,
            self.desktop_projects,
            self.desktop_roots,
        ) = _read_desktop_project_index(self.desktop_state_path)

    def project_for_thread(self, thread):
        project = self._api_projects.get(thread, self.desktop_assignments.get(thread))
        if project is not None:
            return project
        if thread in self.desktop_projectless:
            return ""
        cwd = self._thread_cwds.get(thread, "")
        # Full paths only: names and sibling prefixes do not establish membership.
        matches = [
            root
            for root in self.desktop_roots
            if cwd == root or cwd.startswith(root.rstrip("\\") + "\\")
        ]
        if not matches:
            return None
        projects = self.desktop_roots[max(matches, key=len)]
        return next(iter(projects)) if len(projects) == 1 else None

    def project_evidence(self, thread):
        if thread in self._api_projects:
            return "api"
        if thread in self.desktop_assignments:
            return "desktop_assignment"
        if thread in self.desktop_projectless:
            return "explicit_projectless"
        cwd = self._thread_cwds.get(thread, "")
        matches = [
            root
            for root in self.desktop_roots
            if cwd == root or cwd.startswith(root.rstrip("\\") + "\\")
        ]
        if not matches:
            return "unresolved"
        return (
            "cwd_match"
            if len(self.desktop_roots[max(matches, key=len)]) == 1
            else "cwd_ambiguous"
        )

    @diagnostic_guard
    def _forget_diagnostics(self, thread, *events):
        ref = diagnostic_ref(thread)
        for event in events:
            self.activity_diagnostics.forget(event, ref)

    @diagnostic_guard
    def _diagnose_relation(self, thread, project):
        self._diagnose(
            "metadata_relation",
            thread,
            project_ref=diagnostic_ref(ThreadMetadata(thread, project).project_key),
            project_known=True,
            reason=self.project_evidence(thread),
        )

    @diagnostic_guard
    def _diagnose_resolved(self, metadata, rid):
        thread = metadata.thread_id
        values = dict(
            request_id=rid,
            project_ref=diagnostic_ref(metadata.project_key),
            project_known=metadata.project_id is not None,
            title_present=metadata.title != "Codex 대화",
            parent_ref=diagnostic_thread_ref("codex", metadata.parent_thread_id),
            reason=self.project_evidence(thread),
        )
        self._diagnose("metadata_resolved", thread, **values)
        self._diagnose(
            "metadata_response", thread, detail=True, result="resolved", **values
        )

    @diagnostic_guard
    def _remember_diagnostic_request(self, rid, thread):
        source = "claude_code" if thread.startswith("claude_code:") else "codex"
        self._diagnostic_requests[rid] = dict(
            source=source,
            thread_ref=diagnostic_thread_ref(source, thread),
            request_generation=self.generation,
            request_epoch=self.epoch,
            request_version=self.targets.get(thread, 0),
        )
        self._diagnostic_requests.move_to_end(rid)
        while len(self._diagnostic_requests) > MAX_DIAGNOSTIC_KEYS:
            self._diagnostic_requests.popitem(last=False)

    @diagnostic_guard
    def _finish_diagnostic_request(self, rid, missing):
        fields = self._diagnostic_requests.pop(rid, None)
        if missing and fields is not None:
            self.activity_diagnostics.emit(
                "metadata_discarded",
                **fields,
                generation=self.generation,
                epoch=self.epoch,
                request_id=rid,
                reason="request_invalidated",
            )

    @diagnostic_guard
    def _diagnose(self, event, thread, *, repeat_seconds=0, detail=False, **fields):
        recorder = self.activity_diagnostics
        if detail and not recorder.detailed:
            return
        source = "claude_code" if thread.startswith("claude_code:") else "codex"
        ref = diagnostic_thread_ref(source, thread)
        if event == "metadata_failed":
            # An unchanged successful response after failure is still a recovery.
            recorder.forget("metadata_resolved", ref)
        values = dict(
            source=source,
            thread_ref=ref,
            generation=self.generation,
            epoch=self.epoch,
            target_version=self.targets.get(thread, 0),
            **fields,
        )
        if detail or event not in {
            "metadata_resolved",
            "metadata_failed",
            "metadata_relation",
        }:
            recorder.emit(event, **values)
        else:
            recorder.record(
                event,
                ref,
                repeat_seconds=repeat_seconds,
                now=self.clock(),
                compare=(
                    "generation",
                    "epoch",
                    "target_version",
                    "reason",
                    "error_code",
                    "rpc_code",
                    "project_ref",
                    "project_known",
                    "title_present",
                    "parent_ref",
                    "information_retained",
                ),
                **values,
            )

    def publish_relation(self, thread):
        if not self.account_verified:
            return
        self.refresh_desktop_project_index()
        project = self.project_for_thread(thread)
        if project is None:
            return
        label = self.projects.get(project, "") or self.desktop_projects.get(project, "")
        value = (project, label)
        if self._relation_cache.get(thread) != value:
            self._relation_cache[thread] = value
            self._diagnose_relation(thread, project)
            self.relation.emit(
                thread,
                project,
                label,
                self.generation,
                self.targets[thread],
                self.epoch,
            )

    def pump(self):
        now = self.clock()
        if self.account_verified and now - self._local_checked >= 1:
            self._local_checked = now
            for thread in tuple(self.targets):
                self.publish_relation(thread)
        if not self.client or not self.client.ready:
            return
        if now - self.last_account_check >= 30:
            self.last_account_check = now
            if not any(v == self.generation for v in self.control_requests.values()):
                self.control_request("account/read", {})
        if not self.account_verified:
            return
        inflight = {t for t, _g in self.pending.values()}
        eligible = sorted(
            (
                t
                for t in self.targets
                if t not in inflight and self.due.get(t, 0) <= now
            ),
            key=lambda t: (self.priority(t), self.due.get(t, 0), t),
        )
        self.queue = OrderedDict((t, self.generation) for t in eligible[:512])
        while self.queue and len(self.pending) < 4:
            thread, generation = self.queue.popitem(last=False)
            maintenance = self.priority(thread) > 0
            if maintenance and len(self._maintenance) >= 2:
                continue
            rid = self.client.request(
                "thread/read", {"threadId": thread, "includeTurns": False}
            )
            if rid is None:
                self.due[thread] = now + 3
                break
            self.due[thread] = now + self._policies.get(thread, (1, 3))[1]
            self.pending[rid] = (thread, generation)
            self.stamps[rid] = (self.targets[thread], self.epoch)
            self._remember_diagnostic_request(rid, thread)
            self._diagnose("metadata_requested", thread, detail=True, request_id=rid)
            if maintenance:
                self._maintenance.add(rid)
            self.timing.emit(
                thread,
                "requested",
                self.clock(),
                generation,
                self.targets[thread],
                self.epoch,
            )

    def priority(self, thread):
        return (
            0 if thread not in self._resolved else self._policies.get(thread, (1, 3))[0]
        )

    def response(self, rid, method, _params, result, error):
        self._maintenance.discard(rid)
        request = self.pending.pop(rid, None)
        generation = self.control_requests.pop(rid, None)
        stamp = self.stamps.pop(rid, None)
        if method == "thread/read":
            self._finish_diagnostic_request(rid, not request)
            if not request:
                return
            pending_thread, request_generation = request
            if request_generation != self.generation:
                self._diagnose(
                    "metadata_discarded",
                    pending_thread,
                    reason="old_generation",
                    request_id=rid,
                    request_generation=request_generation,
                )
                return
            if stamp is not None and stamp != (
                self.targets.get(pending_thread),
                self.epoch,
            ):
                self._diagnose(
                    "metadata_discarded",
                    pending_thread,
                    reason="stale_registration_or_epoch",
                    request_id=rid,
                    request_epoch=stamp[1],
                    request_version=stamp[0],
                )
                return
            invalid = (
                not isinstance(result, dict)
                or not isinstance(result.get("thread"), dict)
                or result["thread"].get("id") != pending_thread
            )
            if error or invalid:
                failures = self.failures.get(pending_thread, 0) + 1
                self.failures[pending_thread] = failures
                code = error.get("code") if isinstance(error, dict) else None
                reason = (
                    "timeout"
                    if code == "timeout"
                    else "rpc_error"
                    if error
                    else "id_mismatch"
                    if isinstance(result, dict)
                    and isinstance(result.get("thread"), dict)
                    else "invalid_response"
                )
                self._diagnose(
                    "metadata_failed",
                    pending_thread,
                    repeat_seconds=60,
                    request_id=rid,
                    error_code=reason,
                    attempt=failures,
                    rpc_code=code
                    if isinstance(code, int) and not isinstance(code, bool)
                    else None,
                    information_retained=pending_thread in self._resolved,
                )
                self._diagnose(
                    "metadata_response",
                    pending_thread,
                    detail=True,
                    request_id=rid,
                    result="failed",
                    error_code=reason,
                )
                self.due[pending_thread] = (
                    self.clock() + (3, 6, 12, 30)[min(failures - 1, 3)]
                )
                self.status.emit("일부 메타데이터 확인 불가 · 마지막 이름 유지")
                return
            failed = self.failures.pop(pending_thread, None)
            if failed:
                self._diagnose(
                    "metadata_recovered", pending_thread, request_id=rid, attempt=failed
                )
            self._forget_diagnostics(pending_thread, "metadata_failed")
            self._resolved.add(pending_thread)
            if stamp is not None:
                self.timing.emit(
                    pending_thread,
                    "responded",
                    self.clock(),
                    request_generation,
                    stamp[0],
                    stamp[1],
                )
        if method in {"account/read", "project/list"} and generation != self.generation:
            return
        if error or not isinstance(result, dict):
            self.status.emit("일부 메타데이터 확인 불가 · 임시 이름 사용")
            return
        if method == "project/list":
            values = result.get("data", result.get("projects", []))
            if not isinstance(values, list):
                return
            for project in values[:1000]:
                if isinstance(project, dict) and project.get("id"):
                    self.projects[project["id"]] = safe_label(
                        project.get("name"), "Codex 작업"
                    )
            cursor = result.get("nextCursor")
            if (
                isinstance(cursor, str)
                and cursor
                and cursor not in self.cursors
                and len(self.cursors) < 31
                and len(self.projects) < 1000
            ):
                self.cursors.add(cursor)
                self.control_request("project/list", {"cursor": cursor})
        elif method == "account/read":
            if "account" not in result:
                return
            account = result["account"]
            if account is not None and (
                not isinstance(account, dict)
                or not account.get("type")
                and not account.get("id")
                and not account.get("email")
            ):
                return
            key = (
                (account.get("type"), account.get("id"), account.get("email"))
                if account is not None
                else (None, None, None)
            )
            changed = self.account is not None and key != self.account
            self.account = key
            if changed:
                self.account_verified = False
                self.reset.emit()
                return
            reconnecting = not self.account_verified
            self.account_verified = True
            self._local_checked = 0
            if reconnecting:
                for thread in self.targets:
                    self.due[thread] = min(self.due.get(thread, 0), self.clock())
        elif method == "thread/read" and request:
            if not self.account_verified:
                self._diagnose(
                    "metadata_discarded",
                    request[0],
                    reason="account_unverified",
                    request_id=rid,
                )
                return
            thread_id, generation = request
            if generation != self.generation:
                return
            thread_data = result.get("thread") or {}
            if not isinstance(thread_data, dict) or thread_data.get("id") != thread_id:
                return
            self.refresh_desktop_project_index()
            raw_project_id = thread_data.get("projectId")
            if isinstance(raw_project_id, str):
                self._api_projects[thread_id] = raw_project_id
            else:
                self._api_projects.pop(thread_id, None)
            self._thread_cwds[thread_id] = _normalized_project_path(
                thread_data.get("cwd")
            )
            project_id = self.project_for_thread(thread_id)
            # Verified against the installed Codex sidebar; never use preview.
            metadata = ThreadMetadata(
                thread_id,
                project_id,
                self.projects.get(project_id, "")
                or self.desktop_projects.get(project_id, ""),
                str(thread_data.get("cwd") or ""),
                conversation_title(thread_data.get("name")),
                str(thread_data.get("parentThreadId") or ""),
            )
            self.result.emit(metadata, generation)
            self._diagnose_resolved(metadata, rid)
            if stamp is not None:
                self.delivered.emit(metadata, generation, stamp[0], stamp[1])

    @Slot()
    def close(self):
        if self.poll:
            self.poll.stop()
        if self.client:
            self.client.close()
        QThread.currentThread().quit()

    @Slot()
    def reconnect(self):
        if self.client is not None:
            self.account_verified = False
            # The shared monitor has already reset the account boundary.
            self.account = None
            self.pending.clear()
            self.stamps.clear()
            self.control_requests.clear()
            self.client.close()
            self.client.start()


class ConversationMetadataService(QObject):
    requested = Signal(str, int)
    targets_changed = Signal(object, int)
    invalidated = Signal(int)
    stop_requested = Signal()
    reconnect_requested = Signal()
    status_changed = Signal(str)

    def __init__(self, activity, parent=None, client_factory=CodexAppServerClient):
        super().__init__(parent)
        self.activity = activity
        self.activity_diagnostics = DiagnosticRecorder()
        self.last_diagnostics: OrderedDict[str, dict] = OrderedDict()
        self._requested = {}
        self._serial = 0
        self._epoch = 0
        self._generation = activity.generation
        self._thread = QThread(self)
        self.worker = _MetadataWorker(client_factory)
        self.worker.diagnostic_event.connect(self.receive_diagnostic)
        self.worker.moveToThread(self._thread)
        self._thread.started.connect(self.worker.start)
        self._thread.finished.connect(self.worker.deleteLater)
        self.targets_changed.connect(self.worker.sync_targets)
        self.invalidated.connect(self.worker.invalidate)
        self.stop_requested.connect(
            self.worker.close, Qt.ConnectionType.QueuedConnection
        )
        self.reconnect_requested.connect(self.worker.reconnect)
        self.worker.delivered.connect(self.receive)
        self.worker.relation.connect(self.receive_relation)
        self.worker.connection_changed.connect(self.connection_changed)
        self.worker.reset.connect(self.reset)
        self.worker.status.connect(self.status_changed)
        self.worker.timing.connect(self.receive_timing)
        self._target_policies = {}
        activity.changed.connect(self.refresh_active)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(1000)
        self.refresh_timer.timeout.connect(self.refresh_active)

    @Slot(str, object)
    @diagnostic_guard
    def receive_diagnostic(self, event, fields):
        ref = fields.get("thread_ref")
        if ref and event in {
            "metadata_resolved",
            "metadata_failed",
            "metadata_discarded",
            "metadata_target_removed",
        }:
            self.last_diagnostics[ref] = dict(fields, lookup_result=event)
            self.last_diagnostics.move_to_end(ref)
            while len(self.last_diagnostics) > 512:
                self.last_diagnostics.popitem(last=False)
        if event == "metadata_invalidated":
            self.last_diagnostics.clear()
        self.activity_diagnostics.emit(event, **fields)

    @Slot(int)
    def connection_changed(self, epoch):
        self._epoch = epoch

    def valid(self, thread, generation, version, epoch):
        return (
            generation == self.activity.generation
            and epoch == self._epoch
            and self._requested.get(thread) == version
        )

    @Slot(object, int, int, int)
    def receive(self, metadata, generation, version, epoch):
        if self.valid(metadata.thread_id, generation, version, epoch):
            self.activity.set_metadata(metadata, generation)
        else:
            self._diagnose_discarded(
                metadata.thread_id, generation, version, epoch, "stale_delivery"
            )

    @diagnostic_guard
    def _diagnose_discarded(self, thread, generation, version, epoch, reason):
        self.activity_diagnostics.emit(
            "metadata_delivery_discarded",
            thread_ref=diagnostic_ref(thread),
            generation=generation,
            epoch=epoch,
            target_version=version,
            reason=reason,
        )

    @diagnostic_guard
    def _diagnose_target_selected(self, thread):
        item = self.activity.activities.get(thread)
        self.activity_diagnostics.emit(
            "metadata_target_selected",
            thread_ref=diagnostic_ref(thread),
            source="claude_code" if thread.startswith("claude_code:") else "codex",
            scope=item.scope if item else "unknown",
            generation=self.activity.generation,
            target_version=self._requested[thread],
        )

    @Slot(str, object, str, int, int, int)
    def receive_relation(self, thread, project, label, generation, version, epoch):
        if self.valid(thread, generation, version, epoch):
            self.activity.set_project_relation(thread, project, label, generation)
        else:
            self._diagnose_discarded(
                thread, generation, version, epoch, "stale_relation"
            )

    @Slot(str, str, float, int, int, int)
    def receive_timing(self, thread, stage, at, generation, version, epoch):
        if self.valid(thread, generation, version, epoch):
            self.activity.mark_latency(thread, stage, at)

    def refresh_active(self):
        if self._generation != self.activity.generation:
            self._generation = self.activity.generation
            self._requested.clear()
            self.invalidated.emit(self._generation)
        now = self.activity.now()
        targets = {
            i.thread_id
            for i in self.activity.activities.values()
            if not i.expires or i.expires > now and i.state != "done"
        }
        targets.update(r.thread_id for r in self.activity.visible_completions)
        for thread in tuple(targets):
            seen = set()
            while thread not in seen:
                seen.add(thread)
                metadata = self.activity.metadata.get(thread)
                if not metadata or not metadata.parent_thread_id:
                    break
                thread = metadata.parent_thread_id
                targets.add(thread)
        changed = set(self._requested) != targets
        for thread in set(self._requested) - targets:
            del self._requested[thread]
        for thread in sorted(targets - set(self._requested)):
            self._serial += 1
            self._requested[thread] = self._serial
            self._diagnose_target_selected(thread)
            self.requested.emit(thread, self.activity.generation)
            self.activity.mark_latency(thread, "queued")
        policies = {}
        for thread, version in self._requested.items():
            item = self.activity.activities.get(thread)
            running = item is not None and not item.expires and item.state != "done"
            priority = 0 if running and item.scope == "unknown" else 1 if running else 2
            policies[thread] = (version, priority, 3 if running else 15)
        if changed or policies != self._target_policies:
            self._target_policies = policies
            self.targets_changed.emit(policies, self.activity.generation)

    def request(self, _thread):
        self.refresh_active()

    def reset(self):
        self.activity.reset()

    @Slot(bool)
    def account_changed(self, changed):
        # Fence already queued old-process results before restarting the worker.
        self._epoch += 1
        if changed:
            self.reset()
        self.reconnect_requested.emit()

    def start(self):
        self.refresh_active()
        self.refresh_timer.start()
        self._thread.start()

    def close(self):
        self.refresh_timer.stop()
        if self._thread.isRunning():
            self.stop_requested.emit()
            self._thread.wait()
