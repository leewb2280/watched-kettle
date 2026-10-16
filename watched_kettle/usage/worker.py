"""Thread-owned usage runtime with a bounded GUI command mailbox."""

import sqlite3
import logging
from collections import deque
from dataclasses import dataclass, replace
from threading import Lock
from time import monotonic

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot, Qt

from watched_kettle.application.logging import log_event
from watched_kettle.integrations.codex_app_server import CodexAppServerClient
from watched_kettle.integrations.account_monitor import AccountMonitor
from watched_kettle.storage.claude_code_repository import ClaudeCodeRepository
from watched_kettle.storage.database import DatabaseManager, StorageAvailability
from watched_kettle.storage.usage_repository import (
    SqliteUsageRepository,
    VolatileUsageRepository,
)
from watched_kettle.usage.claude_code_service import (
    ClaudeCodeUsageService,
    ClaudeCodeUsageSnapshot,
)
from watched_kettle.usage.models import UsageSnapshot, UsageRefreshState
from datetime import datetime, timezone
from watched_kettle.usage.presentation import format_tray_summary
from watched_kettle.usage.service import CodexUsageService


@dataclass
class WorkerPreferences:
    enabled: bool
    quiet: bool
    selected_limit_key: str = ""
    claude_code_enabled: bool = True

    def load_usage_enabled(self):
        return self.enabled

    def save_usage_enabled(self, value):
        self.enabled = value

    def load_usage_quiet_summary_enabled(self):
        return self.quiet

    def save_usage_quiet_summary_enabled(self, value):
        self.quiet = value

    def load_usage_widget_limit_key(self):
        return self.selected_limit_key


@dataclass(frozen=True)
class UsageWorkerResult:
    request_id: int
    account_generation: int
    snapshot: UsageSnapshot
    recovery: bool = False


CLAUDE_CODE_PREFIX = "claude_code."


