"""Codex turn evidence must not mutate a different turn or observation epoch."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication

from watched_kettle.features.project_activity.service import ProjectActivityService
from watched_kettle.integrations.codex_log import CodexLogMonitor
from watched_kettle.integrations.codex_log_worker import (
    ThreadedCodexLogMonitor,
    _LogWorker,
)
from watched_kettle.usage.device import DeviceBatch


class CollectorReliabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.now = 100.0
        self.wall = 20000.0
        self.projects = ProjectActivityService(
            now=lambda: self.now, wall_now=lambda: self.wall
        )
        self.monitor = CodexLogMonitor(
            now=lambda: datetime.fromtimestamp(self.wall, timezone.utc)
        )
        self.path = Path("synthetic-reliability.jsonl")
        self.monitor._session_ids[self.path] = "s"
        self.monitor._agent_scopes[self.path] = "main"
        self.events = []
        self.monitor.payload_detected.connect(self.receive)

    def receive(self, event):
        self.events.append(event)
        self.projects.observe(event)

    def record(self, kind, **payload):
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

    def start_two_turns(self):
        self.record("event_msg", type="task_started", turn_id="1")
        self.record("response_item", type="function_call", name="tool", call_id="old")
        self.record("event_msg", type="task_complete", turn_id="1")
        self.record("event_msg", type="task_started", turn_id="2")

    def test_old_return_does_not_confirm_current_turn(self):
        self.start_two_turns()
        self.now += 61
        self.wall += 61
        self.projects.expire()
        self.assertTrue(self.projects.activities["s"].uncertain)
        self.record("response_item", type="function_call_output", call_id="old")
        self.assertTrue(self.projects.activities["s"].uncertain)

    def test_old_terminal_preserves_current_question_and_heartbeat(self):
        self.start_two_turns()
        self.record(
            "response_item",
            type="function_call",
            name="request_user_input_async",
            call_id="q",
        )
        self.record("event_msg", type="task_complete", turn_id="1")
        self.assertEqual(self.monitor._active_turns[self.path], "2")
        self.record(
            "response_item",
            type="message",
            role="user",
            internal_chat_message_metadata_passthrough={"turn_id": "2"},
        )
        self.assertFalse(self.projects.activities["s"].question_waits)

    def test_one_missing_or_unreadable_file_does_not_block_healthy_files(self):
        for error in (FileNotFoundError(), PermissionError()):
            with self.subTest(error=type(error).__name__):
                bad, good = Path("missing.jsonl"), Path("healthy.jsonl")
                self.monitor._positions = {bad: 0, good: 0}
                seen = []

                def read(path):
                    if path == bad:
                        raise error
                    seen.append(path)

                with (
                    patch.object(self.monitor, "_discover_recent_files"),
                    patch.object(self.monitor, "_read_new_records", side_effect=read),
                    patch.object(self.monitor, "_poll_usage"),
                    patch.object(self.monitor, "_poll_recovery"),
                ):
                    self.monitor.poll_now()
                self.assertEqual(seen, [good])

    def test_previous_account_outputs_are_all_rejected(self):
        monitor = ThreadedCodexLogMonitor()
        monitor._thread = SimpleNamespace(isRunning=lambda: True)
        events = []
        batches = []
        monitor.payload_detected.connect(events.append)
        monitor.usage_detected.connect(batches.append)
        generation = monitor._generation
        monitor.account_changed(True)
        monitor._receive_payload((generation, {"event": "prompt"}))
        monitor._receive_usage(DeviceBatch(generation, (), ()))
        monitor._receive((generation, {"old": True}, {"old": "main"}))
        self.assertFalse(events)
        self.assertFalse(batches)
        self.assertNotIn("old", monitor._scopes)
        monitor._thread = None

    def test_task_complete_is_not_success_evidence(self):
        self.record("event_msg", type="task_started", turn_id="1")
        self.record(
            "event_msg",
            type="error",
            turn_id="1",
            codex_error_info="usage_limit_exceeded",
        )
        self.record("event_msg", type="task_complete", turn_id="1")
        self.assertEqual(self.projects.activities["s"].state, "ended")
        self.assertFalse(self.projects.completions)

    def test_error_then_retry_and_success_does_not_become_failure(self):
        self.record("event_msg", type="task_started", turn_id="1")
        self.record(
            "event_msg",
            type="error",
            turn_id="1",
            codex_error_info="rate_limit_exceeded",
        )
        self.assertEqual(self.projects.activities["s"].state, "running")
        self.record("response_item", type="reasoning", turn_id="1")
        self.record("event_msg", type="task_complete", turn_id="1")
        self.assertEqual(self.projects.activities["s"].state, "ended")
        self.projects.observe(
            dict(
                source="codex",
                session_id="s",
                turn_id="1",
                event="done",
                agent_scope="main",
            )
        )
        self.assertEqual(self.projects.activities["s"].state, "done")
        self.assertEqual(len(self.projects.completions), 1)

    def test_account_cutover_rebaselines_existing_files_without_replay(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "rollout-s.jsonl"

            def append(turn):
                with path.open("a", encoding="utf-8") as f:
                    f.write(
                        json.dumps(
                            dict(
                                type="event_msg",
                                payload=dict(type="task_started", turn_id=turn),
                            )
                        )
                        + "\n"
                    )

            append("before-start")
            worker = _LogWorker(dict(sessions_root=root))
            events = []
            worker.payload.connect(events.append)
            worker.start()
            try:
                append("before-account-switch")
                worker.reset_account(2)
                worker.reader.poll_now()
                self.assertFalse(events)
                self.assertFalse(worker.reader._recovery)
                append("after-switch")
                worker.reader.poll_now()
                self.assertEqual(events[-1][0], 2)
                self.assertEqual(events[-1][1]["turn_id"], "after-switch")
            finally:
                worker.reader.close()
