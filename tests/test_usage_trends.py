"""Usage overview trends: averages, remaining percent and moving averages."""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
import unittest

from watched_kettle.usage.claude_code_service import DAILY_DAYS, trend_values
from watched_kettle.usage.models import RateLimitBucket, main_codex_limit_id
from watched_kettle.usage.trends import (
    current_hours,
    daily_series,
    hourly_profile,
    hours_by_day,
    remaining_series,
)

LOCAL = timezone(timedelta(hours=9))
DAY = date(2026, 10, 4)


def at(hour, minute=0, day=DAY):
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=LOCAL)


def flat(value, hours=range(24)):
    day = [0] * 24
    for hour in hours:
        day[hour] = value
    return day


class HourlyProfileTests(unittest.TestCase):
    def test_average_uses_recorded_days_and_skips_unobserved_hours(self):
        unobserved = flat(100)
        unobserved[10] = None
        previous = [flat(100), flat(300), unobserved, flat(0), None]
        profile = hourly_profile(flat(200, hours=[9, 10]), previous, now_hour=10)

        self.assertEqual(profile["average_days"], 3)
        # Hour 10 averages the two days that observed it.
        self.assertEqual(profile["average"][9], (100 + 300 + 100) / 3)
        self.assertEqual(profile["average"][10], (100 + 300) / 2)
        self.assertEqual(profile["total"], 400)
        self.assertEqual(profile["peak_hour"], 9)

    def test_versus_average_compares_only_the_hours_so_far(self):
        previous = [flat(100)] * 3
        profile = hourly_profile(flat(150, hours=range(0, 12)), previous, now_hour=11)
        self.assertEqual(profile["versus_average"], 50)

    def test_too_few_days_give_no_average(self):
        profile = hourly_profile(flat(10), [flat(5), flat(5)], now_hour=3)
        self.assertIsNone(profile["average"])
        self.assertIsNone(profile["versus_average"])
        self.assertEqual(profile["average_days"], 2)

    def test_nothing_observed_today(self):
        profile = hourly_profile([None] * 24, [], now_hour=5)
        self.assertIsNone(profile["total"])
        self.assertIsNone(profile["peak_hour"])

    def test_a_profile_from_yesterday_keeps_only_its_average(self):
        yesterday = DAY - timedelta(days=1)
        profile = hourly_profile(flat(50), [flat(10)] * 3, now_hour=23, day=yesterday)
        self.assertIs(current_hours(profile, yesterday), profile)
        today = current_hours(profile, DAY)
        # Shown at 0 o'clock today, yesterday's hours must not fill the bars.
        self.assertEqual(today["hours"], [None] * 24)
        self.assertIsNone(today["total"])
        self.assertEqual(today["average"], profile["average"])
        self.assertIsNone(current_hours(None, DAY))

    def test_hours_by_day_marks_days_without_turns_as_no_record(self):
        yesterday = DAY - timedelta(days=1)
        days = hours_by_day(
            [(at(9, 30), 10), (at(9, 50), 5), (at(23, 59, yesterday), 7)],
            [DAY, yesterday, DAY - timedelta(days=2)],
            LOCAL,
        )
        self.assertEqual(days[DAY][9], 15)
        self.assertEqual(days[yesterday][23], 7)
        self.assertIsNone(days[DAY - timedelta(days=2)])


