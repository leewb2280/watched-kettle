"""Example values for the settings preview before any limit was measured."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from watched_kettle.usage.activity import HourlyActivityBucket
from watched_kettle.usage.claude_code_limits import LIMIT_ID, LIMIT_NAME
from watched_kettle.usage.models import (
    RateLimitBucket,
    UsageAvailability,
    UsageSnapshot,
    UsageWindow,
)

SAMPLE_ACTIVITY = {"codex": {"running": 1}, "claude_code": {"attention": 1}}


def _hourly(peak):
    """A working day's rise and fall, zero outside 8 to 18 o'clock."""
    return tuple(
        max(0, peak - abs(hour - 13) * peak // 6) if 8 <= hour <= 18 else 0
        for hour in range(24)
    )


SAMPLE_CLAUDE_CODE_HOURLY = _hourly(12_000)


def sample_snapshot(now=None):
    """Both providers with one tight and one loose limit each."""
    now = now or datetime.now(timezone.utc)
    midnight = now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    return UsageSnapshot(
        availability=UsageAvailability("available", "예시 값"),
        account_hash="sample",
        buckets=(
            RateLimitBucket(
                "codex",
                primary=UsageWindow(58, 42, 300, now + timedelta(hours=2)),
                secondary=UsageWindow(81, 19, 10080, now + timedelta(days=3)),
            ),
            RateLimitBucket(
                LIMIT_ID,
                LIMIT_NAME,
                primary=UsageWindow(30, 70, 300, now + timedelta(hours=3)),
                secondary=UsageWindow(45, 55, 10080, now + timedelta(days=2)),
            ),
        ),
        hourly_activity=tuple(
            HourlyActivityBucket(midnight + timedelta(hours=hour), tokens, 1)
            for hour, tokens in enumerate(_hourly(20_000))
        ),
        last_sample_at=now,
        last_updated_at=now,
    )
