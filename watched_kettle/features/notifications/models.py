"""Immutable notification contracts shared across features."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class NoticeRequest:
    source: str
    message: str
    urgency: str = "normal"
    deduplication_key: str = ""
    session_id: str = ""
    animation: str = "waving"
    category: str = ""
    replacement_key: str = ""
    action_token: str = ""


@dataclass(frozen=True)
class NoticeRecord:
    recorded_at: datetime
    source: str
    message: str
    urgency: str
    record_id: str = ""
    category: str = "system"
    replacement_key: str = ""
    action_token: str = ""
    delivery: str = "queued"
    confirmed: bool = False


@dataclass(frozen=True)
class NotificationSnapshot:
    recent: tuple[NoticeRecord, ...] = ()
    last_message: str = ""
