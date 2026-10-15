import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (
    QApplication,
)

from watched_kettle.application.paths import AppPaths
from watched_kettle.application.runtime import ApplicationRuntime
from watched_kettle.app_preferences import ApplicationPreferences
from watched_kettle.pet.window import DesktopPet
from tests.runtime_support import isolated_codex_server
from tests.test_pet_preferences import FakeSettings


class ApplicationRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.settings = FakeSettings()
        self.pet = DesktopPet(
            Path("pets/mori-bot"),
            settings=self.settings,
        )
        root = Path(self.temp.name)
        self.runtime = ApplicationRuntime(
            self.app,
            self.pet,
            ApplicationPreferences(self.settings),
            AppPaths(root),
            codex_server=isolated_codex_server(root),
        )

    def tearDown(self):
        self.runtime.close()
        self.pet.close()
        self.temp.cleanup()

    def test_pet_routes_settings_through_application_runtime(self):
        center = self.runtime.center
        with patch.object(center, "_launch") as launch:
            self.pet.show_usage()
            self.assertEqual(center.route["page"], "usage")
            self.pet.show_settings()
            self.assertEqual(center.route["page"], "pet")
        self.assertEqual(launch.call_count, 2)

    def test_runtime_start_and_close_are_idempotent(self):
        self.runtime.codex_log_monitor.start = Mock()
        self.runtime.codex_server.start = Mock()
        self.runtime.usage_service.start = Mock()
        self.runtime.start()
        self.runtime.start()
        self.runtime.codex_log_monitor.start.assert_called_once_with()
        self.runtime.codex_server.start.assert_called_once_with()
        self.runtime.usage_service.start.assert_called_once_with()

    def test_runtime_isolates_component_start_failure(self):
        self.runtime.codex_log_monitor.start = Mock(
            side_effect=RuntimeError("log failed")
        )
        self.runtime.codex_server.start = Mock()
        self.runtime.usage_service.start = Mock()
        self.runtime.start()
        self.runtime.codex_server.start.assert_called_once_with()
        self.runtime.usage_service.start.assert_called_once_with()
        self.assertIn("codex_log_monitor", self.runtime.lifecycle_errors)

    def test_injected_server_is_closed_and_its_name_can_be_reused(self):
        server = self.runtime.codex_server
        server_name = server.server_name
        self.assertTrue(server.start(), server.last_error)
        self.runtime.close()

        replacement = isolated_codex_server(
            Path(self.temp.name) / "replacement",
            server_name=server_name,
        )
        try:
            self.assertTrue(replacement.start(), replacement.last_error)
        finally:
            replacement.close()

    def test_isolated_runtime_listens_while_another_endpoint_is_occupied(self):
        occupied_name = f"watched-kettle-occupied-{uuid4().hex}"
        blocker = isolated_codex_server(
            Path(self.temp.name) / "blocker",
            server_name=occupied_name,
        )
        try:
            self.assertTrue(blocker.start(), blocker.last_error)
            self.assertNotEqual(self.runtime.codex_server.server_name, occupied_name)
            self.assertTrue(
                self.runtime.codex_server.start(),
                self.runtime.codex_server.last_error,
            )
        finally:
            blocker.close()


if __name__ == "__main__":
    unittest.main()
