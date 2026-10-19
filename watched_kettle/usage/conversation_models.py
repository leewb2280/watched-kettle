"""Content-free totals and display-only conversation labels."""

from watched_kettle.localization import t

from dataclasses import dataclass
from datetime import datetime
from functools import cmp_to_key
from PySide6.QtCore import QCollator, QLocale


UNCLASSIFIED_PROJECT_KEY = "unclassified"
_UNCLASSIFIED_SOURCE_KEYS = frozenset({"none", "unknown"})


@dataclass(frozen=True)
class ThreadProjectRelation:
    project_key: str
    evidence: str
    checked_at: datetime


@dataclass(frozen=True)
class ConversationUsage:
    thread_hash: str
    title: str
    project_key: str
    project_name: str
    completed_at: datetime
    task_count: int
    measured_count: int
    unavailable_count: int
    legacy_count: int
    total_tokens: int | None


@dataclass(frozen=True)
class ConversationPage:
    records: tuple[ConversationUsage, ...] = ()
    has_more: bool = False


@dataclass(frozen=True)
class ProjectUsageSummary:
    project_key: str
    name: str
    conversation_count: int
    matched_count: int
    completed_at: datetime


@dataclass(frozen=True)
class ProjectPage:
    records: tuple[ProjectUsageSummary, ...] = ()
    has_more: bool = False
    total_count: int = 0


def sort_projects(
    records: list[ProjectUsageSummary] | tuple[ProjectUsageSummary, ...],
    order="recent",
    custom=(),
):
    collator = QCollator(QLocale("ko_KR"))
    collator.setNumericMode(True)
    records = sorted(records, key=lambda r: r.project_key)

    def compare(a: ProjectUsageSummary, b: ProjectUsageSummary):
        return collator.compare(a.name, b.name)

    records.sort(key=cmp_to_key(compare))
    if order == "recent":
        records.sort(key=lambda r: r.completed_at, reverse=True)
    elif order == "custom":
        positions = {key: i for i, key in enumerate(custom)}
        records.sort(key=lambda r: positions.get(r.project_key, len(positions)))
    if (
        order != "custom"
        or UNCLASSIFIED_PROJECT_KEY not in custom
        or custom[-1] == UNCLASSIFIED_PROJECT_KEY
    ):
        records.sort(key=lambda r: r.project_key == UNCLASSIFIED_PROJECT_KEY)
    return records


def label_for(labels, account, thread, relations=None, project_names=None):
    title, project_key, project_name = labels.get(
        (account, thread),
        (t("message.0349", value0=thread[:8]), "unknown", t("message.0350")),
    )
    relation = (relations or {}).get((account, thread))
    if relation is not None:
        if project_key != relation.project_key:
            project_name = t("message.0353")
        project_key = relation.project_key
    project_name = (project_names or {}).get((account, project_key), project_name)
    if project_key in _UNCLASSIFIED_SOURCE_KEYS:
        return title, UNCLASSIFIED_PROJECT_KEY, t("message.0027")
    return title, project_key, project_name
