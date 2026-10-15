import unittest

from watched_kettle.state.events import (
    build_decision,
    normalize_agent_source,
    normalize_event_name,
    normalize_urgency,
)


class AgentEventTests(unittest.TestCase):
    def test_normalizes_codex_source_alias(self):
        self.assertEqual(normalize_agent_source("codex-cli"), "codex")

    def test_normalizes_schedule_provider_aliases(self):
        self.assertEqual(normalize_agent_source("calendar"), "schedule")
        self.assertEqual(normalize_agent_source("reminder"), "schedule")
        self.assertEqual(normalize_event_name("ScheduleDue"), "notification")

    def test_normalizes_camel_case_hook_event(self):
        self.assertEqual(normalize_event_name("PreToolUse"), "tool_start")

    def test_session_start_enters_running_immediately(self):
        decision = build_decision(
            {"source": "codex", "event": "SessionStart", "session_id": "one"}
        )

        self.assertEqual(decision.persistent_state, "running")
        self.assertEqual(decision.session_id, "codex:one")

    def test_codex_work_and_compaction_stay_running(self):
        for event in ("thinking", "PostToolUse", "PreCompact", "PostCompact"):
            with self.subTest(event=event):
                decision = build_decision(
                    {"source": "codex", "event": event, "session_id": "one"}
                )
                self.assertEqual(decision.persistent_state, "running")
                self.assertEqual(decision.message, "Codex가 작업하고 있어요")

    def test_manual_review_remains_available(self):
        decision = build_decision({"source": "manual", "event": "review"})
        self.assertEqual(decision.persistent_state, "review")

    def test_tool_identity_survives_raw_and_normalized_inputs(self):
        for key in ("event_id", "tool_use_id", "call_id"):
            with self.subTest(key=key):
                decision = build_decision(
                    {
                        "source": "codex",
                        "event": "PermissionRequest",
                        key: "call-1",
                    }
                )
                self.assertEqual(decision.event_id, "call-1")

    def test_tool_start_stays_running_even_for_tests(self):
        decision = build_decision(
            {
                "source": "codex",
                "event": "PreToolUse",
                "session_id": "one",
                "command": "pytest",
            }
        )

        self.assertEqual(decision.persistent_state, "running")

    def test_permission_request_waits_for_user(self):
        decision = build_decision(
            {"source": "codex", "event": "PermissionRequest", "approval_actor": "user"}
        )

        self.assertEqual(decision.persistent_state, "waiting")

    def test_notification_is_temporary_wave(self):
        decision = build_decision({"source": "codex", "event": "notification"})

        self.assertEqual(decision.visual_state, "waving")
        self.assertIsNone(decision.persistent_state)
        self.assertGreater(decision.duration_ms, 0)

    def test_done_is_terminal_jump(self):
        decision = build_decision(
            {"source": "codex", "event": "Stop", "session_id": "one"}
        )

        self.assertTrue(decision.terminal)
        self.assertEqual(decision.visual_state, "jumping")

    def test_cancelled_is_terminal_idle_without_failure_animation(self):
        decision = build_decision(
            {"source": "codex", "event": "cancelled", "session_id": "one"}
        )

        self.assertTrue(decision.terminal)
        self.assertEqual(decision.visual_state, "idle")
        self.assertEqual(decision.message, "Codex 작업이 중단됐어요")

    def test_tool_failure_keeps_working_without_a_failure_animation(self):
        decision = build_decision(
            {"source": "codex", "event": "tool_failed", "session_id": "one"}
        )

        self.assertFalse(decision.terminal)
        self.assertEqual(decision.persistent_state, "running")
        self.assertIsNone(decision.visual_state)
        self.assertEqual(decision.duration_ms, 0)

    def test_schedule_notification_normalizes_urgency_and_label(self):
        decision = build_decision(
            {
                "source": "calendar",
                "event": "ReminderDue",
                "urgency": "urgent",
            }
        )

        self.assertEqual(decision.source, "schedule")
        self.assertEqual(decision.event, "notification")
        self.assertEqual(decision.urgency, "high")
        self.assertEqual(decision.message, "일정 알림이 있어요")
        self.assertEqual(normalize_urgency("quiet"), "low")
        self.assertEqual(normalize_urgency("unknown"), "normal")

    def test_message_is_trimmed_and_limited(self):
        decision = build_decision(
            {
                "source": "notes-app",
                "event": "notification",
                "message": f"  {'a' * 130}  ",
            }
        )

        self.assertEqual(len(decision.message), 120)

    def test_unknown_or_invalid_payload_is_ignored(self):
        self.assertIsNone(build_decision({"source": "codex", "event": "mystery"}))
        self.assertIsNone(build_decision([]))


if __name__ == "__main__":
    unittest.main()
