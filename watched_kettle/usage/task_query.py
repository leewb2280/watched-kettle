"""Bounded task-history queries shared by persistent and fallback stores."""

from watched_kettle.localization import t

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


def search_labels():
    return {
        "done": t("message.0319"),
        "failed": t("message.0284"),
        "cancelled": t("message.0320"),
        "legacy": t("message.0355"),
        "checking": t("message.0358"),
        "unavailable": t("message.0359"),
        "partial": t("message.0356"),
        "measured": t("message.0357"),
    }


def search_text(record, pending=()):
    labels = search_labels()
    outcome = {
        "done": labels["done"],
        "completed": labels["done"],
        "failed": labels["failed"],
        "aborted": labels["cancelled"],
        "cancelled": labels["cancelled"],
    }.get(record.outcome, record.outcome)
    return "\0".join(
        (
            record.completed_at.astimezone().strftime("%m/%d %H:%M:%S"),
            outcome,
            measurement_text(record, pending),
            record.model or "—",
        )
    ).casefold()
