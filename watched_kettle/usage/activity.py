"""Pure device and account activity aggregation; callers select the source."""

from dataclasses import dataclass
from datetime import datetime, time, timezone
from math import isfinite
from watched_kettle.usage.device import DeviceTokenEvent, DeviceQuotaSample


@dataclass(frozen=True)
class UsageActivitySample:
    """One privacy-limited observation of the official cumulative token count."""

    account_hash: str
    sampled_at: datetime
    cumulative_tokens: int


@dataclass(frozen=True)
class HourlyActivityBucket:
    """Locally derived activity assigned to one hour of the current local day."""

    hour_start: datetime
    tokens: int | None = None
    observed_intervals: int = 0


@dataclass(frozen=True)
class LocalTokenEvent:
    """One deduplicated token delta extracted from a local rollout log."""

    account_hash: str
    event_hash: str
    session_hash: str
    occurred_at: datetime
    delta_tokens: int


@dataclass(frozen=True)
class QuotaUsageSample:
    """One privacy-limited observation of an account quota window."""

    account_hash: str
    event_hash: str
    limit_id: str
    window_slot: str
    observed_at: datetime
    used_percent: float
    window_duration_mins: int | None = None
    resets_at: datetime | None = None


@dataclass(frozen=True)
class HourlyQuotaBucket:
    """Positive quota movement assigned to one local hour."""

    hour_start: datetime
    percent_points: float | None = None
    observed_intervals: int = 0


def aggregate_local_token_events(
    events, *, local_day=None, local_timezone=None, now=None
):
    """Aggregate already-deduplicated local token deltas into 24 hours."""

    now = now or datetime.now().astimezone()
    local_timezone = local_timezone or now.tzinfo or timezone.utc
    local_day = local_day or now.astimezone(local_timezone).date()
    values: list[int | None] = [None] * 24
    counts = [0] * 24
    for event in sorted(
        (
            item
            for item in events
            if isinstance(item, (LocalTokenEvent, DeviceTokenEvent))
        ),
        key=lambda item: item.occurred_at,
    ):
        if event.occurred_at.tzinfo is None or event.delta_tokens <= 0:
            continue
        local = event.occurred_at.astimezone(local_timezone)
        if local.date() != local_day:
            continue
        values[local.hour] = (values[local.hour] or 0) + event.delta_tokens
        counts[local.hour] += 1
    return tuple(
        HourlyActivityBucket(
            datetime.combine(local_day, time(hour), tzinfo=local_timezone),
            values[hour],
            counts[hour],
        )
        for hour in range(24)
    )


def aggregate_quota_activity(
    samples,
    selected_key,
    *,
    local_day=None,
    local_timezone=None,
    now=None,
):
    """Aggregate monotonic high-water changes for one logical quota window."""

    now = now or datetime.now().astimezone()
    local_timezone = local_timezone or now.tzinfo or timezone.utc
    local_day = local_day or now.astimezone(local_timezone).date()
    limit_id, separator, slot = str(selected_key or "").partition("|")
    if not separator:
        limit_id = slot = ""
    ordered = sorted(
        (
            item
            for item in samples
            if isinstance(item, (QuotaUsageSample, DeviceQuotaSample))
            and item.limit_id == limit_id
            and item.window_slot == slot
            and item.observed_at.tzinfo is not None
            and item.resets_at is not None
        ),
        key=lambda item: item.observed_at,
    )
    values: list[float | None] = [None] * 24
    counts = [0] * 24
    # Keep accounts independent even if a caller supplies a mixed batch. The
    # cycle anchor stays fixed so successive small clock shifts cannot drift
    # indefinitely into another quota window.
    baselines: dict[tuple[type, str], tuple[datetime, float, int | None, datetime]] = {}
    for sample in ordered:
        if (
            sample.resets_at is None
            or sample.resets_at.tzinfo is None
            or not isfinite(sample.used_percent)
        ):
            continue
        used = max(0.0, float(sample.used_percent))
        identity = (type(sample), getattr(sample, "account_hash", ""))
        baseline = baselines.get(identity)
        current = (
            sample.resets_at,
            used,
            sample.window_duration_mins,
            sample.observed_at,
        )
        if baseline is None:
            baselines[identity] = current
            continue
        reset_at, high_water, duration, previous_at = baseline
        reset_shift = (sample.resets_at - reset_at).total_seconds()
        if sample.observed_at <= previous_at:
            continue
        if sample.window_duration_mins != duration or reset_shift > 60:
            baselines[identity] = current
            continue
        if reset_shift < -60:
            # Late observations from a retired cycle cannot replace its successor.
            continue
        delta = max(0.0, used - high_water)
        baselines[identity] = (
            reset_at,
            max(high_water, used),
            duration,
            sample.observed_at,
        )
        local = sample.observed_at.astimezone(local_timezone)
        if local.date() != local_day:
            continue
        values[local.hour] = (values[local.hour] or 0.0) + delta
        counts[local.hour] += 1
    return tuple(
        HourlyQuotaBucket(
            datetime.combine(local_day, time(hour), tzinfo=local_timezone),
            values[hour],
            counts[hour],
        )
        for hour in range(24)
    )


