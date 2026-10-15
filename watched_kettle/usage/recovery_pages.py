"""Recover retained history in bounded batches, independently of visible rows."""

from time import monotonic
import sqlite3

from PySide6.QtCore import QObject, QTimer


class RecoveryPages(QObject):
    def __init__(self, service):
        super().__init__(service)
        self.service = service
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.advance)
        self.cancel()

    def cancel(self):
        self.timer.stop()
        self.scope = None
        self.cursor = 0
        self.batch = set()
        self.manual = False
        self.next_cycle = 0.0
        self.expires = None

    def start(self, manual=False):
        self.scope = (
            self.service.snapshot.account_hash,
            self.service.account.generation,
        )
        self.cursor = 0
        self.manual = manual
        self.next_cycle = 0.0
        self.expires = None
        self.timer.start()

    def advance(self):
        service = self.service
        if self.scope != (service.snapshot.account_hash, service.account.generation):
            self.cancel()
            return
        if service.snapshot.account_checking or monotonic() < self.next_cycle:
            return
        scanner = service.turn_recovery
        if scanner.work is not None or scanner.rediscover:
            return
        service._flush_recovery()
        if service._recovery_changes:
            return
        if self.batch:
            scanner.acknowledge(self.batch)
            self.batch.clear()
        try:
            records, cursor = service.repository.recovery_page(
                self.scope[0], self.cursor, 200
            )
        except (OSError, sqlite3.DatabaseError) as error:
            service._storage_failed(error)
            self.next_cycle = monotonic() + 30
            return
        if not records:
            self.cursor = 0
            self.manual = False
            if self.expires is None:
                self.expires = monotonic() + 300
            if monotonic() >= self.expires:
                self.timer.stop()
            self.next_cycle = monotonic() + 30
            return
        self.cursor = cursor
        self.batch = {(r.thread_hash, r.turn_hash) for r in records}
        scanner.add_records(records, manual=self.manual, resume=True)
