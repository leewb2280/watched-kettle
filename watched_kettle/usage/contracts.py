"""Persistence contracts used by the Work쨌Codex usage service."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from watched_kettle.usage.task_query import TaskPage
from watched_kettle.usage.device import DeviceTokenEvent, DeviceQuotaSample

from watched_kettle.usage.models import (
    LocalTokenEvent,
    QuotaUsageSample,
    TaskUsageRecord,
    UsageActivitySample,
)
from watched_kettle.usage.conversation_models import ThreadProjectRelation


class DeviceStore(Protocol):
    def append(
        self,
        tokens: tuple[DeviceTokenEvent, ...] = (),
        quotas: tuple[DeviceQuotaSample, ...] = (),
    ) -> None: ...
    def tokens(self) -> tuple[DeviceTokenEvent, ...]: ...
    def quotas(self) -> tuple[DeviceQuotaSample, ...]: ...
    def legacy(self) -> tuple: ...
    def clear(self, when: datetime | None = None) -> bool: ...


class UsageRepository(Protocol):
    """Store privacy-limited usage records and notification markers."""

    @property
    def device(self) -> DeviceStore: ...

    def load(self, account_hash: str) -> tuple[TaskUsageRecord, ...]: ...

    def load_legacy(self, account_hash: str) -> tuple[TaskUsageRecord, ...]: ...

    def set_thread_labels(self, account: str, labels: dict) -> bool: ...
    def clear_thread_labels(self) -> None: ...
    def retained_threads(self, account: str) -> tuple[str, ...]: ...
    def load_thread_projects(
        self, account: str
    ) -> dict[str, ThreadProjectRelation]: ...
    def save_thread_projects(
        self, account: str, relations: dict[str, ThreadProjectRelation]
    ) -> None: ...
    def set_project_names(self, account: str, names: dict[str, str]) -> bool: ...
    def project_summaries(self, account_hash: str, search: str = ""): ...
    def query_projects(
        self,
        account_hash: str,
        search: str = "",
        order: str = "recent",
        custom: tuple = (),
        offset: int = 0,
        limit: int = 100,
    ): ...
    def query_conversations(
        self,
        account_hash: str,
        search: str = "",
        order: str = "recent",
        offset: int = 0,
        limit: int = 100,
        thread_hash: str | None = None,
        project_key: str | None = None,
    ): ...

    def query_tasks(
        self,
        account_hash: str,
        limit: int = 100,
        search: str = "",
        order: str = "recent",
        pending: frozenset = frozenset(),
        offset: int = 0,
        thread_hash: str | None = None,
    ) -> TaskPage: ...

    def recovery_page(
        self, account_hash: str, after: int = 0, limit: int = 200
    ) -> tuple: ...

    def append(self, record: TaskUsageRecord) -> None: ...

    def apply_recovery_batch(
        self, account_hash: str, evidence: tuple, reasons: tuple
    ) -> bool: ...

    def enrich_unavailable(self, account_hash: str, evidence: object) -> bool: ...

    def update_recovery_reason(
        self, account_hash: str, thread_hash: str, turn_hash: str, reason: str
    ) -> None: ...

    def load_activity_samples(
        self, account_hash: str
    ) -> tuple[UsageActivitySample, ...]: ...

    def append_activity_sample(self, sample: UsageActivitySample) -> None: ...

    def append_local_usage_batch(
        self,
        account_hash: str,
        token_events: tuple[LocalTokenEvent, ...] = (),
        quota_samples: tuple[QuotaUsageSample, ...] = (),
    ) -> None: ...

    def load_local_token_events(
        self, account_hash: str
    ) -> tuple[LocalTokenEvent, ...]: ...

    def append_server_quota_samples(
        self, account_hash: str, samples: tuple[QuotaUsageSample, ...] = ()
    ) -> None: ...

    def load_quota_samples(self, account_hash: str) -> tuple[QuotaUsageSample, ...]: ...

    def clear(self, account_hash: str, cleared_at: datetime | None = None) -> bool: ...

    def load_threshold_markers(self, account_hash: str) -> frozenset[str]: ...

    def replace_threshold_markers(
        self, account_hash: str, markers: set[str] | frozenset[str]
    ) -> None: ...

    def was_daily_summary_sent(self, account_hash: str, local_date: str) -> bool: ...

    def mark_daily_summary_sent(
        self, account_hash: str, local_date: str, sent_at: datetime
    ) -> None: ...
