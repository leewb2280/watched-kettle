"""Immutable, forward-compatible models for Codex App Server usage data."""

from __future__ import annotations

from math import isfinite

from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from typing import Any, Mapping

from watched_kettle.usage.activity import (
    UsageActivitySample as UsageActivitySample,
    HourlyActivityBucket as HourlyActivityBucket,
    LocalTokenEvent as LocalTokenEvent,
    QuotaUsageSample as QuotaUsageSample,
    HourlyQuotaBucket as HourlyQuotaBucket,
    aggregate_local_token_events as aggregate_local_token_events,
    aggregate_quota_activity as aggregate_quota_activity,
    aggregate_hourly_activity as aggregate_hourly_activity,
    unclassified_activity_tokens as unclassified_activity_tokens,
)


def _number(value, cast=float):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = cast(value)
        return number if isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _text(value):
    return None if value is None else str(value)


def _utc_from_epoch(value):
    seconds = _number(value, int)
    if seconds is None:
        return None
    try:
        return datetime.fromtimestamp(seconds, timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None


@dataclass(frozen=True)
class UsageWindow:
    used_percent: float | None = None
    remaining_percent: float | None = None
    window_duration_mins: int | None = None
    resets_at: datetime | None = None
    # Computed, not observed: the window passed its reset with no new sample.
    estimated: bool = False

    @classmethod
    def from_json(cls, value):
        if not isinstance(value, Mapping):
            return None
        used = _number(value.get("usedPercent"))
        remaining = None if used is None else min(100.0, max(0.0, 100.0 - used))
        return cls(
            used_percent=used,
            remaining_percent=remaining,
            window_duration_mins=_number(value.get("windowDurationMins"), int),
            resets_at=_utc_from_epoch(value.get("resetsAt")),
        )


@dataclass(frozen=True)
class RateLimitBucket:
    limit_id: str
    limit_name: str | None = None
    plan_type: str | None = None
    primary: UsageWindow | None = None
    secondary: UsageWindow | None = None
    credit_balance: float | None = None
    has_credits: bool | None = None
    unlimited_credits: bool | None = None
    spend_control_reached: bool | None = None
    reached_type: str | None = None
    individual_limit: str | None = None
    individual_used: str | None = None
    individual_remaining_percent: float | None = None
    individual_resets_at: datetime | None = None
    unknown: Mapping[str, Any] = field(default_factory=dict, compare=False)

    @classmethod
    def from_json(cls, value, fallback_id="default"):
        if not isinstance(value, Mapping):
            return None
        credits_value = value.get("credits")
        credits = credits_value if isinstance(credits_value, Mapping) else {}
        individual_value = value.get("individualLimit")
        individual = individual_value if isinstance(individual_value, Mapping) else {}
        limit_id = str(value.get("limitId") or fallback_id)
        known = {
            "limitId",
            "limitName",
            "planType",
            "primary",
            "secondary",
            "credits",
            "individualLimit",
            "spendControlReached",
            "rateLimitReachedType",
        }
        return cls(
            limit_id=limit_id,
            limit_name=_text(value.get("limitName")),
            plan_type=_text(value.get("planType")),
            primary=UsageWindow.from_json(value.get("primary")),
            secondary=UsageWindow.from_json(value.get("secondary")),
            credit_balance=_number(credits.get("balance")),
            has_credits=(
                credits.get("hasCredits")
                if isinstance(credits.get("hasCredits"), bool)
                else None
            ),
            unlimited_credits=(
                credits.get("unlimited")
                if isinstance(credits.get("unlimited"), bool)
                else None
            ),
            spend_control_reached=(
                value.get("spendControlReached")
                if isinstance(value.get("spendControlReached"), bool)
                else None
            ),
            reached_type=_text(value.get("rateLimitReachedType")),
            individual_limit=_text(individual.get("limit")),
            individual_used=_text(individual.get("used")),
            individual_remaining_percent=_number(individual.get("remainingPercent")),
            individual_resets_at=_utc_from_epoch(individual.get("resetsAt")),
            unknown={key: item for key, item in value.items() if key not in known},
        )


@dataclass(frozen=True)
class UsageLimitOption:
    key: str
    label: str
    limit_id: str
    slot: str
    window: UsageWindow
    name: str = ""


def _usage_duration_label(minutes):
    if minutes is None:
        return ""
    if minutes % 1440 == 0:
        return f"{minutes // 1440}일 한도"
    if minutes % 60 == 0:
        return f"{minutes // 60}시간 한도"
    return f"{minutes}분 한도"


def usage_limit_options(buckets):
    options = []
    for bucket in buckets:
        name = bucket.limit_name or (
            "Codex" if bucket.limit_id == "codex" else bucket.limit_id
        )
        durations = [
            _usage_duration_label(window.window_duration_mins)
            for window in (bucket.primary, bucket.secondary)
            if window is not None
        ]
        # Window lengths name the two limits; fall back to the slot only
        # when they cannot tell them apart.
        ambiguous = len(durations) == 2 and (
            not all(durations) or durations[0] == durations[1]
        )
        for slot, window, slot_label in (
            ("primary", bucket.primary, "기본 구간"),
            ("secondary", bucket.secondary, "추가 구간"),
        ):
            if window is None:
                continue
            duration = _usage_duration_label(window.window_duration_mins)
            parts = [name]
            if duration:
                parts.append(duration)
            if ambiguous:
                parts.append(slot_label)
            options.append(
                UsageLimitOption(
                    f"{bucket.limit_id}|{slot}",
                    " · ".join(parts),
                    bucket.limit_id,
                    slot,
                    window,
                    name,
                )
            )
    return tuple(options)


def is_reserve_limit(limit_id, name=""):
    """A Codex reserve limit, shown last and left out of the trend chart."""
    return limit_id == "base_model_inference" or "reserve" in (name or "").casefold()


def main_codex_limit_id(buckets, default="codex"):
    """The Codex limit the overview trend follows: the first non-reserve one."""
    for bucket in buckets:
        if bucket.limit_id == "claude_code":
            continue
        if not is_reserve_limit(bucket.limit_id, bucket.limit_name):
            return bucket.limit_id
    return default


def usage_limit_groups(options, *, codex_enabled, claude_code_enabled):
    """Group provider cards, keeping reserve last within Codex.

    A tool whose usage switch is off has no group, so a tool the user did not
    pick in setup does not take room on the home and usage pages.
    """
    codex: list[UsageLimitOption] = []
    claude: list[UsageLimitOption] = []
    reserve: list[UsageLimitOption] = []
    for option in options:
        if option.limit_id == "claude_code":
            if claude_code_enabled:
                claude.append(option)
        elif codex_enabled:
            target = (
                reserve if is_reserve_limit(option.limit_id, option.name) else codex
            )
            target.append(option)
    groups = []
    if codex_enabled:
        groups.append(dict(key="codex", label="Codex", limits=tuple(codex + reserve)))
    if claude_code_enabled:
        groups.append(
            dict(key="claude_code", label="Claude Code", limits=tuple(claude))
        )
    return tuple(groups)


def resolve_usage_limit(buckets, selected_key=""):
    options = usage_limit_options(buckets)
    for option in options:
        if option.key == selected_key:
            return option
    if not options:
        return None
    return min(
        enumerate(options),
        key=lambda item: (
            item[1].window.window_duration_mins
            if item[1].window.window_duration_mins is not None
            else float("inf"),
            item[1].window.resets_at.timestamp()
            if item[1].window.resets_at is not None
            else float("inf"),
            item[0],
        ),
    )[1]


def parse_rate_limit_buckets(response):
    if not isinstance(response, Mapping):
        return ()
    mapped = response.get("rateLimitsByLimitId")
    buckets = []
    if isinstance(mapped, Mapping) and mapped:
        for key, value in mapped.items():
            bucket = RateLimitBucket.from_json(value, str(key))
            if bucket is not None:
                buckets.append(bucket)
    else:
        bucket = RateLimitBucket.from_json(response.get("rateLimits"), "default")
        if bucket is not None:
            buckets.append(bucket)
    return tuple(buckets)


def merge_rate_limit_buckets(current, update):
    """Merge a sparse notification without treating omitted values as clears."""
    by_id = {bucket.limit_id: bucket for bucket in current}
    for fresh in update:
        old = by_id.get(fresh.limit_id)
        if old is None:
            by_id[fresh.limit_id] = fresh
            continue
        by_id[fresh.limit_id] = replace(
            old,
            limit_name=fresh.limit_name or old.limit_name,
            plan_type=fresh.plan_type or old.plan_type,
            primary=fresh.primary or old.primary,
            secondary=fresh.secondary or old.secondary,
            credit_balance=(
                fresh.credit_balance
                if fresh.credit_balance is not None
                else old.credit_balance
            ),
            has_credits=(
                fresh.has_credits if fresh.has_credits is not None else old.has_credits
            ),
            unlimited_credits=(
                fresh.unlimited_credits
                if fresh.unlimited_credits is not None
                else old.unlimited_credits
            ),
            spend_control_reached=(
                fresh.spend_control_reached
                if fresh.spend_control_reached is not None
                else old.spend_control_reached
            ),
            reached_type=fresh.reached_type or old.reached_type,
            individual_limit=fresh.individual_limit or old.individual_limit,
            individual_used=fresh.individual_used or old.individual_used,
            individual_remaining_percent=(
                fresh.individual_remaining_percent
                if fresh.individual_remaining_percent is not None
                else old.individual_remaining_percent
            ),
            individual_resets_at=fresh.individual_resets_at or old.individual_resets_at,
            unknown={**old.unknown, **fresh.unknown},
        )
    return tuple(by_id.values())


@dataclass(frozen=True)
class AccountUsageSummary:
    lifetime_tokens: int | None = None
    peak_daily_tokens: int | None = None
    longest_running_turn_sec: int | None = None
    current_streak_days: int | None = None
    longest_streak_days: int | None = None

    @classmethod
    def from_json(cls, value):
        value = value if isinstance(value, Mapping) else {}
        return cls(
            lifetime_tokens=_number(value.get("lifetimeTokens"), int),
            peak_daily_tokens=_number(value.get("peakDailyTokens"), int),
            longest_running_turn_sec=_number(value.get("longestRunningTurnSec"), int),
            current_streak_days=_number(value.get("currentStreakDays"), int),
            longest_streak_days=_number(value.get("longestStreakDays"), int),
        )


@dataclass(frozen=True)
class DailyUsageBucket:
    start_date: date
    tokens: int | None = None

    @classmethod
    def from_json(cls, value):
        if not isinstance(value, Mapping):
            return None
        try:
            parsed_date = date.fromisoformat(str(value.get("startDate"))[:10])
        except (TypeError, ValueError):
            return None
        return cls(parsed_date, _number(value.get("tokens"), int))


@dataclass(frozen=True)
class ThreadUsageGroup:
    estimated_credits_micros: int | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    speed: str | None = None
    input_tokens: int | None = None
    net_new_input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None

    @classmethod
    def from_json(cls, value):
        if not isinstance(value, Mapping):
            return None
        return cls(
            estimated_credits_micros=_number(
                value.get("estimatedUsageCreditsMicros"), int
            ),
            model=_text(value.get("model")),
            reasoning_effort=_text(value.get("reasoningEffort")),
            speed=_text(value.get("speed")),
            input_tokens=_number(value.get("inputTokens"), int),
            net_new_input_tokens=_number(value.get("netNewInputTokens"), int),
            cached_input_tokens=_number(value.get("cachedInputTokens"), int),
            output_tokens=_number(value.get("outputTokens"), int),
            total_tokens=_number(value.get("totalTokens"), int),
        )


@dataclass(frozen=True)
class ThreadUsageSnapshot:
    thread_id: str
    estimated_credits_micros: int | None = None
    estimated_usd_micros: int | None = None
    groups: tuple[ThreadUsageGroup, ...] = ()

    @classmethod
    def from_response(cls, response):
        if not isinstance(response, Mapping) or not isinstance(
            response.get("threadUsage"), Mapping
        ):
            return None
        value = response["threadUsage"]
        thread_id = str(value.get("threadId") or "")
        if not thread_id:
            return None
        groups = (
            tuple(
                group
                for group in (
                    ThreadUsageGroup.from_json(item) for item in value.get("groups", ())
                )
                if group is not None
            )
            if isinstance(value.get("groups", ()), (list, tuple))
            else ()
        )
        return cls(
            thread_id=thread_id,
            estimated_credits_micros=_number(
                value.get("estimatedUsageCreditsMicros"), int
            ),
            estimated_usd_micros=_number(value.get("estimatedUsageUsdMicros"), int),
            groups=groups,
        )


def _delta(after, before):
    if after is None or before is None or after < before:
        return None
    return after - before


@dataclass(frozen=True)
class TaskUsageRecord:
    completed_at: datetime
    account_hash: str
    thread_hash: str
    outcome: str
    input_tokens: int | None = None
    net_new_input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    estimated_credits_micros: int | None = None
    estimated_usd_micros: int | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    speed: str | None = None
    data_quality: str = "estimated"
    turn_hash: str = ""
    source_version: int = 3
    quality_reason: str = ""


def subtract_thread_usage(
    before, after, account_hash, thread_hash, outcome, completed_at=None
):
    if before is None or after is None or before.thread_id != after.thread_id:
        return None
    before_group = before.groups[0] if len(before.groups) == 1 else None
    after_group = after.groups[0] if len(after.groups) == 1 else None
    fields: dict[str, Any] = {}
    for name in (
        "input_tokens",
        "net_new_input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "total_tokens",
    ):
        before_values = [
            getattr(group, name)
            for group in before.groups
            if getattr(group, name) is not None
        ]
        after_values = [
            getattr(group, name)
            for group in after.groups
            if getattr(group, name) is not None
        ]
        if before_values and after_values and sum(after_values) < sum(before_values):
            return None
        fields[name] = (
            _delta(sum(after_values), sum(before_values))
            if before_values and after_values
            else None
        )
    for counter_name in ("estimated_credits_micros", "estimated_usd_micros"):
        old, new = getattr(before, counter_name), getattr(after, counter_name)
        if old is not None and new is not None and new < old:
            return None
    credits = _delta(after.estimated_credits_micros, before.estimated_credits_micros)
    usd = _delta(after.estimated_usd_micros, before.estimated_usd_micros)
    if all(value is None for value in (*fields.values(), credits, usd)):
        return None
    return TaskUsageRecord(
        completed_at=completed_at or datetime.now(timezone.utc),
        account_hash=account_hash,
        thread_hash=thread_hash,
        outcome=outcome,
        estimated_credits_micros=credits,
        estimated_usd_micros=usd,
        model=after_group.model if after_group else None,
        reasoning_effort=after_group.reasoning_effort if after_group else None,
        speed=after_group.speed if after_group else None,
        data_quality="estimated" if before_group and after_group else "partial",
        **fields,
    )


@dataclass(frozen=True)
class UsageAvailability:
    state: str = "starting"
    message: str = "사용량 서비스를 시작하는 중입니다."


@dataclass(frozen=True)
class UsageRefreshState:
    request_id: int = 0
    state: str = "idle"
    phase: str = ""
    message: str = ""
    completed_at: datetime | None = None

    @property
    def busy(self):
        return self.state == "refreshing"


@dataclass(frozen=True)
class UsageSnapshot:
    project_mode: bool = False
    projects: tuple = ()
    project_search: str = ""
    project_order: str = "recent"
    project_custom_order: tuple[str, ...] = ()
    project_offset: int = 0
    projects_has_more: bool = False
    project_count: int = 0
    selected_project_key: str = ""
    conversation_mode: bool = False
    conversations: tuple = ()
    conversation_search: str = ""
    conversation_order: str = "recent"
    conversation_offset: int = 0
    conversations_has_more: bool = False
    selected_conversation: object = None
    selected_thread_hash: str = ""
    conversation_status: str = ""
    device_legacy_records: tuple = ()
    device_history_message: str = ""
    availability: UsageAvailability = field(default_factory=UsageAvailability)
    account_hash: str = ""
    buckets: tuple[RateLimitBucket, ...] = ()
    summary: AccountUsageSummary = field(default_factory=AccountUsageSummary)
    daily_buckets: tuple[DailyUsageBucket, ...] = ()
    recent_tasks: tuple[TaskUsageRecord, ...] = ()
    # Newest tasks regardless of the history tab's selection, search or page.
    latest_tasks: tuple[TaskUsageRecord, ...] = ()
    recovery_pending: frozenset[tuple[str, str]] = frozenset()
    legacy_tasks: tuple[TaskUsageRecord, ...] = ()
    task_history_managed: bool = False
    task_history_search: str = ""
    task_history_order: str = "recent"
    task_history_limit: int = 100
    task_history_has_more: bool = False
    hourly_activity: tuple[HourlyActivityBucket, ...] = ()
    observed_today_tokens: int | None = None
    unclassified_today_tokens: int | None = None
    last_sample_at: datetime | None = None
    quota_hourly_activity: tuple[HourlyQuotaBucket, ...] = ()
    # Overview trends (usage.trends): today's hours against recent days and
    # each Codex limit's remaining percent today. Charts only; the widget
    # keeps using quota_hourly_activity.
    trend_hours: dict | None = None
    trend_quota: dict | None = None
    observed_today_percent_points: float | None = None
    selected_quota_observation_count: int = 0
    quota_last_sample_at: datetime | None = None
    selected_quota_key: str = ""
    reset_credit_count: int | None = None
    last_updated_at: datetime | None = None
    storage_error: str = ""
    clearing_history: bool = False
    history_message: str = ""
    refresh: UsageRefreshState = field(default_factory=UsageRefreshState)
    account_checking: bool = False
    account_email: str = ""
    account_plan: str = ""

    def for_display(self):
        if not self.account_checking:
            return self
        return replace(
            self,
            account_hash="",
            projects=(),
            project_search="",
            project_custom_order=(),
            project_offset=0,
            projects_has_more=False,
            project_count=0,
            selected_project_key="",
            conversations=(),
            selected_conversation=None,
            selected_thread_hash="",
            conversation_search="",
            conversation_offset=0,
            conversations_has_more=False,
            conversation_status="",
            account_email="",
            account_plan="",
            buckets=(),
            summary=AccountUsageSummary(),
            daily_buckets=(),
            recent_tasks=(),
            latest_tasks=(),
            recovery_pending=frozenset(),
            legacy_tasks=(),
            task_history_has_more=False,
            task_history_search="",
            task_history_order="recent",
            task_history_limit=100,
            quota_hourly_activity=(),
            trend_quota=None,
            observed_today_percent_points=None,
            selected_quota_observation_count=0,
            quota_last_sample_at=None,
            reset_credit_count=None,
            last_updated_at=None,
            availability=self.availability
            if self.availability.state == "offline"
            else UsageAvailability("checking", "현재 계정 확인 중"),
        )


def parse_account_usage(response):
    response = response if isinstance(response, Mapping) else {}
    summary = AccountUsageSummary.from_json(response.get("summary"))
    raw = response.get("dailyUsageBuckets")
    daily = (
        tuple(
            bucket
            for bucket in (DailyUsageBucket.from_json(item) for item in raw)
            if bucket is not None
        )
        if isinstance(raw, (list, tuple))
        else ()
    )
    return summary, daily
