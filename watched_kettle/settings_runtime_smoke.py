"""Packaged Electron lifecycle probe with temporary application settings."""

import argparse
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic


def run_settings_smoke(arguments, runtime_factory, agent_controller_factory):
    parser = argparse.ArgumentParser()
    parser.add_argument("--settings-ui-smoke-test", action="store_true")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(arguments)
    previous_local = os.environ.get("LOCALAPPDATA")
    result = {"status": "failed", "phases": []}
    try:
        with TemporaryDirectory(prefix="watched-kettle-electron-smoke-") as directory:
            os.environ["LOCALAPPDATA"] = directory
            from PySide6.QtCore import QProcess, QSettings, QTimer
            from PySide6.QtWidgets import QApplication
            from watched_kettle.app import resolve_startup_pet
            from watched_kettle.app_preferences import ApplicationPreferences
            from watched_kettle.application.paths import AppPaths
            from watched_kettle.pet.window import DesktopPet

            app = QApplication.instance() or QApplication([])
            app.setQuitOnLastWindowClosed(False)
            settings = QSettings(
                str(Path(directory) / "settings.ini"), QSettings.Format.IniFormat
            )
            preferences = ApplicationPreferences(settings)
            pet = DesktopPet(
                resolve_startup_pet(preferences=preferences),
                settings=settings,
                agent_controller_factory=agent_controller_factory,
            )
            runtime = runtime_factory(app, pet, preferences, AppPaths(Path(directory)))
            host = getattr(runtime, "center", None) or runtime.settings
            host.process.finished.connect(
                lambda code, status: result.setdefault("exits", []).append(
                    dict(code=code, status=str(status))
                )
            )
            host.process.errorOccurred.connect(
                lambda error: result.setdefault("process_errors", []).append(str(error))
            )
            started = monotonic()
            phase = 0
            first_pid = 0

            def step():
                nonlocal phase, first_pid
                if monotonic() - started > 35:
                    result["connection"] = dict(
                        authenticated=host.authenticated,
                        visible=host.visible,
                        subscriptions=sorted(host.subscriptions),
                        state=str(host.process.state()),
                        error=host.process.errorString(),
                    )
                    result["error"] = "lifecycle_timeout"
                    app.quit()
                elif (
                    phase == 0
                    and host.authenticated
                    and host.visible
                    and "settings" in host.subscriptions
                ):
                    first_pid = host.process.processId()
                    result["first_open_ms"] = round((monotonic() - started) * 1000)
                    result["phases"].append("renderer_ready")
                    host.hide()
                    phase = 1
                elif phase == 1 and not host.visible:
                    result["phases"].append("hidden")
                    host.open_route("pet_settings")
                    phase = 2
                elif phase == 2 and host.visible and "settings" in host.subscriptions:
                    if host.process.processId() != first_pid:
                        result["error"] = "unexpected_process_replacement"
                        app.quit()
                        return
                    result["phases"].append("reused_process")
                    host.process.kill()
                    phase = 3
                elif (
                    phase == 3
                    and host.process.state() == QProcess.ProcessState.NotRunning
                ):
                    host.open_route("app_startup")
                    phase = 4
                elif (
                    phase == 4
                    and host.authenticated
                    and host.visible
                    and "settings" in host.subscriptions
                ):
                    result["phases"].append("recovered_after_kill")
                    phase = 5
                    host._execute("app.quit", {})

            timer = QTimer()
            timer.timeout.connect(step)
            timer.start(50)
            host.open_route("pet_settings")
            try:
                app.exec()
            finally:
                runtime.close()
                pet.close()
                timer.stop()
            result["child_stopped"] = (
                host.process.state() == QProcess.ProcessState.NotRunning
            )
            result["runtime_closed"] = runtime._closed
            result["status"] = (
                "passed"
                if phase == 5 and result["child_stopped"] and runtime._closed
                else "failed"
            )
    except Exception as error:
        result["error"] = type(error).__name__ + ": " + str(error)
    finally:
        if previous_local is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = previous_local
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0 if result["status"] == "passed" else 1
