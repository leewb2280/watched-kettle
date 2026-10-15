"""Edition and migration checks for the stage-10 split."""

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from PySide6.QtCore import QSettings

from watched_kettle.application.settings_store import migrate_registry_settings


class Stage10BoundaryTests(unittest.TestCase):
    def test_settings_quit_exits_the_runtime_process(self):
        with TemporaryDirectory() as directory:
            report = Path(directory) / "assistant-exit.json"
            environment = dict(os.environ, QT_QPA_PLATFORM="offscreen")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "watched_kettle",
                    "--runtime-smoke-test",
                    "--require-tray",
                    "--exit-via-settings",
                    # The smoke run checks the tray every 2 seconds; a 3-second run
                    # had one chance, which slow CI runners sometimes missed.
                    "--duration-seconds",
                    "6",
                    "--report",
                    str(report),
                ],
                cwd=Path(__file__).resolve().parents[1],
                env=environment,
                capture_output=True,
                timeout=25,
                check=False,
            )
            details = (
                json.loads(report.read_text(encoding="utf-8"))
                if report.exists()
                else {}
            )
            self.assertEqual(
                result.returncode,
                0,
                (result.stderr.decode(errors="replace"), details),
            )
            self.assertEqual(details["status"], "observation_complete")
            self.assertTrue(details["quit_requested"])
            self.assertTrue(details["tray_closed"])
            for observed in (
                "settings_quit_accepted",
                "settings_hide_preserved_runtime",
                "pet_visible_at_quit",
                "tray_visible_at_quit",
                "runtime_closed_on_exit",
                "settings_closed_on_exit",
                "tray_closed_on_exit",
            ):
                self.assertTrue(details[observed], observed)

    def test_pet_only_process_starts_without_assistant_or_database(self):
        with TemporaryDirectory() as directory:
            report = Path(directory) / "smoke.json"
            environment = dict(os.environ, QT_QPA_PLATFORM="offscreen")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "watched_kettle.pet_entrypoint",
                    "--runtime-smoke-test",
                    "--duration-seconds",
                    "2",
                    "--report",
                    str(report),
                ],
                cwd=Path(__file__).resolve().parents[1],
                env=environment,
                capture_output=True,
                timeout=25,
                check=False,
            )
            self.assertEqual(
                result.returncode, 0, result.stderr.decode(errors="replace")
            )
            self.assertEqual(
                json.loads(report.read_text(encoding="utf-8")),
                {
                    "status": "passed",
                    "assistant_imported": False,
                    "db_created": False,
                },
            )

    def test_registry_settings_migrate_once_and_preserve_source(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = QSettings(str(root / "registry.ini"), QSettings.Format.IniFormat)
            legacy.setValue("selectedPetId", "mori-bot-v2")
            legacy.setValue("usage/enabled", False)
            legacy.sync()
            target = root / "new" / "settings.ini"
            self.assertTrue(migrate_registry_settings(target, legacy))
            moved = QSettings(str(target), QSettings.Format.IniFormat)
            self.assertEqual(moved.value("selectedPetId"), "mori-bot-v2")
            self.assertEqual(moved.value("usage/enabled", type=bool), False)
            legacy.setValue("selectedPetId", "changed")
            legacy.sync()
            self.assertTrue(migrate_registry_settings(target, legacy))
            self.assertEqual(moved.value("selectedPetId"), "mori-bot-v2")
