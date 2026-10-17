"""Background log observation; only sanitized events and metadata reach Qt UI."""

from dataclasses import replace
from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt

from watched_kettle.integrations.codex_log import CodexLogMonitor
from watched_kettle.usage.device import DeviceBatch, parse_device_batch


class _LogWorker(QObject):
    payload = Signal(object)
    usage = Signal(object)
    state = Signal(object)
    recovery = Signal(object)

    def __init__(self, kwargs):
        super().__init__()
        self.kwargs = kwargs
        self.reader = None
        self.generation = 0
        self.recovery_allowed = True

    @Slot()
    def start(self):
        self.reader = CodexLogMonitor(parent=self, **self.kwargs)
        self.reader.payload_detected.connect(self.deliver)
        self.reader.usage_detected.connect(self.deliver_usage)
        self.reader.recovery_detected.connect(self.deliver_recovery)
        self.reader.timer.timeout.connect(self.publish)
        self.reader.start()
        self.publish()

    @Slot(object)
    def deliver_recovery(self, snapshot):
        if self.recovery_allowed:
            self.recovery.emit(replace(snapshot, generation=self.generation))

    @Slot(object)
    def deliver_usage(self, records):
        tokens, quotas = parse_device_batch(records)
        self.usage.emit(DeviceBatch(self.generation, tokens, quotas))

    @Slot(dict)
    def deliver(self, payload):
        self.publish()
        self.payload.emit((self.generation, payload))

    @Slot()
    def publish(self):
        if self.reader is not None:
            scopes = {
                key: self.reader.session_scope(key)
                for key in self.reader._session_ids.values()
            }
            self.state.emit((self.generation, self.reader.diagnostics(), scopes))

    @Slot()
    def close(self):
        if self.reader is not None:
            self.reader.close()
        self.thread().quit()

    @Slot()
    def clear_pending_questions(self):
        if self.reader is not None:
            self.reader.clear_pending_questions()

    @Slot(int)
    def reset_account(self, generation):
        # The main thread fences queued old outputs before this slot runs.
        self.generation = generation
        self.recovery_allowed = False
        if self.reader is not None:
            self.reader.close()
            self.reader.start()
            self.reader._recovery.clear()
            self.reader._recovery_confirmed.clear()
            self.publish()


class ThreadedCodexLogMonitor(QObject):
    payload_detected = Signal(dict)
    usage_detected = Signal(object)
    stop_requested = Signal()
    reset_questions_requested = Signal()
    reset_account_requested = Signal(int)
    recovery_detected = Signal(object)

    def __init__(self, parent=None, **kwargs):
        super().__init__(parent)
        self._state = {
            "active": False,
            "sessions_root_exists": False,
            "tracked_files": 0,
            "event_count": 0,
            "last_event": "",
            "last_detected_at": None,
            "last_error": "",
        }
        self._scopes = {}
        self._generation = 0
        self._kwargs = kwargs
        self._thread = None
        self._recovery_allowed = True

    def _create_worker(self):
        self._thread = QThread(self)
        self._worker = _LogWorker(self._kwargs)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.start)
        self._thread.finished.connect(self._worker.deleteLater)
        self._worker.payload.connect(self._receive_payload)
        self._worker.usage.connect(self._receive_usage)
        self._worker.state.connect(self._receive)
        self._worker.recovery.connect(self._receive_recovery)
        self.stop_requested.connect(
            self._worker.close, Qt.ConnectionType.QueuedConnection
        )
        self.reset_questions_requested.connect(
            self._worker.clear_pending_questions, Qt.ConnectionType.QueuedConnection
        )
        self.reset_account_requested.connect(
            self._worker.reset_account, Qt.ConnectionType.QueuedConnection
        )
        self._worker.generation = self._generation
        self._worker.recovery_allowed = self._recovery_allowed

    @Slot(object)
    def _receive_recovery(self, snapshot):
        if (
            self._recovery_allowed
            and snapshot.generation == self._generation
            and self.is_active
        ):
            self.recovery_detected.emit(snapshot)

    @Slot(bool)
    def account_changed(self, changed):
        if changed:
            self._recovery_allowed = False
            self._generation += 1
            self._scopes.clear()
            self._state = {**self._state, "tracked_files": 0, "last_event": ""}
            self.reset_account_requested.emit(self._generation)

    @Slot(object)
    def _receive_usage(self, batch):
        if batch.generation == self._generation and self.is_active:
            self.usage_detected.emit(batch)

    @Slot(object)
    def _receive_payload(self, result):
        generation, payload = result
        if generation == self._generation and self.is_active:
            self.payload_detected.emit(payload)

    @Slot(object)
    def _receive(self, result):
        generation, state, scopes = result
        if generation == self._generation and self.is_active:
            self._state, self._scopes = state, scopes

    @property
    def is_active(self):
        return self._thread is not None and self._thread.isRunning()

    def start(self):
        if not self.is_active:
            self._generation += 1
            self._create_worker()
            assert self._thread is not None
            self._thread.start()

    def close(self):
        self._generation += 1
        if self.is_active and self._thread is not None:
            self.stop_requested.emit()
            self._thread.wait()
            self._thread.deleteLater()
            self._thread = None
        self._state = {
            "active": False,
            "sessions_root_exists": False,
            "tracked_files": 0,
            "event_count": 0,
            "last_event": "",
            "last_detected_at": None,
            "last_error": "",
        }
        self._scopes = {}

    def diagnostics(self):
        return dict(self._state)

    def session_scope(self, session_id):
        return self._scopes.get(session_id, "unknown")
