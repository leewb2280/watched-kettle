"""Project/conversation hierarchy, account isolation and bounded details."""

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
from watched_kettle.usage.identifiers import hash_identifier
from watched_kettle.usage.models import TaskUsageRecord, UsageSnapshot
from watched_kettle.usage.service import CodexUsageService
from watched_kettle.usage.worker import WorkerPreferences
from tests.test_usage_service import FakeClient


class UsageConversationsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = TemporaryDirectory()
        self.db = DatabaseManager(Path(self.directory.name) / "usage.db")
        self.assertTrue(self.db.start().available)
        self.repo = SqliteUsageRepository(self.db)
        self.now = datetime.now(timezone.utc)
        self.client = FakeClient()
        self.service = CodexUsageService(
            self.client, WorkerPreferences(True, False), self.repo
        )
        self.service.snapshot = UsageSnapshot(account_hash="a")

    def tearDown(self):
        self.service.close()
        self.db.close()
        self.directory.cleanup()

    def record(self, i, thread="one", **changes):
        return replace(
            TaskUsageRecord(
                self.now - timedelta(seconds=i),
                "a",
                hash_identifier(thread),
                "done",
                turn_hash=str(i),
                data_quality="estimated",
                total_tokens=i,
            ),
            **changes,
        )

    def fill(self):
        for i in range(205):
            self.repo.append(self.record(i))
        self.repo.append(
            self.record(300, total_tokens=None, data_quality="unavailable")
        )
        self.repo.append(self.record(301, total_tokens=20, data_quality="partial"))
        self.repo.append(self.record(302, total_tokens=999999, source_version=2))
        self.repo.append(
            self.record(
                303, thread="two", total_tokens=None, data_quality="unavailable"
            )
        )
        self.repo.append(self.record(304, account_hash="b", total_tokens=99999999))
        self.repo.set_thread_labels(
            "a",
            {
                hash_identifier("one"): ("사용량 화면 개선", "pets", "Demo_app"),
                hash_identifier("two"): ("일반 질문", "none", "프로젝트 없음"),
            },
        )

    def test_conversation_totals_include_all_pages_and_exclude_unknown_and_legacy(self):
        self.fill()
        records = self.repo.query_conversations("a").records
        one = next(r for r in records if r.thread_hash == hash_identifier("one"))
        self.assertEqual(one.total_tokens, sum(range(205)) + 20)
        self.assertEqual(
            (
                one.task_count,
                one.measured_count,
                one.unavailable_count,
                one.legacy_count,
            ),
            (208, 206, 1, 1),
        )
        self.assertIsNone(
            next(r for r in records if r.thread_hash != one.thread_hash).total_tokens
        )
        tasks = self.repo.query_tasks("a", thread_hash=one.thread_hash)
        self.assertEqual(len(tasks.records), 100)
        self.assertTrue(all(r.thread_hash == one.thread_hash for r in tasks.records))
        self.assertEqual(
            self.repo.query_conversations("a", search="demo").records, (one,)
        )
        self.assertEqual(
            self.repo.query_conversations("a", search="사용량").records, (one,)
        )
        # SQL metadata functions are rebound for each account; names never bleed.
        self.assertTrue(
            self.repo.query_conversations("b")
            .records[0]
            .title.startswith("제목 확인 불가")
        )

    def test_conversation_paging_does_not_load_task_rows_or_lose_zero(self):
        for i in range(230):
            self.repo.append(self.record(i, thread=f"thread-{i}", total_tokens=0))
        with patch.object(
            self.repo, "query_tasks", wraps=self.repo.query_tasks
        ) as load:
            self.service.set_conversation_query()
            self.assertEqual(len(self.service.snapshot.conversations), 100)
            self.assertFalse(self.service.snapshot.recent_tasks)
            load.assert_not_called()
            first = {r.thread_hash for r in self.service.snapshot.conversations}
            self.service.set_conversation_query(offset=100)
            self.assertFalse(
                first & {r.thread_hash for r in self.service.snapshot.conversations}
            )
            chosen = self.service.snapshot.conversations[0]
            self.assertEqual(chosen.total_tokens, 0)
            self.service.select_usage_conversation(chosen.thread_hash)
            self.assertEqual(len(self.service.snapshot.recent_tasks), 1)
        self.assertFalse(self.service.select_usage_conversation("other-account-only"))

    def test_stale_detail_requests_cannot_change_another_conversation(self):
        self.fill()
        self.service.set_conversation_query()
        one, two = hash_identifier("one"), hash_identifier("two")
        self.service.select_usage_conversation(one)
        self.assertTrue(self.service.set_task_query(limit=200, thread_hash=one))
        self.assertEqual(len(self.service.snapshot.recent_tasks), 100)
        self.service.select_usage_conversation(two)
        before = self.service.snapshot
        self.assertFalse(self.service.set_task_query(limit=200, thread_hash=one))
        self.assertEqual(before, self.service.snapshot)
        self.service._reset_account("signed_out")
        self.assertFalse(self.repo.thread_labels)
        self.assertIsNone(self.service.snapshot.selected_conversation)
        self.assertFalse(
            self.service.set_conversation_query(
                expected_account="a", expected_generation=0
            )
        )

    def test_catalog_uses_only_name_and_verified_project_relations_and_discards_late_response(
        self,
    ):
        self.fill()
        self.client.ready = True
        catalog = self.service.conversation_catalog
        index = ({}, {"two"}, {"p": "Demo_app"}, {"c:\\work\\pets": {"p"}})
        with patch(
            "watched_kettle.usage.conversation_catalog._read_desktop_project_index",
            return_value=index,
        ):
            self.service.set_conversation_query()
        project_id = next(
            rid for rid, method, _ in self.client.requests if method == "project/list"
        )
        self.client.respond(project_id, {"data": [{"id": "p", "name": "Demo_app"}]})
        first = next(
            rid for rid, method, _ in self.client.requests if method == "thread/list"
        )
        self.client.respond(
            first,
            {
                "data": [
                    {
                        "id": "one",
                        "name": "실제 제목",
                        "cwd": "C:/work/pets/src",
                        "preview": "SECRET PROMPT",
                    },
                    {"id": "two", "preview": "SECRET PROMPT"},
                ],
                "nextCursor": "next",
            },
        )
        label = self.repo.thread_labels[("a", hash_identifier("one"))]
        self.assertEqual(label[0], "실제 제목")
        self.assertEqual(label[2], "Demo_app")
        self.assertTrue(
            self.repo.thread_labels[("a", hash_identifier("two"))][0].startswith(
                "제목 확인 불가"
            )
        )
        self.assertEqual(
            self.repo.thread_labels[("a", hash_identifier("two"))][1], "none"
        )
        self.assertNotIn("SECRET", repr(self.repo.thread_labels))
        pending = self.client.requests[-1][0]
        self.service._reset_account("signed_out")
        self.client.respond(pending, {"data": [{"id": "one", "name": "OLD ACCOUNT"}]})
        self.assertFalse(self.repo.thread_labels)
        self.assertFalse(catalog.pending)
        self.assertNotIn("실제 제목", "\n".join(self.repo.connection.iterdump()))

    def test_catalog_repeated_cursor_and_errors_are_bounded(self):
        self.fill()
        self.client.ready = True
        self.service.set_conversation_query()
        catalog = self.service.conversation_catalog
        project = next(
            rid for rid, method, _ in self.client.requests if method == "project/list"
        )
        self.client.respond(project, error={"code": "unsupported"})
        for _ in range(4):
            self.client.respond(
                self.client.requests[-1][0], {"data": [], "nextCursor": "same"}
            )
        self.assertFalse(catalog.pending)
        before = len(self.client.requests)
        catalog.tick()
        self.assertEqual(len(self.client.requests), before)
        self.assertIn("확인 불가", catalog.status)

    def test_volatile_aggregates_match_sqlite(self):
        self.fill()
        other = VolatileUsageRepository(lambda: self.now)
        other.records = list(self.repo.load_all_for_maintenance())
        other.thread_labels = dict(self.repo.thread_labels)
        self.assertEqual(
            other.query_conversations("a"), self.repo.query_conversations("a")
        )
