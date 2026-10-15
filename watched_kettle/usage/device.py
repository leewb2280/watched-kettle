"""Account-independent observations from this Windows user's local logs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite

from watched_kettle.usage.identifiers import hash_identifier


@dataclass(frozen=True)
class DeviceTokenEvent:
    event_hash: str
    session_hash: str
    occurred_at: datetime
    delta_tokens: int


@dataclass(frozen=True)
class DeviceQuotaSample:
    event_hash: str
    limit_id: str
    window_slot: str
    observed_at: datetime
    used_percent: float
    window_duration_mins: int | None = None
    resets_at: datetime | None = None


@dataclass(frozen=True)
class DeviceBatch:
    generation: int
    tokens: tuple[DeviceTokenEvent, ...]
    quotas: tuple[DeviceQuotaSample, ...]


def utc_timestamp(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def nonnegative(value, cast=int):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = cast(value)
        return number if isfinite(number) and 0 <= number <= 2**63 - 1 else None
    except (TypeError, ValueError, OverflowError):
        return None


def parse_device_batch(records):
    tokens, quotas = [], []
    for record in records:
        if not isinstance(record, dict):
            continue
        observed = utc_timestamp(record.get("occurred_at"))
        key = record.get("event_key")
        if observed is None or not isinstance(key, str) or not key:
            continue
        event_hash = hash_identifier(key)
        if record.get("kind") == "token":
            delta = nonnegative(record.get("delta_tokens"))
            if delta:
                tokens.append(
                    DeviceTokenEvent(
                        event_hash,
                        hash_identifier(record.get("session_id")),
                        observed,
                        delta,
                    )
                )
        elif record.get("kind") == "quota":
            used = nonnegative(record.get("used_percent"), float)
            if used is not None:
                quotas.append(
                    DeviceQuotaSample(
                        event_hash,
                        str(record.get("limit_id") or "default")[:160],
                        str(record.get("slot") or "primary")[:16],
                        observed,
                        used,
                        nonnegative(record.get("window_duration_mins")),
                        utc_timestamp(record.get("resets_at")),
                    )
                )
    return tuple(tokens), tuple(quotas)
