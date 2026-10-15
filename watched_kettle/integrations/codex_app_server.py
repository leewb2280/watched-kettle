"""Read-only JSON-RPC client for ``codex app-server``."""

from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from watched_kettle.application.logging import log_event


_SAFE_OPERATIONS = frozenset(
    {
        "initialize",
        "account/read",
        "account/rateLimits/read",
        "account/usage/read",
    }
)


def _safe_operation(method):
    method = str(method)
    return method if method in _SAFE_OPERATIONS else "other"


def find_codex_program():
    explicit = os.environ.get("CODEX_EXECUTABLE")
    if explicit and Path(explicit).is_file():
        return explicit
    found = shutil.which("codex")
    if found:
        return found
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates = sorted(
            (Path(local) / "OpenAI" / "Codex" / "bin").glob("*/codex.exe"),
            key=lambda item: item.stat().st_mtime_ns if item.exists() else 0,
            reverse=True,
        )
        if candidates:
            return str(candidates[0])
    return ""


MAX_MESSAGE_BYTES = 4 * 1024 * 1024
MAX_PENDING_REQUESTS = 64
MAX_POOLED_TIMERS = 32


class CodexAppServerClient(QObject):
    """Small fail-open client that only exposes generic JSON-RPC requests."""

    ready_changed = Signal(bool)
    response_received = Signal(int, str, object, object, object)
    notification_received = Signal(str, object)
    error_changed = Signal(str)

    def __init__(
        self,
        parent=None,
        program=None,
        process_factory=QProcess,
        *,
        server_arguments=None,
    ):
        super().__init__(parent)
        self.program = program
        self.process_factory = process_factory
        self.server_arguments = tuple(
            server_arguments or ("app-server", "--listen", "stdio://")
        )
        self.process = None
        self.ready = False
        self.error = ""
        self._buffer = b""
        self._next_id = 1
        self._pending = {}
        self._timer_pool = []
        self._timer_callbacks = {}
        self._closing = False
        self._restart_attempt = 0
        self.rejected_messages = 0
        self._restart_timer = QTimer(self)
        self._restart_timer.setSingleShot(True)
        self._restart_timer.timeout.connect(self.start)

    def start(self):
        self._closing = False
        if (
            self.process is not None
            and self.process.state() != QProcess.ProcessState.NotRunning
        ):
            return
        program = self.program or find_codex_program()
        if not program:
            log_event(
                "integrations.codex_app_server",
                "process_start_failed",
                logging.WARNING,
                error_code="executable_not_found",
            )
            self._set_error("Codex CLI를 찾을 수 없습니다.")
            self._schedule_restart()
            return
        log_event(
            "integrations.codex_app_server",
            "process_start",
            operation="app-server",
            attempt=self._restart_attempt + 1,
        )
        self._buffer = b""
        process = self.process_factory(self)
        self.process = process
        process.readyReadStandardOutput.connect(
            lambda p=process: self._read_stdout() if self.process is p else None
        )
        process.readyReadStandardError.connect(
            lambda p=process: self._read_stderr() if self.process is p else None
        )
        process.started.connect(
            lambda p=process: self._send_initialize_when_started()
            if self.process is p
            else None
        )
        process.finished.connect(
            lambda *args, p=process: self._process_finished(*args)
            if self.process is p
            else None
        )
        process.errorOccurred.connect(
            lambda error, p=process: self._process_error(error)
            if self.process is p
            else None
        )
        process.setProgram(program)
        process.setArguments(list(self.server_arguments))
        process.start()

    def close(self):
        self._closing = True
        self._restart_timer.stop()
        self._set_ready(False)
        self._fail_pending("사용량 서비스를 종료했습니다.")
        process = self.process
        self.process = None
        if process is not None and process.state() != QProcess.ProcessState.NotRunning:
            process.terminate()
            if not process.waitForFinished(1000):
                process.kill()
                process.waitForFinished(1000)
        if process is not None:
            self._dispose_process(process)
        self._buffer = b""

    def request(self, method, params=None, timeout_ms=10_000):
        process = self.process
        if process is None or process.state() != QProcess.ProcessState.Running:
            return None
        if len(self._pending) >= MAX_PENDING_REQUESTS:
            log_event(
                "integrations.codex_app_server",
                "request_rejected",
                logging.WARNING,
                operation=_safe_operation(method),
                error_code="pending_limit",
            )
            self._set_error("app_server_request_limit")
            return None
        request_id = self._next_id
        self._next_id += 1
        reused_timer = bool(self._timer_pool)
        timer = self._timer_pool.pop() if reused_timer else QTimer(self)
        timer.setSingleShot(True)

        def callback(rid=request_id):
            self._request_timed_out(rid)

        self._timer_callbacks[timer] = callback
        timer.timeout.connect(callback)
        self._pending[request_id] = (str(method), params, timer)
        message = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": str(method),
            "params": {} if params is None else params,
        }
        process.write(
            (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")
        )
        timer.start(max(1, int(timeout_ms)))
        return request_id

    def _send_initialize_when_started(self):
        process = self.process
        if process is None:
            return
        request_id = self.request(
            "initialize",
            {
                "clientInfo": {"name": "Watched Kettle", "version": "1"},
                "capabilities": {"experimentalApi": True},
            },
            10_000,
        )
        if request_id is not None:
            log_event(
                "integrations.codex_app_server",
                "initialize_sent",
                operation="initialize",
                request_id=request_id,
            )
            self._pending[request_id] = (*self._pending[request_id], "initialize")

    def _read_stdout(self):
        process = self.process
        if process is None:
            return
        self.feed_bytes(bytes(process.readAllStandardOutput()))

    def feed_bytes(self, chunk):
        """Parse complete JSONL records; public to enable transport tests."""
        for part in bytes(chunk).splitlines(keepends=True):
            if len(self._buffer) + len(part) > MAX_MESSAGE_BYTES:
                self.rejected_messages += 1
                self._buffer = b""
                self._set_error("app_server_message_limit")
                if self.process is not None:
                    self.process.kill()
                self._fail_pending("app_server_message_limit")
                return
            self._buffer += part
            self._parse_buffer()

    def _parse_buffer(self):
        while b"\n" in self._buffer:
            line, self._buffer = self._buffer.split(b"\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, ValueError, TypeError):
                self._set_error("Codex App Server가 잘못된 응답을 보냈습니다.")
                continue
            self._handle_message(message)

    def _handle_message(self, message):
        if not isinstance(message, dict):
            return
        if "id" in message and "method" in message:
            self.rejected_messages += 1
            self._set_error("unsupported_server_request")
            if self.process is not None:
                self.process.write(
                    (
                        json.dumps(
                            {
                                "jsonrpc": "2.0",
                                "id": message["id"],
                                "error": {
                                    "code": -32601,
                                    "message": "Read-only client: request unsupported",
                                },
                            }
                        )
                        + "\n"
                    ).encode("utf-8")
                )
            return
        if "id" in message:
            if isinstance(message["id"], bool) or not isinstance(message["id"], int):
                return
            try:
                request_id = int(message["id"])
            except (TypeError, ValueError):
                return
            pending = self._pending.pop(request_id, None)
            if pending is None:
                return
            method, params, timer, *markers = pending
            timer.stop()
            self._release_timer(timer)
            result = message.get("result")
            error = message.get("error")
            if markers and markers[-1] == "initialize" and error is None:
                log_event(
                    "integrations.codex_app_server",
                    "initialize_succeeded",
                    operation="initialize",
                    request_id=request_id,
                )
                self._send_notification("initialized", {})
                self._restart_attempt = 0
                self._set_error("")
                self._set_ready(True)
            elif markers and markers[-1] == "initialize":
                log_event(
                    "integrations.codex_app_server",
                    "initialize_failed",
                    logging.WARNING,
                    operation="initialize",
                    request_id=request_id,
                    error_code="server_error",
                )
                self._set_error("Codex App Server 초기화에 실패했습니다.")
                if self.process is not None:
                    self.process.kill()
            self.response_received.emit(request_id, method, params, result, error)
            return
        method = message.get("method")
        if isinstance(method, str):
            self.notification_received.emit(method, message.get("params"))

    def _send_notification(self, method, params=None):
        process = self.process
        if process is None or process.state() != QProcess.ProcessState.Running:
            return
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        process.write(
            (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")
        )

    def _request_timed_out(self, request_id):
        pending = self._pending.pop(request_id, None)
        if pending is None:
            return
        method, params, timer, *markers = pending
        timer.stop()
        self._release_timer(timer)
        error = {"code": "timeout", "message": f"{method} 요청 시간이 초과되었습니다."}
        log_event(
            "integrations.codex_app_server",
            "request_timeout",
            logging.WARNING,
            operation=_safe_operation(method),
            request_id=request_id,
            error_code="timeout",
        )
        self.response_received.emit(request_id, method, params, None, error)
        self._set_error(error["message"])
        if markers and markers[-1] == "initialize" and self.process is not None:
            self.process.kill()

    def _read_stderr(self):
        process = self.process
        if process is None:
            return
        # App Server writes normal tracing logs to stderr. Consume them without
        # exposing local paths or treating healthy diagnostics as a failure.
        process.readAllStandardError()

    def _process_error(self, _error):
        log_event(
            "integrations.codex_app_server",
            "process_error",
            logging.WARNING,
            error_code=(getattr(_error, "name", None) or "process_error"),
        )
        self._set_error("Codex App Server 프로세스 오류가 발생했습니다.")
        if _error == QProcess.ProcessError.FailedToStart:
            self._set_ready(False)
            self._fail_pending("Codex App Server를 시작하지 못했습니다.")
            process, self.process = self.process, None
            if process is not None:
                self._dispose_process(process)
            if not self._closing:
                self._schedule_restart()

    def _process_finished(self, *_args):
        exit_code = _args[0] if _args and isinstance(_args[0], int) else None
        log_event(
            "integrations.codex_app_server",
            "process_finished",
            logging.WARNING if not self._closing else logging.INFO,
            exit_code=exit_code,
        )
        self._set_ready(False)
        self._fail_pending("Codex App Server 연결이 종료되었습니다.")
        process, self.process = self.process, None
        if process is not None:
            self._dispose_process(process)
        self._buffer = b""
        if not self._closing:
            self._schedule_restart()

    def _fail_pending(self, message):
        for request_id, pending in tuple(self._pending.items()):
            method, params, timer, *_ = pending
            timer.stop()
            self._release_timer(timer)
            self.response_received.emit(
                request_id, method, params, None, {"code": "closed", "message": message}
            )
        self._pending.clear()

    @staticmethod
    def _dispose_process(process):
        for signal in (
            process.started,
            process.finished,
            process.errorOccurred,
            process.readyReadStandardOutput,
            process.readyReadStandardError,
        ):
            try:
                signal.disconnect()
            except (RuntimeError, TypeError):
                pass
        process.deleteLater()

    def _release_timer(self, timer):
        timer.stop()
        callback = self._timer_callbacks.pop(timer, None)
        if callback is not None:
            timer.timeout.disconnect(callback)
        if len(self._timer_pool) < MAX_POOLED_TIMERS:
            self._timer_pool.append(timer)
        else:
            timer.deleteLater()

    def _schedule_restart(self):
        delays = (5_000, 15_000, 60_000, 300_000)
        delay = delays[min(self._restart_attempt, len(delays) - 1)]
        self._restart_attempt += 1
        log_event(
            "integrations.codex_app_server",
            "restart_scheduled",
            logging.WARNING,
            attempt=self._restart_attempt,
            delay_ms=delay,
        )
        self._restart_timer.start(delay)

    def _set_ready(self, ready):
        ready = bool(ready)
        if ready != self.ready:
            self.ready = ready
            log_event(
                "integrations.codex_app_server",
                "ready_changed",
                state="ready" if ready else "offline",
                ready=ready,
            )
            self.ready_changed.emit(ready)

    def _set_error(self, message):
        message = str(message or "")
        if message != self.error:
            self.error = message
            self.error_changed.emit(message)
