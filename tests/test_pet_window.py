import json
import os
import shutil
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from watched_kettle.config import FRAME_HEIGHT, FRAME_WIDTH
from watched_kettle.app_preferences import ApplicationPreferences
from watched_kettle.application.paths import AppPaths
from watched_kettle.application.runtime import ApplicationRuntime
from watched_kettle.features.notifications.service import NotificationService
from watched_kettle.features.pet.viewmodel import PetViewModel
from watched_kettle.features.usage.viewmodel import UsageViewModel
from watched_kettle.integrations.windows_startup import StartupRegistrationStatus
from watched_kettle.pet.window import DesktopPet
from watched_kettle.pet.placement import create_saved_placement
from watched_kettle.ui.assistant_tray import AssistantSystemTray
from watched_kettle.ui.menu import PetMenuCommand
from watched_kettle.ui.pet_controls import STATE_LABELS
from watched_kettle.ui.speech_bubble import BUBBLE_TAIL_SIZE
from watched_kettle.ui.speech_bubble_paint import bubble_frame_insets
from watched_kettle.pet.bubble_theme import (
    DEFAULT_BUBBLE_THEME,
    bubble_theme_from_manifest,
)
from watched_kettle.usage.models import (
    AccountUsageSummary,
    DailyUsageBucket,
    RateLimitBucket,
    TaskUsageRecord,
    UsageAvailability,
    UsageSnapshot,
    UsageWindow,
)
from tests.runtime_support import isolated_codex_server
from tests.test_pet_preferences import FakeSettings


# Public pet copies stand in for the original character packs in these tests.
FIXTURE_PET_MANIFESTS = {
    "sample-main": {
        "displayName": "Sample Main",
        "mirrorRightLookFromLeft": True,
        "bubbleTheme": {"tail": "none"},
    },
    "sample-second": {
        "displayName": "Sample Second.",
        "bubbleTheme": {"background": "#ffeedd", "shape": "cloud"},
    },
}
_fixture_pets = None


def setUpModule():
    global _fixture_pets
    _fixture_pets = TemporaryDirectory()
    source = Path("pets/mori-bot")
    base = json.loads((source / "pet.json").read_text(encoding="utf-8"))
    for pet_id, overrides in FIXTURE_PET_MANIFESTS.items():
        pet = Path(_fixture_pets.name, pet_id)
        pet.mkdir()
        shutil.copyfile(source / "spritesheet.webp", pet / "spritesheet.webp")
        manifest = {**base, "id": pet_id, **overrides}
        (pet / "pet.json").write_text(json.dumps(manifest), encoding="utf-8")


def tearDownModule():
    _fixture_pets.cleanup()


def fixture_pet(pet_id="sample-main"):
    return Path(_fixture_pets.name, pet_id)


class FakeStartupRegistration:
    def __init__(self, enabled=False, matches=True):
        self.enabled = enabled
        self.matches = matches
        self.changes = []

    def inspect(self):
        return StartupRegistrationStatus(
            supported=True,
            enabled=self.enabled,
            matches_current_app=self.enabled and self.matches,
            expected_command='"C:\\Assistant\\pet.exe"',
            current_command=(
                '"C:\\Assistant\\pet.exe"' if self.matches else '"C:\\Old\\pet.exe"'
            )
            if self.enabled
            else "",
        )

    def set_enabled(self, enabled):
        self.changes.append(bool(enabled))
        self.enabled = bool(enabled)
        self.matches = True
        return self.inspect()


class FakeUsageService(QObject):
    snapshot_changed = Signal(object)
    availability_changed = Signal(object)
    assistant_notice_ready = Signal(dict)

    def __init__(self):
        super().__init__()
        now = datetime.now(timezone.utc)
        self.enabled = True
        self.quiet_summary_enabled = True
        self.snapshot = UsageSnapshot(
            availability=UsageAvailability("available", "사용 가능"),
            buckets=(
                RateLimitBucket("five", "5시간", primary=UsageWindow(40, 60, 300, now)),
            ),
            summary=AccountUsageSummary(peak_daily_tokens=2000, current_streak_days=3),
            daily_buckets=(DailyUsageBucket(date.today(), 1000),),
            recent_tasks=(
                TaskUsageRecord(now, "account", "thread", "done", total_tokens=250),
            ),
            last_updated_at=now,
        )
        self.refreshed = False

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)

    def set_quiet_summary_enabled(self, enabled):
        self.quiet_summary_enabled = bool(enabled)

    def refresh(self, force=False):
        self.refreshed = bool(force)
        return True

    def clear_history(self):
        self.snapshot = UsageSnapshot()
        return True

    def tray_summary(self):
        return "잔여 60%"


class DesktopPetStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.settings = FakeSettings()
        self.runtime = None
        self.runtime_temp = None
        self.startup_registration = FakeStartupRegistration()
        self.pet = DesktopPet(
            fixture_pet(),
            settings=self.settings,
        )

    def tearDown(self):
        if self.runtime is not None:
            self.runtime.close()
        self.pet.close()
        if self.runtime_temp is not None:
            self.runtime_temp.cleanup()

    def create_runtime(self):
        """Compose UI tests through the production application boundary."""
        self.runtime_temp = TemporaryDirectory()
        root = Path(self.runtime_temp.name)
        self.runtime = ApplicationRuntime(
            self.app,
            self.pet,
            ApplicationPreferences(self.settings),
            AppPaths(root),
            codex_server=isolated_codex_server(root),
        )
        self.runtime.startup_registration = self.startup_registration
        self.runtime.settings_vm.startup_registration = self.startup_registration
        return self.runtime

    def create_tray(self, service=None):
        """Create the application-owned tray against feature view models."""
        usage_service = service or FakeUsageService()
        tray = AssistantSystemTray(
            PetViewModel(self.pet),
            UsageViewModel(usage_service, ApplicationPreferences(self.settings)),
            NotificationService(),
            lambda _route: None,
            self.pet.frames["idle"][0],
        )
        self.addCleanup(tray.close)
        return tray

    def test_non_idle_state_suspends_pointer_look(self):
        self.pet.look_direction_index = 4
        self.pet.set_state("running")

        self.assertIsNone(self.pet.look_direction_index)
        self.assertEqual(self.pet.current_state, "running")

    def test_mirror_manifest_uses_mirrored_right_pose_family(self):
        self.assertTrue(self.pet.manifest.get("mirrorRightLookFromLeft"))
        self.assertFalse(self.pet.look_direction_mirrored)
        self.assertEqual(self.pet.look_direction_offset, 0)

    def test_double_click_wave_returns_to_idle(self):
        self.pet.double_click_waving = True
        self.pet.set_state("waving")
        self.pet.finish_waving()

        self.assertFalse(self.pet.double_click_waving)
        self.assertEqual(self.pet.current_state, "idle")

    def test_left_double_click_waves_and_requests_one_action(self):
        event = Mock()
        event.button.return_value = Qt.MouseButton.LeftButton
        action = Mock()
        self.pet.double_click_requested.connect(action)
        self.pet.mouseDoubleClickEvent(event)
        action.assert_called_once_with()
        event.accept.assert_called_once_with()
        self.assertTrue(self.pet.double_click_waving)
        self.assertEqual(self.pet.current_state, "waving")
        self.pet.double_click_requested.disconnect(action)

    def test_right_double_click_does_not_request_action(self):
        event = Mock()
        event.button.return_value = Qt.MouseButton.RightButton
        action = Mock()
        self.pet.double_click_requested.connect(action)
        self.pet.mouseDoubleClickEvent(event)
        action.assert_not_called()
        event.accept.assert_not_called()
        self.assertFalse(self.pet.double_click_waving)
        self.pet.double_click_requested.disconnect(action)

    def test_double_click_does_not_replace_project_bubbles_with_preview(self):
        event = Mock()
        event.button.return_value = Qt.MouseButton.LeftButton
        with patch.object(self.pet.bubble_controller, "preview") as preview:
            self.pet.mouseDoubleClickEvent(event)
        preview.assert_not_called()
        self.assertEqual(self.pet.current_state, "waving")

    def test_stale_wave_callback_does_not_override_new_state(self):
        self.pet.double_click_waving = True
        self.pet.set_state("waving")
        self.pet.set_state("review")
        self.pet.finish_waving()

        self.assertEqual(self.pet.current_state, "review")

    def test_agent_session_start_changes_visible_state(self):
        result = self.pet.apply_agent_payload(
            {
                "source": "codex",
                "event": "SessionStart",
                "session_id": "one",
            }
        )

        self.assertEqual(result.aggregate.state, "running")
        self.assertEqual(self.pet.current_state, "running")

    def test_agent_thinking_and_permission_change_visible_state(self):
        self.pet.apply_agent_payload(
            {
                "source": "codex",
                "event": "thinking",
                "session_id": "one",
            }
        )
        self.assertEqual(self.pet.current_state, "running")

        self.pet.apply_agent_payload(
            {
                "source": "codex",
                "event": "PermissionRequest",
                "approval_actor": "user",
                "session_id": "one",
            }
        )
        self.assertEqual(self.pet.current_state, "waiting")

    def test_important_agent_changes_use_bubble_but_tool_events_do_not_replace_it(self):
        self.pet.show()
        self.app.processEvents()
        self.pet.apply_agent_payload(
            {
                "source": "codex",
                "event": "UserPromptSubmit",
                "session_id": "one",
            }
        )
        first_message = self.pet.bubble_controller.window.message

        self.assertTrue(self.pet.bubble_controller.window.isVisible())
        self.assertIn("작업", first_message)

        self.pet.apply_agent_payload(
            {
                "source": "codex",
                "event": "PreToolUse",
                "session_id": "one",
            }
        )

        self.assertEqual(self.pet.bubble_controller.window.message, first_message)

    def test_todo_notice_returns_to_persistent_waiting_bubble(self):
        self.pet.show()
        self.app.processEvents()
        self.pet.apply_agent_payload(
            {
                "source": "codex",
                "event": "PermissionRequest",
                "approval_actor": "user",
                "session_id": "one",
            }
        )
        waiting_message = self.pet.bubble_controller.window.message

        self.pet.apply_agent_payload(
            {
                "source": "notes-app",
                "event": "notification",
                "session_id": "todo-one",
                "message": "오늘 일정이 있어요",
            }
        )
        visible_messages = {
            window.message for window in self.pet.bubble_controller.visible_windows
        }
        self.assertIn("오늘 일정이 있어요", visible_messages)
        self.assertIn(waiting_message, visible_messages)

        self.pet.bubble_controller.finish_transient()

        self.assertEqual(
            self.pet.bubble_controller.window.message,
            waiting_message,
        )
        self.assertTrue(self.pet.bubble_controller.window.isVisible())

    def test_assistant_summary_exposes_counts_without_message_text(self):
        self.pet.apply_agent_payload(
            {
                "source": "codex",
                "event": "PermissionRequest",
                "approval_actor": "user",
                "session_id": "one",
                "message": "민감한 확인 원문",
            }
        )
        self.pet.apply_agent_payload(
            {
                "source": "notes-app",
                "event": "notification",
                "session_id": "todo-one",
                "message": "민감한 일정 원문",
            }
        )

        summary = self.pet.bubble_controller.assistant_summary
        self.assertIn("확인 1건", summary)
        self.assertIn("알림 1건", summary)
        self.assertNotIn("민감한", summary)

    def test_schedule_bubbles_and_history_use_urgency_and_safe_label(self):
        self.pet.show()
        self.app.processEvents()
        self.pet.apply_agent_payload(
            {
                "source": "schedule",
                "event": "notification",
                "session_id": "later",
                "urgency": "low",
                "message": "나중 일정",
            }
        )
        self.pet.apply_agent_payload(
            {
                "source": "calendar",
                "event": "ScheduleDue",
                "session_id": "soon",
                "urgency": "high",
                "message": "곧 시작하는 일정",
            }
        )

        self.assertEqual(
            self.pet.bubble_controller.window.message,
            "곧 시작하는 일정",
        )
        self.assertEqual(
            self.pet.bubble_controller.recent_history[0].summary,
            "일정 알림 1건",
        )
        self.assertNotIn(
            "곧 시작하는 일정",
            repr(self.pet.bubble_controller.recent_history),
        )

        self.pet.bubble_controller.finish_transient()

        for window in self.pet.bubble_controller._window_pool:
            self.assertEqual(window.message, "")
            self.assertEqual(window.accessibleName(), "")

    def test_removed_bubble_scrubs_raw_text_before_window_reuse(self):
        raw_message = "메모리에 남으면 안 되는 일정 제목"
        self.pet.apply_agent_payload(
            {
                "source": "schedule",
                "event": "notification",
                "session_id": "private",
                "message": raw_message,
            }
        )
        window = self.pet.bubble_controller.window
        self.assertEqual(window.message, raw_message)

        self.pet.bubble_controller.finish_transient()

        self.assertIn(window, self.pet.bubble_controller._window_pool)
        self.assertEqual(window.message, "")
        self.assertEqual(window.accessibleName(), "")

    def test_recent_history_keeps_only_privacy_safe_state_summary(self):
        payload = {
            "source": "codex",
            "event": "PermissionRequest",
            "approval_actor": "user",
            "session_id": "one",
            "message": "민감한 확인 원문",
        }

        self.pet.apply_agent_payload(payload)
        self.pet.apply_agent_payload(payload)

        history = self.pet.bubble_controller.recent_history
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].kind, "waiting")
        self.assertEqual(history[0].summary, "Codex 확인 필요 1건")
        self.assertNotIn("민감한", repr(history))

    def test_transient_bubble_expiry_does_not_erase_recent_history(self):
        self.pet.apply_agent_payload(
            {
                "source": "codex",
                "event": "SessionStart",
                "session_id": "one",
            }
        )
        self.assertEqual(len(self.pet.bubble_controller.recent_history), 1)

        self.pet.bubble_controller.finish_transient()

        self.assertFalse(self.pet.bubble_controller.window.isVisible())
        self.assertEqual(len(self.pet.bubble_controller.recent_history), 1)

    def test_recent_history_is_bounded_to_twenty_entries(self):
        for index in range(25):
            self.pet.apply_agent_payload(
                {
                    "source": "system",
                    "event": "notification",
                    "session_id": f"notice-{index}",
                    "message": f"알림 원문 {index}",
                }
            )

        history = self.pet.bubble_controller.recent_history
        self.assertEqual(len(history), 20)
        self.assertTrue(all(entry.summary == "비서 알림 1건" for entry in history))

    def test_bubble_setting_hides_and_persists(self):
        self.pet.show()
        self.app.processEvents()
        self.pet.apply_agent_payload(
            {
                "source": "codex",
                "event": "PermissionRequest",
                "approval_actor": "user",
                "session_id": "one",
            }
        )

        self.pet.set_bubbles_enabled(False)

        self.assertFalse(self.pet.bubble_controller.window.isVisible())
        self.assertFalse(self.settings.values["bubblesEnabled"])

    def test_bubble_scale_resizes_content_and_persists(self):
        bubble = self.pet.bubble_controller.window
        bubble.set_message(
            "말풍선 크기 조절을 확인하는 충분히 긴 메시지입니다",
            "waiting",
            "codex",
        )
        original_size = bubble.sizeHint()
        original_font_size = bubble.label.font().pointSizeF()

        applied = self.pet.set_bubble_scale(140)
        enlarged_size = bubble.sizeHint()

        self.assertEqual(applied, 140)
        self.assertEqual(self.pet.bubble_scale, 140)
        self.assertEqual(self.pet.bubble_controller.scale_percent, 140)
        self.assertEqual(bubble.scale_percent, 140)
        self.assertEqual(self.settings.values["bubbleScalePercent"], 140)
        self.assertGreater(enlarged_size.width(), original_size.width())
        self.assertGreater(
            bubble.label.font().pointSizeF(),
            original_font_size,
        )

    def test_character_bubble_theme_is_loaded_from_pet_package(self):
        expected = bubble_theme_from_manifest(self.pet.manifest)

        self.assertIsNotNone(expected)
        self.assertEqual(self.pet.bubble_controller.theme, expected)
        self.assertEqual(self.pet.bubble_controller.window.theme, expected)

    def test_default_bubble_theme_mode_applies_and_persists(self):
        applied = self.pet.set_bubble_theme_mode("default")

        self.assertEqual(applied, "default")
        self.assertEqual(self.pet.bubble_theme_mode, "default")
        self.assertEqual(self.pet.bubble_controller.theme, DEFAULT_BUBBLE_THEME)
        self.assertEqual(self.settings.values["bubbleThemeMode"], "default")

    def test_bubble_duration_applies_to_transient_timer_and_persists(self):
        applied = self.pet.set_bubble_duration_seconds(11)
        self.pet.apply_agent_payload(
            {
                "source": "codex",
                "event": "SessionStart",
                "session_id": "duration-test",
            }
        )
        entry = next(iter(self.pet.bubble_controller._entries.values()))

        self.assertEqual(applied, 11)
        self.assertEqual(self.pet.bubble_controller.duration_seconds, 11)
        self.assertEqual(entry.timer.interval(), 11_000)
        self.assertEqual(self.settings.values["bubbleDurationSeconds"], 11)

    def test_duration_change_does_not_restart_visible_preview_timer(self):
        self.pet.bubble_controller.preview("표시 시간 테스트")
        entry = next(iter(self.pet.bubble_controller._entries.values()))
        interval = entry.timer.interval()
        remaining = entry.timer.remainingTime()
        self.pet.set_bubble_duration_seconds(60)
        self.assertEqual(entry.timer.interval(), interval)
        self.assertLessEqual(entry.timer.remainingTime(), remaining)

    def test_changing_pet_updates_character_bubble_theme(self):
        previous_theme = self.pet.bubble_controller.theme

        self.assertTrue(self.pet.change_pet("sample-second"))

        self.assertNotEqual(self.pet.bubble_controller.theme, previous_theme)
        self.assertEqual(
            self.pet.bubble_controller.theme,
            bubble_theme_from_manifest(self.pet.manifest),
        )

    def test_custom_bubble_theme_is_isolated_per_pet(self):
        custom_theme = DEFAULT_BUBBLE_THEME.__class__(
            background="#112233",
            border="#445566",
            text="#ffffff",
            shadow="#000000",
            shape="jelly",
        )
        self.pet.set_custom_bubble_theme(custom_theme)

        self.assertTrue(self.pet.change_pet("sample-second"))
        self.assertIsNone(self.pet.custom_bubble_theme)
        self.assertEqual(self.pet.bubble_theme_mode, "character")

        self.assertTrue(self.pet.change_pet("sample-main"))
        self.assertEqual(self.pet.custom_bubble_theme, custom_theme)
        self.assertEqual(self.pet.bubble_theme_mode, "custom")

    def test_bubble_has_true_transparent_rounded_corners(self):
        bubble = self.pet.bubble_controller.window
        bubble.set_message("둥근 말풍선")
        bubble.adjustSize()

        image = QImage(
            bubble.size(),
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        image.fill(Qt.GlobalColor.transparent)
        bubble.render(image)

        self.assertTrue(
            bubble.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        )
        self.assertGreaterEqual(bubble.width(), bubble.theme.minimum_width)
        self.assertLessEqual(
            bubble.width(),
            bubble.theme.maximum_width
            + round(sum(bubble_frame_insets(bubble.theme)[index] for index in (0, 2))),
        )
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
        self.assertEqual(bubble.styleSheet(), "")
        self.assertGreater(
            image.pixelColor(image.width() // 2, image.height() // 2).alpha(),
            0,
        )

    def test_long_bubble_is_bounded_and_elided_after_three_lines(self):
        bubble = self.pet.bubble_controller.window
        bubble.set_message("아주 긴 비서 메시지 " * 30)

        self.assertLessEqual(
            bubble.width(),
            bubble.theme.maximum_width
            + round(sum(bubble_frame_insets(bubble.theme)[index] for index in (0, 2))),
        )
        self.assertIn("…", bubble.message)
        self.assertLessEqual(
            bubble.label.height(),
            bubble.label.fontMetrics().lineSpacing() * 3,
        )

    def test_activity_label_toggle_shows_non_idle_state_and_hides_idle(self):
        self.pet.show()
        self.app.processEvents()

        self.pet.set_activity_labels_enabled(True)
        self.pet.set_state("waving")

        caption = self.pet.activity_caption_controller.window
        self.assertTrue(caption.isVisible())
        self.assertFalse(self.pet.bubble_controller.window.isVisible())
        self.assertEqual(
            caption.message,
            "인사하는 중",
        )
        self.assertGreater(
            caption.y(),
            self.pet.frameGeometry().bottom(),
        )
        self.assertEqual(caption.styleSheet(), "")
        self.assertTrue(self.settings.values["activityLabelsEnabled"])

        image = QImage(
            caption.size(),
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        image.fill(Qt.GlobalColor.transparent)
        caption.render(image)
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
        self.assertGreater(
            image.pixelColor(
                image.width() // 2,
                image.height() // 2,
            ).alpha(),
            0,
        )

        self.pet.set_state("idle")

        self.assertFalse(caption.isVisible())

    def test_important_notice_and_activity_caption_are_independent(self):
        self.pet.show()
        self.app.processEvents()
        self.pet.set_activity_labels_enabled(True)

        self.pet.apply_agent_payload(
            {
                "source": "codex",
                "event": "UserPromptSubmit",
                "session_id": "one",
            }
        )
        self.assertIn("작업", self.pet.bubble_controller.window.message)
        self.assertEqual(
            self.pet.activity_caption_controller.window.message,
            "Codex 작업을 돕는 중",
        )
        self.assertTrue(self.pet.activity_caption_controller.window.isVisible())

        self.pet.bubble_controller.finish_transient()

        self.assertFalse(self.pet.bubble_controller.window.isVisible())
        self.assertTrue(self.pet.activity_caption_controller.window.isVisible())

    def test_action_tab_can_preview_bubble_without_changing_agent_state(self):
        self.pet.show()
        self.pet.set_bubbles_enabled(False)
        before = self.pet.agent_controller.aggregate_state
        viewmodel = PetViewModel(self.pet)

        viewmodel.preview_bubble("확인이 필요한 작업을 미리 보여드려요")

        self.assertEqual(len(self.pet.bubble_controller.visible_windows), 1)
        self.assertIn(
            "확인이 필요한",
            self.pet.bubble_controller.window.message,
        )
        self.assertEqual(
            self.pet.agent_controller.aggregate_state,
            before,
        )
        self.pet.bubble_controller.finish_transient()
        self.assertFalse(self.pet.bubble_controller.window.isVisible())

    def test_bubble_stack_merges_starts_from_multiple_sessions(self):
        self.pet.show()
        self.app.processEvents()

        for session_id in ("one", "two"):
            self.pet.apply_agent_payload(
                {
                    "source": "codex",
                    "event": "SessionStart",
                    "session_id": session_id,
                }
            )

        self.assertEqual(len(self.pet.bubble_controller.visible_windows), 1)
        self.assertIn("2개", self.pet.bubble_controller.window.message)

    def test_terminal_notice_replaces_start_for_the_same_session(self):
        self.pet.show()
        self.app.processEvents()
        self.pet.apply_agent_payload(
            {
                "source": "codex",
                "event": "SessionStart",
                "session_id": "one",
            }
        )

        self.pet.apply_agent_payload(
            {
                "source": "codex",
                "event": "Stop",
                "session_id": "one",
            }
        )

        self.assertEqual(len(self.pet.bubble_controller.visible_windows), 1)
        self.assertIn("완료", self.pet.bubble_controller.window.message)

    def test_terminal_notice_keeps_other_started_session_summary(self):
        self.pet.show()
        self.app.processEvents()
        for session_id in ("one", "two"):
            self.pet.apply_agent_payload(
                {
                    "source": "codex",
                    "event": "SessionStart",
                    "session_id": session_id,
                }
            )

        self.pet.apply_agent_payload(
            {
                "source": "codex",
                "event": "Stop",
                "session_id": "one",
            }
        )

        messages = {
            window.message for window in self.pet.bubble_controller.visible_windows
        }
        self.assertEqual(len(messages), 2)
        self.assertTrue(any("완료" in message for message in messages))
        self.assertTrue(any("시작" in message for message in messages))
        self.assertFalse(any("2개" in message for message in messages))

    def test_bubble_stack_limits_visible_notices_to_three(self):
        self.pet.show()
        self.app.processEvents()

        for index in range(4):
            self.pet.apply_agent_payload(
                {
                    "source": "notes-app",
                    "event": "notification",
                    "session_id": f"todo-{index}",
                    "message": f"일정 {index}",
                }
            )

        self.assertEqual(len(self.pet.bubble_controller.visible_windows), 3)
        self.assertIn(
            "외 1개",
            self.pet.bubble_controller.visible_windows[-1].message,
        )

    def test_tailless_bubble_theme_draws_no_tail(self):
        self.pet.show()
        self.app.processEvents()
        self.pet.apply_agent_payload(
            {
                "source": "codex",
                "event": "PermissionRequest",
                "approval_actor": "user",
                "session_id": "one",
            }
        )

        self.assertIsNone(self.pet.bubble_controller.window._tail_side)

    def test_bubble_exposes_notice_kind_and_accessible_summary(self):
        self.pet.show()
        self.app.processEvents()
        self.pet.apply_agent_payload(
            {
                "source": "codex",
                "event": "PermissionRequest",
                "approval_actor": "user",
                "session_id": "one",
            }
        )

        bubble = self.pet.bubble_controller.window
        self.assertEqual(bubble.notice_kind, "waiting")
        self.assertTrue(bubble.accessibleName().startswith("확인 필요:"))
        # Agent sources are a dot only when both are in use (stage 14).
        self.assertEqual(bubble.category_label.text(), "확인 필요")
        self.assertTrue(bubble.category_label.isVisible())

    def test_bubble_tail_margin_keeps_body_content_balanced(self):
        bubble = self.pet.bubble_controller.window
        bubble.set_theme(DEFAULT_BUBBLE_THEME)
        bubble.set_message("정렬 확인", "waiting", "codex")
        bubble.set_tail_side("bottom")

        margins = bubble.content_layout.contentsMargins()
        self.assertEqual(margins.left(), margins.right())
        self.assertEqual(margins.bottom() - BUBBLE_TAIL_SIZE, 14)
        self.assertTrue(bubble.label.alignment() & Qt.AlignmentFlag.AlignVCenter)
        self.assertTrue(bubble.label.alignment() & Qt.AlignmentFlag.AlignHCenter)

    def test_failed_diagnostic_event_has_a_korean_label(self):
        self.assertEqual(STATE_LABELS["failed"], "작업 실패")

    def test_viewmodel_resets_active_jobs_and_notices_but_keeps_history(self):
        self.pet.apply_agent_payload(
            {
                "source": "codex",
                "event": "PermissionRequest",
                "approval_actor": "user",
                "session_id": "one",
                "message": "확인이 필요해요",
            }
        )
        history = self.pet.bubble_controller.recent_history
        PetViewModel(self.pet).reset_agent_state()
        self.assertEqual(self.pet.agent_controller.current_presentation.active_count, 0)
        self.assertEqual(self.pet.current_state, "idle")
        self.assertIsNone(self.pet.bubble_controller.current_notice)
        self.assertEqual(self.pet.bubble_controller.recent_history, history)

    def test_temporary_focus_mode_hides_then_restores_bubbles(self):
        self.pet.show()
        self.app.processEvents()
        self.pet.apply_agent_payload(
            {
                "source": "codex",
                "event": "PermissionRequest",
                "approval_actor": "user",
                "session_id": "one",
            }
        )
        controller = self.pet.bubble_controller
        self.assertTrue(controller.window.isVisible())

        controller.snooze(20)

        self.assertTrue(controller.is_snoozed)
        self.assertFalse(controller.window.isVisible())
        self.assertTrue(self.pet.bubbles_enabled)
        self.assertEqual(len(controller.recent_history), 1)

        # The 20 ms snooze ends on a timer; under a long test run the event
        # loop can be slower than a fixed wait, so wait for the result.
        for _ in range(100):
            if not controller.is_snoozed and controller.window.isVisible():
                break
            QTest.qWait(20)

        self.assertFalse(controller.is_snoozed)
        self.assertTrue(controller.window.isVisible())

    def test_tray_controls_focus_mode_without_disabling_bubbles(self):
        tray = self.create_tray()
        try:
            tray.focus_menu.actions()[0].trigger()
            tray.refresh()

            self.assertTrue(self.pet.bubble_controller.is_snoozed)
            self.assertTrue(self.pet.bubbles_enabled)
            tray.focus_menu.actions()[-1].trigger()
            tray.refresh()

            self.assertFalse(self.pet.bubble_controller.is_snoozed)
        finally:
            tray.close()

    def test_preview_finishes_without_discarding_real_notice(self):
        self.pet.show()
        self.app.processEvents()
        self.pet.apply_agent_payload(
            {
                "source": "codex",
                "event": "SessionStart",
                "session_id": "one",
            }
        )
        real_message = self.pet.bubble_controller.window.message

        self.pet.bubble_controller.preview("미리보기")

        self.assertNotIn(
            "외 ",
            self.pet.bubble_controller.window.message,
        )
        self.pet.bubble_controller.finish_transient()

        self.assertEqual(self.pet.bubble_controller.window.message, real_message)
        self.assertTrue(self.pet.bubble_controller.window.isVisible())

    def test_agent_done_jumps_then_returns_to_idle(self):
        self.pet.apply_agent_payload(
            {
                "source": "codex",
                "event": "SessionStart",
                "session_id": "one",
            }
        )
        self.pet.apply_agent_payload(
            {
                "source": "codex",
                "event": "Stop",
                "session_id": "one",
            }
        )

        self.assertEqual(self.pet.current_state, "jumping")

        self.pet.agent_controller.finish_transient()

        self.assertEqual(self.pet.current_state, "idle")

    def test_agent_done_returns_to_another_active_session(self):
        self.pet.apply_agent_payload(
            {
                "source": "codex",
                "event": "SessionStart",
                "session_id": "running",
            }
        )
        self.pet.apply_agent_payload(
            {
                "source": "codex",
                "event": "PermissionRequest",
                "approval_actor": "user",
                "session_id": "waiting",
            }
        )
        self.pet.apply_agent_payload(
            {
                "source": "codex",
                "event": "Stop",
                "session_id": "waiting",
            }
        )

        self.assertEqual(self.pet.current_state, "jumping")

        self.pet.agent_controller.finish_transient()

        self.assertEqual(self.pet.current_state, "running")

    def test_waiting_keeps_character_caption_tray_and_bubble_aligned(self):
        self.pet.show()
        self.pet.look_timer.stop()
        self.pet.set_activity_labels_enabled(True, persist=False)
        self.pet.set_bubbles_enabled(True, persist=False)
        tray = self.create_tray()
        self.pet.apply_agent_payload(
            {
                "source": "codex",
                "event": "waiting",
                "session_id": "question",
                "event_id": "approval",
            }
        )
        for event in ("done", "failed"):
            self.pet.apply_agent_payload(
                {
                    "source": "codex",
                    "event": event,
                    "session_id": event,
                }
            )
            tray.refresh()
            self.assertEqual(self.pet.current_state, "waiting")
            self.assertEqual(self.pet.activity_caption_controller.state, "waiting")
            self.assertIn("확인 대기", tray.status_action.text())
            self.assertEqual(self.pet.bubble_controller.current_notice.kind, "waiting")
        kinds = {entry.kind for entry in self.pet.bubble_controller.recent_history}
        self.assertTrue({"waiting", "done", "error"}.issubset(kinds))
        self.pet.apply_agent_payload(
            {
                "source": "codex",
                "event": "tool_end",
                "session_id": "question",
                "event_id": "approval",
            }
        )
        tray.refresh()
        self.assertEqual(self.pet.current_state, "running")
        self.assertEqual(self.pet.activity_caption_controller.state, "running")
        self.assertIn("작업 중", tray.status_action.text())
        self.assertIsNone(self.pet.agent_controller.transient_state)

    def test_completion_preserves_frames_then_resumes_idle_custom_behavior(self):
        self.pet.show()
        self.pet.look_timer.stop()
        self.pet.pointer_near = False
        self.pet.set_auto_movement_enabled(True)
        self.pet.activity_controller.enabled = True
        self.pet.activity_controller.activities = [
            {"state": "review", "weight": 1, "duration": 2_000},
        ]
        preferences = dict(self.settings.values)
        self.pet.start_scheduled_auto_movement()
        self.assertTrue(self.pet.movement_controller.is_active)
        self.pet.apply_agent_payload({"source": "codex", "event": "prompt"})
        self.assertFalse(self.pet.movement_controller.is_active)
        self.pet.next_frame()
        frame = self.pet.current_frame
        for event in ("tool_end", "review", "tool_failed"):
            self.pet.apply_agent_payload({"source": "codex", "event": event})
            self.assertEqual(self.pet.current_state, "running")
            self.assertEqual(self.pet.current_frame, frame)
        self.pet.apply_agent_payload({"source": "codex", "event": "done"})
        self.assertEqual(self.pet.current_state, "jumping")
        self.assertFalse(self.pet.can_start_idle_activity())
        self.assertFalse(self.pet.can_start_auto_movement())
        self.pet.agent_controller.finish_transient()
        self.assertEqual(self.pet.current_state, "idle")
        self.assertTrue(self.pet.activity_controller.delay_timer.isActive())
        self.assertTrue(self.pet.movement_controller.delay_timer.isActive())
        self.pet.start_idle_activity()
        self.assertEqual(self.pet.current_state, "review")
        self.pet.apply_agent_payload({"source": "codex", "event": "prompt"})
        self.assertFalse(self.pet.activity_controller.is_active)
        self.pet.apply_agent_payload({"source": "codex", "event": "done"})
        self.pet.agent_controller.finish_transient()
        cursor = self.pet.frameGeometry().center() + QPoint(90, 0)
        with patch(
            "watched_kettle.pet.pointer_interaction.QCursor.pos", return_value=cursor
        ):
            self.pet.update_look_direction()
        self.assertTrue(self.pet.pointer_near)
        self.assertIsNotNone(self.pet.look_direction_index)
        self.assertEqual(self.settings.values, preferences)

    def test_switching_pet_keeps_correlated_wait_and_completion_timer(self):
        self.pet.apply_agent_payload(
            {
                "source": "codex",
                "event": "waiting",
                "session_id": "one",
                "event_id": "approval",
            }
        )
        self.assertTrue(self.pet.change_pet("sample-second"))
        self.assertEqual(self.pet.current_state, "waiting")
        self.pet.apply_agent_payload(
            {
                "source": "codex",
                "event": "tool_end",
                "session_id": "one",
                "event_id": "other",
            }
        )
        self.assertEqual(self.pet.current_state, "waiting")
        self.pet.apply_agent_payload(
            {
                "source": "codex",
                "event": "tool_end",
                "session_id": "one",
                "event_id": "approval",
            }
        )
        self.assertEqual(self.pet.current_state, "running")
        self.pet.apply_agent_payload(
            {
                "source": "codex",
                "event": "done",
                "session_id": "one",
            }
        )
        timer_id = self.pet.agent_controller.transient_timer.timerId()
        self.assertTrue(self.pet.change_pet("sample-main"))
        self.assertEqual(self.pet.current_state, "jumping")
        self.assertEqual(self.pet.agent_controller.transient_timer.timerId(), timer_id)
        self.pet.agent_controller.finish_transient()
        self.assertEqual(self.pet.current_state, "idle")

    def test_drag_visual_returns_to_agent_state(self):
        self.pet.apply_agent_payload(
            {
                "source": "codex",
                "event": "SessionStart",
                "session_id": "one",
            }
        )
        self.pet.dragging = True
        self.pet.set_state("running-left")

        self.pet.dragging = False
        self.pet.restore_agent_display_state()

        self.assertEqual(self.pet.current_state, "running")

    def test_double_click_wave_returns_to_agent_state(self):
        self.pet.apply_agent_payload(
            {
                "source": "codex",
                "event": "SessionStart",
                "session_id": "one",
            }
        )
        self.pet.double_click_waving = True
        self.pet.set_state("waving")

        self.pet.finish_waving()

        self.assertEqual(self.pet.current_state, "running")

    def test_agent_event_during_manual_wave_waits_for_wave_to_finish(self):
        self.pet.double_click_waving = True
        self.pet.set_state("waving")

        self.pet.apply_agent_payload(
            {
                "source": "codex",
                "event": "SessionStart",
                "session_id": "one",
            }
        )

        self.assertEqual(self.pet.current_state, "waving")

        self.pet.finish_waving()

        self.assertEqual(self.pet.current_state, "running")

    def test_agent_work_suspends_idle_activity(self):
        self.pet.activity_controller.enabled = True
        self.pet.pointer_near = False
        self.pet.apply_agent_payload(
            {
                "source": "codex",
                "event": "SessionStart",
                "session_id": "one",
            }
        )

        self.pet.schedule_idle_activity()

        self.assertFalse(self.pet.activity_controller.delay_timer.isActive())

    def test_always_on_top_can_be_disabled_without_persisting(self):
        self.pet.set_always_on_top(False, persist=False)

        self.assertFalse(self.pet.always_on_top)
        self.assertFalse(
            bool(self.pet.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        )

    def test_click_through_passes_input_persists_and_survives_a_new_pet(self):
        flag = Qt.WindowType.WindowTransparentForInput
        preferences = ApplicationPreferences(self.settings)
        self.pet.show()
        self.pet.dragging = True
        with patch.object(self.pet.bubble_controller, "preview") as preview:
            self.pet.set_click_through(True)
        self.assertTrue(self.pet.windowFlags() & flag)
        self.assertTrue(self.pet.isVisible())
        self.assertFalse(self.pet.dragging)
        preview.assert_called_once()
        self.assertTrue(preferences.load_pet_click_through())

        restored = DesktopPet(fixture_pet(), settings=self.settings)
        self.addCleanup(restored.close)
        self.assertTrue(restored.click_through)
        self.assertTrue(restored.windowFlags() & flag)

        with patch.object(self.pet.bubble_controller, "preview") as preview:
            self.pet.toggle_click_through()
        preview.assert_not_called()
        self.assertFalse(self.pet.windowFlags() & flag)
        self.assertFalse(preferences.load_pet_click_through())

    def test_action_bubbles_join_the_lock_only_when_chosen(self):
        with patch.object(self.pet.bubble_controller, "sync_click_through") as sync:
            self.pet.set_click_through(True, persist=False)
            sync.assert_called_with(False)
            self.pet.set_click_through_bubbles(True)
            sync.assert_called_with(True)
            self.pet.set_click_through(False, persist=False)
            sync.assert_called_with(False)
        self.assertTrue(
            ApplicationPreferences(self.settings).load_pet_click_through_bubbles()
        )
        self.assertFalse(ApplicationPreferences(self.settings).load_pet_click_through())

    def test_tray_unlocks_the_pet_and_widget(self):
        tray = self.create_tray()
        self.pet.set_click_through(True, persist=False)
        tray.refresh()
        self.assertTrue(tray.click_through_action.isChecked())
        tray.click_through_action.trigger()
        self.assertFalse(self.pet.click_through)
        tray.widget_click_through_action.trigger()
        self.assertTrue(
            ApplicationPreferences(self.settings).load_usage_widget_click_through()
        )
        tray.refresh()
        self.assertTrue(tray.widget_click_through_action.isChecked())

    def test_menu_locks_the_pet_and_toggles_the_widget_lock(self):
        requested = []
        self.pet.usage_widget_click_through_requested.connect(requested.append)
        for command in (
            PetMenuCommand("set_click_through", True),
            PetMenuCommand("set_usage_widget_click_through", True),
        ):
            with patch("watched_kettle.pet.window.show_pet_context_menu") as menu:
                menu.return_value = command
                event = Mock()
                self.pet.contextMenuEvent(event)
        self.assertTrue(self.pet.click_through)
        self.assertEqual(requested, [True])

    def test_move_to_screen_center_uses_available_geometry(self):
        self.pet.move_to_screen_center()
        screen = QApplication.primaryScreen()
        expected_center = screen.availableGeometry().center()

        self.assertLessEqual(
            abs(self.pet.frameGeometry().center().x() - expected_center.x()),
            1,
        )
        self.assertLessEqual(
            abs(self.pet.frameGeometry().center().y() - expected_center.y()),
            1,
        )

    def test_position_move_is_debounced_and_persisted(self):
        screen = QApplication.primaryScreen()
        target = screen.availableGeometry().topLeft() + QPoint(40, 50)
        self.pet.show()
        self.app.processEvents()

        self.pet.move(target)
        self.app.processEvents()

        self.assertTrue(self.pet.position_save_timer.isActive())
        self.pet.save_window_placement()
        placement = self.pet.app_preferences.load_window_placement()
        self.assertEqual(QPoint(placement.x, placement.y), target)
        self.assertEqual(placement.screen_name, screen.name())

    def test_saved_position_is_restored_for_a_new_pet_window(self):
        screen = QApplication.primaryScreen()
        settings = FakeSettings()
        target = screen.availableGeometry().topLeft() + QPoint(70, 90)
        placement = create_saved_placement(
            screen.name(),
            target,
            self.pet.size(),
            screen.availableGeometry(),
        )
        ApplicationPreferences(settings).save_window_placement(placement)

        restored_pet = DesktopPet(
            fixture_pet(),
            settings=settings,
        )
        try:
            self.assertEqual(restored_pet.pos(), target)
        finally:
            restored_pet.close()

    def test_pet_viewmodel_exposes_current_pet_state(self):
        self.pet.apply_agent_payload(
            {
                "source": "codex",
                "event": "SessionStart",
                "session_id": "one",
            }
        )

        snapshot = PetViewModel(self.pet).refresh()
        self.assertEqual(snapshot.visual_state, "running")
        self.assertEqual(snapshot.active_count, 1)

    def test_pet_folder_button_creates_and_opens_user_directory(self):
        self.pet.close()
        with TemporaryDirectory() as directory:
            user_root = Path(directory) / "new-pets"
            self.pet = DesktopPet(
                fixture_pet(),
                settings=self.settings,
                pets_roots=(user_root, fixture_pet().parent),
                user_pets_root=user_root,
            )
            with patch(
                "watched_kettle.features.pet.viewmodel.QDesktopServices.openUrl",
                return_value=True,
            ) as open_url:
                PetViewModel(self.pet).open_pet_folder()

            self.assertTrue(user_root.is_dir())
            open_url.assert_called_once()

    def test_pet_menu_quit_requests_app_quit(self):
        with (
            patch(
                "watched_kettle.pet.window.show_pet_context_menu",
                return_value=PetMenuCommand("quit"),
            ),
            patch("watched_kettle.pet.window.QApplication.quit") as quit_app,
        ):
            self.pet.contextMenuEvent(Mock(globalPos=lambda: QPoint()))
        quit_app.assert_called_once_with()

    def test_switching_pet_preserves_agent_state_and_loads_pet_settings(self):
        self.pet.close()
        settings = FakeSettings(
            {
                "pets/sample-second/width": 224,
                "pets/sample-second/alwaysOnTop": False,
            }
        )
        self.pet = DesktopPet(
            fixture_pet(),
            settings=settings,
        )
        self.pet.apply_agent_payload(
            {
                "source": "codex",
                "event": "SessionStart",
                "session_id": "one",
            }
        )

        changed = self.pet.change_pet("sample-second")

        self.assertTrue(changed)
        self.assertEqual(self.pet.pet_id, "sample-second")
        self.assertEqual(self.pet.pet_display_name, "Sample Second.")
        self.assertEqual(self.pet.pet_width, 224)
        self.assertFalse(self.pet.always_on_top)
        self.assertEqual(self.pet.current_state, "running")
        self.assertEqual(settings.values["selectedPetId"], "sample-second")

    def test_codex_width_changes_window_without_changing_atlas(self):
        self.pet.set_pet_width(224, persist=False)

        self.assertEqual(
            self.pet.size().width(),
            224,
        )
        self.assertEqual(
            self.pet.size().height(),
            round(224 * FRAME_HEIGHT / FRAME_WIDTH),
        )
        self.assertEqual(
            self.pet.frames["idle"][0].width(),
            FRAME_WIDTH,
        )

    def test_extended_width_reaches_352(self):
        self.pet.set_pet_width(352, persist=False)

        self.assertEqual(self.pet.size().width(), 352)
        self.assertEqual(
            self.pet.size().height(),
            round(352 * FRAME_HEIGHT / FRAME_WIDTH),
        )
        self.assertEqual(
            self.pet.frames["idle"][0].width(),
            FRAME_WIDTH,
        )

    def test_smooth_scaling_is_cached(self):
        self.pet.set_pet_width(224, persist=False)

        source = self.pet.frames["idle"][0]
        scaled = self.pet.renderer.scale(
            source,
            self.pet.size(),
        )
        cached = self.pet.renderer.scale(
            source,
            self.pet.size(),
        )

        self.assertEqual(scaled.size(), self.pet.size())
        self.assertEqual(self.pet.renderer.cache_size, 1)
        self.assertEqual(cached.cacheKey(), scaled.cacheKey())

    def test_original_size_uses_source_without_caching(self):
        self.pet.set_pet_width(FRAME_WIDTH, persist=False)

        source = self.pet.frames["idle"][0]
        rendered = self.pet.renderer.scale(
            source,
            self.pet.size(),
        )

        self.assertEqual(rendered.cacheKey(), source.cacheKey())
        self.assertEqual(self.pet.renderer.cache_size, 0)

    def test_width_outside_codex_options_is_ignored(self):
        original_width = self.pet.pet_width
        original_size = self.pet.size()

        self.pet.set_pet_width(225, persist=False)

        self.assertEqual(self.pet.pet_width, original_width)
        self.assertEqual(self.pet.size(), original_size)

    def test_look_range_can_be_changed_and_persisted_per_pet(self):
        self.pet.close()
        settings = FakeSettings()
        self.pet = DesktopPet(
            fixture_pet(),
            settings=settings,
        )

        self.assertEqual(self.pet.look_range, 240)
        self.pet.set_look_range(180)

        self.assertEqual(self.pet.look_range, 180)
        self.assertEqual(
            settings.values["pets/sample-main/lookRange"],
            180,
        )

    def test_auto_movement_can_be_enabled_independently(self):
        self.pet.close()
        settings = FakeSettings()
        self.pet = DesktopPet(
            fixture_pet(),
            settings=settings,
        )

        self.assertTrue(self.pet.activity_controller.enabled)
        self.assertFalse(self.pet.movement_controller.enabled)

        self.pet.set_auto_movement_enabled(True)

        self.assertTrue(self.pet.activity_controller.enabled)
        self.assertTrue(self.pet.movement_controller.enabled)
        self.assertTrue(settings.values["pets/sample-main/autoMovementEnabled"])

    def test_auto_movement_changes_window_position_and_returns_to_idle(self):
        self.pet.show()
        self.pet.look_timer.stop()
        self.pet.set_auto_movement_enabled(True)
        start_position = QPoint(self.pet.pos())

        self.pet.start_scheduled_auto_movement()
        movement_state = self.pet.current_state
        self.pet.movement_controller.advance(10_000)

        self.assertIn(
            movement_state,
            {"running-left", "running-right"},
        )
        self.assertNotEqual(self.pet.pos(), start_position)
        self.assertFalse(self.pet.movement_controller.is_active)
        self.assertEqual(self.pet.current_state, "idle")

    def test_agent_state_cancels_active_auto_movement(self):
        self.pet.show()
        self.pet.look_timer.stop()
        self.pet.set_auto_movement_enabled(True)
        self.pet.start_scheduled_auto_movement()
        self.assertTrue(self.pet.movement_controller.is_active)

        self.pet.apply_agent_payload(
            {
                "source": "codex",
                "event": "SessionStart",
                "session_id": "one",
            }
        )

        self.assertFalse(self.pet.movement_controller.is_active)
        self.assertEqual(self.pet.current_state, "running")

    def test_auto_action_and_auto_movement_do_not_overlap(self):
        self.pet.show()
        self.pet.look_timer.stop()
        self.pet.activity_controller.enabled = True
        self.pet.activity_controller.activities = [
            {
                "state": "jumping",
                "weight": 1,
                "duration": 1_000,
            }
        ]
        self.pet.start_idle_activity()
        self.pet.set_auto_movement_enabled(True)

        self.pet.start_scheduled_auto_movement()

        self.assertTrue(self.pet.activity_controller.is_active)
        self.assertFalse(self.pet.movement_controller.is_active)
        self.assertEqual(self.pet.current_state, "jumping")

    def test_manual_movement_test_runs_when_disabled_and_restores_agent_state(self):
        self.pet.show()
        self.pet.look_timer.stop()
        self.assertFalse(self.pet.movement_controller.enabled)
        self.pet.apply_agent_payload(
            {
                "source": "codex",
                "event": "SessionStart",
                "session_id": "one",
            }
        )

        self.pet.start_auto_movement_test()
        movement_state = self.pet.current_state
        self.pet.movement_controller.advance(10_000)

        self.assertIn(
            movement_state,
            {"running-left", "running-right"},
        )
        self.assertFalse(self.pet.movement_controller.enabled)
        self.assertFalse(self.pet.movement_test_active)
        self.assertEqual(self.pet.current_state, "running")

    def test_specific_auto_movement_screen_never_uses_another_display(self):
        primary = Mock()
        primary.name.return_value = "DISPLAY1"
        primary.availableGeometry.return_value = QRect(0, 0, 1000, 800)
        secondary = Mock()
        secondary.name.return_value = "DISPLAY2"
        secondary.availableGeometry.return_value = QRect(1000, 40, 1200, 900)
        self.pet.available_auto_movement_screens = Mock(
            return_value=[primary, secondary]
        )
        self.pet.auto_movement_screen_mode = "specific"
        self.pet.auto_movement_screen_name = "DISPLAY2"

        def screen_at(point):
            return secondary if point.x() >= 1000 else primary

        with (
            patch(
                "watched_kettle.pet.window.QApplication.screenAt",
                side_effect=screen_at,
            ),
            patch(
                "watched_kettle.pet.window.QApplication.primaryScreen",
                return_value=primary,
            ),
        ):
            self.assertIsNone(self.pet.auto_movement_bounds())

            self.pet.move_to_auto_movement_screen()

            self.assertEqual(
                self.pet.auto_movement_bounds(),
                secondary.availableGeometry(),
            )
            self.assertGreaterEqual(self.pet.x(), 1000)
            self.assertLessEqual(
                self.pet.x() + self.pet.width(),
                secondary.availableGeometry().right() + 1,
            )

    def test_smaller_default_look_range_rejects_a_distant_pointer(self):
        center = self.pet.frameGeometry().center()
        pointer = QPoint(
            center.x() + round(260 * self.pet.scale_factor),
            center.y(),
        )
        with patch(
            "watched_kettle.pet.pointer_interaction.QCursor.pos",
            return_value=pointer,
        ):
            self.pet.update_look_direction()

        self.assertFalse(self.pet.pointer_near)

        self.pet.set_look_range(300, persist=False)
        with patch(
            "watched_kettle.pet.pointer_interaction.QCursor.pos",
            return_value=pointer,
        ):
            self.pet.update_look_direction()

        self.assertTrue(self.pet.pointer_near)

    def test_idle_activity_runs_and_returns_to_idle(self):
        self.pet.activity_controller.enabled = True
        self.pet.pointer_near = False
        self.pet.activity_controller.activities = [
            {
                "state": "jumping",
                "weight": 1,
                "duration": 1_000,
            }
        ]

        self.pet.start_idle_activity()

        self.assertTrue(self.pet.activity_controller.is_active)
        self.assertEqual(self.pet.current_state, "jumping")

        self.pet.finish_idle_activity()

        self.assertFalse(self.pet.activity_controller.is_active)
        self.assertEqual(self.pet.current_state, "idle")

    def test_manual_state_cancels_stale_idle_activity_callback(self):
        self.pet.activity_controller.enabled = True
        self.pet.pointer_near = False
        self.pet.activity_controller.activities = [
            {
                "state": "waving",
                "weight": 1,
                "duration": 1_000,
            }
        ]
        self.pet.start_idle_activity()

        self.pet.set_state("review")
        self.pet.finish_idle_activity()

        self.assertFalse(self.pet.activity_controller.is_active)
        self.assertEqual(self.pet.current_state, "review")

    def test_nearby_pointer_suspends_idle_activity_timer(self):
        self.pet.activity_controller.enabled = True
        self.pet.pointer_near = True

        self.pet.set_state("idle")

        self.assertFalse(self.pet.activity_controller.delay_timer.isActive())


if __name__ == "__main__":
    unittest.main()
