"""Gesture routing stays common and never owns agent or bubble state."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from watched_kettle.app_preferences import ApplicationPreferences
from watched_kettle.application.pet_actions import PetDoubleClickActions
from watched_kettle.application.pet_runtime import PetRuntime
from watched_kettle.application.paths import AppPaths
from watched_kettle.integrations.windows_apps import AppOpenResult
from watched_kettle.pet.idle_controller import IdlePetController
from watched_kettle.pet.window import DesktopPet
from tests.test_pet_preferences import FakeSettings


class GesturePet(QObject):
    double_click_requested = Signal()


class PetActionsTests(unittest.TestCase):
    def setUp(self):
        self.pet = GesturePet()
        self.preferences = ApplicationPreferences(FakeSettings())
        self.home, self.error = Mock(), Mock()
        self.opener = Mock(return_value=AppOpenResult(True))
        self.claude = Mock(return_value=AppOpenResult(True))
        self.actions = PetDoubleClickActions(
            self.pet,
            self.preferences,
            self.home,
            self.error,
            dict(codex=self.opener, claude=self.claude),
        )
        self.addCleanup(self.actions.close)

    def test_default_opens_home_and_wave_only_has_no_navigation(self):
        self.pet.double_click_requested.emit()
        self.home.assert_called_once_with()
        self.preferences.save_double_click_action("wave_only")
        self.pet.double_click_requested.emit()
        self.home.assert_called_once_with()
        self.opener.assert_not_called()
        self.claude.assert_not_called()

    def test_codex_failure_opens_home_with_error_without_changing_choice(self):
        self.preferences.save_double_click_action("codex")
        self.opener.return_value = AppOpenResult(False, "실행 실패")
        self.pet.double_click_requested.emit()
        self.opener.assert_called_once_with()
        self.home.assert_called_once_with()
        self.error.assert_called_once_with("실행 실패")
        self.assertEqual(self.preferences.load_double_click_action(), "codex")

    def test_success_only_opens_codex_and_shutdown_disconnects_once(self):
        self.preferences.save_double_click_action("codex")
        self.pet.double_click_requested.emit()
        self.opener.assert_called_once_with()
        self.home.assert_not_called()
        self.error.assert_not_called()
        self.actions.close()
        self.actions.close()
        self.pet.double_click_requested.emit()
        self.opener.assert_called_once_with()

    def test_claude_opens_only_vscode_and_failure_falls_back_to_home(self):
        self.preferences.save_double_click_action("claude")
        self.pet.double_click_requested.emit()
        self.claude.assert_called_once_with()
        self.opener.assert_not_called()
        self.home.assert_not_called()
        self.claude.return_value = AppOpenResult(False, "실행 실패")
        self.pet.double_click_requested.emit()
        self.home.assert_called_once_with()
        self.error.assert_called_once_with("실행 실패")
        self.assertEqual(self.preferences.load_double_click_action(), "claude")

    def test_default_launchers_are_imported_only_when_their_action_runs(self):
        actions = PetDoubleClickActions(GesturePet(), self.preferences, Mock(), Mock())
        self.addCleanup(actions.close)
        for action, target in (
            ("codex", "watched_kettle.integrations.codex_launcher.open_codex"),
            ("claude", "watched_kettle.integrations.vscode_launcher.open_vscode"),
        ):
            with patch(target, return_value=AppOpenResult(True)) as launcher:
                self.assertTrue(actions.openers[action]().opened)
            launcher.assert_called_once_with()

    def test_preferences_survive_pet_selection_and_reject_unknown_values(self):
        self.preferences.save_double_click_action("codex")
        self.preferences.save_selected_pet_id("different-pet")
        self.assertEqual(
            ApplicationPreferences(
                self.preferences.settings
            ).load_double_click_action(),
            "codex",
        )
        for value in ("unknown", "", None, ["codex"]):
            with self.assertRaises(ValueError):
                self.preferences.save_double_click_action(value)
            self.preferences.settings.setValue("pet/doubleClickAction", value)
            self.assertEqual(
                self.preferences.load_double_click_action(), "settings_home"
            )


class PetOnlyActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_pet_only_runtime_routes_the_gesture_to_home_and_preserves_context_menu(
        self,
    ):
        with TemporaryDirectory() as temporary:
            preferences = ApplicationPreferences(FakeSettings())
            pet = DesktopPet(
                Path("pets/mori-bot"),
                settings=preferences.settings,
                agent_controller_factory=IdlePetController,
            )
            runtime = PetRuntime(self.app, pet, preferences, AppPaths(Path(temporary)))
            try:
                with patch.object(runtime.settings, "_launch"):
                    pet.double_click_requested.emit()
                    self.assertEqual(runtime.settings.route["page"], "home")
                    pet.show_settings()
                    self.assertEqual(runtime.settings.route["page"], "pet")
            finally:
                runtime.close()
                pet.close()
