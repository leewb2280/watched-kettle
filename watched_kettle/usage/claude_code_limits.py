"""Claude Code 5-hour and 7-day usage from status line samples (stage 13).

Samples carry only the official ``rate_limits`` percentages and reset times.
They are shown with the same ``RateLimitBucket`` model the Codex limits use,
so the overview cards, widget choices and tray read both the same way.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from watched_kettle.usage.identifiers import hash_identifier
from watched_kettle.usage.models import RateLimitBucket, UsageWindow
from watched_kettle.usage.notice_policy import ALERT_THRESHOLDS


LIMIT_ID = "claude_code"
LIMIT_NAME = "Claude Code"
WINDOWS = {
    "five_hour": ("primary", 5 * 60, "5시간"),
    "seven_day": ("secondary", 7 * 24 * 60, "7일"),
}
LOCAL_ACCOUNT = "claude_code:local"


@dataclass(frozen=True)
class QuotaSample:
    window: str
    observed_at: datetime
    used_percent: float
    resets_at: datetime | None


@dataclass(frozen=True)
class LimitNotice:
    message: str
    urgency: str
    deduplication_key: str
    replacement_key: str


def account_hash(config_dir):
    """Hash of the signed-in Claude account; ``claude_code:local`` without one.

    Claude Code keeps ``.claude.json`` next to its config folder by default and
    inside it when ``CLAUDE_CONFIG_DIR`` is set.
    """
    folder = Path(config_dir)
    for candidate in (folder / ".claude.json", folder.parent / ".claude.json"):
        try:
            value = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        account = value.get("oauthAccount") if isinstance(value, dict) else None
        uuid = account.get("accountUuid") if isinstance(account, dict) else None
        if isinstance(uuid, str) and uuid:
            return "claude_code:" + hash_identifier(uuid)
    return LOCAL_ACCOUNT


def samples_from_payload(payload, now=None):
    observed = _epoch(payload.get("collected_at")) or now or datetime.now(timezone.utc)
    samples = []
    for window in WINDOWS:
        percent = payload.get(f"{window}_percent")
        if isinstance(percent, (int, float)) and not isinstance(percent, bool):
            samples.append(
                QuotaSample(
                    window,
                    observed,
                    float(percent),
                    _epoch(payload.get(f"{window}_resets_at")),
                )
            )
    return tuple(samples)


def bucket(latest, now=None):
    """One bucket of the current windows.

    Samples arrive only while terminal Claude Code runs. A window past its
    reset has started over since, so it is shown as an estimate with all of
    it remaining until the next sample replaces it.
    """
    now = now or datetime.now(timezone.utc)
    windows = {}
    for name, sample in latest.items():
        slot, minutes, _label = WINDOWS[name]
        if sample.resets_at is not None and sample.resets_at <= now:
            windows[slot] = UsageWindow(
                0.0,
                100.0,
                minutes,
                _next_reset(name, sample.resets_at, now),
                estimated=True,
            )
            continue
        used = min(100.0, max(0.0, sample.used_percent))
        windows[slot] = UsageWindow(used, 100.0 - used, minutes, sample.resets_at)
    if not windows:
        return ()
    return (
        RateLimitBucket(
            LIMIT_ID,
            LIMIT_NAME,
            primary=windows.get("primary"),
            secondary=windows.get("secondary"),
        ),
    )


def _next_reset(name, resets_at, now):
    """The estimated window's reset: the 7-day one keeps its weekly rhythm,
    the 5-hour one starts at the next use and is unknown until then."""
    if name != "seven_day":
        return None
    period = timedelta(minutes=WINDOWS[name][1])
    return resets_at + period * ((now - resets_at) // period + 1)


def threshold_notices(previous, sample, now=None):
    """Notices for thresholds this sample crossed in the same reset window.

    Without an earlier sample (first run) nothing is announced, like the Codex
    limits' first refresh. A new reset window starts again from zero.
    """
    if previous is None:
        return ()
    before = previous.used_percent if previous.resets_at == sample.resets_at else 0.0
    now = now or datetime.now(timezone.utc)
    reset_key = sample.resets_at.isoformat() if sample.resets_at else "unknown"
    label = WINDOWS[sample.window][2]
    notices = []
    for threshold in ALERT_THRESHOLDS:
        if not before < threshold <= sample.used_percent:
            continue
        remaining = max(0.0, 100.0 - sample.used_percent)
        text = f"Claude Code {label} 잔여 {remaining:.0f}%"
        if sample.resets_at is not None:
            seconds = max(0, int((sample.resets_at - now).total_seconds()))
            hours, rest = divmod(seconds, 3600)
            text += (
                f" · {hours}시간 {rest // 60}분 후 초기화"
                if hours
                else f" · {rest // 60}분 후 초기화"
            )
        prefix = f"{LIMIT_ID}|{sample.window}|{reset_key}"
        notices.append(
            LimitNotice(
                text,
                "high" if threshold >= 90 else "normal",
                f"{prefix}|{threshold}",
                prefix,
            )
        )
    return tuple(notices)


def tray_summary(buckets):
    parts = []
    for item in buckets:
        for slot, label in (("primary", "5시간"), ("secondary", "7일")):
            window = getattr(item, slot)
            if window is not None and window.remaining_percent is not None:
                estimate = "(추정)" if window.estimated else ""
                parts.append(f"{label} 잔여 {window.remaining_percent:.0f}%{estimate}")
    return " · ".join(parts) if parts else "확인 불가"


def _epoch(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value, timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None
