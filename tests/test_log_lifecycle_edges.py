"""Malformed and boundary rollout records stay bounded and content-free."""

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from watched_kettle.integrations import log_lifecycle
from watched_kettle.integrations.log_lifecycle import normalize_codex_log_record


def record(kind, payload, stamp="2026-10-01T05:00:00Z"):
    return {"timestamp": stamp, "type": kind, "payload": payload}


def async_question(call_id):
    return record(
        "response_item",
        {
            "type": "function_call",
            "name": "request_user_input_async",
            "call_id": call_id,
        },
    )


class LogLifecycleEdgeTests(unittest.TestCase):
    def test_malformed_and_unrelated_records_are_ignored(self):
        user_message = record("response_item", {"type": "message", "role": "user"})
        for value, options in (
            (["not", "a", "record"], {}),
            ({"type": "event_msg", "payload": "text"}, {}),
            (record("response_item", {"type": "reasoning"}), {}),
            (user_message, {}),
            (
                user_message,
                {
                    "pending_async_questions": {"call-1": ("other-turn", True)},
                    "active_turn_id": "turn-1",
                },
            ),
        ):
            with self.subTest(value=value, options=options):
                self.assertIsNone(normalize_codex_log_record(value, "s", **options))

    def test_timestamp_without_zone_is_read_as_utc(self):
        event = normalize_codex_log_record(
            record("response_item", {"type": "compaction"}, "2026-10-01T05:00:00"),
            "s",
        )
        expected = datetime(2026, 10, 1, 5, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(event["collected_at"], expected.timestamp())

    def test_blocking_question_waits_without_a_tracking_set(self):
        event = normalize_codex_log_record(
            record(
                "response_item",
                {
                    "type": "function_call",
                    "name": "request_user_input",
                    "call_id": "call-1",
                },
            ),
            "s",
        )
        self.assertEqual((event["event"], event["tool_status"]), ("waiting", "waiting"))

    def test_unreadable_async_output_resolves_the_question(self):
        pending = {"call-1": ("turn-1", True)}
        event = normalize_codex_log_record(
            record(
                "response_item",
                {
                    "type": "function_call_output",
                    "call_id": "call-1",
                    "output": "not json",
                },
            ),
            "s",
            pending_async_questions=pending,
        )
        self.assertEqual(event["event"], "question_resolved")
        self.assertEqual(pending["call-1"], ("turn-1", False))

    def test_full_question_table_evicts_resolved_entries_before_overflowing(self):
        with patch.object(log_lifecycle, "MAX_TRACKED_ASYNC_QUESTIONS", 2):
            pending = {"resolved": ("turn-1", False), "open": ("turn-1", True)}
            event = normalize_codex_log_record(
                async_question("new"),
                "s",
                pending_async_questions=pending,
                active_turn_id="turn-1",
            )
            self.assertEqual(event["event"], "question_wait")
            self.assertEqual(set(pending), {"open", "new"})

            event = normalize_codex_log_record(
                async_question("overflow"),
                "s",
                pending_async_questions=pending,
                active_turn_id="turn-1",
            )
            self.assertEqual(event["event"], "tool_start")
            self.assertEqual(set(pending), {"open", "new"})


if __name__ == "__main__":
    unittest.main()
