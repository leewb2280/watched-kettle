import unittest

from PySide6.QtCore import QRect, QSize

from watched_kettle.state.events import build_decision
from watched_kettle.state.presentation import (
    ActivityPresentationPolicy,
    NOTICE_PRIORITIES,
)
from watched_kettle.state.session_manager import AgentSessionManager
from watched_kettle.ui.activity_caption import caption_position
from watched_kettle.ui.speech_bubble import bubble_position, bubble_stack_positions


class FakeClock:
    def __init__(self):
        self.value = 1_000

    def __call__(self):
        return self.value

    def advance(self, milliseconds):
        self.value += milliseconds


class ActivityPresentationPolicyTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.policy = ActivityPresentationPolicy(now_ms=self.clock)
        self.manager = AgentSessionManager(now_ms=self.clock)

    def apply(self, payload):
        decision = build_decision(payload)
        return self.policy.build(self.manager.apply(decision))

    def test_start_is_announced_but_repeated_tool_events_are_quiet(self):
        started = self.apply(
            {
                "source": "codex",
                "event": "UserPromptSubmit",
                "session_id": "one",
            }
        )
        tool = self.apply(
            {
                "source": "codex",
                "event": "PreToolUse",
                "session_id": "one",
            }
        )

        self.assertIsNotNone(started.notice)
        self.assertGreater(started.notice.duration_ms, 0)
        self.assertIsNone(tool.notice)

    def test_duplicate_start_notice_is_suppressed_within_window(self):
        first = self.apply(
            {
                "source": "codex",
                "event": "SessionStart",
                "session_id": "one",
            }
        )
        second = self.apply(
            {
                "source": "codex",
                "event": "UserPromptSubmit",
                "session_id": "one",
            }
        )

        self.assertIsNotNone(first.notice)
        self.assertIsNone(second.notice)

    def test_waiting_notice_is_persistent_until_aggregate_changes(self):
        waiting = self.apply(
            {
                "source": "codex",
                "event": "PermissionRequest",
                "approval_actor": "user",
                "session_id": "one",
            }
        )
        resumed = self.apply(
            {
                "source": "codex",
                "event": "PostToolUse",
                "session_id": "one",
            }
        )

        self.assertTrue(waiting.notice.persistent)
        self.assertIsNotNone(waiting.persistent_notice)
        self.assertIsNone(resumed.persistent_notice)

    def test_notification_keeps_waiting_notice_as_return_target(self):
        self.apply(
            {
                "source": "codex",
                "event": "PermissionRequest",
                "approval_actor": "user",
                "session_id": "one",
            }
        )
        notification = self.apply(
            {
                "source": "notes-app",
                "event": "notification",
                "session_id": "todo-one",
                "message": "오늘 일정이 있어요",
            }
        )

        self.assertEqual(notification.notice.message, "오늘 일정이 있어요")
        self.assertEqual(notification.persistent_notice.event, "waiting")

    def test_notices_include_assistant_priority_and_merge_identity(self):
        started = self.apply(
            {
                "source": "codex",
                "event": "SessionStart",
                "session_id": "one",
            }
        )
        failed = self.apply(
            {
                "source": "codex",
                "event": "StopFailure",
                "session_id": "one",
            }
        )

        self.assertEqual(started.notice.kind, "start")
        self.assertEqual(started.notice.replace_key, "codex:start")
        self.assertEqual(started.notice.member_ids, ("codex:one",))
        self.assertGreater(failed.notice.priority, started.notice.priority)
        self.assertEqual(failed.notice.kind, "error")

    def test_tool_failure_is_diagnostic_only(self):
        failed = self.apply(
            {
                "source": "codex",
                "event": "PostToolUseFailure",
                "session_id": "one",
            }
        )
        self.assertEqual(failed.state, "running")
        self.assertEqual(failed.event, "tool_failed")
        self.assertIsNone(failed.notice)
        self.assertEqual(
            self.manager.list_sessions()[0].recent_events[-1]["event"], "tool_failed"
        )

    def test_confirmation_stays_above_terminal_failure(self):
        self.apply({"source": "codex", "event": "waiting", "session_id": "one"})
        failed = self.apply(
            {
                "source": "codex",
                "event": "failed",
                "session_id": "two",
            }
        )
        self.assertEqual(failed.state, "waiting")
        self.assertEqual(failed.notice.kind, "error")
        self.assertGreater(failed.persistent_notice.priority, failed.notice.priority)

    def test_cancelled_notice_is_neutral_and_returns_to_idle(self):
        self.apply(
            {
                "source": "codex",
                "event": "UserPromptSubmit",
                "session_id": "one",
            }
        )
        cancelled = self.apply(
            {
                "source": "codex",
                "event": "cancelled",
                "session_id": "one",
            }
        )

        self.assertEqual(cancelled.state, "idle")
        self.assertEqual(cancelled.notice.kind, "cancelled")
        self.assertEqual(cancelled.notice.message, "Codex 작업이 중단됐어요")
        self.assertLess(cancelled.notice.priority, NOTICE_PRIORITIES["done"])

    def test_each_waiting_session_becomes_a_persistent_notice(self):
        self.apply(
            {
                "source": "codex",
                "event": "PermissionRequest",
                "approval_actor": "user",
                "session_id": "one",
            }
        )
        waiting = self.apply(
            {
                "source": "codex",
                "event": "PermissionRequest",
                "approval_actor": "user",
                "session_id": "two",
            }
        )

        self.assertEqual(len(waiting.persistent_notices), 2)
        self.assertEqual(
            {notice.session_id for notice in waiting.persistent_notices},
            {"codex:one", "codex:two"},
        )

    def test_schedule_urgency_orders_notifications_below_confirmation(self):
        low = self.apply(
            {
                "source": "schedule",
                "event": "notification",
                "session_id": "low",
                "urgency": "low",
                "message": "나중에 확인할 일정",
            }
        )
        high = self.apply(
            {
                "source": "schedule",
                "event": "notification",
                "session_id": "high",
                "urgency": "high",
                "message": "곧 시작하는 일정",
            }
        )
        waiting = self.apply(
            {
                "source": "codex",
                "event": "PermissionRequest",
                "approval_actor": "user",
                "session_id": "waiting",
            }
        )

        self.assertGreater(high.notice.priority, low.notice.priority)
        self.assertGreater(
            waiting.notice.priority,
            high.notice.priority,
        )


