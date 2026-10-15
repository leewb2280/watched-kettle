"""Fault injection for account, migration and local input boundaries."""

import json
import logging
import os
import sqlite3
import unittest
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from watched_kettle.application.logging import (
    LOGGER_NAME,
    close_logging,
    configure_logging,
    logging_status,
)
from watched_kettle.application.paths import AppPaths
from watched_kettle.integrations.codex_app_server import CodexAppServerClient
from watched_kettle.integrations.codex_log import CodexLogMonitor
from watched_kettle.integrations.codex_paths import codex_home
from watched_kettle.integrations.codex_spool import (
    drain_spooled_events,
    read_hook_health,
)
from watched_kettle.pet.loader import load_pet
from watched_kettle.storage.database import DatabaseManager, SCHEMA_VERSION
from watched_kettle.storage.usage_repository import SqliteUsageRepository
from watched_kettle.ui.bubble_elements import BubbleElementRegistry
from watched_kettle.usage.models import TaskUsageRecord
from watched_kettle.usage.turn_log import TurnUsageEvidence
from watched_kettle.usage.worker import UsageWorkerService
from tests.test_codex_app_server import FakeProcess
from tests import test_usage_service as usage_fixture
from tests.test_usage_service import FakeClient


class UsageBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.fixture = usage_fixture.UsageServiceTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.service, self.client = self.fixture.service, self.fixture.client
        self.fixture._ready_and_account()

    def request(self, kind):
        return next(
            rid
            for rid, context in reversed(tuple(self.service.account.requests.items()))
            if context.kind == kind
        )

    def event(self, event, turn="one"):
        self.service.observe_agent_payload(
            {
                "source": "codex",
                "agent_scope": "main",
                "event": event,
                "session_id": "thread",
                "turn_id": turn,
            }
        )

    def usage(self, total, turn="one", thread="thread"):
        self.service.observe_local_turn_evidence(
            TurnUsageEvidence(
                thread,
                turn,
                self.fixture.now,
                total,
                total,
                0,
                0,
                "gpt-6-sol",
                "medium",
                False,
            )
        )
        self.service._flush_recovery()

    def test_null_email_never_loads_other_accounts(self):
        self.service.repository.append(
            TaskUsageRecord(
                self.fixture.now, "another", "thread", "done", total_tokens=999
            )
        )
        self.client.notification_received.emit("account/updated", {})
        self.client.respond(
            self.request("account"), {"account": {"type": "chatgpt", "email": None}}
        )
        self.client.respond(
            self.request("limits"), {"rateLimits": {"primary": {"usedPercent": 20}}}
        )
        self.assertEqual(self.service.snapshot.account_hash, "")
        self.assertEqual(self.service.snapshot.recent_tasks, ())
        self.assertFalse(self.service.clear_history())

    def test_identity_is_stable_across_email_refresh_and_sparse_limits(self):
        original = self.service.snapshot.account_hash
        self.service.refresh()
        self.client.respond(
            self.request("account"),
            {"account": {"type": "chatgpt", "email": "person@example.com"}},
        )
        self.client.respond(
            self.request("limits"),
            {"accountId": "acct", "rateLimits": {"primary": {"usedPercent": 25}}},
        )
        self.client.notification_received.emit(
            "account/rateLimits/updated",
            {"rateLimits": {"primary": {"usedPercent": 30}}},
        )
        self.assertEqual(self.service.snapshot.account_hash, original)

    def test_old_account_response_cannot_restore_signed_out_data(self):
        old_usage = self.request("usage")
        self.client.notification_received.emit("account/updated", {})
        self.client.respond(self.request("account"), {"account": None})
        self.client.respond(old_usage, {"summary": {"lifetimeTokens": 99999}})
        self.assertEqual(self.service.snapshot.account_hash, "")
        self.assertIsNone(self.service.snapshot.summary.lifetime_tokens)

    def test_clear_command_is_bound_to_reviewed_account_generation(self):
        account, generation = (
            self.service.snapshot.account_hash,
            self.service.account.generation,
        )
        self.service._reset_account()
        self.assertFalse(self.service.clear_history(account, generation))

    def test_overlapping_turn_does_not_record_wrong_delta(self):
        self.event("prompt")
        self.event("prompt", "two")
        self.event("done")
        records = self.service.snapshot.recent_tasks
        self.assertEqual(len(records), 1)
        self.assertIsNone(records[0].total_tokens)
        self.assertEqual(records[0].quality_reason, "overlapping_turn")
        self.event("done", "two")
        self.usage(30, "two")
        self.assertEqual(len(self.service.snapshot.recent_tasks), 2)
        self.assertEqual(self.service.snapshot.recent_tasks[-1].total_tokens, 30)
        self.assertIsNone(self.service.snapshot.recent_tasks[0].total_tokens)

    def test_duplicates_and_late_response_preserve_completion_time(self):
        self.event("prompt")
        self.event("prompt")
        self.event("done")
        completed = self.fixture.now
        self.fixture.now = completed.replace(hour=11)
        self.event("done")
        self.fixture.now = completed
        self.usage(50)
        self.usage(50)
        self.assertEqual(len(self.service.snapshot.recent_tasks), 1)
        self.assertEqual(self.service.snapshot.recent_tasks[0].completed_at, completed)

    def test_wrong_thread_or_missing_evidence_is_unavailable(self):
        self.event("prompt", "wrong")
        self.event("done", "wrong")
        self.usage(100, "wrong", thread="other")
        self.event("prompt", "missing")
        self.event("done", "missing")
        self.assertTrue(
            all(r.total_tokens is None for r in self.service.snapshot.recent_tasks)
        )
        self.assertEqual(self.service.measurements.tasks, {})


class StorageFaultTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "usage.db"

    def test_future_database_is_byte_identical_after_open_rejection(self):
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at_utc TEXT)"
            )
            connection.execute("INSERT INTO schema_migrations VALUES(999, 'future')")
        before = self.path.read_bytes()
        manager = DatabaseManager(self.path)
        self.assertFalse(manager.start().available)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(Path(str(self.path) + "-wal").exists())

    def test_commit_failure_rolls_back_entire_migration(self):
        class CommitFailure(sqlite3.Connection):
            def __exit__(self, kind, error, traceback):
                if kind is None:
                    self.rollback()
                    raise sqlite3.OperationalError("injected_commit_failure")
                return super().__exit__(kind, error, traceback)

        with closing(sqlite3.connect(":memory:", factory=CommitFailure)) as connection:
            with self.assertRaises(sqlite3.OperationalError):
                DatabaseManager(self.path)._migrate(connection)
            self.assertEqual(
                connection.execute("SELECT name FROM sqlite_master").fetchall(), []
            )

    def test_v2_rows_are_not_promoted_to_new_measurements(self):
        manager = DatabaseManager(self.path)
        with closing(sqlite3.connect(self.path)) as connection:
            manager._migrate(connection, target_version=2)
            connection.execute(
                "INSERT INTO usage_task_records(fingerprint, account_hash, thread_hash, completed_at_utc, outcome, total_tokens, data_quality) VALUES('old','acct','thread',?,'done',50,'measured')",
                (datetime.now(timezone.utc).isoformat(),),
            )
            connection.commit()
        self.assertTrue(manager.start().available)
        try:
            repository = SqliteUsageRepository(manager)
            self.assertEqual(repository.load("acct"), ())
            previous = repository.load_legacy("acct")[0]
            self.assertEqual(previous.total_tokens, 50)
            self.assertEqual(previous.data_quality, "legacy_unverified")
            from watched_kettle.storage.database import SCHEMA_VERSION

            self.assertTrue(
                tuple(self.path.parent.glob(f"*.v2-to-v{SCHEMA_VERSION}.*.bak"))
            )
        finally:
            manager.close()

    def test_each_migration_statement_failure_rolls_back_and_retries(self):
        manager = DatabaseManager(self.path)
        statements = []
        reference = sqlite3.connect(":memory:")
        reference.set_trace_callback(statements.append)
        manager._migrate(reference)
        reference.close()
        mutating = [
            s
            for s in statements
            if s.lstrip().startswith(("CREATE", "ALTER", "INSERT", "UPDATE"))
        ]
        for statement in mutating:
            with self.subTest(statement=statement[:65]):

                class FaultConnection(sqlite3.Connection):
                    def execute(self, sql, parameters=()):
                        if " ".join(sql.split()) == " ".join(statement.split()) or (
                            sql.startswith("INSERT INTO schema_migrations")
                            and statement.startswith("INSERT INTO schema_migrations")
                        ):
                            raise sqlite3.OperationalError("injected")
                        return super().execute(sql, parameters)

                connection = sqlite3.connect(":memory:", factory=FaultConnection)
                with self.assertRaises(sqlite3.DatabaseError):
                    manager._migrate(connection)
                self.assertEqual(
                    connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall(),
                    [],
                )
                connection.close()
        connection = sqlite3.connect(":memory:")
        manager._migrate(connection)
        self.assertEqual(
            connection.execute("SELECT max(version) FROM schema_migrations").fetchone()[
                0
            ],
            SCHEMA_VERSION,
        )
        connection.close()

    def test_empty_partial_schema_recovers_but_nonempty_is_preserved(self):
        for has_data in (False, True):
            path = self.path.with_name(f"partial-{has_data}.db")
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute(
                    "CREATE TABLE app_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )
                if has_data:
                    connection.execute(
                        "INSERT INTO app_metadata VALUES('keep', 'value')"
                    )
            manager = DatabaseManager(path)
            try:
                self.assertEqual(manager.start().available, not has_data)
            finally:
                manager.close()
            if has_data:
                with closing(sqlite3.connect(path)) as connection, connection:
                    self.assertEqual(
                        connection.execute("SELECT value FROM app_metadata").fetchone()[
                            0
                        ],
                        "value",
                    )

    def test_legacy_is_preserved_and_select_does_not_take_write_lock(self):
        manager = DatabaseManager(self.path)
        self.assertTrue(manager.start().available)
        self.addCleanup(manager.close)
        repository = SqliteUsageRepository(manager)
        record = TaskUsageRecord(
            datetime.now(timezone.utc), "account", "thread", "done", total_tokens=20
        )
        repository.append(record)
        repository.append(
            replace(record, source_version=2, data_quality="legacy_unverified")
        )
        with closing(sqlite3.connect(self.path, timeout=0.01)) as lock, lock:
            lock.execute("BEGIN IMMEDIATE")
            self.assertEqual(repository.load("account"), (record,))
            self.assertEqual(len(repository.load_legacy("account")), 1)
        for operation in (
            repository.load,
            repository.clear,
            repository.load_activity_samples,
        ):
            with self.assertRaises(ValueError):
                operation("")


WAIT_STEPS = 1000  # 10 ms each


class InputFaultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_log_failure_and_exception_chain_do_not_leak_content(self):
        with patch(
            "watched_kettle.application.logging.SafeRotatingFileHandler",
            side_effect=PermissionError("private@example.com"),
        ):
            self.assertIsNone(configure_logging(self.root))
        self.assertGreater(logging_status()["write_failures"], 0)
        path = configure_logging(self.root)
        try:
            try:
                raise ValueError("private@example.com C:\\Secret\\token")
            except ValueError as error:
                raise RuntimeError("arbitrary private prompt") from error
        except RuntimeError:
            logging.getLogger(LOGGER_NAME).exception(
                "operation failed", stack_info=True
            )
        close_logging()
        content = path.read_text(encoding="utf-8")
        self.assertNotIn("private@example.com", content)
        self.assertNotIn("arbitrary private prompt", content)
        self.assertNotIn("Secret", content)
        self.assertIn("RuntimeError", content)

    def test_nonobject_metadata_and_oversized_manifest_preserve_source(self):
        path = self.root / "bad.json"
        registry = BubbleElementRegistry(self.root)
        for value in ([], None, {"name": []}):
            path.write_text(json.dumps(value), encoding="utf-8")
            self.assertIsNone(registry._load_metadata(path))
            self.assertTrue(path.exists())
        (self.root / "pet.json").write_bytes(b" " * (256 * 1024 + 1))
        with self.assertRaises(ValueError):
            load_pet(self.root)

    def test_spool_and_health_reject_large_or_nonobject_files(self):
        path = self.root / "large.json"
        path.write_bytes(b"x" * (3 * 1024))
        self.assertEqual(list(drain_spooled_events(self.root)), [])
        path.write_text("[]")
        self.assertFalse(read_hook_health(path)["valid"])
        path.write_bytes(b"x" * 5000)
        self.assertFalse(read_hook_health(path)["valid"])

    def test_app_server_limits_and_server_request_id_collision(self):
        client = CodexAppServerClient(program="fake", process_factory=FakeProcess)
        self.addCleanup(client.close)
        client.start()
        request = client.request("account/read")
        client.feed_bytes(
            (
                json.dumps(
                    {"id": request, "method": "item/commandExecution/requestApproval"}
                )
                + "\n"
            ).encode()
        )
        self.assertIn(request, client._pending)
        response = json.loads(client.process.writes[-1])
        self.assertEqual(response["error"]["code"], -32601)
        for _ in range(100):
            client.request("account/read")
        self.assertLessEqual(len(client._pending), 64)
        client.feed_bytes(b"x" * (4 * 1024 * 1024 + 1))
        self.assertEqual(client._buffer, b"")
        self.assertLessEqual(len(client._timer_pool), 32)

    def test_log_budget_resumes_without_losing_partial_lines(self):
        monitor = CodexLogMonitor(sessions_root=self.root)
        self.addCleanup(monitor.close)
        path = self.root / "rollout-test.jsonl"
        records = []
        for index in range(450):
            for payload_type in ("task_started", "item_completed"):
                records.append(
                    json.dumps(
                        {
                            "type": "event_msg",
                            "payload": {
                                "type": payload_type,
                                "turn_id": str(index),
                            },
                        }
                    ).encode()
                    + b"\n"
                )
        path.write_bytes(b"".join(records[:-1]) + records[-1][:-3])
        monitor._positions[path] = 0
        received = []
        monitor.payload_detected.connect(received.append)
        monitor.poll_now()
        self.assertLessEqual(len(received), 200)
        for _ in range(20):
            monitor.poll_now()
        with path.open("ab") as stream:
            stream.write(records[-1][-3:])
        for _ in range(20):
            monitor.poll_now()
            if len(received) == 450:
                break
        self.assertEqual(len(received), 450)

    def test_codex_home_uses_explicit_root(self):
        with patch.dict(os.environ, {"CODEX_HOME": str(self.root)}):
            self.assertEqual(codex_home(), self.root.resolve())

    def test_storage_worker_keeps_gui_timer_alive_under_write_lock(self):
        # Each wait ends as soon as its condition holds; the long limit is for
        # slow CI runners, where the worker took over a second to open storage.
        fixture = usage_fixture.UsageServiceTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        worker = UsageWorkerService(
            AppPaths(self.root),
            fixture.preferences,
            client_factory=lambda parent: FakeClient(),
        )
        self.addCleanup(worker.close)
        for _ in range(WAIT_STEPS):
            self.app.processEvents()
            if worker.availability.available:
                break
            QTest.qWait(10)
        self.assertTrue(worker.availability.available)
        worker._send(
            "_handle_limits",
            {"accountId": "test", "rateLimits": {"primary": {"usedPercent": 1}}},
        )
        for _ in range(WAIT_STEPS):
            QTest.qWait(10)
            if worker.snapshot.account_hash:
                break
        self.assertTrue(worker.snapshot.account_hash)
        ticks = []
        timer = QTimer()
        timer.timeout.connect(lambda: ticks.append(1))
        timer.start(10)
        with (
            closing(sqlite3.connect(AppPaths(self.root).database)) as connection,
            connection,
        ):
            connection.execute("BEGIN IMMEDIATE")
            worker.observe_local_usage_batch(
                (
                    {
                        "kind": "token",
                        "event_key": "write-lock-test",
                        "session_id": "session",
                        "occurred_at": datetime.now(timezone.utc).isoformat(),
                        "delta_tokens": 100,
                    },
                )
            )
            for _ in range(WAIT_STEPS):
                QTest.qWait(10)
                if worker.snapshot.storage_error and len(ticks) >= 15:
                    break
        timer.stop()
        self.assertGreaterEqual(len(ticks), 15)
        self.assertTrue(worker.snapshot.storage_error)
        worker.close()
        self.assertFalse(worker._thread.isRunning())


if __name__ == "__main__":
    unittest.main()
