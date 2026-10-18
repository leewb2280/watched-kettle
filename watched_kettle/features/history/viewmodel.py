"""Read-only merged local history projection."""

from watched_kettle.localization import t

from dataclasses import dataclass
from datetime import datetime, timezone

from PySide6.QtCore import QObject, Signal


@dataclass(frozen=True)
class HistoryEntry:
    occurred_at: datetime
    kind: str
    result: str
    summary: str
    action_token: str = ""
    # Display name of the agent that produced the entry; "" for app notices.
    source: str = ""


@dataclass(frozen=True)
class HistorySnapshot:
    entries: tuple[HistoryEntry, ...] = ()


class HistoryViewModel(QObject):
    snapshot_changed = Signal(object)

    def __init__(
        self, notifications, usage_vm, parent=None, projects=None, router=None
    ):
        super().__init__(parent)
        self.projects = projects
        self.router = router
        self.notifications = notifications
        self.usage_vm = usage_vm
        self.snapshot = HistorySnapshot()
        notifications.snapshot_changed.connect(lambda _value: self.refresh())
        usage_vm.snapshot_changed.connect(lambda _value: self.refresh())
        claude_code = getattr(usage_vm, "claude_code_changed", None)
        if claude_code is not None:
            claude_code.connect(lambda _value: self.refresh())
        self.refresh(emit=False)

    def refresh(self, emit=True):
        entries = []
        # A tool switched off keeps its saved history but is not listed.
        codex = getattr(self.usage_vm, "enabled", True)
        for record in self.usage_vm.snapshot.latest_tasks if codex else ():
            entries.append(
                HistoryEntry(
                    record.completed_at,
                    t("message.0441"),
                    record.outcome,
                    t("message.0442", value0=f"{record.total_tokens:,}")
                    if record.total_tokens is not None
                    else t("message.0359"),
                    source="Codex",
                )
            )
        claude_code = getattr(self.usage_vm, "claude_code_snapshot", None)
        if not getattr(self.usage_vm, "claude_code_enabled", True):
            claude_code = None
        for record in getattr(claude_code, "latest_tasks", ()):
            entries.append(
                HistoryEntry(
                    record.completed_at,
                    t("message.0026"),
                    {
                        "completed": t("message.0319"),
                        "cancelled": t("message.0320"),
                        "running": t("message.0445"),
                    }.get(record.outcome, record.outcome),
                    t("message.0443", value0=f"{record.total_tokens:,}")
                    if record.total_tokens is not None
                    else t("message.0359"),
                    source="Claude Code",
                )
            )
        for record in self.notifications.snapshot.recent:
            router = getattr(self, "router", None)
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
                    (t("message.0317") if record.confirmed else t("message.0444"))
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
        projects = getattr(self, "projects", None)
        if projects is not None:
            from watched_kettle.features.project_activity.service import (
                DEFAULT_TITLES,
                state_label,
                thread_source,
            )
            from watched_kettle.state.events import source_display_label

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
                        t("message.0235"),
                        state_label(record.state, thread_source(record.thread_id)),
                        title,
                        self.router.register("thread", record.thread_id),
                        source,
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
                        self.router.register("thread", completion.thread_id)
                        if self.router
                        else "",
                        source,
                    )
                )
        entries.sort(key=lambda item: item.occurred_at, reverse=True)
        self.snapshot = HistorySnapshot(tuple(entries))
        if emit:
            self.snapshot_changed.emit(self.snapshot)
        return self.snapshot
