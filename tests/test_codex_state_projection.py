"""Codex confidence, correlated outcomes and dismissal across actual Qt rows."""

import unittest
from dataclasses import replace

from tests import test_bubble_state_regressions as helpers
from watched_kettle.integrations.activity_recovery import RecoverySnapshot
from watched_kettle.state.codex_activity import CodexTurnOutcome


class CodexStateProjectionTests(unittest.TestCase):
    setUpClass = classmethod(helpers.BubbleStateRegressions.setUpClass.__func__)
    setUp = helpers.BubbleStateRegressions.setUp
    tearDown = helpers.BubbleStateRegressions.tearDown
    send = helpers.BubbleStateRegressions.send
    start = helpers.BubbleStateRegressions.start
    advance = helpers.BubbleStateRegressions.advance
    row = helpers.BubbleStateRegressions.row
    window = helpers.BubbleStateRegressions.window

    def test_uncertain_is_idle_count_free_and_can_be_hidden_until_real_activity(self):
        self.start()
        self.advance(61)
        self.assertEqual(self.pet.current_state, "idle")
        self.assertEqual(self.pet.agent_controller.current_presentation.active_count, 0)
        row = self.row()
        self.assertIn("마지막 확인:", row.badge.toolTip())
        self.assertFalse(row.close_button.isHidden())
        row.close_button.click()
        self.controller._render()
        self.assertFalse(self.controller.visible_windows)
        self.assertIn("a", self.projects.activities)
        self.projects.set_metadata(
            replace(self.projects.metadata["a"], title="new title"), 0
        )
        self.controller._render()
        self.assertFalse(self.controller.visible_windows)
        self.send("heartbeat")
        self.assertEqual(self.row().badge.text(), "작업 중")
        self.assertEqual(self.pet.current_state, "running")

    def test_old_dismissal_cannot_hide_new_activity_or_turn(self):
        self.start()
        self.advance(61)
        token = self.projects.cards[0].rows[0].dismiss_id
        self.send("heartbeat")
        self.projects.dismiss_rows([token])
        self.assertTrue(self.projects.cards)
        self.send("prompt", turn="2")
        self.projects.dismiss_rows([token])
        self.assertTrue(self.projects.cards)

    def test_ended_is_neutral_and_confirmation_keeps_original_deadlines(self):
        self.start()
        self.send("ended", outcome_reason="usage_limit")
        first = self.projects.activities["a"].terminal_at
        self.assertEqual(self.row().badge.text(), "종료됨")
        self.assertFalse(self.projects.completions)
        target = self.projects.codex_turn_targets()[0]
        self.advance(2)
        self.activity.observe_turn_outcome(CodexTurnOutcome(target, "done"))
        self.controller._render()
        self.assertEqual(self.row().badge.text(), "완료")
        self.assertEqual(self.projects.completions[0].highlight_until, first + 15)
        self.assertEqual(self.projects.completions[0].expires_at, first + 300)
        self.assertEqual(self.pet.current_state, "idle")

    def test_failure_reason_only_from_correlated_terminal_evidence(self):
        self.start()
        self.advance(61)
        target = self.projects.codex_turn_targets()[0]
        self.activity.observe_turn_outcome(
            CodexTurnOutcome(target, "failed", "usage_limit")
        )
        self.controller._render()
        self.assertEqual(self.row().badge.text(), "사용량 제한으로 중단")
        self.assertFalse(self.projects.completions)

    def test_expired_ended_and_new_turn_cannot_be_resurrected(self):
        self.start()
        self.send("ended")
        target = self.projects.codex_turn_targets()[0]
        self.advance(9)
        self.activity.observe_turn_outcome(CodexTurnOutcome(target, "done"))
        self.assertFalse(self.projects.completions)
        self.send("prompt", turn="2")
        self.activity.observe_turn_outcome(CodexTurnOutcome(target, "failed"))
        self.assertEqual(self.projects.activities["a"].state, "running")

    def test_hidden_uncertain_is_not_resurrected_by_a_read_reply(self):
        self.start()
        self.advance(61)
        target = self.projects.codex_turn_targets()[0]
        self.projects.dismiss_rows([self.projects.cards[0].rows[0].dismiss_id])
        self.activity.observe_turn_outcome(
            CodexTurnOutcome(target, "failed", "usage_limit")
        )
        self.assertFalse(self.projects.cards)

    def test_confirmed_recovery_becomes_live_before_later_completion(self):
        self.projects.restore_activity(
            RecoverySnapshot(
                "r",
                "t",
                "main",
                self.projects.wall_now() - 30,
                self.projects.wall_now() - 1,
                self.projects.wall_now(),
            )
        )
        self.send("heartbeat", thread="r", turn="t")
        self.assertFalse(self.projects.activities["r"].recovered)
        self.advance(61)
        target = self.projects.codex_turn_targets()[0]
        self.activity.observe_turn_outcome(CodexTurnOutcome(target, "done"))
        self.assertEqual(len(self.projects.completions), 1)

    def test_explicit_main_success_can_confirm_unknown_scope_ended(self):
        self.send("prompt", agent_scope="unknown")
        self.send("ended", agent_scope="unknown")
        self.assertFalse(self.projects.completions)
        self.send("done", agent_scope="main", transport=helpers.JSONL_TRANSPORT)
        self.assertEqual(len(self.projects.completions), 1)

    def test_heartbeat_refreshes_pet_beyond_twelve_hours(self):
        self.start()
        self.advance(12 * 3600 + 1)
        self.send("heartbeat")
        self.pet.agent_controller.expire_stale_sessions()
        self.assertEqual(self.pet.current_state, "running")
        self.assertEqual(self.pet.agent_controller.current_presentation.active_count, 1)

    def test_stale_children_do_not_mask_or_resurrect_parent_results(self):
        for terminal in ("done", "failed", "cancelled", "ended"):
            with self.subTest(terminal=terminal):
                self.projects.reset()
                self.start()
                self.send(
                    "prompt",
                    thread="child",
                    agent_scope="subagent",
                    parent_session_id="a",
                )
                self.advance(61)
                self.send(terminal)
                self.assertEqual(self.projects.cards[0].rows[0].state, terminal)
                self.advance(301)
                self.assertFalse(self.projects.cards)
                self.send("heartbeat", thread="child", agent_scope="subagent")
                self.assertEqual(self.projects.cards[0].rows[0].state, "running")

    def test_fresh_child_and_human_wait_are_preserved(self):
        self.start()
        self.send(
            "prompt", thread="child", agent_scope="subagent", parent_session_id="a"
        )
        self.send("waiting", thread="child", agent_scope="subagent", event_id="ask")
        self.advance(61)
        self.send("done")
        self.assertEqual(self.projects.cards[0].rows[0].state, "waiting")

    def test_internal_failure_does_not_interrupt_main_work(self):
        self.start()
        self.send("prompt", thread="guardian", agent_scope="internal")
        self.send("failed", thread="guardian", agent_scope="internal")
        self.assertEqual(self.pet.current_state, "running")
        self.assertEqual(self.pet.agent_controller.current_presentation.active_count, 1)
        self.assertIsNone(self.pet.agent_controller.current_presentation.notice)

    def test_recovery_terminal_evidence_drops_row_without_completion(self):
        self.projects.restore_activity(
            RecoverySnapshot(
                "recovered",
                "t",
                "main",
                self.projects.wall_now() - 30,
                self.projects.wall_now() - 1,
                self.projects.wall_now(),
            )
        )
        target = self.projects.codex_turn_targets()[0]
        self.activity.observe_turn_outcome(CodexTurnOutcome(target, "done"))
        self.assertNotIn("recovered", self.projects.activities)
        self.assertFalse(self.projects.completions)
