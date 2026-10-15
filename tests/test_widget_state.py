"""Which providers the usage widget shows and how each limit is described."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest

from watched_kettle.usage.claude_code_limits import LIMIT_ID, LIMIT_NAME
from watched_kettle.usage.models import (
    HourlyActivityBucket,
    RateLimitBucket,
    UsageAvailability,
    UsageSnapshot,
    UsageWindow,
)
from watched_kettle.usage.widget_state import (
    age_text,
    limit_level,
    reset_text,
    today_flow,
    widget_state,
)

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


def codex(five_hour=32, seven_day=10):
    return RateLimitBucket(
        "codex",
        primary=UsageWindow(100 - five_hour, five_hour, 300, NOW + timedelta(hours=2)),
        secondary=UsageWindow(
            100 - seven_day, seven_day, 10080, NOW + timedelta(days=2)
        ),
    )


def claude(five_hour=75, seven_day=60):
    return RateLimitBucket(
        LIMIT_ID,
        LIMIT_NAME,
        primary=UsageWindow(100 - five_hour, five_hour, 300, NOW + timedelta(hours=3)),
        secondary=UsageWindow(
            100 - seven_day, seven_day, 10080, NOW + timedelta(days=1)
        ),
    )


def snapshot(*buckets, state="available", account="account", updated=NOW):
    return UsageSnapshot(
        availability=UsageAvailability(state, ""),
        buckets=buckets,
        account_hash=account,
        last_updated_at=updated,
    )


class WidgetStateTests(unittest.TestCase):
    def test_both_providers_show_their_tighter_limit_first(self):
        result = widget_state(
            snapshot(codex(), claude()), claude_code_observed_at=NOW, now=NOW
        )
        codex_row, claude_row = result["providers"]
        self.assertEqual(
            (codex_row["main"]["label"], codex_row["main"]["remaining"]), ("7일", 10)
        )
        self.assertEqual(codex_row["other"]["label"], "5시간")
        self.assertEqual(codex_row["main"]["level"], "low")
        self.assertEqual(claude_row["name"], "Claude Code")
        self.assertEqual(claude_row["main"]["remaining"], 60)
        self.assertFalse(result["empty"])

    def test_emphasis_picks_the_chosen_window_when_it_exists(self):
        row = widget_state(snapshot(codex()), emphasis="five_hour", now=NOW)[
            "providers"
        ][0]
        self.assertEqual(
            (row["main"]["label"], row["other"]["label"]), ("5시간", "7일")
        )
        row = widget_state(snapshot(codex()), emphasis="unknown", now=NOW)["providers"][
            0
        ]
        self.assertEqual(row["main"]["label"], "7일")

    def test_unseen_or_disabled_providers_take_no_room(self):
        self.assertTrue(
            widget_state(snapshot(state="offline", account=""), now=NOW)["empty"]
        )
        self.assertTrue(
            widget_state(snapshot(codex(), state="disabled"), now=NOW)["providers"]
            == []
        )
        only_claude = widget_state(
            snapshot(claude(), state="offline", account=""), now=NOW
        )
        self.assertEqual([p["key"] for p in only_claude["providers"]], ["claude_code"])
        disabled_claude = widget_state(
            snapshot(codex(), claude()), claude_code_enabled=False, now=NOW
        )
        self.assertEqual([p["key"] for p in disabled_claude["providers"]], ["codex"])

    def test_states_without_limits_are_named(self):
        def state_of(**kwargs):
            return widget_state(snapshot(**kwargs), now=NOW)["providers"][0]["state"]

        self.assertEqual(state_of(state="checking"), "loading")
        self.assertEqual(state_of(state="offline"), "offline")
        self.assertEqual(state_of(state="signed_out"), "no_account")
        claude_row = widget_state(snapshot(codex()), claude_code_enabled=True, now=NOW)[
            "providers"
        ][1]
        self.assertEqual((claude_row["state"], claude_row["main"]), ("no_limits", None))

    def test_old_values_are_marked_stale(self):
        old = snapshot(codex(), updated=NOW - timedelta(minutes=18))
        row = widget_state(old, now=NOW)["providers"][0]
        self.assertEqual((row["state"], row["age"]), ("stale", "18분 전"))
        fresh = widget_state(replace(old, last_updated_at=NOW), now=NOW)
        self.assertEqual(fresh["providers"][0]["state"], "ok")

    def test_activity_counts_follow_their_provider(self):
        result = widget_state(
            snapshot(codex(), claude()),
            activity={"claude_code": {"running": 1, "attention": 2}},
            now=NOW,
        )
        counts = [(p["running"], p["attention"]) for p in result["providers"]]
        self.assertEqual(counts, [(0, 0), (1, 2)])

    def test_today_flow_marks_unobserved_hours_and_respects_the_range(self):
        hours = [None] * 24
        hours[9], hours[10], hours[11] = 0, 500, 1_000
        flow = today_flow(hours, (9, 12))
        self.assertEqual(flow["bars"], [0.0, 0.5, 1.0])
        self.assertEqual(flow["total"], "1.5K")
        self.assertEqual(today_flow(hours, (0, 3))["bars"], [-1, -1, -1])
        self.assertIsNone(today_flow([None] * 24))
        self.assertIsNone(today_flow(()))

    def test_today_flow_is_added_per_provider_only_when_requested(self):
        codex_hours = tuple(
            HourlyActivityBucket(NOW, 100 if hour == 9 else None, 1)
            for hour in range(24)
        )
        data = replace(snapshot(codex(), claude()), hourly_activity=codex_hours)
        claude_hours = tuple(300 if hour == 10 else 0 for hour in range(24))
        rows = widget_state(data, today=True, claude_code_hourly=claude_hours, now=NOW)[
            "providers"
        ]
        self.assertEqual(rows[0]["today"]["total"], "100")
        self.assertEqual(rows[1]["today"]["bars"][10], 1.0)
        self.assertNotIn("today", widget_state(data, now=NOW)["providers"][0])

    def test_text_helpers(self):
        self.assertEqual(
            [limit_level(v) for v in (None, 9, 10, 29, 30)],
            ["unknown", "critical", "low", "low", "ok"],
        )
        self.assertEqual(
            reset_text(NOW + timedelta(days=1, hours=2), NOW), "1일 2시간 뒤"
        )
        self.assertEqual(reset_text(NOW + timedelta(minutes=5), NOW), "5분 뒤")
        self.assertEqual(age_text(NOW - timedelta(hours=2), NOW), ("2시간 전", True))
        self.assertEqual(age_text(NOW, NOW), ("방금", False))


if __name__ == "__main__":
    unittest.main()
