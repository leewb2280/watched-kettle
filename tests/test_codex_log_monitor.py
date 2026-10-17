import json
import os
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from watched_kettle.integrations.codex_ipc import (
    CodexHookServer,
    JSONL_TRANSPORT,
    PIPE_TRANSPORT,
)
from watched_kettle.integrations.codex_log import (
    CodexLogMonitor,
    normalize_codex_log_record,
)


class CodexLogRecordTests(unittest.TestCase):
    def test_maps_privacy_safe_task_and_tool_metadata(self):
        cases = (
            ("event_msg", "task_complete", "ended"),
            ("event_msg", "context_compacted", "review"),
            ("response_item", "compaction", "review"),
            ("response_item", "function_call", "tool_start"),
            ("response_item", "custom_tool_call", "tool_start"),
            ("response_item", "function_call_output", "tool_end"),
            ("response_item", "custom_tool_call_output", "tool_end"),
        )
        for record_type, payload_type, expected in cases:
            with self.subTest(payload_type=payload_type):
                event = normalize_codex_log_record(
                    {
                        "type": record_type,
                        "payload": {
                            "type": payload_type,
                            "turn_id": "turn-1",
                            "call_id": "call-1",
                            "message": "private prompt or response",
                            "arguments": "private tool arguments",
                            "output": "private tool output",
                        },
                    },
                    "session-1",
                    set(),
                )
                self.assertEqual(event["event"], expected)
                serialized = json.dumps(event)
                self.assertNotIn("private", serialized)
                self.assertNotIn("message", serialized)
                self.assertNotIn("arguments", serialized)
                self.assertNotIn("output", serialized)

    def test_task_started_is_only_a_monitor_candidate(self):
        event = normalize_codex_log_record(
            {
                "type": "event_msg",
                "payload": {"type": "task_started", "turn_id": "turn-1"},
            },
            "session-1",
            set(),
        )

        self.assertIsNone(event)

    def test_interrupted_turn_is_cancelled_but_other_abort_is_failed(self):
        interrupted = normalize_codex_log_record(
            {
                "type": "event_msg",
                "payload": {
                    "type": "turn_aborted",
                    "reason": "interrupted",
                    "turn_id": "turn-1",
                },
            },
            "session-1",
            set(),
        )
        failed = normalize_codex_log_record(
            {
                "type": "event_msg",
                "payload": {
                    "type": "turn_aborted",
                    "reason": "runtime_error",
                    "turn_id": "turn-2",
                },
            },
            "session-1",
            set(),
        )

        self.assertEqual(interrupted["event"], "cancelled")
        self.assertEqual(failed["event"], "failed")

    def test_request_user_input_waits_until_its_output(self):
        pending = set()
        waiting = normalize_codex_log_record(
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "request_user_input",
                    "call_id": "call-1",
                    "arguments": "private questions",
                },
            },
            "session-1",
            pending,
        )
        resumed = normalize_codex_log_record(
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "call_id": "call-1",
                    "output": "private answer",
                },
            },
            "session-1",
            pending,
        )

        self.assertEqual(waiting["event"], "waiting")
        self.assertEqual(resumed["event"], "tool_end")
        self.assertEqual(resumed["event_id"], waiting["event_id"])
        self.assertEqual(pending, set())

    def test_async_question_waits_for_next_user_message_in_same_turn(self):
        questions = {}

        def record(payload):
            return normalize_codex_log_record(
                {"type": "response_item", "payload": payload},
                "session-1",
                set(),
                "main",
                questions,
                "turn-1",
            )

        for call in ("first", "second"):
            opened = record(
                {
                    "type": "function_call",
                    "name": "request_user_input_async",
                    "call_id": call,
                    "arguments": "private question",
                }
            )
            self.assertEqual(opened["event"], "question_wait")
            self.assertEqual(opened["event_id"], call)
            self.assertNotIn("private", str(opened))
            self.assertIsNone(
                record(
                    {
                        "type": "function_call_output",
                        "call_id": call,
                        "output": '{"accepted": true}',
                    }
                )
            )

        self.assertEqual(
            record({"type": "function_call", "call_id": "other"})["event"], "tool_start"
        )
        self.assertIsNone(
            normalize_codex_log_record(
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "internal_chat_message_metadata_passthrough": {
                            "turn_id": "old-turn"
                        },
                        "content": [{"type": "input_text", "text": "private reply"}],
                    },
                },
                "session-1",
                set(),
                "main",
                questions,
                "turn-1",
            )
        )
        first = record(
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "private reply"}],
            }
        )
        second = record({"type": "message", "role": "user"})
        self.assertEqual((first["event_id"], second["event_id"]), ("first", "second"))
        self.assertEqual((first["event"], second["event"]), ("question_resolved",) * 2)
        self.assertNotIn("private", str(first))
        self.assertIsNone(
            record(
                {
                    "type": "function_call_output",
                    "call_id": "first",
                    "output": '{"accepted": true}',
                }
            )
        )

    def test_rejected_async_question_is_resolved_without_user_message(self):
        questions = {}
        call = {
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "request_user_input_async",
                "call_id": "failed-question",
            },
        }
        output = {
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "call_id": "failed-question",
                "output": '{"accepted": false}',
            },
        }
        self.assertEqual(
            normalize_codex_log_record(
                call, "session-1", set(), "main", questions, "turn-1"
            )["event"],
            "question_wait",
        )
        self.assertEqual(
            normalize_codex_log_record(
                output, "session-1", set(), "main", questions, "turn-1"
            )["event"],
            "question_resolved",
        )


class CodexLogMonitorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_diagnostics_reports_whether_sessions_root_exists(self):
        with TemporaryDirectory() as directory:
            missing = Path(directory) / "missing"
            monitor = CodexLogMonitor(missing)

            self.assertFalse(monitor.diagnostics()["sessions_root_exists"])
            missing.mkdir()
            self.assertTrue(monitor.diagnostics()["sessions_root_exists"])

    def test_server_detects_codex_config_or_sessions_without_guessing_exe(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / ".codex" / "config.toml"
            sessions = root / ".codex" / "sessions"
            monitor = CodexLogMonitor(sessions)
            server = CodexHookServer(
                f"watched-kettle-presence-{uuid4().hex}",
                codex_config_path=config,
            )
            server.attach_log_monitor(monitor)
            try:
                environment = server.diagnostics()["codex_environment"]
                self.assertFalse(environment["detected"])
                self.assertFalse(environment["config_exists"])
                self.assertFalse(environment["sessions_root_exists"])

                config.parent.mkdir()
                config.write_text("", encoding="utf-8")
                environment = server.diagnostics()["codex_environment"]
                self.assertTrue(environment["detected"])
                self.assertTrue(environment["config_exists"])

                config.unlink()
                sessions.mkdir()
                environment = server.diagnostics()["codex_environment"]
                self.assertTrue(environment["detected"])
                self.assertTrue(environment["sessions_root_exists"])
            finally:
                server.close()

    def test_starting_monitor_does_not_replay_existing_records(self):
        with TemporaryDirectory() as directory:
            now = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
            day = Path(directory) / "2026" / "08" / "31"
            day.mkdir(parents=True)
            rollout = day / (
                "rollout-2026-08-31T12-00-00-11111111-1111-1111-1111-111111111111.jsonl"
            )
            rollout.write_text(
                json.dumps(
                    {
                        "type": "event_msg",
                        "payload": {"type": "task_started", "turn_id": "old"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            monitor = CodexLogMonitor(
                directory,
                now=lambda: now,
            )
            received = []
            monitor.payload_detected.connect(received.append)
            try:
                monitor.start()
                monitor.poll_now()
                self.assertEqual(received, [])

                with rollout.open("a", encoding="utf-8") as stream:
                    stream.write(
                        json.dumps(
                            {
                                "type": "event_msg",
                                "payload": {
                                    "type": "task_complete",
                                    "turn_id": "new",
                                },
                            }
                        )
                        + "\n"
                    )
                monitor.poll_now()
                self.assertEqual([event["event"] for event in received], ["ended"])
                self.assertEqual(
                    received[0]["session_id"],
                    "11111111-1111-1111-1111-111111111111",
                )
            finally:
                monitor.close()

    def test_existing_today_log_backfills_usage_without_replaying_pet_events(self):
        with TemporaryDirectory() as directory:
            now = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
            day = Path(directory) / "2026" / "08" / "31"
            day.mkdir(parents=True)
            session_id = "11111111-1111-1111-1111-111111111111"
            rollout = day / f"rollout-2026-08-31T11-00-00-{session_id}.jsonl"
            records = [
                {
                    "timestamp": "2026-08-31T11:00:00Z",
                    "type": "session_meta",
                    "payload": {"id": session_id, "session_id": session_id},
                }
            ]
            for index, (total, last, used) in enumerate(
                ((100, 100, 42), (160, 60, 43), (160, 60, 43)), start=1
            ):
                records.append(
                    {
                        "timestamp": f"2026-08-31T11:0{index}:00Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "token_count",
                            "info": {
                                "total_token_usage": {"total_tokens": total},
                                "last_token_usage": {"total_tokens": last},
                            },
                            "rate_limits": {
                                "limit_id": "codex",
                                "primary": {
                                    "used_percent": used,
                                    "window_minutes": 10080,
                                    "resets_at": 1788998400,
                                },
                            },
                        },
                    }
                )
            rollout.write_text(
                "\n".join(json.dumps(record) for record in records) + "\n",
                encoding="utf-8",
            )
            monitor = CodexLogMonitor(directory, now=lambda: now)
            pet_events = []
            usage_batches = []
            monitor.payload_detected.connect(pet_events.append)
            monitor.usage_detected.connect(usage_batches.append)
            try:
                monitor.start()
                for _ in range(10):
                    monitor.poll_now()
                    if usage_batches:
                        break
                usage = [item for batch in usage_batches for item in batch]
                self.assertEqual(pet_events, [])
                self.assertEqual(
                    [item["delta_tokens"] for item in usage if item["kind"] == "token"],
                    [100, 60],
                )
                self.assertEqual(
                    len([item for item in usage if item["kind"] == "quota"]), 3
                )
                serialized = json.dumps(usage)
                self.assertNotIn(str(rollout), serialized)
                self.assertNotIn("prompt", serialized)
            finally:
                monitor.close()

    def test_new_rollout_is_read_from_its_first_complete_record(self):
        with TemporaryDirectory() as directory:
            now = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
            day = Path(directory) / "2026" / "08" / "31"
            monitor = CodexLogMonitor(directory, now=lambda: now)
            received = []
            monitor.payload_detected.connect(received.append)
            try:
                monitor.start()
                day.mkdir(parents=True)
                rollout = day / (
                    "rollout-2026-08-31T12-01-00-"
                    "22222222-2222-2222-2222-222222222222.jsonl"
                )
                rollout.write_text(
                    "\n".join(
                        json.dumps(record)
                        for record in (
                            {
                                "type": "event_msg",
                                "payload": {
                                    "type": "task_started",
                                    "turn_id": "turn-2",
                                    "message": "must not be emitted",
                                },
                            },
                            {
                                "type": "event_msg",
                                "payload": {
                                    "type": "item_completed",
                                    "turn_id": "turn-2",
                                },
                            },
                        )
                    )
                    + "\n",
                    encoding="utf-8",
                )
                for _ in range(20):
                    monitor.poll_now()
                    if received:
                        break
                self.assertEqual(len(received), 1)
                self.assertEqual(received[0]["event"], "prompt")
                self.assertNotIn("message", received[0])
            finally:
                monitor.close()

    def test_async_question_log_emits_wait_then_user_resolution(self):
        with TemporaryDirectory() as directory:
            now = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
            day = Path(directory) / "2026" / "08" / "31"
            monitor = CodexLogMonitor(directory, now=lambda: now)
            received = []
            monitor.payload_detected.connect(received.append)
            try:
                monitor.start()
                day.mkdir(parents=True)
                rollout = day / (
                    "rollout-2026-08-31T12-01-00-"
                    "55555555-5555-5555-5555-555555555555.jsonl"
                )
                records = (
                    {
                        "type": "event_msg",
                        "payload": {"type": "task_started", "turn_id": "turn-1"},
                    },
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "function_call",
                            "name": "request_user_input_async",
                            "call_id": "question",
                            "arguments": "private question",
                        },
                    },
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "function_call_output",
                            "call_id": "question",
                            "output": '{"accepted": true}',
                        },
                    },
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "function_call",
                            "name": "other",
                            "call_id": "other",
                        },
                    },
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "internal_chat_message_metadata_passthrough": {
                                "turn_id": "turn-1"
                            },
                            "content": [
                                {"type": "input_text", "text": "private answer"}
                            ],
                        },
                    },
                )
                rollout.write_text(
                    "\n".join(json.dumps(record) for record in records) + "\n",
                    encoding="utf-8",
                )
                for _ in range(20):
                    monitor.poll_now()
                    if len(received) >= 4:
                        break
                self.assertEqual(
                    [item["event"] for item in received],
                    ["prompt", "question_wait", "tool_start", "question_resolved"],
                )
                self.assertEqual(received[-1]["event_id"], "question")
                self.assertEqual(received[-1]["turn_id"], "turn-1")
                self.assertNotIn("private", str(received))
            finally:
                monitor.close()

    def test_timestamped_records_older_than_start_grace_are_suppressed(self):
        with TemporaryDirectory() as directory:
            now = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
            day = Path(directory) / "2026" / "08" / "31"
            monitor = CodexLogMonitor(directory, now=lambda: now)
            received = []
            monitor.payload_detected.connect(received.append)
            try:
                monitor.start()
                day.mkdir(parents=True)
                rollout = day / (
                    "rollout-2026-08-31T12-01-00-"
                    "33333333-3333-3333-3333-333333333333.jsonl"
                )
                rollout.write_text(
                    "\n".join(
                        json.dumps(record)
                        for record in (
                            {
                                "timestamp": "2026-08-31T11:59:54Z",
                                "type": "event_msg",
                                "payload": {
                                    "type": "task_started",
                                    "turn_id": "old-turn",
                                },
                            },
                            {
                                "timestamp": "2026-08-31T11:59:54Z",
                                "type": "event_msg",
                                "payload": {
                                    "type": "item_completed",
                                    "turn_id": "old-turn",
                                },
                            },
                        )
                    )
                    + "\n",
                    encoding="utf-8",
                )

                for _ in range(20):
                    monitor.poll_now()
                    if monitor.diagnostics()["replay_suppressed_count"]:
                        break

                self.assertEqual(received, [])
                self.assertEqual(monitor.diagnostics()["replay_suppressed_count"], 1)
            finally:
                monitor.close()

    def test_active_turn_heartbeat_is_throttled_to_ten_seconds(self):
        with TemporaryDirectory() as directory:
            clock = [datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)]
            day = Path(directory) / "2026" / "08" / "31"
            monitor = CodexLogMonitor(directory, now=lambda: clock[0])
            received = []
            monitor.payload_detected.connect(received.append)
            try:
                monitor.start()
                day.mkdir(parents=True)
                rollout = day / (
                    "rollout-2026-08-31T12-01-00-"
                    "44444444-4444-4444-4444-444444444444.jsonl"
                )
                rollout.write_text(
                    "\n".join(
                        json.dumps(record)
                        for record in (
                            {
                                "type": "event_msg",
                                "payload": {
                                    "type": "task_started",
                                    "turn_id": "turn-4",
                                },
                            },
                            {
                                "type": "event_msg",
                                "payload": {
                                    "type": "item_completed",
                                    "turn_id": "turn-4",
                                },
                            },
                        )
                    )
                    + "\n",
                    encoding="utf-8",
                )
                for _ in range(20):
                    monitor.poll_now()
                    if received:
                        break
                self.assertEqual([event["event"] for event in received], ["prompt"])

                clock[0] = clock[0].replace(second=9)
                with rollout.open("a", encoding="utf-8") as stream:
                    stream.write(
                        json.dumps(
                            {
                                "type": "event_msg",
                                "payload": {
                                    "type": "item_completed",
                                    "turn_id": "turn-4",
                                },
                            }
                        )
                        + "\n"
                    )
                for _ in range(20):
                    monitor.poll_now()
                    if monitor._positions.get(rollout) == rollout.stat().st_size:
                        break
                self.assertEqual([event["event"] for event in received], ["prompt"])

                clock[0] = clock[0].replace(second=10)
                with rollout.open("a", encoding="utf-8") as stream:
                    stream.write(
                        json.dumps(
                            {
                                "type": "event_msg",
                                "payload": {
                                    "type": "item_completed",
                                    "turn_id": "turn-4",
                                },
                            }
                        )
                        + "\n"
                    )
                for _ in range(20):
                    monitor.poll_now()
                    if len(received) == 2:
                        break
                self.assertEqual(
                    [event["event"] for event in received],
                    ["prompt", "heartbeat"],
                )
            finally:
                monitor.close()

    def test_hook_event_suppresses_matching_jsonl_fallback(self):
        server = CodexHookServer(f"watched-kettle-dedupe-{uuid4().hex}")
        received = []
        server.payload_received.connect(received.append)
        payload = {
            "source": "codex",
            "event": "prompt",
            "session_id": "one",
            "turn_id": "turn-1",
            "agent_scope": "main",
        }
        try:
            self.assertTrue(server._deliver_payload(payload, PIPE_TRANSPORT))
            self.assertFalse(server._deliver_payload(payload, JSONL_TRANSPORT))
            self.assertEqual(received, [payload])
            diagnostics = server.diagnostics()
            self.assertEqual(diagnostics["event_count"], 1)
            self.assertEqual(diagnostics["jsonl_event_count"], 0)
            self.assertEqual(diagnostics["received_jsonl_event_count"], 1)
            self.assertEqual(diagnostics["suppressed_duplicate_count"], 1)
        finally:
            server.close()

    def test_distinct_rapid_jsonl_tool_calls_are_not_collapsed(self):
        server = CodexHookServer(f"watched-kettle-distinct-{uuid4().hex}")
        received = []
        server.payload_received.connect(received.append)
        try:
            for call_id in ("call-1", "call-2"):
                self.assertTrue(
                    server._deliver_payload(
                        {
                            "source": "codex",
                            "event": "tool_start",
                            "session_id": "one",
                            "turn_id": "turn-1",
                            "event_id": call_id,
                        },
                        JSONL_TRANSPORT,
                    )
                )
            self.assertEqual(len(received), 2)
        finally:
            server.close()


if __name__ == "__main__":
    unittest.main()
