"""Lazy Electron process owner and authenticated, bounded local settings server."""

from __future__ import annotations

from watched_kettle.localization import t

from collections import OrderedDict
from collections.abc import Callable
import hmac
import hashlib
import json
from pathlib import Path
import secrets
import sys
import time
from uuid import uuid4

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer
from PySide6.QtNetwork import QLocalServer
from PySide6.QtWidgets import QMessageBox

from watched_kettle.application.settings_ui.contracts import (
    CommandError,
    MAX_FRAME_BYTES,
    PROTOCOL_VERSION,
    require,
    text,
    wire,
)
from watched_kettle.branding import APP_ICON_PATH
from watched_kettle.integrations.windows_zorder import allow_foreground


ROUTES = {
    # Both editions share the settings home.
    "overview": "home",
    "home": "home",
    "widget_settings": "widget",
    "pet_settings": "pet",
    "pet_appearance": "pet",
    "behavior_display": "pet",
    "usage": "usage",
    "notifications_history": "activity",
    "history": "activity",
    "notifications": "activity",
    "integrations_diagnostics": "integration",
    "diagnostics": "integration",
    "integrations": "integration",
    "app_startup": "app",
    "preferences": "app",
    "startup": "app",
    "bubble": "bubble",
    "about": "about",
}
# A hidden renderer still holds ~225 MiB; a cold reopen takes ~0.5 s (ADR 0004).
HIDDEN_RETIRE_MS = 5 * 60 * 1000
RETIRE_KILL_MS = 3000