class SpeechBubblePositionTests(unittest.TestCase):
    def test_bubble_prefers_above_and_clamps_to_work_area(self):
        position = bubble_position(
            QRect(350, 500, 120, 130),
            QSize(220, 70),
            QRect(0, 0, 800, 700),
        )

        self.assertEqual(position.y(), 420)
        self.assertGreaterEqual(position.x(), 0)

    def test_bubble_clamps_above_instead_of_flipping_at_top_edge(self):
        position = bubble_position(
            QRect(10, 5, 100, 110),
            QSize(240, 80),
            QRect(0, 0, 800, 700),
        )

        self.assertEqual(position.y(), 8)
        self.assertEqual(position.x(), 8)

    def test_stack_keeps_primary_notice_closest_to_pet(self):
        positions = bubble_stack_positions(
            QRect(350, 500, 120, 130),
            (QSize(220, 60), QSize(180, 40)),
            QRect(0, 0, 800, 700),
        )

        self.assertEqual(len(positions), 2)
        self.assertGreater(positions[0].y(), positions[1].y())

    def test_stream_stack_aligns_different_widths_to_the_left(self):
        positions = bubble_stack_positions(
            QRect(350, 500, 120, 130),
            (QSize(220, 60), QSize(140, 40)),
            QRect(0, 0, 800, 700),
            alignment="left",
        )

        self.assertEqual(positions[0].x(), positions[1].x())

    def test_caption_does_not_force_a_side_flip(self):
        positions = bubble_stack_positions(
            QRect(10, 5, 100, 110),
            (QSize(200, 60),),
            QRect(0, 0, 800, 700),
            avoid_rects=(QRect(0, 120, 300, 40),),
        )

        self.assertEqual(positions[0].x(), 8)
        self.assertEqual(positions[0].y(), 8)

    def test_stack_stays_inside_negative_coordinate_monitor(self):
        bounds = QRect(-1920, -200, 1920, 1080)
        size = QSize(280, 80)
        positions = bubble_stack_positions(
            QRect(-1900, -180, 120, 130),
            (size,),
            bounds,
        )
        bubble_rect = QRect(positions[0], size)

        self.assertTrue(bounds.contains(bubble_rect))

    def test_fallback_prefers_less_caption_overlap(self):
        bounds = QRect(0, 0, 260, 220)
        pet_rect = QRect(90, 70, 80, 90)
        size = QSize(220, 100)
        caption = QRect(0, 160, 260, 60)
        positions = bubble_stack_positions(
            pet_rect,
            (size,),
            bounds,
            avoid_rects=(caption,),
        )
        bubble_rect = QRect(positions[0], size)
        overlap = bubble_rect.intersected(caption)

        self.assertLess(overlap.height(), 60)


class ActivityCaptionPositionTests(unittest.TestCase):
    def test_caption_is_centered_under_pet(self):
        position = caption_position(
            QRect(300, 300, 120, 130),
            QSize(140, 28),
            QRect(0, 0, 800, 700),
        )

        self.assertEqual(position.x(), 290)
        self.assertEqual(position.y(), 434)

    def test_caption_clamps_to_work_area(self):
        position = caption_position(
            QRect(760, 680, 80, 90),
            QSize(160, 28),
            QRect(0, 0, 800, 700),
        )

        self.assertEqual(position.x(), 640)
        self.assertEqual(position.y(), 672)


if __name__ == "__main__":
    unittest.main()
