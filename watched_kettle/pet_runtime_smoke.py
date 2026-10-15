"""Isolated packaged smoke for the pet-only runtime."""

import argparse
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory


def run_pet_runtime_smoke(arguments):
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-smoke-test", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--duration-seconds", type=int, default=3)
    args = parser.parse_args(arguments)
    old = {key: os.environ.get(key) for key in ("LOCALAPPDATA", "QT_QPA_PLATFORM")}
    try:
        with TemporaryDirectory(prefix="watched-kettle-pet-only-") as directory:
            os.environ["LOCALAPPDATA"] = directory
            os.environ["QT_QPA_PLATFORM"] = "offscreen"
            from PySide6.QtCore import QSettings, QTimer
            from PySide6.QtWidgets import QApplication

            from watched_kettle.app import resolve_startup_pet
            from watched_kettle.app_preferences import ApplicationPreferences
            from watched_kettle.application.paths import AppPaths
            from watched_kettle.application.pet_runtime import PetRuntime
            from watched_kettle.pet.idle_controller import IdlePetController
            from watched_kettle.pet.window import DesktopPet

            app = QApplication.instance() or QApplication([])
            settings = QSettings(
                str(Path(directory) / "test.ini"), QSettings.Format.IniFormat
            )
            preferences = ApplicationPreferences(settings)
            selected = resolve_startup_pet(preferences=preferences)
            pet = DesktopPet(
                selected,
                settings=settings,
                agent_controller_factory=IdlePetController,
            )
            runtime = PetRuntime(app, pet, preferences, paths=AppPaths.default())
            runtime.start()
            pet.show()
            QTimer.singleShot(max(2, min(args.duration_seconds, 30)) * 1000, app.quit)
            app.exec()
            runtime.close()
            pet.close()
            forbidden = any(
                name.startswith(
                    (
                        "watched_kettle.features.tasks",
                        "watched_kettle.usage",
                        "watched_kettle.integrations.codex_",
                    )
                )
                for name in sys.modules
            )
            db_created = (
                Path(directory) / "WatchedKettle" / "assistant-v1.sqlite3"
            ).exists()
            success = not forbidden and not db_created
            if args.report:
                args.report.write_text(
                    json.dumps(
                        {
                            "status": "passed" if success else "failed",
                            "assistant_imported": forbidden,
                            "db_created": db_created,
                        }
                    ),
                    encoding="utf-8",
                )
            return 0 if success else 5
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
