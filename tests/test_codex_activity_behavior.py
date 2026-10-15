"""Behavioral regressions for concurrent Codex work and pet animations."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from watched_kettle.integrations.codex_hooks import normalize_codex_hook
from watched_kettle.integrations.codex_log import normalize_codex_log_record
from watched_kettle.state.controller import PetAgentController
from watched_kettle.state.session_manager import AgentSessionManager


class CodexActivityBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.states = []
        self.presentations = []
        self.controller = PetAgentController(
            self.states.append,
            on_presentation=self.presentations.append,
        )
        self.addCleanup(self.controller.deleteLater)
        self.addCleanup(self.controller.clear)

    def event(self, event, session="main", **fields):
        return self.controller.apply_payload(
            {
                "source": "codex",
                "event": event,
                "session_id": session,
                **fields,
            }
        )

    def hook(self, event, session="main", **fields):
        return self.controller.apply_payload(
            normalize_codex_hook(
                {
                    "hook_event_name": event,
                    "session_id": session,
                    **fields,
                }
            )
        )

    def assert_state(self, state):
        self.assertEqual(self.controller.desired_state, state)
        self.assertEqual(self.states[-1], state)
        self.assertEqual(self.presentations[-1].state, state)

    def test_identified_wait_survives_other_tools_and_compaction(self):
        self.hook("UserPromptSubmit")
        self.hook("PermissionRequest", approval_actor="user", tool_use_id="approval")
        for event in ("PreToolUse", "PostToolUse", "PreCompact", "PostCompact"):
            with self.subTest(event=event):
                self.hook(event, tool_use_id="unrelated")
                self.assert_state("waiting")
                self.assertIn("확인", self.presentations[-1].persistent_notice.message)
        self.hook("PostToolUse", "other", tool_use_id="approval")
        self.assert_state("waiting")
        self.hook("PreToolUse", tool_use_id="approval")
        self.assert_state("waiting")
        self.hook("PostToolUse", tool_use_id="approval")
        self.assert_state("running")
        self.assertIsNone(self.presentations[-1].persistent_notice)

    def test_all_waiting_tools_must_finish_including_failed_results(self):
        for tool_id in ("one", "two"):
            self.hook("PermissionRequest", approval_actor="user", tool_use_id=tool_id)
        self.hook("PostToolUse", tool_use_id="one")
        self.assert_state("waiting")
        self.hook("PostToolUse", tool_use_id="two", tool_response={"success": False})
        self.assert_state("running")
        self.assertIsNone(self.presentations[-1].notice)
        session = self.controller.session_manager.list_sessions()[0]
        self.assertEqual(session.pending_wait_ids, frozenset())
        self.assertEqual(session.recent_events[-1]["event"], "tool_failed")

    def test_legacy_wait_resumes_only_on_same_session_tool_evidence(self):
        for event in ("tool_start", "tool_end", "tool_failed"):
            with self.subTest(event=event):
                self.controller.clear()
                self.event("waiting")
                self.event("review")
                self.event(event, "other")
                self.assert_state("waiting")
                self.event(event)
                self.assert_state("running")

    def test_new_prompt_or_terminal_event_clears_old_waits(self):
        for event in ("prompt", "done", "failed", "cancelled", "session_end"):
            with self.subTest(event=event):
                self.controller.clear()
                self.event("waiting", event_id="old-tool")
                self.event(event)
                self.assertIsNone(self.presentations[-1].persistent_notice)
                self.controller.finish_transient()
                self.event("tool_start", event_id="new-tool")
                self.assert_state("running")

    def test_log_question_wait_is_released_by_its_own_output(self):
        pending = set()

        def record(kind, payload_type, **fields):
            payload = normalize_codex_log_record(
                {"type": kind, "payload": {"type": payload_type, **fields}},
                "main",
                pending,
                agent_scope="main",
            )
            self.assertIsNotNone(payload)
            self.controller.apply_payload(payload)
            return payload

        self.event("prompt")
        record(
            "response_item",
            "function_call",
            name="request_user_input",
            call_id="question",
            arguments="PRIVATE QUESTION",
        )
        self.assert_state("waiting")
        record(
            "response_item",
            "function_call_output",
            call_id="other",
            output="PRIVATE OUTPUT",
        )
        self.assert_state("waiting")
        answer = record(
            "response_item",
            "function_call_output",
            call_id="question",
            output="PRIVATE ANSWER",
        )
        self.assertEqual(answer["event"], "tool_end")
        self.assertEqual(answer["event_id"], "question")
        self.assertNotIn("PRIVATE", str(answer))
        self.assertEqual(pending, set())
        self.assert_state("running")

    def test_routine_and_background_events_do_not_reset_completion_timer(self):
        self.event("prompt", "worker")
        self.event("done")
        timer_id = self.controller.transient_timer.timerId()
        self.assertEqual(self.controller.transient_timer.interval(), 2_600)
        for event in ("tool_start", "tool_end", "review", "thinking", "tool_failed"):
            with self.subTest(event=event):
                self.event(event, "worker")
                self.assert_state("jumping")
                self.assertEqual(self.controller.transient_timer.timerId(), timer_id)
        self.hook("SubagentStart", agent_id="child")
        self.hook("SubagentStop", agent_id="child")
        self.assert_state("jumping")
        self.assertEqual(self.controller.transient_timer.timerId(), timer_id)
        self.assertIsNone(self.presentations[-1].notice)
        self.controller.finish_transient()
        self.assert_state("running")
        self.assertEqual(self.presentations[-1].active_count, 1)

    def test_wait_preempts_existing_animations_without_replaying_them(self):
        for event in ("done", "failed", "notification"):
            with self.subTest(event=event):
                self.controller.clear()
                self.event(event)
                self.assertTrue(self.controller.transient_timer.isActive())
                self.event("waiting", "question", event_id="question-tool")
                self.assert_state("waiting")
                self.assertFalse(self.controller.transient_timer.isActive())
                self.event("tool_end", "question", event_id="question-tool")
                self.assert_state("running")
                self.assertIsNone(self.controller.transient_state)

    def test_wait_blocks_new_animations_but_preserves_notices(self):
        self.event("waiting", "question", event_id="question-tool")
        for event in ("done", "failed", "notification"):
            with self.subTest(event=event):
                self.event(event)
                self.assert_state("waiting")
                self.assertEqual(self.presentations[-1].notice.event, event)
                self.assertGreater(
                    self.presentations[-1].persistent_notice.priority,
                    self.presentations[-1].notice.priority,
                )
                self.assertFalse(self.controller.transient_timer.isActive())
        self.event("tool_end", "question", event_id="question-tool")
        self.controller.finish_transient()
        self.assert_state("running")

    def test_transient_priority_and_equal_priority_replacement(self):
        self.event("notification", "reminder")
        self.event("done", "first")
        self.assert_state("jumping")
        first_timer = self.controller.transient_timer.timerId()
        self.event("done", "second")
        self.assertNotEqual(self.controller.transient_timer.timerId(), first_timer)
        self.assertEqual(self.controller.transient_session_id, "codex:second")
        self.event("failed", "third")
        self.assert_state("failed")
        failure_timer = self.controller.transient_timer.timerId()
        self.assertEqual(self.controller.transient_timer.interval(), 3_200)
        self.event("done", "fourth")
        self.assertEqual(self.presentations[-1].notice.event, "done")
        self.event("notification", "reminder")
        self.assert_state("failed")
        self.assertEqual(self.controller.transient_timer.timerId(), failure_timer)
        self.controller.finish_transient()
        self.assert_state("idle")

    def test_other_prompt_keeps_completion_but_own_prompt_clears_it(self):
        self.event("done")
        self.event("prompt", "other")
        self.assert_state("jumping")
        self.event("prompt")
        self.assert_state("running")
        self.assertFalse(self.controller.transient_timer.isActive())

    def test_cancelled_session_reveals_other_work_in_display_and_presentation(self):
        self.event("prompt")
        self.event("prompt", "other")
        result = self.event("cancelled")
        self.assertEqual(result.display.state, "running")
        self.assert_state("running")
        self.assertEqual(self.presentations[-1].notice.kind, "cancelled")
        self.assertFalse(self.controller.transient_timer.isActive())

    def test_tool_failure_remains_active_until_task_failure(self):
        self.event("tool_failed")
        self.assert_state("running")
        self.assertEqual(self.presentations[-1].active_count, 1)
        self.assertIsNone(self.presentations[-1].notice)
        self.event("failed")
        self.assert_state("failed")
        self.assertEqual(self.presentations[-1].active_count, 0)
        self.assertEqual(self.presentations[-1].notice.kind, "error")
        self.controller.finish_transient()
        self.assert_state("idle")

    def test_stale_sweep_updates_counts_without_interrupting_completion(self):
        now = [1_700_000_000_000]
        self.controller.session_manager = AgentSessionManager(now_ms=lambda: now[0])
        self.event("prompt", "worker")
        self.event("done")
        timer_id = self.controller.transient_timer.timerId()
        now[0] += self.controller.stale_session_age_ms
        self.controller.expire_stale_sessions()
        self.assert_state("jumping")
        self.assertEqual(self.presentations[-1].active_count, 0)
        self.assertEqual(self.controller.transient_timer.timerId(), timer_id)
        self.controller.finish_transient()
        self.assert_state("idle")


if __name__ == "__main__":
    unittest.main()
