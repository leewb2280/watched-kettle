"""No phantom activity from orphan or late tool lifecycle events."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from PySide6.QtWidgets import QApplication
from watched_kettle.features.agent_activity.service import AgentActivityService
from watched_kettle.features.project_activity.service import ProjectActivityService
from watched_kettle.integrations.codex_hooks import normalize_codex_hook
from watched_kettle.integrations.codex_log import CodexLogMonitor


class GhostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.now = 100.0
        self.wall = 10000.0
        self.projects = ProjectActivityService(
            now=lambda: self.now, wall_now=lambda: self.wall
        )

    def event(self, event, turn="1", **extra):
        return self.projects.observe(
            dict(source="codex", session_id="s", event=event, turn_id=turn, **extra)
        )

    def finish(self):
        self.event("prompt")
        self.event("tool_start", event_id="call")
        self.event("done")
        return self.projects.visible_completions[0]

    def test_done_then_idless_return_does_not_restore_running_or_hide_completion(self):
        record = self.finish()
        self.wall += 1
        self.assertFalse(
            self.event("tool_end", turn="", event_id="call", collected_at=self.wall)
        )
        self.assertEqual(self.projects.cards[0].rows[0].state, "done")
        self.assertEqual(self.projects.visible_completions[0], record)
        self.assertFalse(self.event("done"))

    def test_orphan_return_review_wait_and_heartbeat_create_nothing(self):
        for event in (
            "tool_end",
            "tool_failed",
            "review",
            "waiting",
            "heartbeat",
            "done",
        ):
            with self.subTest(event=event):
                self.event(event, event_id="orphan")
                self.assertFalse(self.projects.activities)
                self.assertFalse(self.projects.cards)
                self.assertFalse(self.projects.metadata)

    def test_verified_fresh_tool_start_bootstraps_and_finishes(self):
        self.wall += 1
        self.assertTrue(
            self.event("tool_start", event_id="call", collected_at=self.wall)
        )
        self.assertTrue(
            self.event("tool_end", turn="", event_id="call", collected_at=self.wall)
        )
        self.assertTrue(self.event("done"))
        self.assertEqual(len(self.projects.completions), 1)

    def test_bootstrap_requires_identity_call_time_and_freshness(self):
        for extra in (
            {},
            {"event_id": "call"},
            {"event_id": "call", "collected_at": 9999},
        ):
            self.assertFalse(self.event("tool_start", **extra))
        self.assertFalse(
            self.projects.observe(
                dict(
                    source="codex",
                    event="tool_start",
                    event_id="call",
                    collected_at=self.wall,
                )
            )
        )
        self.assertFalse(self.projects.activities)

    def test_closed_thread_survives_x_expiry_and_rejects_idless_start(self):
        record = self.finish()
        self.projects.dismiss_completions([record.record_id])
        self.now += 301
        self.wall += 301
        self.projects.expire()
        self.assertFalse(
            self.event("tool_start", turn="", event_id="new", collected_at=self.wall)
        )
        self.assertFalse(
            self.event("tool_end", turn="", event_id="call", collected_at=self.wall)
        )
        self.assertFalse(self.projects.cards)
        self.assertTrue(self.event("prompt", turn="2", collected_at=self.wall))
        self.assertEqual(self.projects.cards[0].rows[0].state, "running")

    def test_other_identified_new_turn_can_bootstrap_after_completion(self):
        self.finish()
        self.wall += 1
        self.assertTrue(
            self.event("tool_start", turn="2", event_id="new", collected_at=self.wall)
        )
        self.assertEqual(self.projects.activities["s"].turn_id, "2")
        self.assertFalse(self.projects.visible_completions)
        self.assertEqual(self.projects.cards[0].rows[0].state, "running")
        self.assertFalse(
            self.event("tool_end", turn="", event_id="call", collected_at=self.wall)
        )
        self.assertFalse(self.event("done", turn="1"))
        self.assertTrue(self.event("tool_end", turn="2", event_id="new"))
        self.assertTrue(self.event("done", turn="2"))

    def test_idless_hook_start_then_log_confirmation_preserves_time_and_tools(self):
        self.event("prompt", turn="", collected_at=self.wall)
        self.event("tool_start", turn="", event_id="call", collected_at=self.wall)
        original = self.projects.activities["s"]
        self.now += 1
        self.wall += 1
        self.assertFalse(self.event("prompt", turn="1", collected_at=self.wall))
        self.assertIs(self.projects.activities["s"], original)
        self.assertEqual(original.started_at, 100)
        self.assertEqual(original.active_tools, {"call"})
        self.assertFalse(self.event("prompt", turn="1"))
        self.assertEqual(original.active_tools, {"call"})
        self.assertTrue(self.event("tool_end", turn="", event_id="call"))
        self.assertTrue(self.event("done"))

    def test_fresh_idless_prompt_after_done_is_not_bound_to_retired_turn(self):
        self.finish()
        self.wall += 1
        self.assertTrue(self.event("prompt", turn="", collected_at=self.wall))
        self.assertEqual(self.projects.activities["s"].turn_id, "")
        self.assertFalse(self.event("prompt", turn="2", collected_at=self.wall))
        self.assertTrue(self.event("done", turn="2"))

    def test_unmatched_return_does_not_clear_wait_or_refresh_stale_work(self):
        self.event("prompt")
        self.event("waiting", event_id="approval")
        self.assertFalse(self.event("tool_end", turn="", event_id="other"))
        self.assertEqual(self.projects.cards[0].waiting, 1)
        self.assertTrue(self.event("tool_end", turn="", event_id="approval"))
        self.now += 61
        self.projects.expire()
        self.assertTrue(self.projects.activities["s"].uncertain)
        self.assertFalse(self.event("tool_end", turn="", event_id="approval"))
        self.assertTrue(self.projects.activities["s"].uncertain)

    def test_rejected_payload_never_reaches_pet_surface(self):
        seen = []
        surface = SimpleNamespace(apply_agent_payload=lambda p: seen.append(p))
        service = AgentActivityService(surface, projects=self.projects)
        service.observe(dict(source="codex", session_id="s", event="tool_end"))
        self.assertFalse(seen)

    def test_log_return_uses_call_turn_instead_of_latest_turn(self):
        with TemporaryDirectory() as folder:
            monitor = CodexLogMonitor(sessions_root=Path(folder))
            path = Path(folder) / "synthetic.jsonl"
            monitor._session_ids[path] = "s"
            monitor._agent_scopes[path] = "main"
            events = []
            monitor.payload_detected.connect(events.append)

            def record(kind, payload):
                monitor._process_line(
                    path, json.dumps(dict(type=kind, payload=payload)).encode()
                )

            record("event_msg", dict(type="task_started", turn_id="1"))
            record(
                "response_item", dict(type="function_call", call_id="old", name="tool")
            )
            record("event_msg", dict(type="task_complete", turn_id="1"))
            record("event_msg", dict(type="task_started", turn_id="2"))
            record(
                "response_item", dict(type="function_call", call_id="new", name="tool")
            )
            record("response_item", dict(type="function_call_output", call_id="old"))
            self.assertEqual(events[-1]["turn_id"], "1")
            record(
                "response_item", dict(type="function_call_output", call_id="missing")
            )
            self.assertNotIn("turn_id", events[-1])
            monitor._forget(path)
            self.assertFalse(monitor._tool_turns)

    def test_hook_tool_timestamps_survive_sanitization(self):
        for hook in ("PreToolUse", "PostToolUse"):
            event = normalize_codex_hook(
                dict(hook_event_name=hook, session_id="s", tool_use_id="call")
            )
            self.assertGreater(event["collected_at"], 0)
            self.assertEqual(event["event_id"], "call")

    def test_new_idless_run_does_not_inherit_previous_call(self):
        self.event("prompt", turn="", collected_at=self.wall)
        self.event("tool_start", turn="", event_id="old")
        self.event("done", turn="")
        self.wall += 3
        self.now += 3
        self.event("prompt", turn="", collected_at=self.wall)
        self.assertFalse(self.event("tool_end", turn="", event_id="old"))
        self.assertEqual(self.projects.activities["s"].state, "running")
