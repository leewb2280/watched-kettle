"""Questions and explicit parent stops precede work annotations."""

import unittest

from tests import test_bubble_state_regressions as helpers
from tests import test_codex_plan_mode as plan
from watched_kettle.features.project_activity.service import ThreadMetadata


class AttentionPriorityTests(unittest.TestCase):
    setUpClass = classmethod(helpers.BubbleStateRegressions.setUpClass.__func__)
    setUp = helpers.BubbleStateRegressions.setUp
    tearDown = helpers.BubbleStateRegressions.tearDown
    send = helpers.BubbleStateRegressions.send
    start = helpers.BubbleStateRegressions.start
    advance = helpers.BubbleStateRegressions.advance
    row = helpers.BubbleStateRegressions.row
    window = helpers.BubbleStateRegressions.window
    mode = plan.PlanModeProjectionTests.mode

    def annotated(self):
        self.start()
        self.mode()
        self.send("tool_start", event_id="sleep", tool_kind="time_wait")
        self.send("tool_start", event_id="agent", tool_kind="subagent_wait")

    def test_async_question_precedes_annotations_until_its_correlated_answer(self):
        self.annotated()
        self.send("question_wait", event_id="question")
        self.send("tool_end", event_id="question")  # accepted is not the answer
        self.send("tool_start", event_id="read")
        self.send("tool_end", event_id="read")
        self.assertEqual(self.row().badge.text(), "확인 필요")
        self.send("question_resolved", event_id="question", turn="old")
        self.assertEqual(self.row().badge.text(), "확인 필요")
        self.send("question_resolved", event_id="question")
        self.assertEqual(self.row().badge.text(), "서브에이전트 대기")

    def test_stop_clears_all_annotations_and_cannot_be_masked_by_child_work(self):
        self.annotated()
        self.send(thread="child", agent_scope="subagent", parent_session_id="a")
        self.send("waiting", thread="child", agent_scope="subagent", event_id="ask")
        self.send("cancelled")
        self.assertEqual(self.row().badge.text(), "중단")
        item = self.projects.activities["a"]
        self.assertFalse(item.planning or item.subagent_waits or item.time_waits)
        self.assertEqual(self.pet.agent_controller.current_presentation.active_count, 0)
        for event in (
            "heartbeat",
            "tool_start",
            "tool_end",
            "done",
            "question_resolved",
        ):
            self.send(event, thread="child", agent_scope="subagent", event_id="ask")
            self.assertEqual(self.row().badge.text(), "중단")
        self.advance(9)
        self.send("heartbeat", thread="child", agent_scope="subagent")
        self.assertFalse(self.projects.cards)

    def test_new_parent_turn_does_not_release_an_old_child_turn(self):
        self.start()
        self.send(thread="child", agent_scope="subagent", parent_session_id="a")
        self.send("cancelled")
        self.send("prompt", turn="2")
        self.send(
            "waiting", thread="child", turn="1", agent_scope="subagent", event_id="late"
        )
        self.assertEqual(self.row().badge.text(), "작업 중")
        self.send(
            "prompt",
            thread="child",
            turn="2",
            agent_scope="subagent",
            parent_session_id="a",
        )
        self.send(
            "waiting", thread="child", turn="2", agent_scope="subagent", event_id="new"
        )
        self.assertEqual(self.row().badge.text(), "확인 필요")

    def test_nested_children_are_frozen_but_another_root_is_unchanged(self):
        self.start()
        self.start("other")
        self.send(thread="child", agent_scope="subagent", parent_session_id="a")
        self.send(
            thread="grandchild", agent_scope="subagent", parent_session_id="child"
        )
        self.send("cancelled")
        self.send(
            "waiting", thread="grandchild", agent_scope="subagent", event_id="late"
        )
        self.assertEqual(self.row().badge.text(), "중단")
        self.assertEqual(self.row("other").badge.text(), "작업 중")

    def test_account_reset_removes_stop_barriers(self):
        self.start()
        self.send(thread="child", agent_scope="subagent", parent_session_id="a")
        self.send("cancelled")
        self.projects.reset()
        self.assertFalse(self.projects._blocked_parents)
        self.assertFalse(self.projects._blocked_children)

    def test_unverified_terminal_blocks_children_only_after_main_identity_is_confirmed(
        self,
    ):
        self.send(agent_scope="unknown")
        self.send("cancelled", agent_scope="unknown")
        self.assertNotIn("a", self.projects._blocked_parents)
        self.projects.set_metadata(
            ThreadMetadata("a", agent_scope="main"), self.projects.generation
        )
        self.assertIn("a", self.projects._blocked_parents)
