"""Central notification policy and pet-delivery adapter."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import time
from uuid import uuid4
from watched_kettle.bubble_timing import BubbleDurationPolicy

from PySide6.QtCore import QObject, Signal

from watched_kettle.features.notifications.models import (
    NoticeRecord,
    NoticeRequest,
    NotificationSnapshot,
)


class NotificationService(QObject):
    snapshot_changed = Signal(object)
    payload_ready = Signal(dict)

    def __init__(self, maximum_history=50, parent=None, now=None):
        super().__init__(parent)
        self.projects = None
        self.router = None
        self.maximum_history = int(maximum_history)
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._delivered_keys = set()
        self._key_order = []
        self._current = {}
        self._deadlines = {}
        self.delivery_enabled = True
        self.managed_delivery = False
        self.now = time.monotonic
        self.snapshot = NotificationSnapshot()
        self.duration_policy = BubbleDurationPolicy()

    def bind_navigation(self, projects, router):
        self.projects = projects
        self.router = router

    def submit(self, notice):
        if not isinstance(notice, NoticeRequest):
            return False
        key = notice.deduplication_key.strip()
        if key and key in self._delivered_keys:
            return False
        if key:
            self._delivered_keys.add(key)
            self._key_order.append(key)
            if len(self._key_order) > 4096:
                self._delivered_keys.discard(self._key_order.pop(0))
        message = str(notice.message).strip()[:120]
        if not message:
            return False
        record = NoticeRecord(
            recorded_at=self._now(),
            source=notice.source,
            message=message,
            urgency=notice.urgency,
            record_id=uuid4().hex,
            category=notice.category
            or ("schedule" if notice.source == "schedule" else "system"),
            replacement_key=notice.replacement_key,
            action_token=notice.action_token,
            delivery="queued" if self.delivery_enabled else "expired",
        )
        previous = self.snapshot.recent
        if notice.replacement_key:
            replaced = [
                r
                for r in previous
                if r.replacement_key == notice.replacement_key
                and r.category == record.category
            ]
            for old in replaced:
                self._finish(old.record_id)
            previous = tuple(r for r in previous if r not in replaced)
        recent = (record, *previous)[: self.maximum_history]
        self.snapshot = replace(
            self.snapshot,
            recent=recent,
            last_message=message,
        )
        self.snapshot_changed.emit(self.snapshot)
        if self.managed_delivery:
            return True
        self.payload_ready.emit(
            {
                "source": notice.source,
                "event": "notification",
                "session_id": notice.session_id or f"notice-{notice.source}",
                "urgency": notice.urgency,
                "message": message,
                "animation": notice.animation,
            }
        )
        return True

    def clear_history(self):
        self._current.clear()
        self._deadlines.clear()
        self.snapshot = NotificationSnapshot(last_message=self.snapshot.last_message)
        self.snapshot_changed.emit(self.snapshot)

    @staticmethod
    def lane(record):
        return "schedule" if record.category == "schedule" else "general"

    def _replace_record(self, record_id, **changes):
        self.snapshot = replace(
            self.snapshot,
            recent=tuple(
                replace(r, **changes) if r.record_id == record_id else r
                for r in self.snapshot.recent
            ),
        )

    def _finish(self, record_id):
        self._replace_record(record_id, delivery="expired")
        self._deadlines.pop(record_id, None)
        self._current = {k: v for k, v in self._current.items() if v != record_id}

    def set_delivery_enabled(self, enabled):
        if enabled == self.delivery_enabled:
            return
        self.delivery_enabled = enabled
        if not enabled:
            for record in self.snapshot.recent:
                if record.delivery in {"queued", "showing"}:
                    self._finish(record.record_id)
            self.snapshot_changed.emit(self.snapshot)

    def candidates(self):
        changed = False
        retained = {r.record_id for r in self.snapshot.recent}
        for record_id, deadline in tuple(self._deadlines.items()):
            if record_id not in retained or deadline <= self.now():
                self._finish(record_id)
                changed = True
        selected = []
        if self.delivery_enabled:
            for lane in ("general", "schedule"):
                current = self._current.get(lane)
                record = next(
                    (r for r in self.snapshot.recent if r.record_id == current), None
                )
                if record is None:
                    waiting = [
                        r
                        for r in reversed(self.snapshot.recent)
                        if self.lane(r) == lane and r.delivery == "queued"
                    ]
                    if waiting:
                        record = max(
                            waiting,
                            key=lambda r: {"high": 2, "normal": 1, "low": 0}.get(
                                r.urgency, 1
                            ),
                        )
                if record:
                    selected.append(record)
        if changed:
            self.snapshot_changed.emit(self.snapshot)
        return tuple(selected)

    def shown(self, record_id):
        record = next(
            (r for r in self.snapshot.recent if r.record_id == record_id), None
        )
        if record is None or record.delivery != "queued" or not self.delivery_enabled:
            return
        self._current[self.lane(record)] = record_id
        self._deadlines[record_id] = self.now() + self.duration_policy.seconds(
            self.lane(record)
        )
        self._replace_record(record_id, delivery="showing")
        self.snapshot_changed.emit(self.snapshot)

    def confirm(self, record_id):
        self._finish(record_id)
        self._replace_record(record_id, confirmed=True)
        self.snapshot_changed.emit(self.snapshot)

    def pending_count(self, category):
        lane = "schedule" if category == "schedule" else "general"
        return sum(
            self.lane(r) == lane and r.delivery == "queued"
            for r in self.snapshot.recent
        )
