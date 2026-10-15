"""Shared Desktop observation. A successful private server is never attestation."""

from dataclasses import dataclass
import time

from PySide6.QtCore import QObject, QTimer, Signal

from watched_kettle.features.tasks.scheduling import ExecutionScope, resolve_lock_keys
from watched_kettle.integrations.codex_task_client import CodexTaskClient
from watched_kettle.integrations.codex_app_server import find_codex_program
from watched_kettle.integrations.execution_connection import (
    connection_target,
    CONNECTION_LABELS,
)


@dataclass(frozen=True)
class ExecutionCapabilities:
    readable: bool = False
    observes_desktop: bool = False
    resumes_existing: bool = False
    routes_approvals: bool = False
    interrupts_owned: bool = False

    @property
    def executable(self):
        return all(
            (
                self.readable,
                self.observes_desktop,
                self.resumes_existing,
                self.routes_approvals,
                self.interrupts_owned,
            )
        )


@dataclass(frozen=True)
class ExecutionSnapshot:
    account: str
    generation: int
    observed_at: float
    active_threads: tuple[str, ...]
    busy_lock_keys: frozenset[str]
    active_main_tasks: int
    reliable: bool
    active_projects: frozenset[str] = frozenset()

    def scope(self):
        return ExecutionScope(
            self.reliable,
            self.active_main_tasks,
            self.busy_lock_keys,
            self.active_projects,
        )


