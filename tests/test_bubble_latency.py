"""First-frame latency, bounded startup recovery and metadata queue contracts."""

from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from PySide6.QtTest import QTest

from tests import test_project_completion_rows as helpers
from tests.test_project_metadata import Client
from watched_kettle.features.project_activity.metadata import _MetadataWorker
from watched_kettle.features.project_activity.service import ThreadMetadata
from watched_kettle.integrations.codex_log import CodexLogMonitor
from watched_kettle.integrations.codex_log_worker import ThreadedCodexLogMonitor
from watched_kettle.integrations.activity_recovery import RecoverySnapshot


class BubbleLatencyTests(unittest.TestCase):
    setUpClass = classmethod(helpers.CompletionTests.setUpClass.__func__)
    window = helpers.CompletionTests.window
    row = helpers.CompletionTests.row

    def setUp(self):
        helpers.CompletionTests.setUp(self)
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.wall = datetime.now(timezone.utc).timestamp()
        self.projects.wall_now = lambda: self.wall
        self.projects._collection_started_at = self.wall
        self.root = Path(self.directory.name)
        self.file = self.root / "rollout-11111111-1111-4111-8111-111111111111.jsonl"
        self.monitor = CodexLogMonitor(
            self.root, now=lambda: datetime.fromtimestamp(self.wall, timezone.utc)
        )
        self.monitor.payload_detected.connect(self.projects.observe)
        self.monitor.recovery_detected.connect(self.projects.restore_activity)
        self.events = []
        self.monitor.payload_detected.connect(self.events.append)

    def tearDown(self):
        self.monitor.close()
        helpers.CompletionTests.tearDown(self)

    def record(self, kind, event=None, age=0, **extra):
        return {
            "type": kind,
            "timestamp": datetime.fromtimestamp(
                self.wall - age, timezone.utc
            ).isoformat(),
            "payload": {**({"type": event} if event else {}), **extra},
        }

    def write(self, *records):
        with self.file.open("a", encoding="utf-8") as stream:
            for record in records:
                stream.write(json.dumps(record) + "\n")
        os.utime(self.file, (self.wall, self.wall))

    def seed(self, **header):
        self.write(
            self.record("session_meta", id="t", source="cli", **header),
            self.record("event_msg", "task_started", age=30, turn_id="1"),
            self.record("response_item", "reasoning", age=10),
        )

    def test_live_start_shows_without_waiting_for_activity_or_names(self):
        self.monitor.start()
        started = time.perf_counter()
        self.write(
            self.record("session_meta", id="t", source="cli"),
            self.record("event_msg", "task_started", turn_id="1"),
        )
        while (
            not self.controller.visible_windows and time.perf_counter() - started < 0.5
        ):
            QTest.qWait(5)
        self.assertTrue(self.controller.visible_windows)
        self.assertLess(time.perf_counter() - started, 0.5)
        self.assertEqual(self.row("t").badge.text(), "작업 중")
        self.assertEqual(self.window().content.heading, "프로젝트 확인 중")
        self.projects.set_metadata(
            ThreadMetadata("t", "todo", "Todo_app", title="프로그램 점검"), 0
        )
        self.assertEqual(len(self.controller.visible_windows), 1)
        self.assertEqual(self.window().content.heading, "Todo_app")
        self.assertEqual(set(self.window().project_rows.rows), {"t"})
        self.assertIn("shown", self.projects.latency["t"])
        self.assertIn("named", self.projects.latency["t"])

    def test_hook_start_first_frame_is_under_200ms(self):
        started = time.perf_counter()
        self.projects.observe(
            dict(
                source="codex",
                event="prompt",
                session_id="t",
                turn_id="1",
                agent_scope="main",
            )
        )
        self.app.processEvents()
        self.assertTrue(self.controller.visible_windows)
        self.assertLess(time.perf_counter() - started, 0.2)

    def test_restore_is_uncertain_and_new_reasoning_confirms_without_tool(self):
        self.seed()
        self.monitor.start()
        self.monitor.poll_now()
        self.assertEqual(self.row("t").badge.text(), "응답 없음")
        self.assertFalse(self.events)
        self.assertFalse(self.projects.recent)
        self.assertFalse(self.projects.completions)
        self.wall += 1
        self.write(self.record("response_item", "reasoning"))
        self.monitor.poll_now()
        self.assertEqual(self.row("t").badge.text(), "작업 중")
        self.assertNotIn("t", self.projects._recovery_deadlines)
        self.assertEqual([e["event"] for e in self.events], ["heartbeat"])

    def test_reasoning_during_scan_is_not_lost(self):
        self.seed()
        self.monitor.start()
        self.wall += 1
        self.write(self.record("response_item", "reasoning"))
        self.monitor.poll_now()
        self.assertEqual(self.row("t").badge.text(), "작업 중")

    def test_restore_expires_without_creating_completion(self):
        self.seed()
        self.monitor.start()
        self.monitor.poll_now()
        self.now += 60
        self.projects.expire()
        self.assertNotIn("t", self.projects.activities)
        self.assertFalse(self.controller.visible_windows)
        self.assertFalse(self.projects.completions)

    def test_old_completed_and_cancelled_turns_are_not_restored(self):
        for event in ("task_complete", "turn_aborted"):
            with self.subTest(event=event):
                self.monitor.close()
                self.file.unlink(missing_ok=True)
                self.seed()
                self.write(self.record("event_msg", event, age=5, turn_id="1"))
                self.monitor.start()
                self.monitor.poll_now()
                self.assertFalse(self.projects.activities)

    def test_new_terminal_during_scan_prevents_restore(self):
        self.seed()
        self.monitor.start()
        self.write(self.record("event_msg", "task_complete", turn_id="1"))
        self.monitor.poll_now()
        self.assertFalse(self.projects.activities)

    def test_new_turn_during_scan_wins_over_old_snapshot(self):
        self.seed()
        self.monitor.start()
        self.write(self.record("event_msg", "task_started", turn_id="2"))
        self.monitor.poll_now()
        self.assertEqual(self.projects.activities["t"].turn_id, "2")
        self.assertFalse(self.projects.activities["t"].uncertain)

    def test_inherited_history_and_stale_activity_are_not_restored(self):
        self.seed(subagent_history_start_ordinal=10)
        self.monitor.start()
        self.monitor.poll_now()
        self.assertFalse(self.projects.activities)
        self.monitor.close()
        self.file.unlink()
        self.seed()
        self.wall += 601
        self.monitor.start()
        self.monitor.poll_now()
        self.assertFalse(self.projects.activities)

    def test_recovered_tool_output_correlates_with_original_turn(self):
        self.seed()
        self.write(
            self.record(
                "response_item", "function_call", age=5, call_id="call", name="read"
            )
        )
        self.monitor.start()
        self.monitor.poll_now()
        self.assertEqual(self.projects.activities["t"].active_tools, {"call"})
        self.write(self.record("response_item", "function_call_output", call_id="call"))
        self.monitor.poll_now()
        self.assertFalse(self.projects.activities["t"].active_tools)

    def test_recovery_reads_yield_and_do_not_read_beyond_snapshot(self):
        self.seed()
        self.write(*(self.record("event_msg", "irrelevant") for _ in range(2500)))
        self.monitor.start()
        self.monitor.poll_now()
        self.assertTrue(self.monitor._recovery)
        self.assertFalse(self.projects.activities)
        self.monitor.poll_now()
        self.assertFalse(self.monitor._recovery)
        self.assertIn("t", self.projects.activities)

    def test_account_reset_rejects_old_recovery_evidence(self):
        snapshot = RecoverySnapshot(
            "t", "1", "main", self.wall - 30, self.wall - 5, self.wall
        )
        self.wall += 1
        self.projects.reset()
        self.projects.restore_activity(snapshot)
        self.assertFalse(self.projects.activities)

    def test_log_generation_and_account_filter_recovery(self):
        threaded = ThreadedCodexLogMonitor()
        seen = []
        threaded.recovery_detected.connect(seen.append)
        snapshot = RecoverySnapshot("t", "1", "main", self.wall, self.wall, self.wall)
        with patch.object(
            ThreadedCodexLogMonitor,
            "is_active",
            new_callable=unittest.mock.PropertyMock,
            return_value=True,
        ):
            threaded._receive_recovery(replace(snapshot, generation=99))
            self.assertFalse(seen)
            threaded._receive_recovery(snapshot)
            self.assertEqual(len(seen), 1)
            threaded.account_changed(True)
            threaded._receive_recovery(snapshot)
            self.assertEqual(len(seen), 1)

    def test_usage_keeps_750ms_cadence(self):
        self.seed()
        self.monitor.start()
        with patch(
            "watched_kettle.integrations.codex_log.monotonic", return_value=100.0
        ) as clock:
            with patch.object(
                self.monitor, "_read_usage_records", return_value=([], 0, 0)
            ) as read:
                for tick in (100.0, 100.25, 100.5, 100.75):
                    clock.return_value = tick
                    self.monitor.poll_now()
                self.assertEqual(read.call_count, 2)

    def test_latency_storage_is_bounded_and_expires(self):
        for index in range(600):
            self.projects.mark_latency(str(index), "detected")
        self.assertEqual(len(self.projects.latency), 512)
        self.now += 600
        self.assertFalse(self.projects.diagnostics()["latency"])

    def test_unchanged_activity_file_is_not_reopened_every_tick(self):
        self.seed()
        self.monitor.start()
        self.monitor._recovery.clear()
        self.monitor._last_usage_poll = time.monotonic()
        from watched_kettle.integrations.log_tail import TailCursor

        with patch.object(
            TailCursor, "read", wraps=self.monitor._event_cursors[self.file].read
        ) as read:
            self.monitor.poll_now()
            self.assertEqual(read.call_count, 0)
            self.write(self.record("event_msg", "task_started", turn_id="2"))
            self.monitor.poll_now()
            self.assertEqual(read.call_count, 1)


class MetadataPriorityTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.worker = _MetadataWorker(Client, Path(self.directory.name) / "state.json")
        self.worker.client = Client()
        self.now = 100.0
        self.worker.clock = lambda: self.now
        self.worker.last_account_check = self.now

    def reply_all(self):
        for rid, (thread, _) in tuple(self.worker.pending.items()):
            self.worker.response(
                rid, "thread/read", {}, {"thread": {"id": thread}}, None
            )

    def test_slow_maintenance_leaves_two_slots_for_new_work(self):
        targets = {str(i): (i + 1, 2, 15) for i in range(4)}
        self.worker.sync_targets(targets, 0)
        self.reply_all()
        self.now += 15
        self.worker.pump()
        self.assertEqual(len(self.worker.pending), 2)
        self.worker.sync_targets({**targets, "new": (5, 0, 3)}, 0)
        self.assertIn("new", [t for t, _ in self.worker.pending.values()])
        self.assertEqual(len(self.worker.pending), 3)
        self.worker.pump()
        self.assertEqual(len(self.worker.pending), 3)

    def test_running_and_completed_have_distinct_refresh_intervals(self):
        self.worker.sync_targets({"running": (1, 1, 3), "complete": (2, 2, 15)}, 0)
        self.reply_all()
        self.now += 3
        self.worker.pump()
        self.assertEqual([t for t, _ in self.worker.pending.values()], ["running"])
        self.assertEqual(self.worker.due["complete"], 115)
