"""Turn observation state and conservative, privacy-safe measurement records."""

from dataclasses import dataclass, replace
from datetime import datetime
from watched_kettle.usage.models import (
    ThreadUsageSnapshot,
    TaskUsageRecord,
    subtract_thread_usage,
)
from watched_kettle.usage.identifiers import hash_identifier


@dataclass
class TaskObservation:
    account_hash: str
    thread_id: str
    turn_id: str
    started_at: datetime
    before: ThreadUsageSnapshot | None = None
    completed_at: datetime | None = None
    outcome: str = "done"
    reason: str = ""
    end_requested: bool = False


def complete_measurement(task, after, now):
    completed = task.completed_at or now
    record = None
    if not task.reason:
        record = subtract_thread_usage(
            task.before,
            after,
            task.account_hash,
            hash_identifier(task.thread_id),
            task.outcome,
            completed,
        )
    if record is None:
        record = TaskUsageRecord(
            completed,
            task.account_hash,
            hash_identifier(task.thread_id),
            task.outcome,
            data_quality="unavailable",
            quality_reason=task.reason or "invalid_counter",
        )
    record = replace(record, turn_hash=hash_identifier(task.turn_id))
    return record


class TurnMeasurements:
    def __init__(self):
        self.tasks: dict[tuple[str, str], TaskObservation] = {}
        self.finished: dict[tuple[str, str], datetime] = {}

    def reset(self):
        self.tasks.clear()
        self.finished.clear()
