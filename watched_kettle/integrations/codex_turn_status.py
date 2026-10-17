"""Bounded, read-only terminal evidence; never resume or subscribe to a thread."""

from collections import OrderedDict
from time import monotonic

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal, Slot

from watched_kettle.activity_diagnostics import (
    DiagnosticRecorder,
    diagnostic_guard,
    diagnostic_ref,
)
from watched_kettle.integrations.codex_app_server import CodexAppServerClient
from watched_kettle.state.codex_activity import CodexTurnOutcome
from watched_kettle.state.event_names import outcome_reason


MAX_TARGETS = 128
PAGE_SIZE = 20
MAX_PAGES = 2
RECHECK_SECONDS = 30


class _TurnStatusWorker(QObject):
    outcome = Signal(int, object)
    diagnostic = Signal(int, str, object)

    def __init__(self, factory=CodexAppServerClient, clock=monotonic):
        super().__init__()
        self.factory = factory
        self.clock = clock
        self.client = None
        self.timer = None
        self.targets = OrderedDict()
        self.due = {}
        self.pending = None
        self.epoch = 0
        self.connection = 0
        self.unsupported = False
        self.enabled = True
        self.cursor = 0
        self.diagnostics = DiagnosticRecorder()
        self.diagnostics.callback = lambda event, **fields: self.diagnostic.emit(
            self.epoch, event, fields
        )

    @Slot()
    def start(self):
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.pump)
        self.timer.start()

    @Slot(object, int)
    def sync(self, targets, epoch):
        if epoch != self.epoch:
            return
        targets = sorted(targets, key=lambda t: not t.ended)[:MAX_TARGETS]
        self.targets = OrderedDict(((t.thread_id, t.turn_id), t) for t in targets)
        self.due = {k: v for k, v in self.due.items() if k in self.targets}
        self.pump()

    @Slot(int, bool)
    def reset(self, epoch, enabled):
        self.epoch = epoch
        self.enabled = enabled
        self.targets.clear()
        self.due.clear()
        self.pending = None
        self.unsupported = False
        if self.client is not None:
            self.client.close()
            self.client.deleteLater()
            self.client = None

    def _ensure_client(self):
        if self.client is None:
            self.client = self.factory(parent=self)
            client = self.client
            client.ready_changed.connect(
                lambda ready, c=client: self.ready(ready) if self.client is c else None
            )
            client.response_received.connect(
                lambda *args, c=client: self.response(*args)
                if self.client is c
                else None
            )
            client.start()

    def ready(self, ready):
        self.connection += 1
        self.pending = None
        if ready:
            self.unsupported = False
            self.pump()

    @Slot()
    def pump(self):
        if not self.enabled or not self.targets or self.unsupported or self.pending:
            return
        self._ensure_client()
        if self.pending or self.client is None or not self.client.ready:
            return
        now = self.clock()
        eligible = [t for k, t in self.targets.items() if self.due.get(k, 0) <= now]
        if not eligible:
            return
        ended = [t for t in eligible if t.ended]
        candidates = ended or eligible
        target = candidates[self.cursor % len(candidates)]
        self.cursor += 1
        self.due[(target.thread_id, target.turn_id)] = now + RECHECK_SECONDS
        self.request(target)

    def request(self, target, cursor=None, page=1, seen=()):
        if self.client is None:
            return
        params = dict(
            threadId=target.thread_id,
            limit=PAGE_SIZE,
            sortDirection="desc",
            itemsView="notLoaded",
        )
        if cursor is not None:
            params["cursor"] = cursor
        rid = self.client.request("thread/turns/list", params, 10_000)
        if rid is not None:
            self.pending = (rid, target, self.epoch, self.connection, page, seen)

    def response(self, rid, method, _params, result, error):
        if (
            method != "thread/turns/list"
            or self.pending is None
            or self.pending[0] != rid
        ):
            return
        _, target, epoch, connection, page, seen = self.pending
        self.pending = None
        if (
            epoch != self.epoch
            or connection != self.connection
            or self.targets.get((target.thread_id, target.turn_id)) != target
        ):
            self.record("turn_status_discarded", target, "stale_target")
            return
        if error:
            code = error.get("code") if isinstance(error, dict) else None
            self.unsupported = code == -32601
            self.record(
                "turn_status_failed",
                target,
                "unsupported" if self.unsupported else "request_failed",
            )
            return
        data = result.get("data") if isinstance(result, dict) else None
        if not isinstance(data, list) or len(data) > PAGE_SIZE:
            self.record("turn_status_failed", target, "invalid_response")
            return
        for turn in data:
            if not isinstance(turn, dict) or turn.get("id") != target.turn_id:
                continue
            state = {
                "completed": "done",
                "failed": "failed",
                "interrupted": "cancelled",
            }.get(str(turn.get("status")))
            if state is None or (state == "done" and turn.get("error")):
                return
            detail = turn.get("error")
            reason = outcome_reason(
                detail.get("codexErrorInfo") if isinstance(detail, dict) else None
            )
            self.record("turn_status_resolved", target, state)
            self.outcome.emit(epoch, CodexTurnOutcome(target, state, reason))
            return
        cursor = result.get("nextCursor")
        if (
            isinstance(cursor, str)
            and cursor
            and cursor not in seen
            and page < MAX_PAGES
        ):
            self.request(target, cursor, page + 1, (*seen, cursor))

    @diagnostic_guard
    def record(self, event, target, reason):
        self.diagnostics.record(
            event,
            diagnostic_ref(target.thread_id),
            repeat_seconds=60,
            thread_ref=diagnostic_ref(target.thread_id),
            turn_ref=diagnostic_ref(target.turn_id),
            source="codex",
            reason=reason,
            generation=target.generation,
        )

    @Slot()
    def close(self):
        if self.timer:
            self.timer.stop()
        if self.client:
            self.client.close()
        QThread.currentThread().quit()


