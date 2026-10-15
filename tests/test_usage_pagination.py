import os
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication

from watched_kettle.storage.database import DatabaseManager
from watched_kettle.storage.usage_repository import (
    SqliteUsageRepository,
    VolatileUsageRepository,
)
from watched_kettle.usage.models import TaskUsageRecord, UsageSnapshot
from watched_kettle.usage.service import CodexUsageService
from watched_kettle.usage.worker import WorkerPreferences
from watched_kettle.usage.identifiers import hash_identifier
from tests.test_usage_service import FakeClient
from tests.test_turn_usage_recovery import write_log, rollout, SESSION, COMPLETED


class UsagePaginationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = DatabaseManager(self.root / "usage.db")
        self.assertTrue(self.db.start().available)
        self.repo = SqliteUsageRepository(self.db)
        self.now = datetime.now(timezone.utc)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def record(self, i, **changes):
        return replace(
            TaskUsageRecord(
                self.now - timedelta(seconds=i),
                "a",
                "thread",
                "done",
                turn_hash=str(i),
                total_tokens=i,
                data_quality="estimated",
            ),
            **changes,
        )

    def test_store_keeps_over_500_but_queries_are_bounded_and_global(self):
        for i in range(620):
            self.repo._insert(
                self.record(i, model="rare%_.model" if i == 619 else "gpt-6-sol")
            )
        self.repo.append(self.record(620))
        self.repo.append(self.record(900, completed_at=self.now - timedelta(days=91)))
        self.assertEqual(
            self.repo.connection.execute(
                "SELECT count(*) FROM usage_task_records"
            ).fetchone()[0],
            621,
        )
        first = self.repo.query_tasks("a")
        second = self.repo.query_tasks("a", offset=100)
        self.assertEqual(len(first.records), 100)
        self.assertEqual(len(second.records), 100)
        self.assertTrue(first.has_more)
        self.assertFalse(
            {r.turn_hash for r in first.records} & {r.turn_hash for r in second.records}
        )
        self.assertEqual(
            self.repo.query_tasks("a", order="top").records[0].total_tokens, 620
        )
        self.assertEqual(
            [
                r.turn_hash
                for r in self.repo.query_tasks("a", search="RARE%_.MODEL").records
            ],
            ["619"],
        )
        self.assertEqual(self.repo.query_tasks("b").records, ())
        self.assertFalse(self.repo.query_tasks("a", offset=600).has_more)

    def test_search_pending_partial_zero_and_legacy_and_stable_ties(self):
        zero = self.record(0)
        missing = self.record(
            1, total_tokens=None, data_quality="unavailable", outcome="failed"
        )
        partial = self.record(2, data_quality="partial", completed_at=zero.completed_at)
        for record in (zero, missing, partial, self.record(3, source_version=2)):
            self.repo.append(record)
        pending = frozenset({("thread", "1")})
        self.assertEqual(
            self.repo.query_tasks("a", search="확인 중", pending=pending).records,
            (missing,),
        )
        self.assertEqual(self.repo.query_tasks("a", search="실패").records, (missing,))
        self.assertEqual(
            self.repo.query_tasks("a", search="부분 측정").records, (partial,)
        )
        self.assertEqual(
            [r.total_tokens for r in self.repo.query_tasks("a", order="top").records],
            [2, 0],
        )
        first = self.repo.query_tasks("a", limit=1).records
        second = self.repo.query_tasks("a", limit=1, offset=1).records
        self.assertNotEqual(first, second)

    def make_service(self):
        service = CodexUsageService(
            FakeClient(), WorkerPreferences(True, False), self.repo
        )
        service.snapshot = UsageSnapshot(account_hash="a")
        service._recovery_started_for = ("a", service.account.generation)
        service.turn_recovery.roots = (self.root / "logs",)
        return service

    def test_service_never_sends_more_than_100_and_rejects_old_account_query(self):
        for i in range(620):
            self.repo._insert(self.record(i))
        service = self.make_service()
        try:
            service.set_task_query()
            self.assertEqual(len(service.snapshot.recent_tasks), 100)
            service.set_task_query(limit=200)
            self.assertEqual(service.snapshot.recent_tasks[0].turn_hash, "100")
            self.assertEqual(len(service.snapshot.recent_tasks), 100)
            service.set_task_query(order="top", limit=100)
            self.assertEqual(service.snapshot.recent_tasks[0].total_tokens, 619)
            before = service.snapshot
            self.assertFalse(
                service.set_task_query(expected_account="old", expected_generation=-1)
            )
            self.assertEqual(service.snapshot, before)
            service._reset_account()
            self.assertFalse(service.snapshot.recent_tasks)
            self.assertFalse(service.recovery_pages.timer.isActive())
        finally:
            service.close()

    def test_latest_tasks_ignore_history_search_order_and_page(self):
        for i in range(150):
            self.repo._insert(self.record(i, model="rare" if i == 140 else "gpt"))
        service = self.make_service()
        try:
            # Account loads, appends and recovery refresh the newest tasks.
            service._publish(**service._history_values("a", latest=True))
            newest = [r.turn_hash for r in service.snapshot.latest_tasks]
            self.assertEqual(newest, [str(i) for i in range(20)])
            service.set_task_query(limit=200)
            service.set_task_query(search="rare", order="top", limit=100)
            self.assertEqual(
                [r.turn_hash for r in service.snapshot.recent_tasks], ["140"]
            )
            self.assertEqual(
                [r.turn_hash for r in service.snapshot.latest_tasks], newest
            )
            service._reset_account()
            self.assertFalse(service.snapshot.latest_tasks)
        finally:
            service.close()

    def test_recovery_traverses_pages_and_recovers_a_hidden_old_record(self):
        for i in range(1210):
            self.repo._insert(
                self.record(
                    i,
                    completed_at=COMPLETED + timedelta(hours=1, seconds=i),
                    total_tokens=None,
                    data_quality="unavailable",
                )
            )
        hidden = TaskUsageRecord(
            COMPLETED,
            "a",
            hash_identifier(SESSION),
            "done",
            turn_hash=hash_identifier("turn-one"),
            data_quality="unavailable",
        )
        self.repo._insert(hidden)
        logs = self.root / "logs"
        logs.mkdir()
        write_log(logs, SESSION, rollout())
        service = self.make_service()
        try:
            service.set_task_query()
            self.assertNotIn(hidden, service.snapshot.recent_tasks)
            service.recovery_pages.start()
            with patch.object(
                self.repo, "recovery_page", wraps=self.repo.recovery_page
            ) as loads:
                for _ in range(2000):
                    service.recovery_pages.advance()
                    service.turn_recovery._tick()
                    if service.recovery_pages.next_cycle:
                        break
                else:
                    self.fail("recovery pages did not finish")
                self.assertGreaterEqual(loads.call_count, 4)
                self.assertTrue(
                    all(call.args[2] == 200 for call in loads.call_args_list)
                )
            found = self.repo.connection.execute(
                "SELECT total_tokens FROM usage_task_records WHERE turn_hash=?",
                (hidden.turn_hash,),
            ).fetchone()[0]
            self.assertEqual(found, 15)
            self.assertLessEqual(len(service.snapshot.recent_tasks), 100)
            self.assertLessEqual(len(service.turn_recovery.turns), 200)
            # A repeat pass must keep saved verdicts rather than flicker checking.
            states = []
            service.turn_recovery.on_state = lambda *args: states.append(args)
            service.recovery_pages.next_cycle = 0
            for _ in range(2000):
                service.recovery_pages.advance()
                service.turn_recovery._tick()
                if service.recovery_pages.next_cycle:
                    break
            self.assertFalse(any(args[2] == "checking" for args in states))
        finally:
            service.close()

    def test_fallback_retention_does_not_depend_on_display_limit(self):
        repo = VolatileUsageRepository(lambda: self.now)
        repo.records = [self.record(i) for i in range(600)]
        repo.append(self.record(600))
        self.assertEqual(len(repo.records), 601)
        self.assertEqual(len(repo.query_tasks("a", offset=100).records), 100)
        self.assertEqual(
            repo.query_tasks("a", order="column_3_desc").records[0].total_tokens, 600
        )
