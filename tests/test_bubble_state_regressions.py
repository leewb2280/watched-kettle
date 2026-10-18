"""State regressions across IPC, activity policy and the actual Qt card widgets."""

from types import SimpleNamespace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from tests import test_project_completion_rows as helpers
from watched_kettle.features.agent_activity.service import AgentActivityService
from watched_kettle.features.project_activity.service import (
    ProjectActivityService,
    ThreadMetadata,
)
from watched_kettle.integrations.codex_hooks import sanitize_pet_event
from watched_kettle.integrations.codex_ipc import (
    CodexHookServer,
    JSONL_TRANSPORT,
    PIPE_TRANSPORT,
)
from watched_kettle.state.controller import PetAgentController


class BubbleStateRegressions(unittest.TestCase):
    setUpClass = classmethod(helpers.CompletionTests.setUpClass.__func__)
    advance = helpers.CompletionTests.advance
    window = helpers.CompletionTests.window
    row = helpers.CompletionTests.row

    def setUp(self):
        helpers.CompletionTests.setUp(self)
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.clock_patch = patch(
            "watched_kettle.integrations.codex_ipc.time.monotonic", lambda: self.now
        )
        self.clock_patch.start()
        self.addCleanup(self.clock_patch.stop)
        self.pet.current_state = "idle"
        self.pet.agent_controller = PetAgentController(
            lambda state: setattr(self.pet, "current_state", state), parent=self.pet
        )
        self.pet.apply_agent_payload = self.pet.agent_controller.apply_payload
        self.activity = AgentActivityService(self.pet, projects=self.projects)
        self.server = CodexHookServer(
            f"bubble-regression-{uuid4().hex}",
            spool_directory=Path(self.directory.name) / "queue",
            managed_spool_directory=None,
            managed_hook_health_path=None,
        )
        self.server.payload_received.connect(self.activity.observe)
        # Confirmed main fixtures model a matching persisted rollout header.
        self.log_scopes = {}
        self.server.log_monitor = SimpleNamespace(
            session_scope=lambda thread: self.log_scopes.get(thread, "unknown")
        )

    def tearDown(self):
        self.server.log_monitor = None
        self.server.close()
        self.pet.agent_controller.transient_timer.stop()
        self.pet.agent_controller.stale_session_timer.stop()
        helpers.CompletionTests.tearDown(self)

    def send(
        self, event="prompt", thread="a", turn="1", transport=PIPE_TRANSPORT, **extra
    ):
        payload = sanitize_pet_event(
            dict(
                source="codex",
                session_id=thread,
                event=event,
                turn_id=turn,
                agent_scope=extra.pop("agent_scope", "main"),
                **extra,
            )
        )
        self.assertIsNotNone(payload)
        delivered = self.server._deliver_payload(payload, transport)
        self.controller._render()
        self.app.processEvents()
        return delivered

    def start(self, thread="a", **extra):
        self.log_scopes[thread] = extra.get("agent_scope", "main")
        self.send(thread=thread, **extra)
        self.projects.set_metadata(
            ThreadMetadata(
                thread,
                "p",
                "프로젝트",
                title=thread,
                agent_scope=extra.get("agent_scope", "main"),
            ),
            self.projects.generation,
        )
        self.app.processEvents()

    def assert_status(self, badge, summary, thread="a"):
        self.assertTrue(self.controller.visible_windows)
        self.assertEqual(self.row(thread).badge.text(), badge)
        self.assertEqual(self.window().content.summary, summary)

    def test_unrelated_hook_cannot_discard_user_response(self):
        self.start()
        self.send("waiting", event_id="question", transport=JSONL_TRANSPORT)
        self.send("tool_start", event_id="other")
        self.send("tool_end", event_id="other")
        self.advance(0.5)
        self.assertTrue(
            self.send("tool_end", event_id="question", transport=JSONL_TRANSPORT)
        )
        self.assert_status("작업 중", "작업 중 1개")
        self.assertEqual(self.pet.agent_controller.aggregate_state.state, "running")

    def test_async_question_stays_visible_through_tool_results_and_resolves_one_at_a_time(
        self,
    ):
        self.start()
        for call in ("first", "second"):
            self.send("question_wait", event_id=call, transport=JSONL_TRANSPORT)
        self.assert_status("확인 필요", "확인 필요 1개")
        self.assertEqual(self.pet.agent_controller.aggregate_state.state, "waiting")

        self.send("tool_end", event_id="first")  # PostToolUse for accepted delivery
        self.send("tool_start", event_id="other")
        self.send("tool_end", event_id="other")
        self.send("prompt", turn="")  # Hook may precede the logged user message.
        self.assert_status("확인 필요", "확인 필요 1개")
        self.assertEqual(self.pet.agent_controller.aggregate_state.state, "waiting")

        self.send("question_resolved", event_id="first", transport=JSONL_TRANSPORT)
        self.assert_status("확인 필요", "확인 필요 1개")
        self.assertEqual(self.projects.activities["a"].question_waits, {"second"})
        self.send("question_resolved", event_id="second", transport=JSONL_TRANSPORT)
        self.assert_status("작업 중", "작업 중 1개")
        self.assertEqual(self.pet.agent_controller.aggregate_state.state, "running")

    def test_async_question_keeps_other_wait_and_rejects_old_turn_reply(self):
        self.start()
        self.send("question_wait", event_id="question", transport=JSONL_TRANSPORT)
        self.send("permission", event_id="approval", approval_actor="user")
        self.send(
            "question_resolved",
            event_id="question",
            turn="old",
            transport=JSONL_TRANSPORT,
        )
        self.assertEqual(self.projects.activities["a"].question_waits, {"question"})
        self.send("question_resolved", event_id="question", transport=JSONL_TRANSPORT)
        self.assert_status("확인 필요", "확인 필요 1개")
        self.send("permission_resolved", event_id="approval")
        self.assert_status("작업 중", "작업 중 1개")

    def test_async_question_is_cleared_when_turn_ends(self):
        for ending in ("done", "cancelled", "failed"):
            with self.subTest(ending=ending):
                self.projects.reset()
                self.pet.agent_controller.clear()
                self.start()
                self.send(
                    "question_wait", event_id="question", transport=JSONL_TRANSPORT
                )
                self.send(ending, transport=JSONL_TRANSPORT)
                activity = self.projects.activities.get("a")
                self.assertFalse(activity and activity.question_waits)
                self.assertEqual(
                    self.pet.agent_controller.aggregate_state.state, "idle"
                )

    def test_async_question_after_early_hook_result_and_new_turn(self):
        self.start()
        self.send("tool_start", event_id="question")
        self.send("tool_end", event_id="question")
        self.send("question_wait", event_id="question", transport=JSONL_TRANSPORT)
        self.assert_status("확인 필요", "확인 필요 1개")
        self.send("prompt", turn="2", transport=JSONL_TRANSPORT)
        self.assert_status("작업 중", "작업 중 1개")
        self.assertFalse(self.projects.activities["a"].question_waits)
        self.send(
            "question_resolved",
            turn="1",
            event_id="question",
            transport=JSONL_TRANSPORT,
        )
        self.assertEqual(self.projects.activities["a"].turn_id, "2")
        self.assert_status("작업 중", "작업 중 1개")

    def test_fast_approval_actor_change_reaches_card_and_pet(self):
        self.start()
        self.send("permission", event_id="approval", approval_actor="auto")
        self.advance(0.1)
        self.assertTrue(
            self.send("permission", event_id="approval", approval_actor="user")
        )
        self.assert_status("확인 필요", "확인 필요 1개")
        self.assertEqual(self.pet.agent_controller.aggregate_state.state, "waiting")

    def test_approval_actor_can_return_to_a_previous_value(self):
        self.start()
        for actor, badge in (
            ("user", "확인 필요"),
            ("auto", "작업 중"),
            ("user", "확인 필요"),
        ):
            self.assertTrue(
                self.send("permission", event_id="approval", approval_actor=actor)
            )
            self.assert_status(badge, f"{badge} 1개")
            self.advance(0.1)

    def test_unknown_completion_can_be_confirmed_without_new_animation_or_deadline(
        self,
    ):
        self.start(agent_scope="unknown")
        self.send("done", agent_scope="unknown", transport=JSONL_TRANSPORT)
        self.assertFalse(self.controller.visible_windows)
        self.advance(20)
        self.projects.completion_duration = 60
        self.send("done", transport=JSONL_TRANSPORT)
        self.assert_status("완료", "완료 1개")
        self.assertFalse(self.row().row.highlighted)
        self.assertEqual(len(self.projects.completions), 1)
        record = self.projects.completions[0]
        self.assertEqual(
            (record.completed_at, record.highlight_until, record.expires_at),
            (100, 115, 400),
        )
        self.assertEqual(self.pet.current_state, "idle")
        self.send("done", transport=JSONL_TRANSPORT)
        self.assertEqual(len(self.projects.completions), 1)

    def test_fresh_parent_is_not_hidden_by_stale_child(self):
        self.start()
        self.advance(1)
        self.send(thread="child", agent_scope="subagent", parent_session_id="a")
        window, row = self.window(), self.row()
        self.advance(61)
        self.send("heartbeat")
        self.assertTrue(self.projects.activities["child"].uncertain)
        self.assert_status("작업 중", "작업 중 1개")
        self.assertIs(self.window(), window)
        self.assertIs(self.row(), row)

    def test_exact_duplicates_preserve_the_existing_suppression_windows(self):
        self.start()
        self.send("tool_start", event_id="tool")
        self.advance(1)
        self.assertFalse(self.send("tool_start", event_id="tool"))
        self.advance(2)
        self.assertFalse(
            self.send("tool_start", event_id="tool", transport=JSONL_TRANSPORT)
        )
        self.advance(0.01)
        self.assertTrue(
            self.send("tool_start", event_id="tool", transport=JSONL_TRANSPORT)
        )
        self.assertEqual(self.projects.activities["a"].active_tools, {"tool"})
        self.assertEqual(self.server.suppressed_duplicate_count, 2)

    def test_new_turn_with_same_call_id_is_not_a_duplicate(self):
        self.start()
        self.send("tool_start", event_id="reused")
        self.send("tool_end", event_id="reused")
        self.send("prompt", turn="2", transport=JSONL_TRANSPORT)
        self.send("waiting", turn="2", event_id="reused", transport=JSONL_TRANSPORT)
        self.assertTrue(
            self.send(
                "tool_end", turn="2", event_id="reused", transport=JSONL_TRANSPORT
            )
        )
        self.assert_status("작업 중", "작업 중 1개")
        self.assertEqual(self.projects.activities["a"].turn_id, "2")

    def test_identified_log_start_enriches_idless_hook_without_losing_wait(self):
        self.start(turn="")
        self.send("waiting", turn="", event_id="question")
        original = self.projects.activities["a"]
        self.assertTrue(self.send("prompt", transport=JSONL_TRANSPORT))
        self.assertIs(self.projects.activities["a"], original)
        self.assertEqual(original.turn_id, "1")
        self.assert_status("확인 필요", "확인 필요 1개")
        self.send("tool_end", event_id="question", transport=JSONL_TRANSPORT)
        self.assert_status("작업 중", "작업 중 1개")

    def test_identified_log_completion_is_not_hidden_by_idless_hook(self):
        self.start()
        self.send("done", turn="")
        self.assert_status("작업 중", "작업 중 1개")
        self.assertTrue(self.send("done", transport=JSONL_TRANSPORT))
        self.assert_status("완료", "완료 1개")
        self.assertEqual(len(self.projects.completions), 1)

    def test_compaction_start_and_end_with_same_id_are_different_events(self):
        self.start()
        self.send("review", event_id="cycle", compaction_phase="start")
        self.assert_status("컨텍스트 압축 중", "작업 중 1개")
        self.assertTrue(self.send("review", event_id="cycle", compaction_phase="end"))
        self.assert_status("작업 중", "작업 중 1개")

    def test_permission_changes_and_results_preserve_other_requests(self):
        self.start()
        self.send("waiting", event_id="question", transport=JSONL_TRANSPORT)
        self.send("permission", event_id="approval", approval_actor="user")
        self.send("permission", event_id="approval", approval_actor="unknown")
        self.assertEqual(self.projects.activities["a"].waits, {"question", "approval"})
        self.send("tool_end", event_id="approval")
        self.send("tool_end", event_id="question", transport=JSONL_TRANSPORT)
        self.assert_status("작업 중", "작업 중 1개")
        self.assertEqual(self.pet.agent_controller.aggregate_state.state, "running")

    def test_resolution_of_one_request_does_not_clear_another(self):
        self.start()
        self.send("waiting", event_id="question")
        self.send("permission", event_id="approval", approval_actor="user")
        self.send("permission_resolved", event_id="approval")
        self.assert_status("확인 필요", "확인 필요 1개")
        self.assertEqual(self.projects.activities["a"].waits, {"question"})
        self.send("tool_end", event_id="question", turn="old")
        self.assert_status("확인 필요", "확인 필요 1개")
        self.send("tool_end", event_id="question")
        self.assert_status("작업 중", "작업 중 1개")

    def test_old_permission_replay_cannot_reopen_a_resolved_request(self):
        self.start()
        for event, call in (("permission_resolved", "first"), ("tool_end", "second")):
            self.send("permission", event_id=call, approval_actor="user")
            self.send(event, event_id=call)
            self.advance(4)
            self.send("permission", event_id=call, approval_actor="user")
            self.assert_status("작업 중", "작업 중 1개")
            self.assertEqual(self.pet.agent_controller.aggregate_state.state, "running")

    def test_completion_enrichment_within_highlight_window_keeps_original_record(self):
        self.start(agent_scope="unknown")
        self.send("done", agent_scope="unknown")
        self.advance(2)
        self.send("done", transport=JSONL_TRANSPORT)
        self.assert_status("완료", "완료 1개")
        self.assertTrue(self.row().row.highlighted)
        record = self.projects.completions[0]
        self.assertEqual(record.highlight_until, 115)
        self.assertEqual(self.pet.current_state, "idle")
        self.advance(3)
        self.send("done", transport=JSONL_TRANSPORT)
        self.assertEqual(self.projects.completions, (record,))
        self.advance(10)
        self.assertFalse(self.row().row.highlighted)

    def test_repeated_unknown_completion_does_not_extend_confirmation_lifetime(self):
        self.start(agent_scope="unknown")
        self.send("done", agent_scope="unknown")
        self.advance(10)
        self.send("done", agent_scope="unknown")
        self.advance(289)
        self.send("done", transport=JSONL_TRANSPORT)
        self.assertEqual(self.projects.completions[0].expires_at, 400)
        self.advance(1)
        self.assertFalse(self.controller.visible_windows)

    def test_new_turn_removes_unconfirmed_completion_and_rejects_old_confirmation(self):
        self.start(agent_scope="unknown")
        self.send("done", agent_scope="unknown")
        self.send("prompt", turn="2", transport=JSONL_TRANSPORT)
        self.send("done", turn="1")
        self.assert_status("작업 중", "작업 중 1개")
        self.assertEqual(self.projects.activities["a"].turn_id, "2")
        self.assertFalse(self.projects.completions)
        self.assertFalse(self.projects._unconfirmed_completions)
        self.assertEqual(self.pet.agent_controller.aggregate_state.state, "running")

    def test_reset_and_expiry_never_allow_late_confirmation(self):
        for cleanup in ("reset", "expiry", "expiry_without_tick"):
            with self.subTest(cleanup=cleanup):
                self.start(thread=cleanup, agent_scope="unknown")
                self.send("done", thread=cleanup, agent_scope="unknown")
                if cleanup == "reset":
                    self.projects.reset()
                elif cleanup == "expiry":
                    self.advance(300)
                else:
                    self.now += 300
                self.send("done", thread=cleanup, transport=JSONL_TRANSPORT)
                self.assertFalse(self.projects.completions)
                self.assertFalse(self.projects._unconfirmed_completions)
                self.assertFalse(self.controller.visible_windows)

    def test_confirmation_cannot_resurrect_a_dismissed_completion(self):
        self.start(agent_scope="unknown")
        self.send("done", agent_scope="unknown")
        self.send("done", transport=JSONL_TRANSPORT)
        record = self.projects.completions[0]
        self.row().title.click()
        self.assertEqual(self.projects.visible_completions, (record,))
        self.row().close_button.click()
        self.advance(4)
        self.send("done", transport=JSONL_TRANSPORT)
        self.assertFalse(self.controller.visible_windows)
        self.assertTrue(self.projects.completions[0].dismissed)

    def test_child_internal_and_parent_metadata_block_completion_enrichment(self):
        for scope in ("subagent", "internal", "parent_metadata", "parent_payload"):
            with self.subTest(scope=scope):
                self.start(thread=scope, agent_scope="unknown")
                self.send("done", thread=scope, agent_scope="unknown")
                if scope == "parent_metadata":
                    self.projects.set_metadata(
                        ThreadMetadata(scope, parent_thread_id="parent"),
                        self.projects.generation,
                    )
                if scope == "parent_payload":
                    self.send("done", thread=scope, parent_session_id="parent")
                elif scope in {"subagent", "internal"}:
                    self.send("done", thread=scope, agent_scope=scope)
                self.advance(2)
                self.send("done", thread=scope, transport=JSONL_TRANSPORT)
                self.assertFalse(self.projects.completions)
                self.assertFalse(self.controller.visible_windows)

    def test_idless_unknown_completion_is_not_guessed_from_later_main_event(self):
        self.start(turn="", agent_scope="unknown")
        self.send("done", turn="", agent_scope="unknown")
        self.send("done", transport=JSONL_TRANSPORT)
        self.assertFalse(self.projects.completions)
        self.assertIn("a", self.projects._unconfirmed_completions)

    def test_fresh_child_is_not_hidden_by_stale_parent(self):
        self.send(thread="child", agent_scope="subagent", parent_session_id="a")
        self.advance(1)
        self.start()
        self.advance(61)
        self.send("heartbeat", thread="child", agent_scope="subagent")
        self.assertTrue(self.projects.activities["a"].uncertain)
        self.assert_status("작업 중", "작업 중 1개")

    def test_all_stale_then_child_wait_then_recovery_agree_with_header(self):
        self.start()
        self.send(thread="child", agent_scope="subagent", parent_session_id="a")
        self.advance(61)
        self.assert_status("상태 확인 중", "상태 확인 중 1개")
        self.send("waiting", thread="child", agent_scope="subagent", event_id="ask")
        self.send("heartbeat")
        self.assert_status("확인 필요", "확인 필요 1개")
        self.send("tool_end", thread="child", agent_scope="subagent", event_id="ask")
        self.assert_status("작업 중", "작업 중 1개")

    def test_unconfirmed_records_are_bounded_and_retain_metadata_until_expiry(self):
        service = ProjectActivityService(now=lambda: self.now)
        with patch(
            "watched_kettle.features.project_activity.service.MAX_UNCONFIRMED_COMPLETIONS",
            3,
        ):
            for index in range(5):
                for event in ("prompt", "done"):
                    service.observe(
                        dict(
                            source="codex",
                            session_id=str(index),
                            turn_id="1",
                            event=event,
                            agent_scope="unknown",
                        )
                    )
            self.now += 10
            service.expire()
            self.assertEqual(set(service.metadata), {"2", "3", "4"})
            for thread in ("0", "4"):
                service.observe(
                    dict(
                        source="codex",
                        session_id=thread,
                        turn_id="1",
                        event="done",
                        agent_scope="main",
                    )
                )
            self.assertEqual([r.thread_id for r in service.completions], ["4"])
            self.now += 290
            service.expire()
            self.assertFalse(service._unconfirmed_completions)


if __name__ == "__main__":
    unittest.main()
