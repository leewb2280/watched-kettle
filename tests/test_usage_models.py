import unittest
from datetime import date, datetime, timedelta, timezone

from watched_kettle.usage.models import (
    LocalTokenEvent,
    QuotaUsageSample,
    RateLimitBucket,
    ThreadUsageSnapshot,
    UsageActivitySample,
    aggregate_hourly_activity,
    aggregate_local_token_events,
    aggregate_quota_activity,
    merge_rate_limit_buckets,
    parse_account_usage,
    parse_rate_limit_buckets,
    resolve_usage_limit,
    unclassified_activity_tokens,
    subtract_thread_usage,
    usage_limit_options,
    usage_limit_groups,
    UsageWindow,
)


class UsageModelTests(unittest.TestCase):
    def test_provider_groups_keep_reserve_last_and_exclude_disabled_provider(self):
        options = usage_limit_options(
            (
                RateLimitBucket(
                    "base_model_inference", primary=UsageWindow(remaining_percent=76)
                ),
                RateLimitBucket(
                    "claude_code", primary=UsageWindow(remaining_percent=60)
                ),
                RateLimitBucket(
                    "codex",
                    primary=UsageWindow(remaining_percent=90),
                    secondary=UsageWindow(remaining_percent=70),
                ),
            )
        )
        groups = usage_limit_groups(
            options, codex_enabled=True, claude_code_enabled=True
        )
        self.assertEqual([group["key"] for group in groups], ["codex", "claude_code"])
        self.assertEqual([len(group["limits"]) for group in groups], [3, 1])
        self.assertEqual(
            [limit.limit_id for limit in groups[0]["limits"]],
            ["codex", "codex", "base_model_inference"],
        )
        # A tool whose usage is off takes no room at all.
        groups = usage_limit_groups(
            options, codex_enabled=False, claude_code_enabled=True
        )
        self.assertEqual([group["key"] for group in groups], ["claude_code"])
        groups = usage_limit_groups(
            options, codex_enabled=True, claude_code_enabled=False
        )
        self.assertEqual([group["key"] for group in groups], ["codex"])
        self.assertEqual(
            usage_limit_groups(options, codex_enabled=False, claude_code_enabled=False),
            (),
        )
        named_reserve = usage_limit_options(
            (
                RateLimitBucket(
                    "future",
                    limit_name="GPT reserve",
                    primary=UsageWindow(remaining_percent=50),
                ),
            )
        )
        groups = usage_limit_groups(
            named_reserve, codex_enabled=True, claude_code_enabled=True
        )
        self.assertEqual(groups[0]["key"], "codex")
        self.assertEqual(groups[0]["limits"][-1].limit_id, "future")

    def test_local_events_aggregate_exact_deltas_by_local_hour(self):
        tz = timezone(timedelta(hours=9))
        events = (
            LocalTokenEvent("a", "e1", "s", datetime(2026, 9, 4, 0, 1, tzinfo=tz), 40),
            LocalTokenEvent("a", "e2", "s", datetime(2026, 9, 4, 1, 1, tzinfo=tz), 60),
        )
        buckets = aggregate_local_token_events(
            events, local_day=date(2026, 9, 4), local_timezone=tz
        )
        self.assertEqual((buckets[0].tokens, buckets[1].tokens), (40, 60))

    def test_quota_activity_uses_high_water_not_oscillating_snapshots(self):
        tz = timezone.utc
        reset = datetime(2026, 9, 10, tzinfo=tz)
        samples = tuple(
            QuotaUsageSample(
                "a",
                f"e{index}",
                "codex",
                "primary",
                datetime(2026, 9, 4, 10, index, tzinfo=tz),
                value,
                10080,
                reset,
            )
            for index, value in enumerate((42, 43, 42, 43, 51))
        )
        buckets = aggregate_quota_activity(
            samples,
            "codex|primary",
            local_day=date(2026, 9, 4),
            local_timezone=tz,
        )
        self.assertEqual(buckets[10].percent_points, 9)
        self.assertEqual(buckets[10].observed_intervals, 4)

    def test_quota_reset_starts_a_new_baseline(self):
        tz = timezone.utc
        samples = (
            QuotaUsageSample(
                "a",
                "1",
                "x",
                "primary",
                datetime(2026, 9, 4, 9, tzinfo=tz),
                80,
                300,
                datetime(2026, 9, 4, 12, tzinfo=tz),
            ),
            QuotaUsageSample(
                "a",
                "2",
                "x",
                "primary",
                datetime(2026, 9, 4, 10, tzinfo=tz),
                5,
                300,
                datetime(2026, 9, 4, 17, tzinfo=tz),
            ),
            QuotaUsageSample(
                "a",
                "3",
                "x",
                "primary",
                datetime(2026, 9, 4, 11, tzinfo=tz),
                10,
                300,
                datetime(2026, 9, 4, 17, tzinfo=tz),
            ),
        )
        buckets = aggregate_quota_activity(
            samples,
            "x|primary",
            local_day=date(2026, 9, 4),
            local_timezone=tz,
        )
        self.assertEqual(buckets[11].percent_points, 5)

    def test_widget_limit_options_use_stable_keys_and_shortest_fallback(self):
        buckets = (
            RateLimitBucket(
                "codex",
                limit_name="Codex",
                primary=UsageWindow(window_duration_mins=300),
                secondary=UsageWindow(window_duration_mins=10080),
            ),
            RateLimitBucket(
                "other",
                primary=UsageWindow(window_duration_mins=None),
            ),
        )
        options = usage_limit_options(buckets)
        self.assertEqual(
            [option.key for option in options],
            ["codex|primary", "codex|secondary", "other|primary"],
        )
        self.assertEqual(options[0].label, "Codex · 5시간 한도")
        self.assertNotIn("구간", options[1].label)
        self.assertEqual(resolve_usage_limit(buckets).key, "codex|primary")
        self.assertEqual(
            resolve_usage_limit(buckets, "codex|secondary").key,
            "codex|secondary",
        )
        self.assertEqual(
            resolve_usage_limit(buckets, "missing|primary").key,
            "codex|primary",
        )

    def test_slot_names_only_separate_windows_of_the_same_length(self):
        same = RateLimitBucket(
            "codex",
            primary=UsageWindow(window_duration_mins=300),
            secondary=UsageWindow(window_duration_mins=300),
        )
        labels = [option.label for option in usage_limit_options((same,))]
        self.assertEqual(
            labels,
            ["Codex · 5시간 한도 · 기본 구간", "Codex · 5시간 한도 · 추가 구간"],
        )

    def test_hourly_activity_uses_only_continuous_same_day_samples(self):
        tz = timezone(timedelta(hours=9))
        samples = (
            UsageActivitySample("account", datetime(2026, 9, 4, 0, 0, tzinfo=tz), 100),
            UsageActivitySample("account", datetime(2026, 9, 4, 0, 10, tzinfo=tz), 160),
            UsageActivitySample("account", datetime(2026, 9, 4, 1, 0, tzinfo=tz), 260),
            UsageActivitySample("account", datetime(2026, 9, 4, 1, 10, tzinfo=tz), 200),
            UsageActivitySample("account", datetime(2026, 9, 4, 1, 20, tzinfo=tz), 250),
        )

        buckets = aggregate_hourly_activity(
            samples, local_day=date(2026, 9, 4), local_timezone=tz
        )

        self.assertEqual(len(buckets), 24)
        self.assertEqual(buckets[0].tokens, 60)
        self.assertEqual(buckets[1].tokens, 50)
        self.assertIsNone(buckets[2].tokens)

        self.assertEqual(
            unclassified_activity_tokens(
                samples, local_day=date(2026, 9, 4), local_timezone=tz
            ),
            100,
        )

    def test_hourly_activity_does_not_cross_local_midnight(self):
        tz = timezone(timedelta(hours=9))
        samples = (
            UsageActivitySample(
                "account", datetime(2026, 9, 3, 23, 55, tzinfo=tz), 100
            ),
            UsageActivitySample("account", datetime(2026, 9, 4, 0, 5, tzinfo=tz), 140),
            UsageActivitySample("account", datetime(2026, 9, 4, 0, 15, tzinfo=tz), 180),
        )

        buckets = aggregate_hourly_activity(
            samples, local_day=date(2026, 9, 4), local_timezone=tz
        )

        self.assertEqual(buckets[0].tokens, 40)
        self.assertEqual(buckets[0].observed_intervals, 1)

    def test_multiple_unknown_buckets_and_remaining_clamp_are_preserved(self):
        buckets = parse_rate_limit_buckets(
            {
                "rateLimitsByLimitId": {
                    "short": {
                        "limitId": "short",
                        "limitName": "5h",
                        "primary": {"usedPercent": 27, "windowDurationMins": 300},
                    },
                    "future": {
                        "primary": {"usedPercent": 125},
                        "individualLimit": {
                            "limit": "20",
                            "used": "5",
                            "remainingPercent": 75,
                            "resetsAt": 1800000000,
                        },
                        "newField": 42,
                    },
                }
            }
        )
        self.assertEqual([item.limit_id for item in buckets], ["short", "future"])
        self.assertEqual(buckets[0].primary.remaining_percent, 73)
        self.assertEqual(buckets[1].primary.remaining_percent, 0)
        self.assertEqual(buckets[1].individual_remaining_percent, 75)
        self.assertEqual(buckets[1].unknown["newField"], 42)

    def test_sparse_update_does_not_clear_secondary_window(self):
        original = parse_rate_limit_buckets(
            {
                "rateLimitsByLimitId": {
                    "x": {
                        "primary": {"usedPercent": 10},
                        "secondary": {"usedPercent": 20},
                        "planType": "plus",
                    }
                }
            }
        )
        update = parse_rate_limit_buckets(
            {"rateLimitsByLimitId": {"x": {"primary": {"usedPercent": 30}}}}
        )
        merged = merge_rate_limit_buckets(original, update)[0]
        self.assertEqual(merged.primary.used_percent, 30)
        self.assertEqual(merged.secondary.used_percent, 20)
        self.assertEqual(merged.plan_type, "plus")

    def test_null_daily_and_thread_usage_remain_unknown(self):
        summary, daily = parse_account_usage(
            {
                "summary": {"lifetimeTokens": None},
                "dailyUsageBuckets": None,
                "threadUsage": None,
            }
        )
        self.assertIsNone(summary.lifetime_tokens)
        self.assertEqual(daily, ())
        self.assertIsNone(ThreadUsageSnapshot.from_response({"threadUsage": None}))

    def test_thread_delta_never_uses_account_limit_change(self):
        before = ThreadUsageSnapshot.from_response(
            {
                "threadUsage": {
                    "threadId": "abc",
                    "estimatedUsageCreditsMicros": 10,
                    "groups": [
                        {
                            "totalTokens": 100,
                            "inputTokens": 70,
                            "outputTokens": 30,
                            "model": "gpt-x",
                        }
                    ],
                }
            }
        )
        after = ThreadUsageSnapshot.from_response(
            {
                "threadUsage": {
                    "threadId": "abc",
                    "estimatedUsageCreditsMicros": 25,
                    "groups": [
                        {
                            "totalTokens": 160,
                            "inputTokens": 110,
                            "outputTokens": 50,
                            "model": "gpt-x",
                        }
                    ],
                }
            }
        )
        record = subtract_thread_usage(
            before, after, "acct", "thread", "done", datetime.now(timezone.utc)
        )
        self.assertEqual(record.total_tokens, 60)
        self.assertEqual(record.estimated_credits_micros, 15)
        self.assertEqual(record.model, "gpt-x")
        self.assertIsNone(subtract_thread_usage(None, after, "acct", "thread", "done"))

    def test_thread_delta_aggregates_multiple_server_groups(self):
        before = ThreadUsageSnapshot.from_response(
            {
                "threadUsage": {
                    "threadId": "abc",
                    "estimatedUsageCreditsMicros": 0,
                    "groups": [{"totalTokens": 10}, {"totalTokens": 20}],
                }
            }
        )
        after = ThreadUsageSnapshot.from_response(
            {
                "threadUsage": {
                    "threadId": "abc",
                    "estimatedUsageCreditsMicros": 0,
                    "groups": [{"totalTokens": 15}, {"totalTokens": 35}],
                }
            }
        )
        record = subtract_thread_usage(before, after, "acct", "thread", "done")
        self.assertEqual(record.total_tokens, 20)
        self.assertEqual(record.data_quality, "partial")


if __name__ == "__main__":
    unittest.main()
