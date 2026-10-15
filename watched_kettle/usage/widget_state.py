"""Plain widget state for the Qt Quick usage widget; no Qt types.

The widget shows Codex and Claude Code side by side. Each provider row names
its tighter (or chosen) limit, the other limit, and how fresh the values are.
"""

from __future__ import annotations

from datetime import datetime, timezone

from watched_kettle.usage.claude_code_limits import LIMIT_ID as CLAUDE_CODE_LIMIT_ID
from watched_kettle.usage.widget_presentation import compact_token_text

CODEX_LIMIT_ID = "codex"
EMPHASIS_CHOICES = ("auto", "five_hour", "seven_day")
STALE_MINUTES = 15
LOW_PERCENT = 30
CRITICAL_PERCENT = 10
_EMPHASIS_MINUTES = {"five_hour": 300, "seven_day": 10080}
_LOADING = {"starting", "checking"}
_OFFLINE = {"offline", "error"}
_NO_ACCOUNT = {"signed_out", "unsupported_auth"}


def limit_level(remaining):
    if remaining is None:
        return "unknown"
    if remaining < CRITICAL_PERCENT:
        return "critical"
    if remaining < LOW_PERCENT:
        return "low"
    return "ok"


def duration_label(minutes):
    if minutes is None:
        return "한도"
    if minutes % 1440 == 0:
        return f"{minutes // 1440}일"
    if minutes % 60 == 0:
        return f"{minutes // 60}시간"
    return f"{minutes}분"


def reset_text(resets_at, now):
    if resets_at is None:
        return ""
    seconds = max(0, int((resets_at - now).total_seconds()))
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    if days:
        return f"{days}일 {hours}시간 뒤"
    if hours:
        return f"{hours}시간 {minutes}분 뒤"
    return f"{minutes}분 뒤"


def age_text(observed_at, now):
    """Return (text, stale) for when a provider's limits were last seen."""
    if observed_at is None:
        return "", False
    minutes = max(0, int((now - observed_at).total_seconds() // 60))
    if minutes < 2:
        return "방금", False
    if minutes < 60:
        return f"{minutes}분 전", minutes >= STALE_MINUTES
    return f"{minutes // 60}시간 전", True


def _limit(window, now):
    if window is None or window.remaining_percent is None:
        return None
    remaining = max(0, min(100, round(window.remaining_percent)))
    return {
        "label": duration_label(window.window_duration_mins),
        "remaining": remaining,
        "level": limit_level(remaining),
        "reset": reset_text(window.resets_at, now),
        "estimated": window.estimated,
    }


def _ordered_limits(bucket, emphasis, now):
    windows = [w for w in (bucket.primary, bucket.secondary) if w is not None]
    limits = [(w, _limit(w, now)) for w in windows]
    limits = [(w, item) for w, item in limits if item is not None]
    if not limits:
        return None, None
    wanted = _EMPHASIS_MINUTES.get(emphasis)
    chosen = next(
        (pair for pair in limits if pair[0].window_duration_mins == wanted), None
    )
    if chosen is None:
        chosen = min(limits, key=lambda pair: pair[1]["remaining"])
    other = next((item for w, item in limits if w is not chosen[0]), None)
    return chosen[1], other


def today_flow(hours, hour_range=(0, 24)):
    """Bars for one provider's tokens today; None marks an unobserved hour."""
    hours = list(hours or ())
    if len(hours) != 24 or all(value is None for value in hours):
        return None
    start, end = hour_range
    shown = hours[start:end]
    peak = max((value or 0) for value in shown) or 1
    total = sum(value or 0 for value in hours)
    return {
        "total": compact_token_text(total),
        "bars": [-1 if value is None else round(value / peak, 3) for value in shown],
    }


def _provider(key, name, bucket, emphasis, now, observed_at, state, activity):
    main, other = (None, None)
    if bucket is not None:
        main, other = _ordered_limits(bucket, emphasis, now)
    age, stale = age_text(observed_at, now) if main else ("", False)
    if main is None and state == "ok":
        state = "no_limits"
    return {
        "key": key,
        "name": name,
        "state": "stale" if state == "ok" and stale else state,
        "main": main,
        "other": other,
        "age": age,
        "running": int(activity.get("running", 0)),
        "attention": int(activity.get("attention", 0)),
    }


def codex_seen(snapshot):
    """Whether Codex limits or a Codex account were ever seen on this PC."""
    return any(
        bucket.limit_id == CODEX_LIMIT_ID for bucket in snapshot.buckets
    ) or bool(snapshot.account_hash)


def widget_state(
    snapshot,
    *,
    emphasis="auto",
    claude_code_enabled=None,
    claude_code_observed_at=None,
    activity=None,
    today=False,
    hour_range=(0, 24),
    claude_code_hourly=(),
    now=None,
):
    """Describe each provider the widget should show, in display order.

    ``snapshot`` is the usage view model snapshot whose buckets already include
    the Claude Code limits. ``activity`` maps provider keys to running and
    attention counts. A provider that is off and has nothing to show takes no
    room.
    """
    now = now or datetime.now(timezone.utc)
    emphasis = emphasis if emphasis in EMPHASIS_CHOICES else "auto"
    activity = activity or {}
    buckets = {bucket.limit_id: bucket for bucket in snapshot.buckets}
    providers = []

    availability = getattr(snapshot.availability, "state", "")
    codex_bucket = buckets.get(CODEX_LIMIT_ID)
    if availability != "disabled" and codex_seen(snapshot):
        if codex_bucket is not None:
            state = "ok"
        elif availability in _LOADING:
            state = "loading"
        elif availability in _OFFLINE:
            state = "offline"
        elif availability in _NO_ACCOUNT:
            state = "no_account"
        else:
            state = "ok"
        observed = snapshot.last_updated_at or snapshot.last_sample_at
        row = _provider(
            "codex",
            "Codex",
            codex_bucket,
            emphasis,
            now,
            observed,
            state,
            activity.get("codex", {}),
        )
        if today:
            row["today"] = today_flow(
                [bucket.tokens for bucket in snapshot.hourly_activity], hour_range
            )
        providers.append(row)

    claude_bucket = buckets.get(CLAUDE_CODE_LIMIT_ID)
    claude_activity = activity.get("claude_code", {})
    if claude_code_enabled is not False and (
        claude_bucket is not None or claude_code_enabled
    ):
        row = _provider(
            "claude_code",
            "Claude Code",
            claude_bucket,
            emphasis,
            now,
            claude_code_observed_at,
            "ok",
            claude_activity,
        )
        if today:
            # Hours with no finished turn are zero, not unobserved: the
            # transcripts cover the whole day.
            row["today"] = today_flow(claude_code_hourly, hour_range)
        providers.append(row)
    return {"providers": providers, "empty": not providers, "today": bool(today)}
