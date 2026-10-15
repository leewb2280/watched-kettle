"""Read-only importer for the retired JSON usage-history format."""

from __future__ import annotations

import json
from pathlib import Path

from watched_kettle.usage.models import TaskUsageRecord
from watched_kettle.usage.serialization import decode_usage_record


class LegacyUsageImportError(ValueError):
    """Raised when a legacy file cannot be imported without losing records."""


def read_legacy_usage(path: Path) -> tuple[TaskUsageRecord, ...]:
    """Read and validate every record before the caller changes persistent state."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict)
        or payload.get("schemaVersion") != 1
        or not isinstance(payload.get("records"), list)
    ):
        raise LegacyUsageImportError("지원하지 않는 기존 사용량 기록 형식")
    records = tuple(decode_usage_record(raw) for raw in payload["records"])
    if any(record is None for record in records):
        raise LegacyUsageImportError("기존 사용량 기록 검증 실패")
    return tuple(record for record in records if record is not None)
