import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from watched_kettle.ui.menu import PetMenuCommand, show_pet_context_menu
from watched_kettle.ui.pet_controls import ACTION_TEST_STATES, size_label
from watched_kettle.state.presentation import PresentationUpdate
from watched_kettle.ui.pet_controls import tray_status_text


class PetMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_size_labels_distinguish_codex_and_extended_limits(self):
        self.assertEqual(size_label(112), "112px · 기본")
        self.assertEqual(size_label(192), "192px · 원본 크기")
        self.assertEqual(size_label(224), "224px · 표준 최대")
        self.assertEqual(size_label(256), "256px · 확장 크기")
        self.assertEqual(size_label(352), "352px · 확장 최대")

    def test_action_test_maps_all_nine_sprite_states(self):
        self.assertEqual(len(ACTION_TEST_STATES), 9)
        self.assertIn(("기본", "idle"), ACTION_TEST_STATES)
        self.assertIn(("작업 중", "running"), ACTION_TEST_STATES)
        self.assertIn(("검토 중", "review"), ACTION_TEST_STATES)

    def test_context_commands_are_typed_values(self):
        self.assertEqual(
            PetMenuCommand("show_settings").name,
            "show_settings",
        )

    def test_context_menu_toggles_and_resets_usage_widget(self):
        def usage_action(menu, text):
            submenu = next(
                item.menu() for item in menu.actions() if item.text() == "사용량 위젯"
            )
            for item in submenu.actions():
                if item.text() == text:
                    return item
                child = item.menu()
                if child is not None:
                    match = next(
                        (action for action in child.actions() if action.text() == text),
                        None,
                    )
                    if match is not None:
                        return match
            raise AssertionError(text)

        def choose_hidden(menu, _position):
            action = usage_action(menu, "위젯 표시")
            action.setChecked(False)
            return action

        command = show_pet_context_menu(
            None,
            QPoint(),
            "idle",
            True,
            False,
            True,
            usage_widget_available=True,
            usage_widget_visible=True,
            usage_widget_position_customized=True,
            menu_executor=choose_hidden,
        )
        self.assertEqual(command, PetMenuCommand("set_usage_widget_visible", False))

        def choose_today(menu, _position):
            action = usage_action(menu, "오늘 흐름 표시")
            action.setChecked(True)
            return action

        command = show_pet_context_menu(
            None,
            QPoint(),
            "idle",
            True,
            False,
            True,
            usage_widget_available=True,
            usage_widget_visible=True,
            usage_widget_today_visible=False,
            menu_executor=choose_today,
        )
        self.assertEqual(
            command, PetMenuCommand("set_usage_widget_today_visible", True)
        )

        def choose_shape(menu, _position):
            return usage_action(menu, "간단형")

        command = show_pet_context_menu(
            None,
            QPoint(),
            "idle",
            True,
            False,
            True,
            usage_widget_available=True,
            usage_widget_shape="rings",
            menu_executor=choose_shape,
        )
        self.assertEqual(command, PetMenuCommand("set_usage_widget_shape", "chips"))

        def choose_settings(menu, _position):
            return usage_action(menu, "위젯 설정 열기")

        command = show_pet_context_menu(
            None,
            QPoint(),
            "idle",
            True,
            False,
            True,
            usage_widget_available=True,
            menu_executor=choose_settings,
        )
        self.assertEqual(command, PetMenuCommand("show_usage_settings"))

        def choose_reset(menu, _position):
            return usage_action(menu, "펫 옆에 다시 붙이기")

        command = show_pet_context_menu(
            None,
            QPoint(),
            "idle",
            True,
            False,
            True,
            usage_widget_available=True,
            usage_widget_visible=True,
            usage_widget_position_customized=True,
            menu_executor=choose_reset,
        )
        self.assertEqual(command, PetMenuCommand("reset_usage_widget_position"))

    def test_usage_widget_menu_is_disabled_with_usage_assistant(self):
        states = {}

        def inspect_actions(menu, _position):
            usage = next(
                item for item in menu.actions() if item.text() == "사용량 위젯"
            )
            states["submenu"] = usage.isEnabled()
            states.update(
                {
                    item.text(): item.isEnabled()
                    for item in usage.menu().actions()
                    if item.text()
                }
            )
            return None

        show_pet_context_menu(
            None,
            QPoint(),
            "idle",
            True,
            False,
            True,
            usage_widget_available=False,
            usage_widget_visible=True,
            usage_widget_position_customized=True,
            menu_executor=inspect_actions,
        )
        self.assertFalse(states["submenu"])
        self.assertFalse(states["위젯 표시"])
        self.assertFalse(states["링"])
        self.assertFalse(states["펫 옆에 다시 붙이기"])

    def test_tray_uses_readable_codex_and_notification_status(self):
        self.assertEqual(
            tray_status_text(
                PresentationUpdate(
                    state="running",
                    source="codex",
                    active_count=2,
                ),
                "idle",
            ),
            "Codex 작업 중",
        )
        self.assertEqual(
            tray_status_text(
                PresentationUpdate(
                    state="waving",
                    source="notes-app",
                    event="notification",
                ),
                "idle",
            ),
            "알림 표시 중",
        )

    def test_tray_status_names_each_working_agent(self):
        self.assertEqual(
            tray_status_text(None, "running", ("codex", "claude_code")),
            "Codex·Claude Code 작업 중",
        )
        self.assertEqual(
            tray_status_text(
                PresentationUpdate(state="failed", source="claude_code"), "idle"
            ),
            "Claude Code 작업 실패",
        )
        self.assertEqual(tray_status_text(None, "running"), "작업 중")


if __name__ == "__main__":
    unittest.main()
