"""Compaction lifecycle, privacy boundary and clock regressions."""

import json
from datetime import datetime, timezone
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from watched_kettle.features.project_activity.service import (
    ProjectActivityService,
    ThreadMetadata,
)
from watched_kettle.integrations.codex_hooks import (
    normalize_codex_hook,
    sanitize_pet_event,
    encode_pet_event,
)
from watched_kettle.integrations.log_lifecycle import normalize_codex_log_record
from watched_kettle.integrations.codex_spool import (
    spool_pet_event,
    drain_spooled_events,
)


class CompactionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.now = 100.0
        self.wall = 10000.0
        self.projects = ProjectActivityService(
            now=lambda: self.now, wall_now=lambda: self.wall
        )
        self.event("prompt")

    def event(self, event, thread="main", turn="1", **kwargs):
        return self.projects.observe(
            dict(source="codex", event=event, session_id=thread, turn_id=turn, **kwargs)
        )

    def phase(self, phase, **kwargs):
        return self.event("review", compaction_phase=phase, **kwargs)

    def advance(self, seconds):
        self.now += seconds
        self.wall += seconds
        self.projects.expire()

    def test_grace_is_ten_minutes_and_heartbeat_does_not_extend_or_clear_it(self):
        self.phase("start")
        for seconds in (60, 120, 419):
            self.advance(seconds)
            self.event("heartbeat")
            row = self.projects.cards[0].rows[0]
            self.assertTrue(row.compacting)
            self.assertFalse(row.uncertain)
        self.advance(1)
        self.event("heartbeat")
        row = self.projects.cards[0].rows[0]
        self.assertTrue(row.uncertain)
        self.assertFalse(row.compacting)
        self.assertEqual(self.projects.activities["main"].compaction_since, 100)
        self.assertTrue(self.phase("end"))
        self.assertFalse(self.projects.cards[0].rows[0].uncertain)
        self.advance(59)
        self.assertFalse(self.projects.cards[0].rows[0].uncertain)
        self.advance(1)
        self.assertTrue(self.projects.cards[0].rows[0].uncertain)

    def test_repeated_start_preserves_deadline_and_repeated_cycle_is_allowed(self):
        self.phase("start", event_id="start1")
        self.advance(100)
        self.assertFalse(self.phase("start", event_id="start1"))
        self.assertFalse(self.phase("start", event_id="duplicate-source"))
        self.assertEqual(self.projects.activities["main"].compaction_since, 100)
        self.phase("end", event_id="end1")
        self.assertFalse(self.phase("end", event_id="end1"))
        self.phase("start", event_id="start2")
        self.assertEqual(self.projects.activities["main"].compaction_since, 200)

    def test_phase_does_not_change_sort_or_history_and_end_never_completes(self):
        original = self.projects.cards[0].rows[0]
        history = self.projects.recent
        self.phase("start")
        self.advance(80)
        self.phase("end")
        row = self.projects.cards[0].rows[0]
        self.assertEqual((row.state, row.sort_at), (original.state, original.sort_at))
        self.assertEqual(self.projects.recent, history)
        self.assertFalse(self.projects.completions)

    def test_resume_and_priority_events_clear_compaction(self):
        for event in (
            "tool_start",
            "tool_end",
            "tool_failed",
            "waiting",
            "done",
            "failed",
            "cancelled",
        ):
            with self.subTest(event=event):
                self.setUp()
                if event in {"tool_end", "tool_failed"}:
                    self.event("tool_start", event_id="tool")
                self.phase("start")
                self.advance(601)
                self.assertTrue(self.event(event, event_id="tool"))
                activity = self.projects.activities["main"]
                self.assertIsNone(activity.compaction_since)
                self.assertFalse(activity.uncertain)
                self.assertEqual(bool(self.projects.completions), event == "done")

    def test_old_turn_missing_correlation_and_replay_do_not_affect_current(self):
        self.assertFalse(self.phase("start", turn=""))
        self.assertFalse(self.phase("start", turn="", collected_at=self.wall - 1))
        self.assertTrue(self.phase("start", turn="", collected_at=self.wall))
        self.advance(10)
        self.event("prompt", turn="2", collected_at=self.wall)
        self.assertFalse(self.phase("end", turn="1"))
        self.assertFalse(self.phase("start", turn="", collected_at=self.wall - 5))
        self.assertIsNone(self.projects.activities["main"].compaction_since)

    def test_old_end_does_not_end_a_later_compaction_in_same_turn(self):
        self.phase("start", collected_at=self.wall)
        self.advance(2)
        old_end = self.wall
        self.phase("end", collected_at=old_end)
        self.advance(2)
        self.phase("start", collected_at=self.wall)
        self.assertFalse(self.phase("end", collected_at=old_end))
        self.assertIsNotNone(self.projects.activities["main"].compaction_since)

    def test_only_end_refreshes_existing_activity_without_creating_one(self):
        self.advance(60)
        self.assertTrue(self.phase("end"))
        self.assertFalse(self.projects.cards[0].rows[0].uncertain)
        self.assertFalse(self.projects.cards[0].rows[0].compacting)
        self.assertFalse(self.phase("end", thread="missing"))
        self.event("done")
        self.assertFalse(self.phase("start"))
        self.assertFalse(self.phase("end"))
        self.assertEqual(len(self.projects.completions), 1)

    def test_wait_and_child_compaction_do_not_replace_main_display(self):
        self.event(
            "prompt", thread="child", agent_scope="subagent", parent_thread_id="main"
        )
        self.phase("start", thread="child")
        self.assertFalse(self.projects.cards[0].rows[0].compacting)
        self.event("waiting", event_id="approval")
        self.assertFalse(self.phase("start"))
        self.advance(601)
        self.assertEqual(self.projects.cards[0].rows[0].state, "waiting")
        self.assertFalse(self.projects.cards[0].rows[0].uncertain)

    def test_title_updates_do_not_end_compaction_and_reset_clears_it(self):
        self.phase("start")
        self.projects.set_metadata(ThreadMetadata("main", title="Updated"), 0)
        self.assertTrue(self.projects.cards[0].rows[0].compacting)
        self.projects.reset()
        self.assertFalse(self.projects.cards)
        self.assertFalse(self.phase("end"))

    def test_hook_encode_and_spool_keep_phase_time_without_content(self):
        for hook, phase in (
            ("PreCompact", "start"),
            ("PostCompact", "end"),
            ("SessionStart", "end"),
        ):
            with (
                self.subTest(hook=hook),
                patch(
                    "watched_kettle.integrations.codex_hooks.time.time",
                    return_value=10001.0,
                ),
            ):
                event = normalize_codex_hook(
                    dict(
                        hook_event_name=hook,
                        source="compact",
                        session_id="s",
                        turn_id="t",
                        event_id="id",
                        summary="SECRET",
                    )
                )
                self.assertEqual(event["event"], "review")
                self.assertEqual(event["compaction_phase"], phase)
                self.assertEqual(event["collected_at"], 10001)
                self.assertEqual(event["event_id"], "id")
                self.assertNotIn("SECRET", encode_pet_event(event).decode())
                with TemporaryDirectory() as folder:
                    self.assertTrue(spool_pet_event(event, folder))
                    self.assertEqual(list(drain_spooled_events(folder)), [event])

    def test_log_completion_and_compaction_are_end_only_with_original_time(self):
        stamp = datetime.fromtimestamp(self.wall, timezone.utc).isoformat()
        for record_type, kind in (
            ("event_msg", "context_compacted"),
            ("response_item", "compaction"),
        ):
            self.setUp()
            event = normalize_codex_log_record(
                dict(
                    type=record_type,
                    timestamp=stamp,
                    payload=dict(type=kind, summary="SECRET"),
                ),
                "main",
                agent_scope="main",
            )
            self.assertEqual(event["compaction_phase"], "end")
            self.assertEqual(event["collected_at"], self.wall)
            self.assertNotIn("SECRET", json.dumps(event))
            self.assertTrue(self.projects.observe(event))
            self.assertFalse(self.projects.cards[0].rows[0].compacting)

    def test_untrusted_phase_and_timestamp_values_are_filtered(self):
        for value in (None, {}, [], "bogus", True):
            event = sanitize_pet_event(
                dict(
                    source="codex",
                    event="review",
                    compaction_phase=value,
                    collected_at=value,
                )
            )
            self.assertNotIn("compaction_phase", event)
            self.assertNotIn("collected_at", event)
        for value in (float("nan"), float("inf"), -1):
            self.assertNotIn(
                "collected_at",
                sanitize_pet_event(
                    dict(source="codex", event="review", collected_at=value)
                ),
            )
