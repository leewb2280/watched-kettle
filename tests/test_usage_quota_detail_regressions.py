"""Quota cycle transitions and explicit task-detail interaction regressions."""

import os
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


from watched_kettle.usage.activity import QuotaUsageSample, aggregate_quota_activity
from watched_kettle.usage.models import UsageSnapshot
from watched_kettle.usage.widget_presentation import _quota_change_text


class QuotaCycleTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 8, 10, tzinfo=timezone.utc)
        self.reset = self.now + timedelta(days=7)

    def sample(self, minute, used, shift=0, **changes):
        return replace(
            QuotaUsageSample(
                "a",
                str(minute),
                "codex",
                "primary",
                self.now + timedelta(minutes=minute),
                used,
                10080,
                self.reset + timedelta(seconds=shift),
            ),
            **changes,
        )

    def aggregate(self, *samples):
        return aggregate_quota_activity(
            samples,
            "codex|primary",
            local_day=self.now.date(),
            local_timezone=timezone.utc,
        )

    def test_zero_baseline_moves_to_new_cycle_before_usage_increases(self):
        buckets = self.aggregate(
            self.sample(0, 0),
            self.sample(5, 0, 300),
            self.sample(10, 1, 300),
            self.sample(15, 2, 300),
        )
        self.assertEqual(buckets[10].percent_points, 2)
        self.assertEqual(buckets[10].observed_intervals, 2)

    def test_clock_corrections_up_to_sixty_seconds_preserve_consumption(self):
        for shift in (-60, -3, 3, 60):
            with self.subTest(shift=shift):
                buckets = self.aggregate(
                    self.sample(0, 24),
                    self.sample(5, 25, shift),
                    self.sample(10, 26),
                )
                self.assertEqual(buckets[10].percent_points, 2)

    def test_new_cycle_at_higher_usage_and_late_old_cycle(self):
        buckets = self.aggregate(
            self.sample(0, 10),
            self.sample(5, 20, 300),
            self.sample(10, 90),
            self.sample(15, 22, 300),
        )
        self.assertEqual(buckets[10].percent_points, 2)

    def test_reset_recovery_and_oscillation_are_not_added(self):
        buckets = self.aggregate(
            self.sample(0, 80),
            self.sample(5, 0, 300),
            self.sample(10, 2, 300),
            self.sample(15, 1, 300),
            self.sample(20, 2, 300),
            self.sample(25, 3, 300),
        )
        self.assertEqual(buckets[10].percent_points, 3)

    def test_duration_change_starts_baseline(self):
        buckets = self.aggregate(
            self.sample(0, 5),
            self.sample(5, 30, window_duration_mins=300),
            self.sample(10, 32, window_duration_mins=300),
        )
        self.assertEqual(buckets[10].percent_points, 2)

    def test_shorter_duration_can_move_reset_earlier(self):
        buckets = self.aggregate(
            self.sample(0, 5),
            self.sample(5, 30, -3600, window_duration_mins=300),
            self.sample(10, 32, -3600, window_duration_mins=300),
        )
        self.assertEqual(buckets[10].percent_points, 2)

    def test_zero_missing_and_uncomparable_observations_are_distinct(self):
        self.assertEqual(
            self.aggregate(self.sample(0, 5), self.sample(5, 5))[10].percent_points, 0
        )
        self.assertIsNone(self.aggregate(self.sample(0, 5))[10].percent_points)
        self.assertIsNone(
            self.aggregate(self.sample(0, 5), self.sample(5, 5, 300))[10].percent_points
        )
        for count, value, text in (
            (0, None, "오늘 관찰 대기"),
            (1, None, "기준 수집 중"),
            (2, None, "기준 수집 중"),
            (2, 0, "오늘 0%p"),
            (1, 2, "오늘 −2%p"),
        ):
            with self.subTest(count=count, value=value):
                snapshot = UsageSnapshot(
                    selected_quota_observation_count=count,
                    observed_today_percent_points=value,
                )
                self.assertEqual(_quota_change_text(snapshot), text)

    def test_previous_day_baseline_and_account_isolation(self):
        self.now = self.now.replace(hour=0)
        buckets = self.aggregate(
            self.sample(-1, 10),
            self.sample(0, 80, account_hash="b"),
            self.sample(1, 12),
        )
        self.assertEqual(buckets[0].percent_points, 2)
        self.assertTrue(all(b.percent_points is None for b in buckets[1:]))

    def test_invalid_and_duplicate_observations_do_not_create_zero(self):
        first = self.sample(0, 5)
        for second in (
            first,
            self.sample(5, float("nan")),
            self.sample(5, 6, resets_at=None),
        ):
            with self.subTest(second=second):
                self.assertIsNone(self.aggregate(first, second)[10].percent_points)


if __name__ == "__main__":
    unittest.main()