def aggregate_hourly_activity(
    samples,
    *,
    local_day=None,
    local_timezone=None,
    now=None,
    max_gap_minutes=25,
):
    """Return 24 local-hour buckets without inventing values across data gaps."""

    now = now or datetime.now().astimezone()
    local_timezone = local_timezone or now.tzinfo or timezone.utc
    local_day = local_day or now.astimezone(local_timezone).date()
    ordered = sorted(
        (
            sample
            for sample in samples
            if isinstance(sample, UsageActivitySample)
            and sample.sampled_at.tzinfo is not None
        ),
        key=lambda sample: sample.sampled_at,
    )
    values: list[int | None] = [None] * 24
    intervals = [0] * 24
    maximum_gap_seconds = max(1, int(max_gap_minutes)) * 60

    for previous, current in zip(ordered, ordered[1:]):
        elapsed = (current.sampled_at - previous.sampled_at).total_seconds()
        delta = current.cumulative_tokens - previous.cumulative_tokens
        previous_local = previous.sampled_at.astimezone(local_timezone)
        current_local = current.sampled_at.astimezone(local_timezone)
        if (
            elapsed <= 0
            or elapsed > maximum_gap_seconds
            or delta < 0
            or previous_local.date() != local_day
            or current_local.date() != local_day
        ):
            continue
        hour = current_local.hour
        values[hour] = (values[hour] or 0) + delta
        intervals[hour] += 1

    return tuple(
        HourlyActivityBucket(
            datetime.combine(local_day, time(hour), tzinfo=local_timezone),
            values[hour],
            intervals[hour],
        )
        for hour in range(24)
    )


def unclassified_activity_tokens(
    samples,
    *,
    local_day=None,
    local_timezone=None,
    now=None,
    max_gap_minutes=25,
):
    """Count known positive deltas that cannot be assigned across long gaps."""

    now = now or datetime.now().astimezone()
    local_timezone = local_timezone or now.tzinfo or timezone.utc
    local_day = local_day or now.astimezone(local_timezone).date()
    ordered = sorted(
        (
            sample
            for sample in samples
            if isinstance(sample, UsageActivitySample)
            and sample.sampled_at.tzinfo is not None
        ),
        key=lambda sample: sample.sampled_at,
    )
    maximum_gap_seconds = max(1, int(max_gap_minutes)) * 60
    total = 0
    found = False
    for previous, current in zip(ordered, ordered[1:]):
        elapsed = (current.sampled_at - previous.sampled_at).total_seconds()
        delta = current.cumulative_tokens - previous.cumulative_tokens
        previous_local = previous.sampled_at.astimezone(local_timezone)
        current_local = current.sampled_at.astimezone(local_timezone)
        if (
            elapsed > maximum_gap_seconds
            and delta >= 0
            and previous_local.date() == local_day
            and current_local.date() == local_day
        ):
            total += delta
            found = True
    return total if found else None
