"""GUI-thread facade for the worker-owned task feature."""

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot

from watched_kettle.integrations.codex_task_client import CodexTaskClient
from watched_kettle.features.tasks.worker import TaskWorker as _TaskWorker


class TaskService(QObject):
    changed = Signal()
    notice = Signal(str)
    comparison = Signal(str)
    approval = Signal(object)
    review_ready = Signal(object)
    task_saved = Signal(str)
    review_failed = Signal(str, str)
    save_failed = Signal(object, str)
    requested = Signal(str, object)

    def __init__(self, paths, parent=None, *, client_factory=CodexTaskClient):
        super().__init__(parent)
        self.state = {}
        self.worker_thread = QThread(self)
        self.worker = _TaskWorker(paths.database, client_factory)
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.start)
        self.requested.connect(self.worker.command)
        self.worker.snapshot.connect(self._snapshot)
        self.worker.notice.connect(self.notice)
        self.worker.comparison.connect(self.comparison)
        self.worker.approval.connect(self.approval)
        self.worker.review_ready.connect(self.review_ready)
        self.worker.task_saved.connect(self.task_saved)
        self.worker.review_failed.connect(self.review_failed)
        self.worker.save_failed.connect(self.save_failed)
        self.worker_thread.finished.connect(self.worker.deleteLater)

    def start(self):
        if not self.worker_thread.isRunning():
            self.worker_thread.start()

    def send(self, action, payload=None):
        self.requested.emit(action, payload)

    @Slot(object)
    def _snapshot(self, state):
        self.state = state
        self.changed.emit()

    def close(self):
        if self.worker_thread.isRunning():
            from PySide6.QtCore import QMetaObject

            QMetaObject.invokeMethod(
                self.worker, "stop", Qt.ConnectionType.BlockingQueuedConnection
            )
            self.worker_thread.quit()
            self.worker_thread.wait(5000)
        self.state = {}
