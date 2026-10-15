"""Isolated packaged runtime and optional soak test; never connects to Codex."""

from __future__ import annotations

import argparse
import json
import os
import sys

from watched_kettle.branding import APPLICATION_VERSION
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from uuid import uuid4
from datetime import datetime, timezone


def _resources():
    from watched_kettle.process_metrics import current_resources

    return {
        **current_resources(),
        "process_id": os.getpid(),
        "synthetic_child_processes": 0,
    }


def run_runtime_smoke(arguments):
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-smoke-test", action="store_true")
    parser.add_argument("--duration-seconds", type=int, default=5)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--require-tray", action="store_true")
    parser.add_argument("--exit-via-settings", action="store_true")
    args = parser.parse_args(arguments)
    duration = max(2, min(args.duration_seconds, 24 * 3600))
    previous = {
        key: os.environ.get(key)
        for key in ("LOCALAPPDATA", "CODEX_HOME", "QT_QPA_PLATFORM")
    }
    try:
        with TemporaryDirectory(prefix="watched-kettle-smoke-") as directory:
            root = Path(directory)
            os.environ["LOCALAPPDATA"] = str(root)
            os.environ["CODEX_HOME"] = str(root / "codex")
            os.environ["QT_QPA_PLATFORM"] = "offscreen"
            try:
                return _run(
                    root,
                    duration,
                    args.report,
                    require_tray=args.require_tray,
                    exit_via_settings=args.exit_via_settings,
                )
            except Exception as error:
                _write_report(
                    args.report,
                    {
                        "status": "failed",
                        "app_version": APPLICATION_VERSION,
                        "synthetic_codex": True,
                        "offscreen": True,
                        "tray_required": args.require_tray,
                        "tray_checked": False,
                        "initialization_error": type(error).__name__,
                    },
                )
                return 5
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _write_report(report, state):
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        temporary = report.with_suffix(report.suffix + ".tmp")
        temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
        temporary.replace(report)


