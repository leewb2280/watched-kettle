"""One Codex App Server process shared by the usage, metadata and turn readers.

Each reader used to start its own App Server (about 30-35 MiB each). The hub
owns a single ``CodexAppServerClient`` on its own thread and hands every reader
an ``AppServerHandle`` with the client's own surface (``start``, ``close``,
``request``, ``ready`` and the four signals), so the readers keep their code.

- Replies go only to the handle that asked; notifications go to every open one.
- A handle's ``close`` is its own: it sees itself go offline and its pending
  requests fail, while the others stay connected. The process ends once no
  handle is open, and starts again with the next ``start``.
- A handle made with ``restart_on_reopen`` (the usage reader) restarts the
  process when it starts again after a close: an account switch must read the
  new sign-in. The other readers then see the connection drop and return, as
  they do for the account change itself.

``AccountMonitor`` keeps its own short-lived process on purpose and does not
use the hub.
"""

from __future__ import annotations

from itertools import count

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot

from watched_kettle.integrations.codex_app_server import CodexAppServerClient
from watched_kettle.thread_shutdown import wait_for_thread

BROADCAST = 0
_handle_ids = count(1)


class _HubWorker(QObject):
    """Lives on the hub thread and owns the shared client."""

    ready = Signal(int, bool)  # handle id (BROADCAST for all open ones), ready
    response = Signal(int, int, str, object, object, object)
    notification = Signal(str, object)
    error = Signal(str)

    def __init__(self, client_factory):
        super().__init__()
        self.client_factory = client_factory
        self.client = None
        self.open: set[int] = set()
        self.requests: dict[int, tuple[int, int]] = {}

    def _ensure_client(self):
        if self.client is None:
            client = self.client_factory(parent=self)
            client.ready_changed.connect(self._client_ready)
            client.response_received.connect(self._client_response)
            client.notification_received.connect(self.notification)
            client.error_changed.connect(self.error)
            self.client = client
        return self.client

    @Slot(int, bool)
    def open_handle(self, handle, restart):
        self.open.add(handle)
        client = self._ensure_client()
        if restart:
            # Even a process still starting would keep the old sign-in.
            client.close()
        client.start()
        if client.ready:
            self.ready.emit(handle, True)

    @Slot(int)
    def close_handle(self, handle):
        self.open.discard(handle)
        self.requests = {
            rid: owner for rid, owner in self.requests.items() if owner[0] != handle
        }
        if not self.open and self.client is not None:
            self.client.close()

    @Slot(int, int, str, object, int)
    def request(self, handle, local_id, method, params, timeout_ms):
        client = self.client
        rid = (
            client.request(method, params, timeout_ms)
            if client is not None and handle in self.open
            else None
        )
        if rid is None:
            error = {"code": "app_server_request_limit", "message": method}
            self.response.emit(handle, local_id, method, params, None, error)
            return
        self.requests[rid] = (handle, local_id)

    def _client_ready(self, ready):
        self.ready.emit(BROADCAST, bool(ready))

    def _client_response(self, rid, method, params, result, error):
        owner = self.requests.pop(rid, None)
        if owner is not None:
            self.response.emit(owner[0], owner[1], method, params, result, error)

    @Slot()
    def stop(self):
        self.open.clear()
        self.requests.clear()
        if self.client is not None:
            self.client.close()
        QThread.currentThread().quit()


class AppServerHandle(QObject):
    """One reader's view of the shared App Server, on the reader's thread."""

    ready_changed = Signal(bool)
    response_received = Signal(int, str, object, object, object)
    notification_received = Signal(str, object)
    error_changed = Signal(str)

    _open_requested = Signal(int, bool)
    _close_requested = Signal(int)
    _request_requested = Signal(int, int, str, object, int)

    def __init__(self, hub, parent=None, *, restart_on_reopen=False):
        super().__init__(parent)
        self.id = next(_handle_ids)
        self.ready = False
        self.error = ""
        self.restart_on_reopen = restart_on_reopen
        self._open = False
        self._restart_pending = False
        self._next_id = 1
        self._pending: dict[int, tuple[str, object]] = {}
        worker = hub.worker
        self._open_requested.connect(worker.open_handle)
        self._close_requested.connect(worker.close_handle)
        self._request_requested.connect(worker.request)
        worker.ready.connect(self._hub_ready)
        worker.response.connect(self._hub_response)
        worker.notification.connect(self._hub_notification)
        worker.error.connect(self._hub_error)

    def start(self):
        if self._open:
            return
        self._open = True
        restart, self._restart_pending = self._restart_pending, False
        self._open_requested.emit(self.id, restart)

    def close(self):
        # A close asks for a fresh connection next time, even one sent before
        # this reader ever opened: the sign-in may have changed meanwhile.
        if self.restart_on_reopen:
            self._restart_pending = True
        if not self._open:
            return
        self._open = False
        self._close_requested.emit(self.id)
        self._set_ready(False)
        pending, self._pending = self._pending, {}
        for local_id, (method, params) in pending.items():
            self.response_received.emit(
                local_id, method, params, None, {"code": "closed", "message": method}
            )

    def request(self, method, params=None, timeout_ms=10_000):
        if not (self._open and self.ready):
            return None
        local_id = self._next_id
        self._next_id += 1
        self._pending[local_id] = (str(method), params)
        self._request_requested.emit(
            self.id, local_id, str(method), params, int(timeout_ms)
        )
        return local_id

    def _set_ready(self, ready):
        if ready != self.ready:
            self.ready = ready
            self.ready_changed.emit(ready)

    def _hub_ready(self, handle, ready):
        if handle in (BROADCAST, self.id) and self._open:
            self._set_ready(ready)

    def _hub_response(self, handle, local_id, method, params, result, error):
        if handle != self.id or self._pending.pop(local_id, None) is None:
            return
        self.response_received.emit(local_id, method, params, result, error)

    def _hub_notification(self, method, params):
        if self._open:
            self.notification_received.emit(method, params)

    def _hub_error(self, message):
        self.error = message
        if self._open:
            self.error_changed.emit(message)


class AppServerHub(QObject):
    """Owns the hub thread; hand ``handle_factory()`` to each reader."""

    _stop_requested = Signal()

    def __init__(self, parent=None, client_factory=CodexAppServerClient):
        super().__init__(parent)
        self._closed = False
        self._thread = QThread(self)
        self._thread.setObjectName("codex-app-server-hub")
        self.worker = _HubWorker(client_factory)
        self.worker.moveToThread(self._thread)
        self._thread.finished.connect(self.worker.deleteLater)
        self._stop_requested.connect(
            self.worker.stop, Qt.ConnectionType.QueuedConnection
        )
        self._thread.start()

    def handle_factory(self, *, restart_on_reopen=False):
        def make(parent=None):
            return AppServerHandle(self, parent, restart_on_reopen=restart_on_reopen)

        return make

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._thread.isRunning():
            self._stop_requested.emit()
            wait_for_thread(self._thread, "integrations.codex_app_server_hub")