class SettingsWindowHost(QObject):
    def __init__(self, adapter, parent=None, executable=None):
        super().__init__(parent)
        self.adapter = adapter
        self.adapter.changed.connect(self._changed)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._connect)
        self.process = QProcess(self)
        self.process.finished.connect(self._process_finished)
        self.process.errorOccurred.connect(self._process_error)
        self.executable = executable
        self.restart: Callable[[], None] | None = None
        self.socket = None
        self.pending_socket = None
        self.buffer = bytearray()
        self.token = ""
        self.name = ""
        self.authenticated = False
        self.visible = False
        self.closed = False
        self.subscriptions = set()
        self.invalidated = set()
        self.responses = OrderedDict()
        self.response_bytes = 0
        self.route = {"page": "pet", "section": "", "navigationId": ""}
        self.navigation = {}
        self.error_dialog = None
        self.flush_timer = QTimer(self)
        self.flush_timer.setSingleShot(True)
        self.flush_timer.setInterval(80)
        self.flush_timer.timeout.connect(self._flush)
        self.handshake_timer = QTimer(self)
        self.handshake_timer.setSingleShot(True)
        self.handshake_timer.timeout.connect(self._disconnect)
        self.retiring = False
        self.pending_open = False
        self.retire_timer = QTimer(self)
        self.retire_timer.setSingleShot(True)
        self.retire_timer.setInterval(HIDDEN_RETIRE_MS)
        self.retire_timer.timeout.connect(self._retire)

    def _start_server(self):
        if self.server.isListening():
            return
        self.name = "watched-kettle-settings-" + uuid4().hex
        self.token = secrets.token_urlsafe(32)
        require(
            self.server.listen(self.name),
            t("message.0571"),
            "connection_failed",
        )

    def open_route(self, route_id="pet_settings", show=True, section=""):
        raw = getattr(route_id, "value", route_id)
        page = ROUTES.get(
            str(raw),
            str(raw)
            if str(raw) in {"pet", "bubble", "app", "activity", "integration", "widget"}
            else "pet",
        )
        assistant_pages = {"usage", "widget", "activity", "integration"}
        if not self.adapter.assistant and page in assistant_pages:
            page = "pet"
        self.route = dict(page=page, section=section, navigationId="")
        if not show:
            return
        if self.closed:
            return
        if self.retiring:
            # The hidden child is exiting; launch a fresh one once it has gone.
            self.pending_open = True
            return
        try:
            self._start_server()
            if self.process.state() == QProcess.ProcessState.NotRunning:
                self._launch()
            elif self.authenticated:
                # The click made this process the foreground one; without the
                # grant Windows only flashes the settings window's taskbar button.
                allow_foreground(self.process.processId())
                self._send(dict(event="navigate", data=self.route))
        except (OSError, CommandError) as error:
            self._show_error(str(error))

    def _launch(self):
        if getattr(sys, "frozen", False):
            root = Path(sys.executable).parent / "settings-ui"
            executable = root / "WatchedKettleSettings.exe"
            arguments = []
        else:
            root = Path(__file__).resolve().parents[3] / "settings-ui"
            executable = root / "node_modules" / "electron" / "dist" / "electron.exe"
            arguments = [str(root)]
        executable = Path(self.executable or executable)
        require(
            executable.is_file(),
            t("message.0572"),
            "ui_missing",
        )
        if arguments:
            require(
                (root / "dist" / "index.html").is_file(),
                t("message.0574"),
                "ui_missing",
            )
        environment = QProcessEnvironment.systemEnvironment()
        environment.remove("ELECTRON_RUN_AS_NODE")
        environment.insert("WATCHED_KETTLE_SETTINGS_PIPE", self.server.fullServerName())
        environment.insert("WATCHED_KETTLE_SETTINGS_TOKEN", self.token)
        environment.insert(
            "WATCHED_KETTLE_SETTINGS_PROFILE",
            str(self.adapter.preferences.settings.fileName()) + ".electron",
        )
        # Source runs use node_modules' electron.exe, which carries Electron's icon.
        if APP_ICON_PATH.is_file():
            environment.insert("WATCHED_KETTLE_SETTINGS_ICON", str(APP_ICON_PATH))
        self.process.setProcessEnvironment(environment)
        self.process.setWorkingDirectory(str(root))
        self.process.setProcessChannelMode(
            QProcess.ProcessChannelMode.ForwardedErrorChannel
        )
        self.process.setStandardOutputFile(QProcess.nullDevice())
        self.process.start(str(executable), arguments)

    def _connect(self):
        while self.server.hasPendingConnections():
            candidate = self.server.nextPendingConnection()
            if self.socket is not None:
                candidate.abort()
                candidate.deleteLater()
                continue
            self.socket = candidate
            self.buffer.clear()
            self.authenticated = False
            candidate.readyRead.connect(self._read)
            candidate.bytesWritten.connect(self._read)
            candidate.disconnected.connect(self._disconnect)
            self.handshake_timer.start(5000)

    def _disconnect(self):
        self.adapter.cancel_pet_import()
        socket, self.socket = self.socket, None
        self.authenticated = False
        self.handshake_timer.stop()
        self.buffer.clear()
        self.subscriptions.clear()
        self.visible = False
        if socket:
            socket.blockSignals(True)
            socket.abort()
            socket.deleteLater()

    def _read(self):
        if self.socket is None:
            return
        self.buffer.extend(bytes(self.socket.readAll()))
        if len(self.buffer) > MAX_FRAME_BYTES:
            self._disconnect()
            return
        for _ in range(32):
            # Large catalog replies must drain before executing another request.
            # bytesWritten resumes buffered input without growing the outbound
            # queue or relaxing the frame/queue limits.
            if self.socket is None or self.socket.bytesToWrite():
                return
            if b"\n" not in self.buffer:
                return
            raw, _, tail = self.buffer.partition(b"\n")
            self.buffer = bytearray(tail)
            try:
                message = json.loads(raw)
                require(isinstance(message, dict))
                if not self.authenticated:
                    require(
                        message.get("version") == PROTOCOL_VERSION
                        and isinstance(message.get("token"), str)
                        and hmac.compare_digest(message["token"], self.token),
                        code="unauthorized",
                    )
                    self.authenticated = True
                    self.handshake_timer.stop()
                    self._send(
                        dict(
                            event="ready",
                            data=dict(
                                version=PROTOCOL_VERSION,
                                edition="pet-assistant"
                                if self.adapter.assistant
                                else "pet-only",
                                route=self.route,
                            ),
                        )
                    )
                    continue
                self._request(message)
            except (ValueError, TypeError, CommandError):
                self._disconnect()
                return
        if b"\n" in self.buffer:
            QTimer.singleShot(0, self._read)

    def _request(self, message):
        request_id = text(message.get("id"), 80)
        method = text(message.get("method"), 80)
        args = message.get("args", {})
        require(isinstance(args, dict))
        fingerprint = hashlib.sha256(
            json.dumps([method, args], sort_keys=True).encode()
        ).hexdigest()
        if request_id in self.responses:
            prior, payload = self.responses[request_id]
            require(prior == fingerprint, code="duplicate_id")
            self._send(payload)
            return
        try:
            data = self._execute(method, args)
            payload = dict(
                id=request_id,
                ok=True,
                result=wire(data),
                epoch=self.adapter.account_epoch,
            )
        except CommandError as error:
            payload = dict(
                id=request_id, ok=False, error=dict(code=error.code, message=str(error))
            )
        except (OSError, ValueError, TypeError, RuntimeError, KeyError, AttributeError):
            payload = dict(
                id=request_id,
                ok=False,
                error=dict(
                    code="operation_failed",
                    message=t("message.0578"),
                ),
            )
        length = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        if length > MAX_FRAME_BYTES - 1:
            payload = dict(
                id=request_id,
                ok=False,
                error=dict(code="response_limit", message=t("message.0577")),
            )
            length = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        self.responses[request_id] = (fingerprint, payload)
        self.response_bytes += length
        while len(self.responses) > 128 or self.response_bytes > 8 * 1024 * 1024:
            _, (_, old) = self.responses.popitem(last=False)
            self.response_bytes -= len(
                json.dumps(old, ensure_ascii=False).encode("utf-8")
            )
        self._send(payload)

    def _execute(self, method, args):
        if method == "window.subscribe":
            topics = args.get("topics", [])
            require(
                isinstance(topics, list)
                and all(item in {"settings", "usage", "activity"} for item in topics)
            )
            self.subscriptions = set(topics)
            return dict(subscribed=True)
        if method == "window.visibility":
            self.visible = args.get("visible") is True
            if not self.visible:
                self.adapter.cancel_pet_import()
                self.subscriptions.clear()
            self._schedule_retire()
            return dict(visible=self.visible)
        if method == "window.state":
            state = args.get("state")
            require(isinstance(state, dict) and len(json.dumps(state)) < 2048)
            self.adapter.preferences.settings.setValue(
                "settingsUI/window", json.dumps(state)
            )
            self.adapter._sync()
            return dict(saved=True)
        if method == "window.restore":
            try:
                return json.loads(
                    str(
                        self.adapter.preferences.settings.value(
                            "settingsUI/window", "{}"
                        )
                    )
                )
            except (ValueError, TypeError):
                return {}
        if method == "navigation.ack":
            target = self.navigation.pop(text(args.get("navigationId"), 80), None)
            valid = bool(
                target
                and self.adapter.assistant
                and self.visible
                and target["epoch"] == self.adapter.account_epoch
                and time.monotonic() <= target["expires"]
            )
            if valid:
                record_id = target["recordId"]
                if record_id:
                    self.adapter.assistant.runtime.notification_service.confirm(
                        record_id
                    )
            return dict(confirmed=valid)
        if method == "file.import":
            return self.adapter.import_element(
                Path(text(args.get("path"), 32768)), text(args.get("kind"), 20)
            )
        if method == "file.pet.prepare":
            return self.adapter.prepare_pet_import(Path(text(args.get("path"), 32768)))
        if method == "file.pet.start":
            require(not self.adapter.pet_batch.running)
            return self.adapter.pet_import.start(
                path=Path(text(args.get("path"), 32768))
            )
        if method == "file.pet.cancel":
            self.adapter.cancel_pet_import()
            return dict(cancelled=True)
        if method == "file.export" and self.adapter.assistant:
            runtime = self.adapter.assistant.runtime
            runtime.diagnostics_exporter.export(
                Path(text(args.get("path"), 32768)),
                runtime.integrations_vm.refresh_requested(),
            )
            return dict(saved=True)
        if method == "app.restart":
            restart = self.restart
            if restart is None:
                raise CommandError("unsupported", t("app.restart_failed"))
            require(
                not self.adapter.pet_batch.running
                and self.adapter.updates.state
                not in {"downloading", "preparing", "installing"},
                t("app.restart_busy"),
                "operation_busy",
            )
            restart()
            return dict(accepted=True)
        if method == "app.quit":
            QTimer.singleShot(0, self.adapter.app.quit)
            return dict(accepted=True)
        return self.adapter.execute(method, args)

    def open_target(self, target):
        # Asynchronous navigation must not be reported as displayed to bubbles.
        if target.kind == "task":
            return False
        page = {
            "usage": "usage",
            "history": "activity",
            "notice": "activity",
            "diagnostics": "integration",
            "projects": "activity",
        }.get(target.kind)
        if page is None:
            return False
        notice = None
        if target.kind == "notice":
            notice = next(
                (
                    row
                    for row in self.adapter.assistant.runtime.notification_service.snapshot.recent
                    if row.record_id == target.identifier
                ),
                None,
            )
            if notice is None:
                return False
        nav = uuid4().hex
        self.navigation.clear()
        self.navigation[nav] = dict(
            epoch=self.adapter.account_epoch,
            expires=time.monotonic() + 30,
            recordId=target.identifier if target.kind in {"notice", "usage"} else "",
        )
        self.open_route(page)
        self.route.update(
            navigationId=nav,
            notice=wire(notice),
            filter=target.identifier if target.kind == "history" else "",
        )
        if self.authenticated:
            self._send(dict(event="navigate", data=self.route))
        return False

    def _send(self, payload):
        if self.socket is None:
            return
        encoded = (
            json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
            + b"\n"
        )
        if (
            len(encoded) > MAX_FRAME_BYTES
            or self.socket.bytesToWrite() > MAX_FRAME_BYTES
        ):
            self._disconnect()
            return
        self.socket.write(encoded)

    def _changed(self, topic):
        if topic == "account":
            self.navigation.clear()
            self.responses.clear()
            self.response_bytes = 0
            self._send(
                dict(
                    event="invalidate",
                    data=dict(topics=["account"], epoch=self.adapter.account_epoch),
                )
            )
        if topic in self.subscriptions:
            self.invalidated.add(topic)
            if not self.flush_timer.isActive():
                self.flush_timer.start()

    def _flush(self):
        if self.invalidated:
            self._send(
                dict(
                    event="invalidate",
                    data=dict(
                        topics=sorted(self.invalidated),
                        epoch=self.adapter.account_epoch,
                    ),
                )
            )
            self.invalidated.clear()

    def show_action_error(self, message):
        self._show_error(message, title=t("double_click.open_failed_title"))

    def _show_error(self, message, title=None):
        if self.error_dialog:
            self.error_dialog.close()
        self.error_dialog = QMessageBox()
        self.error_dialog.setWindowTitle(title or t("message.0573"))
        self.error_dialog.setText(message)
        self.error_dialog.show()

    def _process_error(self, _error):
        if not self.closed and _error == QProcess.ProcessError.FailedToStart:
            self._show_error(t("message.0575"))

    def _schedule_retire(self):
        if self.visible or self.closed:
            self.retire_timer.stop()
        elif self.process.state() != QProcess.ProcessState.NotRunning:
            self.retire_timer.start()

    def _retire(self):
        """Stop a renderer that stayed hidden; the next open starts a new one."""
        if (
            self.visible
            or self.closed
            or self.retiring
            or self.process.state() == QProcess.ProcessState.NotRunning
        ):
            return
        self.retiring = True
        self._send(dict(event="quit", data={}))
        if self.socket:
            self.socket.flush()
        QTimer.singleShot(RETIRE_KILL_MS, self._force_retire)

    def _force_retire(self):
        if self.retiring and self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()

    def _process_finished(self, _code, _status):
        self._disconnect()
        if self.retiring:
            self.retiring = False
            if self.pending_open and not self.closed:
                self.pending_open = False
                try:
                    self._start_server()
                    self._launch()
                except (OSError, CommandError) as error:
                    self._show_error(str(error))
            return
        if not self.closed and _code:
            self._show_error(t("message.0576"))

    def hide(self):
        self.adapter.cancel_pet_import()
        self._send(dict(event="hide", data={}))
        self.visible = False
        self.subscriptions.clear()
        self._schedule_retire()

    def isVisible(self):
        return self.visible

    def shutdown(self):
        self.adapter.pet_batch.shutdown()
        self.closed = True
        self.flush_timer.stop()
        self.retire_timer.stop()
        self.pending_open = False
        self._send(dict(event="quit", data={}))
        if self.socket:
            self.socket.flush()
        if self.process.state() != QProcess.ProcessState.NotRunning:
            if not self.process.waitForFinished(2000):
                self.process.terminate()
                if not self.process.waitForFinished(1000):
                    self.process.kill()
                    self.process.waitForFinished(1000)
        self._disconnect()
        self.server.close()
        if self.error_dialog:
            self.error_dialog.close()

    def close(self):
        self.hide()
