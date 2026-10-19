"""Fresh collector calls may contradict stored outcomes, never real turn endings."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication

from watched_kettle.application.runtime import ApplicationRuntime
from watched_kettle.features.agent_activity.service import AgentActivityService
from watched_kettle.features.project_activity.service import (
    ProjectActivityService,
    Activity,
)
from watched_kettle.integrations.activity_recovery import RecoverySnapshot
from watched_kettle.integrations.codex_hooks import sanitize_pet_event
from watched_kettle.integrations.codex_ipc import (
    CodexHookServer,
    PIPE_TRANSPORT,
    JSONL_TRANSPORT,
)
from watched_kettle.integrations.codex_log import CodexLogMonitor
from watched_kettle.state.codex_activity import (
    CodexLiveToolStart,
    CodexTurnOutcome,
    CodexTurnTarget,
)
from watched_kettle.state.controller import PetAgentController


class LiveRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.now, self.wall = 100.0, 20000.0
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "rollout-s.jsonl"
        self.projects = ProjectActivityService(
            now=lambda: self.now, wall_now=lambda: self.wall
        )
        self.monitor = CodexLogMonitor(
            now=lambda: datetime.fromtimestamp(self.wall, timezone.utc)
        )
        self.monitor._session_ids[self.path] = "s"
        self.monitor._agent_scopes[self.path] = "main"
        self.server = CodexHookServer(
            "live-recovery",
            spool_directory=Path(self.directory.name) / "queue",
            managed_spool_directory=None,
            managed_hook_health_path=None,
        )
        self.server.attach_log_monitor(self.monitor)
        self.addCleanup(self.server.close)
        self.pet = SimpleNamespace(current_state="idle")
        self.pet.agent_controller = PetAgentController(
            lambda state: setattr(self.pet, "current_state", state)
        )
        self.addCleanup(self.pet.agent_controller.transient_timer.stop)
        self.addCleanup(self.pet.agent_controller.stale_session_timer.stop)
        self.pet.apply_agent_payload = self.pet.agent_controller.apply_payload
        self.activity = AgentActivityService(self.pet, projects=self.projects)
        self.server.payload_received.connect(self.activity.observe)
        self.monitor.recovery_detected.connect(self.projects.restore_activity)
        self.seen = []
        self.server.payload_received.connect(self.seen.append)

    def advance(self, seconds=1):
        self.now += seconds
        self.wall += seconds

    def record(self, kind="response_item", **payload):
        self.monitor._process_line(
            self.path,
            json.dumps(
                dict(
                    timestamp=datetime.fromtimestamp(
                        self.wall, timezone.utc
                    ).isoformat(),
                    type=kind,
                    payload=payload,
                )
            ).encode(),
        )

    def tool(self, call="new"):
        self.record(type="function_call", name="exec", call_id=call)

    def hook(self, event, turn="t", **extra):
        self.server._deliver_payload(
            dict(
                source="codex",
                session_id="s",
                turn_id=turn,
                agent_scope="main",
                event=event,
                collected_at=self.wall,
                **extra,
            ),
            PIPE_TRANSPORT,
        )

    def restore(self):
        self.monitor._active_turns[self.path] = "t"
        self.monitor.recovery_detected.emit(
            RecoverySnapshot("s", "t", "main", self.wall - 30, self.wall - 1, self.wall)
        )

    def outcome(self, state="cancelled", thread="s"):
        item = self.projects.activities[thread]
        target = CodexTurnTarget(
            thread, item.turn_id, item.revision, self.projects.generation
        )
        self.activity.observe_turn_outcome(CodexTurnOutcome(target, state))

    def counts(self):
        return ApplicationRuntime._widget_activity(
            SimpleNamespace(projects=self.projects)
        ).get("codex", {"running": 0, "attention": 0})

    def test_two_tasks_recover_after_stored_interruption_and_finish_once(self):
        self.restore()
        self.activity.observe(
            dict(
                source="codex",
                session_id="other",
                turn_id="u",
                agent_scope="main",
                event="prompt",
            )
        )
        self.outcome()
        self.assertEqual(self.counts()["running"], 1)
        self.assertNotIn("s", self.projects.activities)
        self.advance()
        self.tool()
        self.assertEqual(self.counts()["running"], 2)
        self.assertEqual(self.pet.agent_controller.current_presentation.active_count, 2)
        self.assertFalse(self.projects.completions)
        self.outcome()
        self.assertEqual(self.counts()["running"], 2)
        self.assertFalse(self.projects.codex_turn_targets())
        self.record("event_msg", type="task_complete", turn_id="t")
        self.outcome("done")
        self.assertEqual(self.counts()["running"], 1)
        self.assertEqual(len(self.projects.visible_completions), 1)
        self.assertEqual(self.pet.agent_controller.current_presentation.active_count, 1)

    def test_all_stored_terminal_kinds_allow_later_verified_call(self):
        for state in ("done", "failed", "cancelled"):
            with self.subTest(state=state):
                self.projects.reset()
                self.restore()
                self.outcome(state)
                self.advance()
                self.tool(state)
                self.assertEqual(self.counts()["running"], 1)
                self.assertFalse(self.projects.completions)

    def test_live_work_closed_by_lookup_recovers_and_real_same_terminal_is_accepted(
        self,
    ):
        self.record("event_msg", type="task_started", turn_id="t")
        self.outcome("done")
        self.advance()
        self.tool()
        self.assertEqual(self.counts()["running"], 1)
        self.assertFalse(self.projects.visible_completions)
        self.hook("done")
        self.assertEqual(self.projects.activities["s"].state, "done")
        self.assertEqual(len(self.projects.visible_completions), 1)

    def test_hook_then_log_confirmation_is_not_lost_to_transport_dedup(self):
        self.restore()
        self.outcome()
        self.advance()
        self.hook("tool_start", event_id="new")
        self.assertNotIn("s", self.projects.activities)
        self.tool()
        self.assertEqual(self.counts()["running"], 1)

    def test_heartbeat_return_and_untrusted_proof_cannot_revive(self):
        self.restore()
        self.outcome()
        self.advance()
        proof = CodexLiveToolStart("s", "t", "new", self.wall)
        for event in ("heartbeat", "tool_end", "review", "tool_start"):
            self.hook(event, event_id="new", _codex_live_tool=proof)
            self.assertNotIn("s", self.projects.activities)
        self.hook(
            "tool_start",
            event_id="new",
            _codex_live_tool=dict(
                thread_id="s", turn_id="t", call_id="new", recorded_at=self.wall
            ),
        )
        self.assertNotIn("s", self.projects.activities)
        raw = sanitize_pet_event(
            dict(
                source="codex",
                session_id="s",
                event="tool_start",
                _codex_live_tool=proof,
            )
        )
        self.assertNotIn("_codex_live_tool", raw)

    def test_old_timestamps_and_previously_completed_calls_cannot_revive(self):
        self.record("event_msg", type="task_started", turn_id="t")
        self.tool("old")
        self.record(type="function_call_output", call_id="old", output="ok")
        self.outcome()
        self.advance()
        self.tool("old")
        self.assertNotEqual(self.projects.activities["s"].state, "running")
        self.wall -= 10
        self.tool("old-record")
        self.assertNotEqual(self.projects.activities["s"].state, "running")

    def test_real_terminal_before_new_call_hardens_stored_closure(self):
        for terminal in ("task_complete", "turn_aborted"):
            with self.subTest(terminal=terminal):
                self.projects.reset()
                self.restore()
                self.outcome()
                self.advance()
                self.record(
                    "event_msg", type=terminal, turn_id="t", reason="interrupted"
                )
                self.advance()
                self.tool(terminal)
                self.assertNotIn("s", self.projects.activities)

    def test_new_turn_and_account_reset_discard_old_closure(self):
        self.restore()
        self.outcome()
        self.advance()
        self.record("event_msg", type="task_started", turn_id="u")
        self.assertFalse(self.projects._stored_closures)
        self.record(type="function_call", name="exec", call_id="late", turn_id="t")
        self.assertEqual(self.projects.activities["s"].turn_id, "u")
        self.assertEqual(self.counts()["running"], 1)
        self.projects.reset()
        self.restore()
        self.outcome()
        self.projects.reset()
        self.assertFalse(self.projects._stored_closures)

    def test_unknown_permission_counts_as_work_and_only_new_live_call_clears_it(self):
        self.record("event_msg", type="task_started", turn_id="t")
        self.hook("permission")
        self.assertEqual(self.projects.activities["s"].state, "permission")
        self.assertEqual(self.counts(), dict(running=1, attention=0))
        self.advance()
        self.hook("tool_start", event_id="new")
        self.assertEqual(self.projects.activities["s"].state, "permission")
        self.tool()
        self.assertEqual(self.projects.activities["s"].state, "running")
        self.assertEqual(self.counts(), dict(running=1, attention=0))

    def test_identified_permissions_and_other_human_requests_are_preserved(self):
        self.record("event_msg", type="task_started", turn_id="t")
        self.hook("permission", event_id="identified")
        self.hook("permission", event_id="human", approval_actor="user")
        self.advance()
        self.tool()
        self.assertEqual(self.projects.activities["s"].permissions, {"identified"})
        self.assertEqual(self.counts(), dict(running=0, attention=1))
        self.hook("tool_end", event_id="human")
        self.assertEqual(self.projects.activities["s"].state, "permission")
        self.assertEqual(self.counts(), dict(running=1, attention=0))

    def test_unknown_indicator_does_not_clear_another_wait_and_uncertain_is_not_counted(
        self,
    ):
        self.record("event_msg", type="task_started", turn_id="t")
        self.hook("permission")
        self.hook("waiting", event_id="q")
        self.advance()
        self.tool()
        self.assertFalse(self.projects.activities["s"].permissions)
        self.assertEqual(self.projects.activities["s"].waits, {"q"})
        self.hook("tool_end", event_id="q")
        self.hook("permission")
        self.advance(181)
        self.projects.expire()
        self.assertEqual(self.counts()["running"], 0)

    def test_closure_budget_evicts_oldest_and_reset_releases_all(self):
        for index in range(4097):
            item = Activity(str(index), "t")
            self.projects._remember_stored_closure(item)
        self.assertEqual(len(self.projects._stored_closures), 4096)
        self.assertNotIn(("0", "t"), self.projects._stored_closures)
        self.projects.reset()
        self.assertFalse(self.projects._stored_closures)

    def test_evidence_for_another_call_is_not_accepted(self):
        self.restore()
        self.outcome()
        self.advance()
        self.server._deliver_payload(
            dict(
                source="codex",
                session_id="s",
                turn_id="t",
                event="tool_start",
                event_id="new",
                collected_at=self.wall,
                _codex_live_tool=CodexLiveToolStart("s", "other", "new", self.wall),
            ),
            JSONL_TRANSPORT,
        )
        self.assertNotIn("s", self.projects.activities)

    def test_literal_legacy_id_is_not_confused_with_an_unidentified_request(self):
        self.record("event_msg", type="task_started", turn_id="t")
        self.hook("permission")
        self.hook("permission", event_id="legacy")
        self.advance()
        self.tool()
        self.assertEqual(self.projects.activities["s"].permissions, {"legacy"})
        self.hook("permission", event_id="legacy", approval_actor="user")
        self.advance()
        self.tool("next")
        self.assertEqual(self.projects.activities["s"].waits, {"legacy"})
        self.assertEqual(self.counts(), dict(running=0, attention=1))

    def test_duplicate_logged_call_does_not_clear_the_unidentified_indicator(self):
        self.record("event_msg", type="task_started", turn_id="t")
        self.tool("old")
        self.record(type="function_call_output", call_id="old", output="ok")
        self.hook("permission")
        self.advance()
        self.tool("old")
        self.assertEqual(self.projects.activities["s"].state, "permission")
        self.assertNotIn("_codex_live_tool", self.seen[-1])
        self.advance()
        self.tool("fresh")
        self.assertEqual(self.projects.activities["s"].state, "running")

    def test_live_call_proofs_are_bounded_and_file_cleanup_forgets_them(self):
        for index in range(4097):
            self.monitor._remember_live_call(self.path, "t", str(index))
        self.assertEqual(len(self.monitor._seen_live_calls), 4096)
        self.assertNotIn((self.path, "t", "0"), self.monitor._seen_live_calls)
        self.monitor._clear_lifecycle(self.path)
        self.assertFalse(self.monitor._seen_live_calls)
