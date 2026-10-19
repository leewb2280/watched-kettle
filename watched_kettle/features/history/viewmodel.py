"""Read-only merged notice and activity timeline for this run."""

from watched_kettle.localization import t

from dataclasses import dataclass
from datetime import datetime, timezone

from PySide6.QtCore import QObject, Signal

from watched_kettle.features.project_activity.service import (
    ATTENTION_STATES,
    DEFAULT_TITLES,
    state_label,
    thread_source,
)
from watched_kettle.state.events import source_display_label


@dataclass(frozen=True)
class HistoryEntry:
    occurred_at: datetime
    kind: str
    result: str
    summary: str
    action_token: str = ""
    # Display name of the agent that produced the entry; "" for app notices.
    source: str = ""
    # "notice", "attention", "progress" or "completion".
    group: str = "notice"


@dataclass(frozen=True)
class HistorySnapshot:
    entries: tuple[HistoryEntry, ...] = ()


class HistoryViewModel(QObject):
    snapshot_changed = Signal(object)

    def __init__(self, notifications, parent=None, projects=None, router=None):
        super().__init__(parent)
        self.projects = projects
        self.router = router
        self.notifications = notifications
        self.snapshot = HistorySnapshot()
        notifications.snapshot_changed.connect(lambda _value: self.refresh())
        self.refresh(emit=False)

    def refresh(self, emit=True):
        entries = []
        router = self.router
        for record in self.notifications.snapshot.recent:
            managed = self.notifications.managed_delivery
            category = {
                "usage": t("message.0204"),
                "schedule": t("message.0205"),
                "system": t("message.0202"),
            }.get(record.category, t("message.0440"))
            entries.append(
                HistoryEntry(
                    record.recorded_at,
                    category if managed else t("message.0440"),
                    (t("activity.read") if record.confirmed else t("message.0444"))
                    if managed
                    else record.urgency,
                    record.message,
                    router.register(
                        "usage" if record.category == "usage" else "notice",
                        record.record_id,
                    )
                    if router
                    else "",
                )
            )
        projects = self.projects
        if projects is not None:

            def described(thread_id):
                source = thread_source(thread_id)
                metadata = projects.metadata.get(thread_id)
                title = (metadata.title if metadata else "") or DEFAULT_TITLES[source]
                if source != "codex" and metadata is not None and metadata.project_id:
                    title = f"{metadata.label} · {title}"
                return title, source_display_label(source)

            for record in projects.recent:
                if record.state == "done":
                    continue
                title, source = described(record.thread_id)
                entries.append(
                    HistoryEntry(
                        datetime.fromtimestamp(record.occurred_at, timezone.utc),
                        state_label(record.state, thread_source(record.thread_id)),
                        "",
                        title,
                        router.register("thread", record.thread_id) if router else "",
                        source,
                        "attention" if record.state in ATTENTION_STATES else "progress",
                    )
                )

            for completion in reversed(projects.completions):
                title, source = described(completion.thread_id)
                entries.append(
                    HistoryEntry(
                        datetime.fromtimestamp(completion.occurred_at, timezone.utc),
                        t("message.0275"),
                        t("message.0319"),
                        title,
                        router.register("thread", completion.thread_id)
                        if router
                        else "",
                        source,
                        "completion",
                    )
                )
        entries.sort(key=lambda item: item.occurred_at, reverse=True)
        self.snapshot = HistorySnapshot(tuple(entries))
        if emit:
            self.snapshot_changed.emit(self.snapshot)
        return self.snapshot
