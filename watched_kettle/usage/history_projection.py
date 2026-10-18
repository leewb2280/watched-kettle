"""Stable task-history projection; changes unrelated to records do not reset selection."""

from watched_kettle.localization import t


def number(value):
    return "—" if value is None else f"{value:,}"


def measurement_text(record, pending=()):
    if record.source_version < 3:
        return t("message.0355")
    if record.data_quality == "unavailable":
        return (
            t("message.0358")
            if (record.thread_hash, record.turn_hash) in pending
            else t("message.0359")
        )
    return t("message.0356") if record.data_quality == "partial" else t("message.0357")


class TaskHistoryProjection:
    def __init__(self):
        self.context = None
        self.records = ()
        self._times = {}

    def update(self, snapshot):
        records = tuple(snapshot.recent_tasks) + tuple(snapshot.legacy_tasks)
        context = (snapshot.account_hash, records, snapshot.recovery_pending)
        if context == self.context:
            return None
        self.context, self.records = context, records
        self._times = {
            stamp: self._times.get(stamp)
            or stamp.astimezone().strftime("%m/%d %H:%M:%S")
            for stamp in {r.completed_at for r in records}
        }
        return tuple(
            (
                self._times[r.completed_at],
                {
                    "failed": t("message.0284"),
                    "done": t("message.0319"),
                    "completed": t("message.0319"),
                    "aborted": t("message.0320"),
                    "cancelled": t("message.0320"),
                }.get(r.outcome, r.outcome),
                measurement_text(r, snapshot.recovery_pending),
                number(r.total_tokens),
                number(r.input_tokens),
                number(r.output_tokens),
                r.model or "—",
            )
            for r in records
        )