class _UsageWorker(QObject):
    result = Signal(object)
    claude_code_result = Signal(object)
    notice = Signal(object)
    storage_changed = Signal(object)
    wake_requested = Signal()
    account_changed = Signal(bool)

    def __init__(self, paths, preferences, client_factory, claude_config_dir=None):
        super().__init__()
        self.claude_config_dir = claude_config_dir
        self.paths = paths
        self.preferences = preferences
        self.client_factory = client_factory
        self.commands: deque[tuple[int, str, tuple[object, ...]]] = deque()
        self.lock = Lock()
        self.stopping = False
        self.overflow = False
        self.request_id = 0
        self.wake_pending = False
        self.wake_requested.connect(self.drain, Qt.ConnectionType.QueuedConnection)

    def enqueue(self, request_id, method, args):
        with self.lock:
            if self.stopping:
                return False
            if method == "refresh" and any(item[1] == method for item in self.commands):
                return True
            if len(self.commands) >= 128:
                self.overflow = True
                return False
            self.commands.append((request_id, method, args))
            wake = not self.wake_pending
            self.wake_pending = True
        if wake:
            self.wake_requested.emit()
        return True

    @Slot()
    def initialize(self):
        try:
            self._initialize()
        except Exception as error:
            log_event(
                "usage.worker",
                "initialize_failed",
                logging.ERROR,
                error_code=type(error).__name__,
            )
            if hasattr(self, "database"):
                self.database.close()
            self.storage_changed.emit(
                StorageAvailability(
                    False,
                    "사용량 작업을 시작하지 못했습니다.",
                    code="usage_worker_start_failed",
                )
            )
            self.thread().quit()

    def _initialize(self):
        log_event("usage.worker", "initialize_started")
        self.database = DatabaseManager(self.paths.database)
        status = self.database.start()
        self.storage_changed.emit(status)
        repository = (
            SqliteUsageRepository(self.database)
            if status.available
            else VolatileUsageRepository()
        )
        if isinstance(repository, SqliteUsageRepository):
            try:
                repository.import_legacy(self.paths.legacy_usage_history)
            except (OSError, ValueError, RuntimeError, sqlite3.DatabaseError) as error:
                self.storage_changed.emit(
                    StorageAvailability(
                        True,
                        "기존 기록은 보존되었지만 이전하지 못했습니다.",
                        code=type(error).__name__,
                    )
                )
        self.service = CodexUsageService(
            self.client_factory(parent=self),
            self.preferences,
            repository,
            parent=self,
            account_monitor=AccountMonitor(self.client_factory, parent=self),
        )
        self.service.account_changed.connect(self.account_changed)
        self.service.snapshot_changed.connect(self.publish)
        self.service.notice_requested.connect(self.notice)
        # Claude Code history shares the worker thread and its SQLite owner.
        self.claude = ClaudeCodeUsageService(
            ClaudeCodeRepository(self.database) if status.available else None,
            config_dir=self.claude_config_dir,
            enabled=self.preferences.claude_code_enabled,
            parent=self,
        )
        self.claude.snapshot_changed.connect(self.claude_code_result)
        self.claude.notice_requested.connect(self.notice)
        self.claude.start()
        if not status.available:
            self.service._publish(storage_error=status.message)
        self.maintenance_timer = QTimer(self)
        self.maintenance_timer.setInterval(10 * 60 * 1000)
        self.maintenance_timer.timeout.connect(self.maintain)
        self.maintenance_timer.start()
        log_event(
            "usage.worker",
            "initialized",
            state="available" if status.available else "offline",
        )

    @Slot()
    def maintain(self):
        if isinstance(self.service.repository, SqliteUsageRepository):
            try:
                self.service.repository.maintenance()
                if self.claude.repository is not None:
                    self.claude.repository.prune()
            except sqlite3.DatabaseError:
                log_event(
                    "usage.worker",
                    "maintenance_deferred",
                    logging.WARNING,
                    error_code="database_error",
                )
                self.service._publish(
                    storage_error="기록 정리를 다음 주기로 미뤘습니다. (storage_maintenance_deferred)"
                )

    @Slot(object)
    def publish(self, snapshot):
        self.result.emit(
            UsageWorkerResult(
                self.request_id,
                self.service.account.generation,
                snapshot,
                getattr(self.service, "_publishing_recovery", False),
            )
        )

    @Slot()
    def drain(self):
        with self.lock:
            stopping, overflow = self.stopping, self.overflow
            self.overflow = False
        if stopping:
            self.maintenance_timer.stop()
            try:
                if hasattr(self, "claude"):
                    self.claude.close()
                self.service.close()
            finally:
                self.database.close()
                self.thread().quit()
            return
        if overflow:
            log_event(
                "usage.worker",
                "queue_overflow",
                logging.WARNING,
                queue_size=128,
                error_code="usage_queue_limit",
            )
            self.service._reset_account()
            self.service._publish(
                storage_error="작업 대기량이 많아 관측을 다시 시작합니다. (usage_queue_limit)"
            )
            self.service.refresh()
        deadline = monotonic() + 0.020
        while monotonic() < deadline:
            with self.lock:
                if not self.commands:
                    self.wake_pending = False
                    return
                self.request_id, method, args = self.commands.popleft()
            try:
                if method.startswith(CLAUDE_CODE_PREFIX):
                    getattr(self.claude, method[len(CLAUDE_CODE_PREFIX) :])(*args)
                    continue
                getattr(self.service, method)(*args)
            except Exception as error:
                log_event(
                    "usage.worker",
                    "operation_failed",
                    logging.ERROR,
                    error_code=type(error).__name__,
                )
                self.service._finish_refresh(
                    "error", "새로고침 작업을 처리하지 못했습니다."
                )
                self.service._publish(
                    storage_error="기록 작업을 처리하지 못했습니다. (usage_worker_operation_failed)",
                    clearing_history=False,
                )

        self.wake_requested.emit()


