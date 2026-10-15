"""Turn measurements keep counter deltas only for turns that ended cleanly."""

import unittest
from datetime import datetime, timedelta, timezone

from watched_kettle.usage.identifiers import hash_identifier
from watched_kettle.usage.models import ThreadUsageGroup, ThreadUsageSnapshot
from watched_kettle.usage.turn_measurement import TaskObservation, complete_measurement


STARTED = datetime(2026, 9, 23, 6, 0, tzinfo=timezone.utc)
NOW = STARTED + timedelta(minutes=5)


def snapshot(total, credits):
    group = ThreadUsageGroup(
        model="model-a", total_tokens=total, output_tokens=total // 2
    )
    return ThreadUsageSnapshot(
        "thread-1", estimated_credits_micros=credits, groups=(group,)
    )


def observation(**changes):
    values = {
        "account_hash": "account-hash",
        "thread_id": "thread-1",
        "turn_id": "turn-1",
        "started_at": STARTED,
        "before": snapshot(100, 1000),
    }
    values.update(changes)
    return TaskObservation(**values)


class TurnMeasurementTests(unittest.TestCase):
    def test_clean_turn_records_counter_delta_with_hashed_identifiers(self):
        record = complete_measurement(observation(), snapshot(160, 1500), NOW)

        self.assertEqual(record.total_tokens, 60)
        self.assertEqual(record.output_tokens, 30)
        self.assertEqual(record.estimated_credits_micros, 500)
        self.assertEqual(record.data_quality, "estimated")
        self.assertEqual(record.model, "model-a")
        self.assertEqual(record.completed_at, NOW)
        self.assertEqual(record.thread_hash, hash_identifier("thread-1"))
        self.assertEqual(record.turn_hash, hash_identifier("turn-1"))

    def test_recorded_completion_time_is_kept(self):
        completed = STARTED + timedelta(minutes=2)
        record = complete_measurement(
            observation(completed_at=completed), snapshot(160, 1500), NOW
        )
        self.assertEqual(record.completed_at, completed)

    def test_missing_or_decreasing_counters_are_unavailable(self):
        for after in (None, snapshot(50, 500)):
            with self.subTest(after=after):
                record = complete_measurement(observation(), after, NOW)
                self.assertEqual(record.data_quality, "unavailable")
                self.assertEqual(record.quality_reason, "invalid_counter")
                self.assertIsNone(record.total_tokens)
                self.assertEqual(record.turn_hash, hash_identifier("turn-1"))

    def test_turn_with_reason_skips_subtraction(self):
        record = complete_measurement(
            observation(reason="interrupted", outcome="cancelled"),
            snapshot(160, 1500),
            NOW,
        )
        self.assertEqual(record.data_quality, "unavailable")
        self.assertEqual(record.quality_reason, "interrupted")
        self.assertEqual(record.outcome, "cancelled")
        self.assertIsNone(record.total_tokens)


if __name__ == "__main__":
    unittest.main()