def _run(root, duration, report, *, require_tray=False, exit_via_settings=False):
    from PySide6.QtCore import QObject, QSettings, QTimer, Signal, Qt
    from PySide6.QtWidgets import QApplication

    from watched_kettle.application.paths import AppPaths
    from watched_kettle.application.runtime import ApplicationRuntime
    from watched_kettle.app_preferences import ApplicationPreferences
    from watched_kettle.integrations.codex_ipc import CodexHookServer
    from watched_kettle.pet.catalog import discover_pets
    from watched_kettle.pet.window import DesktopPet
    from watched_kettle.application.routes import RouteId
    from watched_kettle.ui.assistant_tray import AssistantSystemTray

    class SyntheticClient(QObject):
        ready_changed = Signal(bool)
        response_received = Signal(int, str, object, object, object)
        notification_received = Signal(str, object)
        error_changed = Signal(str)

        def __init__(self, parent=None):
            super().__init__(parent)
            self.ready = False
            self.next_id = 0
            self.total = 100

        def start(self):
            self.ready = True
            self.ready_changed.emit(True)

        def close(self):
            self.ready = False
            self.ready_changed.emit(False)

        def request(self, method, params=None, timeout_ms=10000):
            if not self.ready:
                return None
            self.next_id += 1
            rid = self.next_id
            if method == "account/read":
                result = {"account": {"type": "chatgpt", "email": None}}
            elif method == "account/rateLimits/read":
                result = {
                    "accountId": "synthetic-smoke-account",
                    "rateLimits": {"primary": {"usedPercent": 20}},
                }
            elif params and params.get("threadId"):
                self.total += 10
                result = {
                    "threadUsage": {
                        "threadId": params["threadId"],
                        "groups": [{"totalTokens": self.total}],
                    }
                }
            else:
                result = {"summary": {"lifetimeTokens": self.total}}
            QTimer.singleShot(
                0,
                lambda: self.response_received.emit(rid, method, params, result, None),
            )
            return rid

    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    bundle_root = Path(__file__).resolve().parent.parent
    entries = discover_pets(bundle_root / "pets") or discover_pets(
        bundle_root / "private-pets"
    )
    if not entries:
        raise RuntimeError("smoke_pet_missing")
    settings = QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat)
    paths = AppPaths(root / "data")
    pet = DesktopPet(
        entries[0].directory,
        settings=settings,
        user_pets_root=paths.user_pets,
        pets_roots=(entries[0].directory.parent,),
    )
    server = CodexHookServer(
        server_name="watched-kettle-smoke-" + uuid4().hex,
        spool_directory=root / "spool",
        hook_config_path=root / "hooks.json",
        global_hook_config_path=root / "global-hooks.json",
        codex_config_path=root / "config.toml",
        hook_health_path=root / "health.json",
        managed_spool_directory=None,
        managed_hook_health_path=None,
    )
    runtime = ApplicationRuntime(
        app,
        pet,
        ApplicationPreferences(settings),
        paths,
        codex_server=server,
        usage_client_factory=SyntheticClient,
        codex_sessions_root=root / "sessions",
        require_tray=require_tray,
    )
    started = monotonic()
    state = {
        "status": "running",
        "app_version": APPLICATION_VERSION,
        "tray_required": require_tray,
        "tray_created": isinstance(runtime.tray, AssistantSystemTray),
        "tray_checked": False,
        "tray_initial_checked": False,
        "lifecycle_errors": {},
        "synthetic_codex": True,
        "offscreen": True,
        "exit_via_settings": exit_via_settings,
        "duration_seconds": duration,
        "ticks": 0,
        "max_event_loop_gap_seconds": 0.0,
    }
    state["initial_resources"] = _resources()
    last = started
    next_sample = started + 10

    def write_report():
        state["latest_resources"] = _resources()
        if isinstance(runtime.tray, AssistantSystemTray):
            from PySide6.QtGui import QAction
            from PySide6.QtWidgets import QMenu

            state["tray_objects"] = (
                {"menus": 0, "actions": 0}
                if runtime.tray._closed
                else {
                    "menus": len(runtime.tray.menu.findChildren(QMenu)),
                    "actions": len(runtime.tray.menu.findChildren(QAction)),
                }
            )
        _write_report(report, state)
        if report:
            with report.with_suffix(".samples.jsonl").open(
                "a", encoding="utf-8"
            ) as stream:
                stream.write(json.dumps(state) + "\n")

    def tick():
        nonlocal last, next_sample
        now = monotonic()
        state["max_event_loop_gap_seconds"] = max(
            state["max_event_loop_gap_seconds"], now - last
        )
        state["elapsed_seconds"] = round(now - started, 3)
        state["ticks"] += 1
        last = now
        index = state["ticks"]
        if index % 20 == 1:
            runtime.coordinator.observe_agent_payload(
                {
                    "source": "codex",
                    "agent_scope": "main",
                    "event": "prompt",
                    "session_id": "smoke-thread",
                    "turn_id": str(index // 20),
                }
            )
        elif index % 20 == 11:
            runtime.coordinator.observe_agent_payload(
                {
                    "source": "codex",
                    "agent_scope": "main",
                    "event": "done",
                    "session_id": "smoke-thread",
                    "turn_id": str(index // 20),
                }
            )
        if require_tray and index % 20 == 0:
            runtime.tray.refresh()
            if runtime.tray.usage_status_action.text() == "Codex 사용량: 잔여 80%":
                state["tray_checked"] = True
        if now >= next_sample:
            write_report()
            next_sample = now + 10
        if now - started >= duration:
            if exit_via_settings:
                if not state.get("quit_requested"):
                    state["pet_visible_at_quit"] = pet.isVisible()
                    state["tray_visible_at_quit"] = (
                        isinstance(runtime.tray, AssistantSystemTray)
                        and runtime.tray.tray.isVisible()
                    )
                    state["quit_requested"] = True
                    # The same host command the settings window's quit button sends.
                    state["settings_quit_accepted"] = runtime.center._execute(
                        "app.quit", {}
                    ) == {"accepted": True}
            else:
                app.quit()

    timer = QTimer()
    timer.setInterval(100)
    timer.setTimerType(Qt.TimerType.PreciseTimer)
    timer.timeout.connect(tick)
    previous_hook = sys.excepthook

    def capture_callback_error(error_type, _error, _traceback):
        state["lifecycle_errors"]["qt_callback"] = error_type.__name__
        state["status"] = "failed"
        write_report()
        # Queue the exit: an exception from aboutToQuit must not recursively quit.
        QTimer.singleShot(0, app.quit)

    sys.excepthook = capture_callback_error
    try:
        if require_tray:
            if not isinstance(runtime.tray, AssistantSystemTray):
                raise RuntimeError("smoke_tray_missing")
            runtime.tray.refresh()
            state["tray_initial_checked"] = (
                runtime.tray.usage_status_action.text() == "Codex 사용량: 확인 불가"
            )
            if not state["tray_initial_checked"]:
                raise RuntimeError("smoke_tray_initial_summary")
        runtime.start()
        runtime.center.open_route(RouteId.USAGE, show=False)
        runtime.center.open_route(RouteId.INTEGRATIONS_DIAGNOSTICS, show=False)
        if exit_via_settings:
            pet.show()
            runtime.center.open_route(RouteId.NOTIFICATIONS_HISTORY, show=False)
            # Closing the settings window must hide it without marking an app exit.
            runtime.center.close()
            state["settings_hide_preserved_runtime"] = (
                not runtime.center.isVisible()
                and not runtime.center.closed
                and not runtime._closed
            )
        started = last = monotonic()
        next_sample = started + 10
        timer.start()
        write_report()
        app.exec()
        # Capture application cleanup before the harness's finally block can mask it.
        state["runtime_closed_on_exit"] = runtime._closed
        state["settings_closed_on_exit"] = runtime.center.closed
        # The bundle drops unused QML modules; the widget must still load.
        state["usage_widget_ready"] = bool(runtime.usage_companion.window.ready)
        state["tray_closed_on_exit"] = (
            isinstance(runtime.tray, AssistantSystemTray)
            and runtime.tray._closed
            and not runtime.tray.tray.isVisible()
        )
        ok = (
            runtime.database.availability.available
            and bool(runtime.usage_service.snapshot.account_hash)
            and not runtime.lifecycle_errors
            and not state["lifecycle_errors"]
            and state["usage_widget_ready"]
            and (not require_tray or state["tray_checked"])
            and state.get("elapsed_seconds", 0) >= duration
            and (
                not exit_via_settings
                or (
                    state.get("settings_quit_accepted")
                    and state.get("settings_hide_preserved_runtime")
                    and state.get("pet_visible_at_quit")
                    and state["runtime_closed_on_exit"]
                    and state["settings_closed_on_exit"]
                    and (
                        not require_tray
                        or (
                            state.get("tray_visible_at_quit")
                            and state["tray_closed_on_exit"]
                        )
                    )
                )
            )
        )
        state["observation_finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        state["status"] = "observation_complete" if ok else "failed"
        state["records"] = len(runtime.usage_service.snapshot.recent_tasks)
        state["storage_available"] = runtime.database.availability.available
    except Exception as error:
        state["status"] = "failed"
        state["lifecycle_errors"]["runtime"] = type(error).__name__
    finally:
        timer.stop()
        for name, callback in (
            ("runtime", runtime.close),
            ("pet", pet.close),
            ("settings", settings.sync),
        ):
            try:
                callback()
            except Exception as error:
                state["lifecycle_errors"]["close:" + name] = type(error).__name__
        state["lifecycle_errors"].update(runtime.lifecycle_errors)
        if state["lifecycle_errors"]:
            state["status"] = "failed"
        state["tray_closed"] = (
            not runtime.tray.tray.isVisible()
            if isinstance(runtime.tray, AssistantSystemTray)
            else False
        )
        if require_tray and not state["tray_closed"]:
            state["status"] = "failed"
        sys.excepthook = previous_hook
        write_report()
    return 0 if state["status"] == "observation_complete" else 5