class DesktopExecutionAdapter(QObject):
    snapshot_changed = Signal(object)
    changed = Signal()

    def __init__(
        self,
        parent=None,
        *,
        client=None,
        clock=time.monotonic,
        verified_capabilities=None,
        lock_resolver=resolve_lock_keys,
        target=None,
    ):
        super().__init__(parent)
        self.target = target or connection_target(find_codex_program())
        self.client = client or CodexTaskClient(self, connection_target=self.target)
        self.clock = clock
        self.lock_resolver = lock_resolver
        # Supplied only by an adapter contract validated against an actual Desktop build.
        # No current build has passed that validation. This is not a UI bypass switch.
        self.verified = verified_capabilities or ExecutionCapabilities()
        self.capabilities = ExecutionCapabilities()
        self.account = ""
        self.generation = 0
        self.pending = {}
        self.threads = {}
        self.cursors = set()
        self.poll_started = 0.0
        self.reason = "Desktop 공유 실행 연결 검증이 필요합니다."
        self.snapshot = ExecutionSnapshot("", 0, 0, (), frozenset(), 0, False)
        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.poll)
        self.client.ready_changed.connect(self.ready)
        self.client.response_received.connect(self.response)
        self.client.notification_received.connect(self.notification)
        if hasattr(self.client, "error_changed"):
            self.client.error_changed.connect(
                lambda _message: self.invalidate("Desktop 공유 연결에 응답이 없습니다.")
            )
        if hasattr(self.client, "diagnostic_changed"):
            self.client.diagnostic_changed.connect(self.diagnostic)

    def diagnostic(self, status):
        if status.code:
            self.invalidate(
                CONNECTION_LABELS.get(
                    status.code, "Codex 공유 연결을 확인하지 못했습니다."
                )
            )

    def set_account(self, account):
        account = str(account or "")
        if account == self.account:
            return
        self.timer.stop()
        self.client.close()
        self.account = account
        self.invalidate(
            "Desktop 공유 실행 연결 확인 중"
            if account
            else "대화 읽기를 켜고 계정을 확인하세요."
        )
        if account:
            self.client.start()
            self.timer.start()

    def close(self):
        self.set_account(None)
        self.client.close()

    def invalidate(self, reason):
        status = getattr(self.client, "connection_status", None)
        if status and status.code in CONNECTION_LABELS:
            reason = CONNECTION_LABELS[status.code]
        self.generation += 1
        self.pending.clear()
        self.threads.clear()
        self.capabilities = ExecutionCapabilities()
        self.reason = reason
        self.snapshot = ExecutionSnapshot(
            self.account, self.generation, self.clock(), (), frozenset(), 0, False
        )
        self.snapshot_changed.emit(self.snapshot)
        self.changed.emit()

    def ready(self, ready):
        self.invalidate(
            "Desktop 실행 연결 확인 중"
            if ready
            else "Desktop 공유 실행 연결이 끊겼습니다."
        )
        if ready and self.account:
            self.poll()

    def request(self, kind, method, params):
        rid = self.client.request(method, params)
        if rid is None:
            self.invalidate("Desktop 실행 상태를 조회하지 못했습니다.")
            return
        self.pending[rid] = (kind, self.generation)

    def poll(self):
        if not self.account or not self.client.ready:
            return
        if self.pending:
            if self.clock() - self.poll_started > 3:
                self.invalidate("실행 상태 조회가 지연되어 새 작업 시작을 보류합니다.")
            return
        self.poll_started = self.clock()
        self.threads.clear()
        self.cursors.clear()
        self.request("account", "account/read", {})

    def notification(self, method, _params):
        if method in {"account/updated", "account/login/completed"}:
            self.invalidate("계정 변경 후 실행 연결을 다시 확인합니다.")
            self.poll()
        elif method in {"thread/status/changed", "turn/started", "turn/completed"}:
            # Never reuse a pre-change slot observation for a new dispatch.
            self.invalidate("실행 상태 갱신 중")
            self.poll()

    def response(self, rid, _method, params, result, error):
        pending = self.pending.pop(rid, None)
        if pending is None or pending[1] != self.generation:
            return
        if error or not isinstance(result, dict):
            self.invalidate("Desktop 공유 실행 상태를 읽지 못했습니다.")
            return
        kind = pending[0]
        try:
            if kind == "account":
                account = result.get("account") or {}
                identity = (
                    account.get("accountId")
                    or account.get("id")
                    or account.get("email")
                )
                if identity != self.account:
                    raise ValueError("account_mismatch")
                self.request("loaded", "thread/loaded/list", {})
            elif kind == "loaded":
                rows = result.get("data")
                if not isinstance(rows, list) or any(
                    not isinstance(i, str) for i in rows
                ):
                    raise ValueError("invalid_loaded")
                for identity in rows:
                    if identity not in self.threads:
                        self.threads[identity] = None
                cursor = result.get("nextCursor")
                if cursor:
                    if (
                        not isinstance(cursor, str)
                        or cursor in self.cursors
                        or len(self.cursors) >= 100
                    ):
                        raise ValueError("invalid_cursor")
                    self.cursors.add(cursor)
                    self.request("loaded", "thread/loaded/list", {"cursor": cursor})
                else:
                    self.read_next()
            elif kind == "thread":
                thread = result.get("thread")
                if (
                    not isinstance(thread, dict)
                    or thread.get("id") != params["threadId"]
                ):
                    raise ValueError("thread_mismatch")
                self.threads[thread["id"]] = thread
                self.read_next()
        except (ValueError, TypeError, KeyError, AttributeError, OSError):
            self.invalidate(
                "Desktop 전체 실행 상태 또는 작업 경로를 확인하지 못했습니다."
            )

    def read_next(self):
        for identity, thread in self.threads.items():
            if thread is None:
                self.request(
                    "thread",
                    "thread/read",
                    {"threadId": identity, "includeTurns": False},
                )
                return
        active, roots, locks, projects = [], set(), set(), set()
        for identity, thread in self.threads.items():
            status = (thread.get("status") or {}).get("type")
            if status not in {"idle", "active"}:
                raise ValueError("unknown_status")
            if status == "active":
                active.append(identity)
                root, visited = identity, set()
                while self.threads[root].get("parentThreadId"):
                    if root in visited:
                        raise ValueError("parent_cycle")
                    visited.add(root)
                    root = self.threads[root]["parentThreadId"]
                    if root not in self.threads:
                        raise ValueError("unobserved_parent")
                roots.add(root)
                root_thread = self.threads[root]
                projects.add(
                    root_thread.get("projectId") or root_thread.get("cwd") or ""
                )
                if "" in projects:
                    raise ValueError("unknown_project")
                locks.update(self.lock_resolver(thread.get("cwd") or ""))
        self.capabilities = ExecutionCapabilities(
            True,
            self.verified.observes_desktop,
            self.verified.resumes_existing,
            self.verified.routes_approvals,
            self.verified.interrupts_owned,
        )
        reliable = (
            self.capabilities.executable and self.clock() - self.poll_started <= 3
        )
        self.reason = (
            "실행 연결 준비됨"
            if reliable
            else "공유 연결의 Desktop 관측·실행 소유권·승인 전달 검수가 필요합니다."
        )
        self.snapshot = ExecutionSnapshot(
            self.account,
            self.generation,
            self.poll_started,
            tuple(active),
            frozenset(locks),
            len(roots),
            reliable,
            frozenset(projects),
        )
        self.snapshot_changed.emit(self.snapshot)
        self.changed.emit()
