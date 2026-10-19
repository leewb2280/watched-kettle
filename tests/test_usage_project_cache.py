"""Persist only project relations; reuse metadata and isolate stale requests."""

import json
import os
import sqlite3
import unittest
from dataclasses import replace
from contextlib import closing
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
from watched_kettle.usage.conversation_models import ThreadProjectRelation
from watched_kettle.usage.identifiers import hash_identifier
from watched_kettle.usage.models import TaskUsageRecord, UsageSnapshot
from watched_kettle.usage.service import CodexUsageService
from watched_kettle.usage.worker import WorkerPreferences
from tests.test_usage_service import FakeClient


def project(raw):
    return "project:" + hash_identifier(raw)


class UsageProjectCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.db = DatabaseManager(Path(self.temp.name) / "usage.db")
        self.assertTrue(self.db.start().available)
        self.repo = SqliteUsageRepository(self.db)
        self.now = datetime.now(timezone.utc)
        self.client = FakeClient()
        self.service = CodexUsageService(
            self.client, WorkerPreferences(True, False), self.repo
        )
        self.service.snapshot = UsageSnapshot(account_hash="a")
        self.catalog = self.service.conversation_catalog
        self.catalog.desktop_path = Path(self.temp.name) / "desktop.json"
        self.elapsed = 1000.0
        self.catalog.clock = lambda: self.elapsed
        self.record()

    def tearDown(self):
        self.service.close()
        self.db.close()
        self.temp.cleanup()

    def record(self, raw="one", account="a", **changes):
        row = replace(
            TaskUsageRecord(
                self.now,
                account,
                hash_identifier(raw),
                "done",
                total_tokens=10,
                turn_hash=hash_identifier(raw + "turn"),
            ),
            **changes,
        )
        self.repo.append(row)
        return row

    def write_index(self, assignment=None, projectless=(), roots=None, extra=None):
        payload = {
            "local-projects": {
                "p": {"name": "Project P", "rootPaths": roots or ["C:/work"]},
                "q": {"name": "Project Q", "rootPaths": ["C:/other"]},
            },
            "thread-project-assignments": {
                raw: {"projectId": key} for raw, key in (assignment or {}).items()
            },
            "projectless-thread-ids": list(projectless),
        }
        payload.update(extra or {})
        self.catalog.desktop_path.write_text(json.dumps(payload), encoding="utf-8")

    def request(self, method, **params):
        return next(
            rid
            for rid, (requested, args, *_) in self.catalog.pending.items()
            if requested == method and all(args.get(k) == v for k, v in params.items())
        )

    def reply(self, method, result=None, error=None, **params):
        self.client.respond(self.request(method, **params), result, error)

    def start(self):
        self.client.ready = True
        self.service.set_project_query()

    def relation(self, raw="one", account="a"):
        return self.repo.load_thread_projects(account).get(hash_identifier(raw))

    def test_restart_restores_group_before_rpc_and_stores_no_names(self):
        self.write_index({"one": "p"})
        self.start()
        self.reply(
            "thread/read",
            {
                "thread": {
                    "id": "one",
                    "projectId": "p",
                    "name": "PRIVATE TITLE",
                    "cwd": "C:/PRIVATE/PATH",
                    "preview": "SECRET CONTENT",
                }
            },
        )
        self.assertEqual(self.relation().project_key, project("p"))
        self.service.close()
        self.db.close()
        self.assertTrue(self.db.start().available)
        self.repo = SqliteUsageRepository(self.db)
        self.client = FakeClient()  # No transport connection yet.
        self.service = CodexUsageService(
            self.client, WorkerPreferences(True, False), self.repo
        )
        self.service.snapshot = UsageSnapshot(account_hash="a")
        self.service.conversation_catalog.desktop_path = Path(self.temp.name) / "absent"
        self.service.set_project_query()
        self.assertEqual(self.service.snapshot.projects[0].project_key, project("p"))
        self.assertEqual(self.service.snapshot.conversations[0].total_tokens, 10)
        self.assertFalse(self.client.requests)
        columns = {
            r[1]
            for r in self.db.connection.execute(
                "PRAGMA table_info(usage_thread_projects)"
            )
        }
        self.assertEqual(
            columns,
            {
                "account_hash",
                "thread_hash",
                "project_key",
                "evidence",
                "checked_at_utc",
            },
        )
        dump = "\n".join(self.db.connection.iterdump())
        for value in ("PRIVATE TITLE", "PRIVATE/PATH", "Project P", "SECRET CONTENT"):
            self.assertNotIn(value, dump)

    def test_v8_migration_backs_up_without_changing_usage(self):
        expected = self.repo.load("a")
        with self.db.connection:
            self.db.connection.execute("DROP TABLE usage_thread_projects")
            self.db.connection.execute("DELETE FROM schema_migrations WHERE version=9")
        self.db.close()
        self.assertTrue(self.db.start().available)
        self.assertEqual(SqliteUsageRepository(self.db).load("a"), expected)
        backups = list(Path(self.temp.name).glob("usage.db.v8-to-v9.*.bak"))
        self.assertEqual(len(backups), 1)
        with closing(sqlite3.connect(backups[0])) as backup:
            self.assertFalse(
                backup.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='usage_thread_projects'"
                ).fetchone()
            )

    def test_reentry_sort_search_and_manual_refresh_reuse_requests(self):
        self.write_index({"one": "p"})
        self.start()
        self.reply(
            "thread/read", {"thread": {"id": "one", "projectId": "p", "name": "One"}}
        )
        self.reply("project/list", {"data": [{"id": "p", "name": "Project P"}]})
        count = len(self.client.requests)
        self.elapsed += 61  # The previous 60-second restart is gone.
        for _ in range(3):
            self.service.set_project_query(search="Project", order="name")
            self.service.set_conversation_query(project_key=project("p"))
            self.catalog.tick()
        self.assertEqual(len(self.client.requests), count)
        self.catalog.start(force=True)
        self.catalog.start(force=True)
        self.assertEqual(len(self.client.requests), count + 2)
        self.assertFalse(any(m == "thread/list" for _, m, _ in self.client.requests))

    def test_local_assignment_and_name_do_not_wait_for_project_api(self):
        self.write_index({"one": "p"})
        self.start()
        self.assertEqual(self.service.snapshot.projects[0].name, "Project P")
        self.assertEqual(self.relation().project_key, project("p"))
        self.assertIn("thread/read", [m for _, m, _ in self.client.requests])
        self.reply("project/list", error={"code": "unsupported"})
        self.reply("thread/read", {"thread": {"id": "one", "name": "One"}})
        self.assertEqual(self.repo.query_projects("a").records[0].name, "Project P")

    def test_active_and_archived_pages_alternate_and_resume(self):
        self.start()
        self.reply(
            "thread/list", {"data": [], "nextCursor": "active-2"}, archived=False
        )
        self.assertIsNotNone(self.request("thread/list", archived=True))
        self.reply(
            "thread/list", {"data": [], "nextCursor": "archived-2"}, archived=True
        )
        rid = self.request("thread/list", archived=False)
        self.assertEqual(self.catalog.pending[rid][1]["cursor"], "active-2")
        count = len(self.client.requests)
        self.service.set_project_query()
        self.assertEqual(len(self.client.requests), count)
        self.reply(
            "thread/list", {"data": [], "nextCursor": "active-3"}, archived=False
        )
        self.reply(
            "thread/list",
            {"data": [{"id": "one", "name": "Archived", "projectId": "p"}]},
            archived=True,
        )
        self.assertEqual(self.relation().project_key, project("p"))
        self.assertFalse(
            any(p[0] == "thread/list" for p in self.catalog.pending.values())
        )

    def test_project_move_discards_inflight_old_assignment(self):
        self.write_index({"one": "p"})
        self.start()
        old = self.request("thread/read")
        self.write_index({"one": "q"})
        self.catalog.tick()
        self.assertEqual(self.relation().project_key, project("q"))
        self.client.respond(
            old, {"thread": {"id": "one", "projectId": "p", "name": "Old"}}
        )
        self.assertEqual(self.relation().project_key, project("q"))
        self.reply(
            "thread/read", {"thread": {"id": "one", "projectId": "q", "name": "Moved"}}
        )
        self.assertEqual(self.repo.query_projects("a").records[0].name, "Project Q")

    def test_unrelated_desktop_changes_do_not_refetch_threads(self):
        self.write_index({"one": "p"})
        self.start()
        self.reply(
            "thread/read", {"thread": {"id": "one", "projectId": "p", "name": "One"}}
        )
        count = len(self.client.requests)
        self.write_index({"one": "p"}, extra={"window-x": 101})
        self.catalog.tick()
        self.assertEqual(len(self.client.requests), count)

    def test_unresolved_or_failed_lookup_preserves_saved_relation(self):
        self.repo.save_thread_projects(
            "a",
            {
                hash_identifier("one"): ThreadProjectRelation(
                    project("p"), "api", self.now
                )
            },
        )
        self.catalog.observe("one")
        self.start()
        self.reply("thread/read", error={"code": "timeout"})
        self.assertEqual(self.relation().project_key, project("p"))
        self.elapsed += 31
        self.catalog.tick()
        self.reply(
            "thread/read",
            {"thread": {"id": "one", "name": "Still here", "cwd": "relative/path"}},
        )
        self.assertEqual(self.relation().project_key, project("p"))
        self.catalog.start(force=True)
        self.reply("thread/read", {"thread": {"id": "one", "projectId": ""}})
        self.assertEqual(self.relation().project_key, "none")

    def test_generation_change_and_clear_reject_late_responses(self):
        self.write_index({"one": "p"})
        self.start()
        old = self.request("thread/read")
        self.service._reset_account("signed_out")
        self.client.respond(old, {"thread": {"id": "one", "projectId": "q"}})
        self.assertEqual(self.relation().project_key, project("p"))
        self.service.snapshot = UsageSnapshot(account_hash="a")
        self.start()
        stale = self.request("thread/read")
        self.assertTrue(self.service.clear_history())
        self.client.respond(stale, {"thread": {"id": "one", "projectId": "q"}})
        self.assertFalse(self.repo.load_thread_projects("a"))
        self.assertFalse(self.repo.query_projects("a").records)

    def test_new_usage_id_is_queried_without_restarting_full_discovery(self):
        self.write_index({"one": "p"})
        self.start()
        self.reply("thread/read", {"thread": {"id": "one", "projectId": "p"}})
        self.record("new")
        self.catalog.observe("new")
        self.assertIsNotNone(self.request("thread/read", threadId="new"))
        self.assertFalse(any(m == "thread/list" for _, m, _ in self.client.requests))

    def test_thread_read_unsupported_falls_back_to_list(self):
        self.catalog.observe("one")
        self.start()
        self.reply("thread/read", error={"code": -32601})
        self.reply(
            "thread/list", {"data": [{"id": "one", "projectId": "p", "name": "One"}]}
        )
        self.assertEqual(self.relation().project_key, project("p"))
        self.elapsed += 301
        self.catalog.tick()
        self.assertEqual(sum(m == "thread/read" for _, m, _ in self.client.requests), 1)

    def test_revalidation_uses_two_requests_and_honors_retry_backoff(self):
        for raw in ("two", "three", "four"):
            self.record(raw)
        for raw in ("one", "two", "three", "four"):
            self.catalog.observe(raw)
        self.start()
        self.assertEqual(
            sum(p[0] == "thread/read" for p in self.catalog.pending.values()), 2
        )
        raw = self.catalog.pending[self.request("thread/read")][1]["threadId"]
        self.reply("thread/read", error={"code": "temporary"}, threadId=raw)
        self.assertEqual(
            sum(p[0] == "thread/read" for p in self.catalog.pending.values()), 2
        )
        count = len(self.client.requests)
        self.catalog.tick()
        self.assertEqual(len(self.client.requests), count)
        self.assertNotIn(
            raw, [p[1].get("threadId") for p in self.catalog.pending.values()]
        )

    def test_local_move_only_revalidates_the_affected_thread(self):
        self.record("two")
        self.write_index({"one": "p", "two": "p"})
        self.start()
        self.reply(
            "thread/read", {"thread": {"id": "one", "projectId": "p"}}, threadId="one"
        )
        self.reply(
            "thread/read", {"thread": {"id": "two", "projectId": "p"}}, threadId="two"
        )
        before = len(self.client.requests)
        self.write_index({"one": "q", "two": "p"})
        self.catalog.tick()
        self.assertEqual(
            self.client.requests[before:][0][1:],
            ("thread/read", {"threadId": "one", "includeTurns": False}),
        )
        self.assertEqual(len(self.client.requests), before + 1)
        self.assertEqual(self.relation("two").project_key, project("p"))

    def test_new_task_completion_passes_id_to_catalog(self):
        self.write_index({"one": "p"})
        self.start()
        self.reply("thread/read", {"thread": {"id": "one", "projectId": "p"}})
        from watched_kettle.usage.turn_measurement import TaskObservation

        key = ("fresh", "turn-fresh")
        self.service.measurements.tasks[key] = TaskObservation("a", *key, self.now)
        self.service._complete_task(key)
        self.assertIsNotNone(self.request("thread/read", threadId="fresh"))

    def test_confirmed_cache_survives_ambiguous_root_and_identity_mismatch(self):
        self.repo.save_thread_projects(
            "a",
            {
                hash_identifier("one"): ThreadProjectRelation(
                    project("p"), "api", self.now
                )
            },
        )
        self.write_index(
            extra={
                "local-projects": {
                    "p": {"name": "P", "rootPaths": ["C:/work"]},
                    "q": {"name": "Q", "rootPaths": ["C:/work"]},
                }
            }
        )
        self.catalog.observe("one")
        self.start()
        self.reply("thread/read", {"thread": {"id": "different", "projectId": "q"}})
        self.assertEqual(self.relation().project_key, project("p"))
        self.catalog.start(force=True)
        self.reply("thread/read", {"thread": {"id": "one", "cwd": "C:/work/sub"}})
        self.assertEqual(self.relation().project_key, project("p"))

    def test_write_failure_keeps_current_memory_classification(self):
        self.db.connection.execute("""CREATE TEMP TRIGGER cache_write_failure BEFORE INSERT ON usage_thread_projects
            BEGIN SELECT RAISE(ABORT, 'cache unavailable'); END""")
        self.write_index({"one": "p"})
        self.start()
        self.assertEqual(
            self.repo.query_projects("a").records[0].project_key, project("p")
        )
        self.assertTrue(self.service.snapshot.storage_error)
        self.assertFalse(
            self.db.connection.execute("SELECT 1 FROM usage_thread_projects").fetchone()
        )

    def test_relations_are_account_scoped_pruned_and_match_volatile(self):
        self.record(account="b")
        one = hash_identifier("one")
        a = ThreadProjectRelation(project("p"), "api", self.now)
        b = ThreadProjectRelation("none", "explicit_projectless", self.now)
        volatile = VolatileUsageRepository()
        volatile.records = list(self.repo.load_all_for_maintenance())
        for repo in (self.repo, volatile):
            repo.save_thread_projects("a", {one: a})
            repo.save_thread_projects("b", {one: b})
            repo.clear_thread_labels()
            self.assertEqual(repo.load_thread_projects("a"), {one: a})
        self.assertEqual(self.repo.query_projects("a"), volatile.query_projects("a"))
        self.repo.clear("a")
        self.assertEqual(self.repo.load_thread_projects("b"), {one: b})
        self.assertFalse(self.repo.load_thread_projects("a"))
        with self.db.connection:
            self.db.connection.execute(
                "UPDATE usage_task_records SET completed_at_utc=? WHERE account_hash='b'",
                ((self.now - timedelta(days=91)).isoformat(),),
            )
        self.repo.maintenance()
        self.assertFalse(self.repo.load_thread_projects("b"))

    def test_lookup_limits_bound_both_list_scans(self):
        self.start()
        with patch("watched_kettle.usage.conversation_catalog.MAX_THREAD_PAGES", 4):
            for i in range(4):
                self.reply("thread/list", {"data": [], "nextCursor": "page-" + str(i)})
        self.assertFalse(
            any(p[0] == "thread/list" for p in self.catalog.pending.values())
        )
        with patch("watched_kettle.usage.conversation_catalog.MAX_THREAD_PAGES", 2):
            for i in range(2):
                self.reply(
                    "project/list", {"data": [], "nextCursor": "projects-" + str(i)}
                )
        self.assertFalse(self.catalog.pending)

    def test_one_list_page_writes_relations_in_one_transaction(self):
        self.record("two")
        self.record("three")
        self.start()
        operations = []
        self.db.connection.set_trace_callback(
            lambda sql: operations.append(sql.split()[0])
        )
        try:
            self.reply(
                "thread/list",
                {
                    "data": [
                        {"id": raw, "projectId": "p", "name": raw}
                        for raw in ("one", "two", "three")
                    ]
                },
            )
        finally:
            self.db.connection.set_trace_callback(None)
        self.assertEqual(operations.count("COMMIT"), 1)
        self.assertEqual(len(self.repo.load_thread_projects("a")), 3)

    def test_new_record_uses_already_read_local_assignment_before_rpc(self):
        self.write_index({"one": "p", "new": "q"})
        self.start()
        self.record("new")
        self.catalog.observe("new")
        self.assertEqual(self.relation("new").project_key, project("q"))
        self.assertIsNotNone(self.request("thread/read", threadId="new"))