class RemainingSeriesTests(unittest.TestCase):
    def test_day_starts_from_the_last_sample_before_midnight(self):
        reset = at(15)
        series = remaining_series(
            [
                (at(22, day=DAY - timedelta(days=1)), 20.0, reset),
                (at(9), 30.0, reset),
                (at(10), 45.0, reset),
            ],
            DAY,
            LOCAL,
            now=at(11),
        )
        self.assertEqual(series["points"][0], (at(0), 80.0))
        self.assertEqual(series["points"][-1], (at(10), 55.0))
        self.assertEqual(series["spent"], 25.0)
        self.assertEqual(series["now_remaining"], 55.0)
        self.assertEqual(series["resets"], [])

    def test_a_new_cycle_steps_back_to_full(self):
        first, second = at(12), at(17)
        series = remaining_series(
            [
                (at(9), 40.0, first),
                (at(11), 70.0, first),
                (at(13), 10.0, second),
            ],
            DAY,
            LOCAL,
            now=at(14),
        )
        self.assertEqual(series["resets"], [first])
        self.assertIn((first, 30.0), series["points"])
        self.assertIn((first, 100.0), series["points"])
        # 30 %p before the reset and none after it (first sample of a cycle).
        self.assertEqual(series["spent"], 30.0)
        self.assertEqual(series["now_remaining"], 90.0)

    def test_a_reset_after_the_last_sample_still_shows(self):
        reset = at(10)
        series = remaining_series([(at(9), 60.0, reset)], DAY, LOCAL, now=at(12))
        self.assertEqual(series["resets"], [reset])
        self.assertEqual(series["now_remaining"], 100.0)

    def test_no_samples(self):
        series = remaining_series([], DAY, LOCAL, now=at(12))
        self.assertEqual(series["points"], [])
        self.assertIsNone(series["now_remaining"])
        self.assertIsNone(series["spent"])


class DailySeriesTests(unittest.TestCase):
    def test_moving_average_uses_days_before_the_range(self):
        days = [(DAY - timedelta(days=offset), 100) for offset in range(13)]
        series = daily_series(days, count=7)
        self.assertEqual(len(series["days"]), 7)
        self.assertEqual(series["days"][0]["average"], 100)
        self.assertEqual(series["total"], 700)
        self.assertEqual(series["average"], 100)

    def test_short_history_has_no_average_for_the_first_days(self):
        days = [
            (DAY - timedelta(days=offset), (offset + 1) * 10) for offset in range(5)
        ]
        series = daily_series(days, count=7)
        self.assertEqual([row["tokens"] for row in series["days"][:2]], [None, None])
        self.assertIsNone(series["days"][2]["average"])
        self.assertIsNotNone(series["days"][-1]["average"])
        self.assertEqual(series["peak_date"], DAY - timedelta(days=4))

    def test_empty(self):
        self.assertEqual(daily_series([], 7)["days"], [])


class MainLimitTests(unittest.TestCase):
    def test_reserve_is_skipped_and_an_unnamed_limit_is_kept(self):
        buckets = (
            RateLimitBucket("base_model_inference", limit_name="gpt-reserve"),
            RateLimitBucket("default"),
        )
        self.assertEqual(main_codex_limit_id(buckets), "default")
        self.assertEqual(main_codex_limit_id(()), "codex")


class ClaudeCodeTrendTests(unittest.TestCase):
    def test_turns_give_hours_and_daily_sums_from_the_first_turn(self):
        # trend_values reads days in the system zone, like the app.
        local = datetime.now().astimezone().tzinfo

        def moment(hour, minute=0, days_ago=0):
            day = DAY - timedelta(days=days_ago)
            return datetime(day.year, day.month, day.day, hour, minute, tzinfo=local)

        turns = [
            SimpleNamespace(completed_at=moment(9), total_tokens=100),
            SimpleNamespace(completed_at=moment(9, 40), total_tokens=20),
            SimpleNamespace(completed_at=moment(10, days_ago=2), total_tokens=50),
        ]
        profile, daily = trend_values(turns, now=moment(15))
        self.assertEqual(profile["hours"][9], 120)
        self.assertEqual(profile["total"], 120)
        # One earlier day is too few for an average.
        self.assertIsNone(profile["average"])
        self.assertEqual(len(daily), DAILY_DAYS)
        self.assertEqual(daily[0], (DAY, 120))
        self.assertEqual(daily[1], (DAY - timedelta(days=1), 0))
        self.assertEqual(daily[2], (DAY - timedelta(days=2), 50))
        # Before the first turn there is no record, not zero.
        self.assertIsNone(daily[3][1])


if __name__ == "__main__":
    unittest.main()