class CodexTurnStatusMonitor(QObject):
    outcome_detected = Signal(object)
    diagnostic_event = Signal(str, object)
    targets_requested = Signal(object, int)
    reset_requested = Signal(int, bool)
    stop_requested = Signal()

    def __init__(self, parent=None, client_factory=CodexAppServerClient):
        super().__init__(parent)
        self.epoch = 0
        self.enabled = True
        self._thread = QThread(self)
        self.worker = _TurnStatusWorker(client_factory)
        self.worker.moveToThread(self._thread)
        self._thread.started.connect(self.worker.start)
        self._thread.finished.connect(self.worker.deleteLater)
        self.targets_requested.connect(self.worker.sync)
        self.reset_requested.connect(self.worker.reset)
        self.stop_requested.connect(
            self.worker.close, Qt.ConnectionType.QueuedConnection
        )
        self.worker.outcome.connect(self.receive)
        self.worker.diagnostic.connect(self.receive_diagnostic)

    def start(self):
        if not self._thread.isRunning():
            self._thread.start()

    def sync_targets(self, targets):
        if self.enabled:
            self.targets_requested.emit(targets, self.epoch)

    @Slot(int, object)
    def receive(self, epoch, outcome):
        if epoch == self.epoch and self.enabled:
            self.outcome_detected.emit(outcome)

    @Slot(int, str, object)
    def receive_diagnostic(self, epoch, event, fields):
        if epoch == self.epoch and self.enabled:
            self.diagnostic_event.emit(event, fields)

    @Slot(bool)
    def account_changed(self, _changed):
        self.epoch += 1
        self.reset_requested.emit(self.epoch, self.enabled)

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        self.account_changed(False)

    def close(self):
        self.epoch += 1
        self.enabled = False
        if self._thread.isRunning():
            self.stop_requested.emit()
            self._thread.wait()
