"""Explicit execution transport. Existing read-only clients stay read-only."""

from __future__ import annotations

import json

from watched_kettle.integrations.execution_connection import (
    ConnectionStatus,
    transport_failure,
)

from PySide6.QtCore import QProcess, Signal

from watched_kettle.integrations.codex_app_server import CodexAppServerClient


class CodexTaskClient(CodexAppServerClient):
    server_request_received = Signal(object, str, object)
    server_requests_cleared = Signal()
    diagnostic_changed = Signal(object)

    def __init__(self, *args, connection_target=None, **kwargs):
        self.connection_target = connection_target
        if connection_target is not None:
            kwargs.update(
                program=connection_target.program,
                server_arguments=connection_target.arguments,
            )
        super().__init__(*args, **kwargs)
        self._server_requests = {}
        self.connection_status = ConnectionStatus()
        self._diagnostic_tail = b""
        self.ready_changed.connect(self._clear_server_requests)

    def _diagnostic(self, status):
        self.connection_status = status
        self.diagnostic_changed.emit(status)

    def start(self):
        if (
            self.process is None
            or self.process.state() == QProcess.ProcessState.NotRunning
        ):
            self._diagnostic_tail = b""
            self._diagnostic(ConnectionStatus("starting"))
        super().start()

    def _send_initialize_when_started(self):
        self._diagnostic(ConnectionStatus("initialize"))
        super()._send_initialize_when_started()

    def _read_stderr(self):
        if self.process is None:
            return
        self._diagnostic_tail = (
            self._diagnostic_tail + bytes(self.process.readAllStandardError())
        )[-8192:]
        status = transport_failure(
            self._diagnostic_tail,
            endpoint_exists=self.connection_target is None
            or self.connection_target.exists,
        )
        if status:
            self._diagnostic(status)

    def _process_finished(self, exit_code=0, *_args):
        self._read_stderr()
        old = self.connection_status
        self._diagnostic(
            ConnectionStatus(
                old.phase if old.code else "transport",
                old.code or "process_exited",
                exit_code,
                old.os_error,
            )
        )
        self._diagnostic_tail = b""
        super()._process_finished(exit_code, *_args)

    def _process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self._diagnostic(ConnectionStatus("starting", "process_start_failed"))
        super()._process_error(error)

    def _request_timed_out(self, identity):
        request = self._pending.get(identity)
        if request and request[0] == "initialize":
            self._diagnostic(ConnectionStatus("initialize", "initialization_timeout"))
        super()._request_timed_out(identity)

    def _clear_server_requests(self, _ready=False):
        self._server_requests.clear()
        self.server_requests_cleared.emit()

    def _handle_message(self, message):
        if isinstance(message, dict) and not isinstance(message.get("id"), bool):
            pending = (
                self._pending.get(message.get("id"))
                if isinstance(message.get("id"), int)
                else None
            )
            if pending and pending[0] == "initialize":
                self._diagnostic(
                    ConnectionStatus("initialize", "initialization_failed")
                    if message.get("error")
                    else ConnectionStatus("ready")
                )
        if (
            isinstance(message, dict)
            and message.get("method") == "serverRequest/resolved"
        ):
            params = message.get("params") or {}
            self._server_requests.pop(params.get("requestId"), None)
        if (
            not isinstance(message, dict)
            or "id" not in message
            or "method" not in message
        ):
            return super()._handle_message(message)
        identity, method = message["id"], message["method"]
        if (
            isinstance(identity, bool)
            or not isinstance(identity, (int, str))
            or not isinstance(method, str)
        ):
            return
        if identity in self._server_requests:
            return
        if len(self._server_requests) >= 32:
            self._set_error("server_request_limit")
            return
        self._server_requests[identity] = method
        self.server_request_received.emit(identity, method, message.get("params"))

    def answer_server_request(self, identity, result: dict) -> bool:
        """Call only with an explicit user decision on this connection's request."""
        process = self.process
        if (
            identity not in self._server_requests
            or process is None
            or not self.ready
            or process.state() != QProcess.ProcessState.Running
        ):
            return False
        encoded = (
            json.dumps(
                {"jsonrpc": "2.0", "id": identity, "result": result},
                separators=(",", ":"),
            )
            + "\n"
        ).encode()
        if process.write(encoded) != len(encoded):
            self._set_error("server_response_uncertain")
            return False
        self._server_requests.pop(identity)
        return True

    def close(self):
        self._clear_server_requests()
        super().close()
        self._diagnostic_tail = b""
