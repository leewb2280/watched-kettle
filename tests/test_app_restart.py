"""Edition-preserving restart, detached processes and language reload."""

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from watched_kettle.application.restart import (
    AppRestart,
    REOPEN_SETTINGS_FLAG,
    consume_restart_route,
)


class AppRestartTests(unittest.TestCase):
    def test_source_restart_preserves_edition_arguments_and_working_directory(self):
        for pet_only, entry in ((False, "main.py"), (True, "main_pet_only.py")):
            with self.subTest(pet_only=pet_only):
                with (
                    patch.object(sys, "frozen", False, create=True),
                    patch.object(sys, "argv", ["original", "한글 펫 경로"]),
                ):
                    restart = AppRestart(SimpleNamespace(), pet_only=pet_only)
                self.assertEqual(restart.program, sys.executable)
                self.assertEqual(Path(restart.arguments[0]).name, entry)
                self.assertTrue(Path(restart.arguments[0]).is_absolute())
                self.assertEqual(
                    restart.arguments[1:], ["한글 펫 경로", REOPEN_SETTINGS_FLAG]
                )
                self.assertEqual(restart.directory, str(Path.cwd()))

    def test_frozen_restart_uses_same_runtime_and_independent_environment(self):
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "argv", ["WatchedKettle.exe", "pet path"]),
            patch("watched_kettle.application.restart.QProcess") as factory,
        ):
            process = factory.return_value
            process.startDetached.return_value = True
            restart = AppRestart(SimpleNamespace(), pet_only=True)
            self.assertTrue(restart.launch())
            process.setProgram.assert_called_once_with(sys.executable)
            process.setArguments.assert_called_once_with(
                ["pet path", REOPEN_SETTINGS_FLAG]
            )
            environment = process.setProcessEnvironment.call_args.args[0]
            self.assertEqual(environment.value("PYINSTALLER_RESET_ENVIRONMENT"), "1")

    def test_repeated_request_queues_only_one_normal_quit(self):
        app = SimpleNamespace(quit=Mock())
        with patch("watched_kettle.application.restart.QTimer.singleShot") as timer:
            restart = AppRestart(app)
            restart.request()
            restart.request()
        timer.assert_called_once_with(0, app.quit)
        self.assertTrue(restart.requested)
        app.quit.assert_not_called()

    def test_failed_detached_launch_is_reported(self):
        with patch("watched_kettle.application.restart.QProcess") as factory:
            factory.return_value.startDetached.return_value = False
            self.assertFalse(AppRestart(SimpleNamespace()).launch())

    def test_internal_route_flag_is_consumed_before_pet_directory_parsing(self):
        arguments = ["main.py", "한글 펫 경로", REOPEN_SETTINGS_FLAG]
        self.assertTrue(consume_restart_route(arguments))
        self.assertEqual(arguments, ["main.py", "한글 펫 경로"])
        self.assertFalse(consume_restart_route(arguments))

    def test_detached_child_can_take_released_instance_and_read_saved_language(self):
        # Real separate Qt processes, isolated INI and IPC; no user app/runtime.
        helper = """
import json, os, sys
from pathlib import Path
from PySide6.QtCore import QCoreApplication, QSettings, QTimer
from watched_kettle.application.restart import AppRestart, REOPEN_SETTINGS_FLAG
from watched_kettle.integrations.single_instance import SingleInstanceCoordinator
from watched_kettle.app_preferences import ApplicationPreferences
from watched_kettle.application.paths import AppPaths
from watched_kettle.application.localization import initialize_language
app = QCoreApplication([])
root = Path(sys.argv[1])
name = sys.argv[2]
coordinator = SingleInstanceCoordinator(name)
primary = coordinator.start()
assert primary
settings = QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat)
preferences = ApplicationPreferences(settings)
if REOPEN_SETTINGS_FLAG in sys.argv:
    language = initialize_language(preferences, AppPaths(root)).active.pack_id
    (root / "child.tmp").write_text(json.dumps(dict(
        language=language, primary=primary, cleaned=(root / "cleaned").exists(),
        pid=os.getpid(), reopened=True,
    )), encoding="utf-8")
    os.replace(root / "child.tmp", root / "child.json")
    coordinator.close()
else:
    settings.setValue("app/languagePack", "official.en")
    settings.sync()
    restart = AppRestart(app)
    restart.arguments = [__file__, str(root), name, REOPEN_SETTINGS_FLAG]
    QTimer.singleShot(0, restart.request)
    app.exec()
    coordinator.close()
    (root / "cleaned").write_text("closed", encoding="utf-8")
    assert restart.launch()
"""
        from uuid import uuid4

        with TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "restart-probe.py"
            script.write_text(helper, encoding="utf-8")
            result = root / "child.json"
            environment = {
                **os.environ,
                "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
                "QT_QPA_PLATFORM": "offscreen",
            }
            parent = subprocess.Popen(
                [sys.executable, str(script), str(root), "restart-" + uuid4().hex],
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            stdout, stderr = parent.communicate(timeout=15)
            self.assertEqual(parent.returncode, 0, (stdout, stderr))
            deadline = time.monotonic() + 10
            while not result.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(result.is_file(), "Detached child did not report")
            child = json.loads(result.read_text(encoding="utf-8"))
            self.assertTrue(child["primary"])
            self.assertTrue(child["cleaned"])
            self.assertTrue(child["reopened"])
            self.assertEqual(child["language"], "official.en")
            self.assertNotEqual(child["pid"], parent.pid)
