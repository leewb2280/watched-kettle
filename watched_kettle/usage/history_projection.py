"""Stable task-history projection; changes unrelated to records do not reset selection."""


def number(value):
    return "—" if value is None else f"{value:,}"


def measurement_text(record, pending=()):
    if record.source_version < 3:
        return "이전 기록 · 집계 제외"
    if record.data_quality == "unavailable":
        return (
            "확인 중"
            if (record.thread_hash, record.turn_hash) in pending
            else "측정 불가"
        )
    return "부분 측정" if record.data_quality == "partial" else "측정됨"


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
                    "failed": "실패",
                    "done": "완료",
                    "completed": "완료",
                    "aborted": "중단",
                    "cancelled": "중단",
                }.get(r.outcome, r.outcome),
                measurement_text(r, snapshot.recovery_pending),
                number(r.total_tokens),
                number(r.input_tokens),
                number(r.output_tokens),
                r.model or "—",
            )
            for r in records
        )
