"""Bounded task-history queries shared by persistent and fallback stores."""

from dataclasses import dataclass

from watched_kettle.usage.history_projection import measurement_text


PAGE_SIZE = 100
ORDERS = {
    "recent": "completed_at_utc DESC, id DESC",
    "top": "total_tokens DESC, completed_at_utc DESC, id DESC",
    "time_asc": "completed_at_utc ASC, id ASC",
    "input": "input_tokens DESC, completed_at_utc DESC, id DESC",
    "output": "output_tokens DESC, completed_at_utc DESC, id DESC",
}
SORT_FIELDS = (
    "completed_at_utc",
    "outcome",
    "data_quality",
    "total_tokens",
    "input_tokens",
    "output_tokens",
    "model",
)
for column, field in enumerate(SORT_FIELDS):
    for direction in ("asc", "desc"):
        ORDERS[f"column_{column}_{direction}"] = (
            f"{field} {direction.upper()}, completed_at_utc DESC, id DESC"
        )


@dataclass(frozen=True)
class TaskPage:
    records: tuple = ()
    has_more: bool = False


def search_text(record, pending=()):
    outcome = {
        "done": "완료",
        "completed": "완료",
        "failed": "실패",
        "aborted": "중단",
        "cancelled": "중단",
    }.get(record.outcome, record.outcome)
    return "\0".join(
        (
            record.completed_at.astimezone().strftime("%m/%d %H:%M:%S"),
            outcome,
            measurement_text(record, pending),
            record.model or "—",
        )
    ).casefold()