class UsageWorkerService(QObject):
    """GUI facade: no SQLite connection, QProcess, or QSettings crosses threads."""

    snapshot_changed = Signal(object)
    notice_requested = Signal(object)
    availability_changed = Signal(object)
    account_changed = Signal(bool)
    claude_code_snapshot_changed = Signal(object)

    def __init__(
        self,
        paths,
        preferences,
        parent=None,
        client_factory=CodexAppServerClient,
        lifecycle_errors=None,
        claude_config_dir=None,
    ):
        super().__init__(parent)
        self.lifecycle_errors = lifecycle_errors if lifecycle_errors is not None else {}
        self.preferences = preferences
        self.enabled = preferences.load_usage_enabled()
        self.claude_code_enabled = preferences.load_claude_code_usage_enabled()
        self.quiet_summary_enabled = preferences.load_usage_quiet_summary_enabled()
        self.snapshot = UsageSnapshot()
        self.claude_code_snapshot = ClaudeCodeUsageSnapshot()
        self.availability = StorageAvailability(False, "저장소 준비 중")
        self._next_id = 0
        self._account_generation = 0
        self._minimum_result_id = 0
        self._closed = False
        self._pending_recovery = None
        self._recovery_delivery = QTimer(self)
        self._recovery_delivery.setSingleShot(True)
        self._recovery_delivery.timeout.connect(self._deliver_recovery)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(30_000)
        self._refresh_timer.timeout.connect(self._refresh_timed_out)
        self._thread = QThread(self)
        self._worker = _UsageWorker(
            paths,
            WorkerPreferences(
                self.enabled,
                self.quiet_summary_enabled,
                preferences.load_usage_widget_limit_key(),
                self.claude_code_enabled,
            ),
            client_factory,
            claude_config_dir,
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.initialize)
        self._thread.finished.connect(self._worker.deleteLater)
        self._worker.result.connect(self._receive)
        self._worker.claude_code_result.connect(self._receive_claude_code)
        self._worker.notice.connect(self.notice_requested)
        self._worker.storage_changed.connect(self._storage_changed)
        self._worker.account_changed.connect(self.account_changed)
        self._thread.start()

    @Slot(object)
    def _storage_changed(self, availability):
        self.availability = availability
        if availability.code == "usage_worker_start_failed":
            self._refresh_timer.stop()
            self._publish(
                refresh=replace(
                    self.snapshot.refresh,
                    state="error",
                    phase="",
                    message=availability.message,
                )
            )

    @Slot(object)
    def _receive_claude_code(self, snapshot):
        if self._closed:
            return
        self.claude_code_snapshot = snapshot
        self.claude_code_snapshot_changed.emit(snapshot)

    def claude_code(self, method, *args):
        """Send one Claude Code history command to the worker thread."""
        return self._send(CLAUDE_CODE_PREFIX + method, *args)

    def _deliver_recovery(self):
        result, self._pending_recovery = self._pending_recovery, None
        if result is not None:
            self._receive_now(result)

    @Slot(object)
    def _receive(self, result):
        if (
            self._closed
            or result.account_generation < self._account_generation
            or result.request_id < self._minimum_result_id
        ):
            return
        if result.recovery:
            pending = self._pending_recovery
            if pending is None or (result.account_generation, result.request_id) >= (
                pending.account_generation,
                pending.request_id,
            ):
                self._pending_recovery = result
            if not self._recovery_delivery.isActive():
                self._recovery_delivery.start(0)
            return
        self._pending_recovery = None
        self._recovery_delivery.stop()
        self._receive_now(result)

    def _receive_now(self, result):
        if (
            not self._closed
            and result.account_generation >= self._account_generation
            and result.request_id >= self._minimum_result_id
        ):
            incoming = result.snapshot
            current = self.snapshot.refresh
            if incoming.refresh.request_id < current.request_id:
                incoming = replace(incoming, refresh=current)
            elif (
                incoming.refresh.request_id == current.request_id
                and not current.busy
                and incoming.refresh.busy
            ):
                return
            if not incoming.refresh.busy:
                self._refresh_timer.stop()
            self._account_generation = result.account_generation
            self.snapshot = incoming
            self.snapshot_changed.emit(self.snapshot.for_display())
            self.availability_changed.emit(self.snapshot.availability)

    def _send(self, method, *args):
        if self._closed:
            return False
        self._next_id += 1
        accepted = self._worker.enqueue(self._next_id, method, args)
        if not accepted:
            log_event(
                "usage.worker",
                "command_rejected",
                logging.WARNING,
                operation=method,
                error_code="usage_queue_limit",
            )
            self._publish(
                storage_error="기록 처리 대기량을 초과했습니다. (usage_queue_limit)",
                clearing_history=False,
            )
        return accepted

    def _publish(self, **changes):
        self.snapshot = replace(self.snapshot, **changes)
        self.snapshot_changed.emit(self.snapshot.for_display())

    def start(self):
        return self._send("start")

    def tray_summary(self) -> str:
        return format_tray_summary(self.snapshot.for_display())

    def refresh(self, force=False):
        if not self.enabled or self._closed:
            return False
        if self.snapshot.refresh.busy:
            return True
        if not force:
            return self._send("refresh", False)
        request_id = self._next_id + 1
        self._publish(
            refresh=UsageRefreshState(
                request_id, "refreshing", "queued", "현재 계정 확인 중"
            )
        )
        self._refresh_timer.start()
        accepted = self._send("refresh", True, request_id)
        if not accepted:
            self._refresh_timer.stop()
            self._publish(
                refresh=UsageRefreshState(
                    request_id,
                    "error",
                    message="새로고침 요청을 접수하지 못했습니다.",
                    completed_at=datetime.now(timezone.utc),
                )
            )
        return accepted

    def _refresh_timed_out(self):
        refresh = self.snapshot.refresh
        if refresh.busy:
            partial = refresh.phase == "usage"
            self._publish(
                refresh=replace(
                    refresh,
                    state="partial" if partial else "error",
                    phase="",
                    message="한도 갱신 완료 · 상세 사용량 조회 시간 초과"
                    if partial
                    else "새로고침 시간이 초과되었습니다. 다시 시도해 주세요.",
                    completed_at=datetime.now(timezone.utc),
                )
            )
            if self._send("cancel_refresh", refresh.request_id):
                self._minimum_result_id = self._next_id

    def observe_agent_payload(self, payload):
        if isinstance(payload, dict) and payload.get("source") == "claude_code":
            return self.claude_code("observe_agent_payload", dict(payload))
        return self._send("observe_agent_payload", dict(payload))

    def observe_local_usage_batch(self, records):
        if not self.enabled or self._closed:
            return False
        from watched_kettle.usage.device import DeviceBatch, parse_device_batch

        batch = (
            records
            if isinstance(records, DeviceBatch)
            else DeviceBatch(0, *parse_device_batch(records or ()))
        )
        return self._send("observe_local_usage_batch", batch)

    def set_selected_limit_key(self, key):
        return self._send("set_selected_limit_key", str(key or ""))

    def clear_device_history(self):
        return self._send("clear_device_history")

    def set_task_query(self, search="", order="recent", limit=100, thread_hash=None):
        if self.snapshot.account_checking or not self.snapshot.account_hash:
            return False
        return self._send(
            "set_task_query",
            search,
            order,
            limit,
            self.snapshot.account_hash,
            self._account_generation,
            thread_hash,
        )

    def set_conversation_query(
        self, search="", order="recent", offset=0, project_key=None
    ):
        return self._send(
            "set_conversation_query",
            search,
            order,
            offset,
            self.snapshot.account_hash,
            self._account_generation,
            project_key,
        )

    def set_project_query(self, search="", order="recent", offset=0, custom=None):
        return self._send(
            "set_project_query",
            search,
            order,
            offset,
            custom,
            self.snapshot.account_hash,
            self._account_generation,
        )

    def select_usage_project(self, key):
        return self._send(
            "select_usage_project",
            key,
            self.snapshot.account_hash,
            self._account_generation,
        )

    def move_usage_project(self, key, direction=0, target="", before=True):
        return self._send(
            "move_usage_project",
            key,
            direction,
            target,
            before,
            self.snapshot.account_hash,
            self._account_generation,
        )

    def select_usage_conversation(self, thread_hash):
        return self._send(
            "select_usage_conversation",
            thread_hash,
            self.snapshot.account_hash,
            self._account_generation,
        )

    def clear_history(self):
        if (
            not self.snapshot.account_hash
            or self.snapshot.clearing_history
            or self.snapshot.account_checking
        ):
            return False
        self._publish(clearing_history=True, history_message="")
        return self._send(
            "clear_history", self.snapshot.account_hash, self._account_generation
        )

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        self.preferences.save_usage_enabled(self.enabled)
        if not self.enabled:
            self._refresh_timer.stop()
            if self.snapshot.refresh.busy:
                self._publish(
                    refresh=replace(
                        self.snapshot.refresh,
                        state="cancelled",
                        phase="",
                        message="사용량 비서가 꺼져 새로고침을 취소했습니다.",
                    )
                )
        accepted = self._send("set_enabled", self.enabled)
        if accepted and not self.enabled:
            self._minimum_result_id = self._next_id
        return accepted

    def set_claude_code_enabled(self, enabled):
        self.claude_code_enabled = bool(enabled)
        self.preferences.save_claude_code_usage_enabled(self.claude_code_enabled)
        return self.claude_code("set_enabled", self.claude_code_enabled)

    def set_quiet_summary_enabled(self, enabled):
        self.quiet_summary_enabled = bool(enabled)
        self.preferences.save_usage_quiet_summary_enabled(self.quiet_summary_enabled)
        return self._send("set_quiet_summary_enabled", self.quiet_summary_enabled)

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._pending_recovery = None
        self._recovery_delivery.stop()
        self._refresh_timer.stop()
        with self._worker.lock:
            self._worker.stopping = True
            self._worker.commands.clear()
        self._worker.wake_requested.emit()
        # All operations have bounded SQLite waits; never terminate a thread
        # while it owns a database transaction.
        self._thread.wait()
