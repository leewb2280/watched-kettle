"""Strict serialization for the legacy numeric usage record format."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone

from watched_kettle.usage.models import TaskUsageRecord


def encode_usage_record(record: TaskUsageRecord) -> dict[str, object]:
    """Return a JSON-compatible record without adding identity-bearing fields."""
    data = asdict(record)
    data["completed_at"] = record.completed_at.astimezone(timezone.utc).isoformat()
    return {key: value for key, value in data.items() if value is not None}


def decode_usage_record(value: object) -> TaskUsageRecord | None:
    """Decode one strict schema-v1 record, rejecting unknown or malformed fields."""
    if not isinstance(value, dict):
        return None
    allowed = set(TaskUsageRecord.__dataclass_fields__)
    if any(key not in allowed for key in value):
        return None
    try:
        completed = datetime.fromisoformat(
            str(value["completed_at"]).replace("Z", "+00:00")
        )
        if completed.tzinfo is None:
            completed = completed.replace(tzinfo=timezone.utc)
        return TaskUsageRecord(**{**value, "completed_at": completed})
    except (KeyError, TypeError, ValueError):
        return None
