import json
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from watched_kettle.storage.database import DatabaseManager, SCHEMA_VERSION
from watched_kettle.storage.usage_repository import SqliteUsageRepository
from watched_kettle.usage.models import (
    LocalTokenEvent,
    QuotaUsageSample,
    TaskUsageRecord,
    UsageActivitySample,
)


class StructuredStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "assistant-v1.sqlite3"
        self.database = DatabaseManager(self.path)
        self.assertTrue(self.database.start().available)
        self.repository = SqliteUsageRepository(self.database)

    def tearDown(self):
        self.database.close()
        self.temp.cleanup()

    def record(self, account="account", thread="thread"):
        return TaskUsageRecord(
            datetime(2026, 9, 4, tzinfo=timezone.utc),
            account,
            thread,
            "done",
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
            model="gpt-test",
        )

    def test_schema_uses_privacy_limited_columns(self):
        columns = {
            row[1]
            for row in self.database.connection.execute(
                "PRAGMA table_info(usage_task_records)"
            )
        }
        self.assertFalse(
            columns & {"email", "prompt", "title", "path", "command", "output"}
        )
        self.assertIn("account_hash", columns)
        self.assertIn("fingerprint", columns)

    def test_existing_database_is_backed_up_before_first_migration(self):
        self.database.close()
        self.path.unlink(missing_ok=True)
        connection = sqlite3.connect(self.path)
        connection.execute("CREATE TABLE legacy_marker(value TEXT)")
        connection.execute("INSERT INTO legacy_marker(value) VALUES ('keep-me')")
        connection.commit()
        connection.close()

        self.database = DatabaseManager(self.path)
        availability = self.database.start()

        self.assertTrue(availability.available)
        backups = tuple(
            self.path.parent.glob(f"{self.path.name}.v0-to-v{SCHEMA_VERSION}.*.bak")
        )
        self.assertEqual(len(backups), 1)
        backup = sqlite3.connect(backups[0])
        try:
            self.assertEqual(
                backup.execute("SELECT value FROM legacy_marker").fetchone()[0],
                "keep-me",
            )
        finally:
            backup.close()

    def test_v1_database_is_backed_up_and_migrated_to_activity_samples(self):
        self.database.close()
        self.path.unlink(missing_ok=True)
        connection = sqlite3.connect(self.path)
        self.database._migrate(connection, target_version=1)
        connection.execute("CREATE TABLE legacy_marker(value TEXT)")
        connection.execute("INSERT INTO legacy_marker VALUES ('keep-me')")
        connection.commit()
        connection.close()

        self.database = DatabaseManager(self.path)
        self.assertTrue(self.database.start().available)

        backups = tuple(
            self.path.parent.glob(f"{self.path.name}.v1-to-v{SCHEMA_VERSION}.*.bak")
        )
        self.assertEqual(len(backups), 1)
        self.assertEqual(
            self.database.connection.execute(
                "SELECT value FROM legacy_marker"
            ).fetchone()[0],
            "keep-me",
        )
        columns = {
            row[1]
            for row in self.database.connection.execute(
                "PRAGMA table_info(usage_activity_samples)"
            )
        }
        self.assertEqual(
            columns & {"account_hash", "sampled_at_utc", "cumulative_tokens"},
            {"account_hash", "sampled_at_utc", "cumulative_tokens"},
        )

    def test_activity_samples_are_partitioned_capped_and_cleared(self):
        repository = SqliteUsageRepository(self.database, maximum_activity_samples=2)
        now = datetime.now(timezone.utc)
        repository.append_activity_sample(
            UsageActivitySample("account", now - timedelta(days=9), 50)
        )
        samples = tuple(
            UsageActivitySample("account", now + timedelta(minutes=index), 100 + index)
            for index in range(3)
        )
        for sample in samples:
            repository.append_activity_sample(sample)
        repository.append_activity_sample(UsageActivitySample("other", now, 10))

        self.assertEqual(repository.load_activity_samples("account"), samples[1:])
        repository.clear("account")
        self.assertEqual(repository.load_activity_samples("account"), ())
        self.assertEqual(len(repository.load_activity_samples("other")), 1)

    def test_local_usage_is_idempotent_private_and_clear_watermark_blocks_reimport(
        self,
    ):
        now = datetime.now(timezone.utc)
        token = LocalTokenEvent("account", "event", "session-hash", now, 25)
        quota = QuotaUsageSample(
            "account",
            "quota",
            "codex",
            "primary",
            now,
            51,
            10080,
            now + timedelta(days=1),
        )
        self.repository.append_local_usage_batch("account", (token,), ())
        self.repository.append_server_quota_samples("account", (quota,))
        self.repository.append_local_usage_batch("account", (token,), ())
        self.repository.append_server_quota_samples("account", (quota,))
        self.assertEqual(len(self.repository.load_local_token_events("account")), 1)
        self.assertEqual(len(self.repository.load_quota_samples("account")), 1)
        columns = {
            row[1]
            for table in ("usage_local_token_events", "usage_quota_samples")
            for row in self.database.connection.execute(f"PRAGMA table_info({table})")
        }
        self.assertFalse(columns & {"prompt", "response", "path", "email"})

        cleared_at = now + timedelta(seconds=1)
        self.repository.clear("account", cleared_at)
        self.repository.append_local_usage_batch("account", (token,), ())
        self.repository.append_server_quota_samples("account", (quota,))
        self.assertEqual(len(self.repository.load_local_token_events("account")), 1)
        self.repository.device.clear(cleared_at)
        self.assertEqual(self.repository.load_local_token_events("account"), ())
        self.assertEqual(self.repository.load_quota_samples("account"), ())

    def test_duplicate_record_is_idempotent_and_partitioned(self):
        record = self.record()
        self.repository.append(record)
        self.repository.append(record)
        self.repository.append(self.record("other", "two"))
        self.assertEqual(len(self.repository.load_all_for_maintenance()), 2)
        self.assertEqual(self.repository.load("account"), (record,))

    def test_threshold_and_daily_summary_state_are_account_scoped(self):
        marker = "account|five|primary|reset|70"
        self.repository.replace_threshold_markers("account", {marker})
        self.assertEqual(
            self.repository.load_threshold_markers("account"), frozenset({marker})
        )
        self.repository.mark_daily_summary_sent(
            "account", "2026-09-04", datetime.now(timezone.utc)
        )
        self.assertTrue(self.repository.was_daily_summary_sent("account", "2026-09-04"))
        self.assertFalse(self.repository.was_daily_summary_sent("other", "2026-09-04"))

    def test_legacy_json_import_validates_and_deletes_after_success(self):
        legacy = Path(self.temp.name) / "usage-history-v1.json"
        record = self.record()
        legacy.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "records": [
                        {
                            "completed_at": record.completed_at.isoformat(),
                            "account_hash": record.account_hash,
                            "thread_hash": record.thread_hash,
                            "outcome": record.outcome,
                            "input_tokens": record.input_tokens,
                            "output_tokens": record.output_tokens,
                            "total_tokens": record.total_tokens,
                            "model": record.model,
                            "data_quality": record.data_quality,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        self.repository.import_legacy(legacy)
        self.assertFalse(legacy.exists())
        self.assertEqual(len(self.repository.load_all_for_maintenance()), 1)

    def test_corrupt_database_is_preserved_and_rebuilt(self):
        self.database.close()
        self.path.write_bytes(b"not a sqlite database")
        manager = DatabaseManager(self.path)
        availability = manager.start()
        try:
            self.assertTrue(availability.available)
            self.assertIsNotNone(availability.recovered_path)
            self.assertTrue(availability.recovered_path.exists())
            self.assertEqual(
                manager.connection.execute("PRAGMA quick_check").fetchone()[0], "ok"
            )
        finally:
            manager.close()

    def test_only_the_newest_migration_backups_and_corrupt_copies_stay(self):
        self.database.close()
        folder = self.path.parent
        name = self.path.name
        for day in range(1, 5):
            stamp = f"202608{day:02d}T120000000000Z"
            (folder / f"{name}.v{day}-to-v{day + 1}.{stamp}.bak").write_bytes(b"")
            (folder / f"{name}.{stamp}.corrupt").write_bytes(b"")
            (folder / f"{name}.{stamp}.corrupt-wal").write_bytes(b"")
        (folder / f"{name}.mine.bak").write_bytes(b"")
        self.path.unlink()
        connection = sqlite3.connect(self.path)
        connection.execute("CREATE TABLE legacy_marker(value TEXT)")
        connection.commit()
        connection.close()

        self.database = DatabaseManager(self.path)
        self.assertTrue(self.database.start().available)

        backups = sorted(path.name for path in folder.glob(f"{name}.v*.bak"))
        self.assertEqual(len(backups), 2)
        self.assertIn(f"{name}.v4-to-v5.20260804T120000000000Z.bak", backups)
        self.assertTrue(any(f".v0-to-v{SCHEMA_VERSION}." in item for item in backups))
        self.assertTrue((folder / f"{name}.mine.bak").exists())
        # Corrupt copies are trimmed only when another one is preserved.
        self.assertEqual(len(list(folder.glob(f"{name}.*.corrupt"))), 4)

        self.database.close()
        self.path.write_bytes(b"not a sqlite database")
        self.database = DatabaseManager(self.path)
        self.assertTrue(self.database.start().available)
        corrupt = sorted(path.name for path in folder.glob(f"{name}.*.corrupt*"))
        self.assertEqual(len(corrupt), 3)
        self.assertIn(f"{name}.20260804T120000000000Z.corrupt", corrupt)
        self.assertIn(f"{name}.20260804T120000000000Z.corrupt-wal", corrupt)

    def database_at(self, version):
        """Rebuild the file as a release with schema ``version`` left it."""
        self.database.close()
        for path in self.path.parent.glob(f"{self.path.name}*"):
            path.unlink()
        manager = DatabaseManager(self.path)
        connection = manager._connect()
        manager._migrate(connection, target_version=version)
        with connection:
            connection.execute(
                "INSERT INTO app_metadata(key, value) VALUES ('marker', 'keep')"
            )
        connection.close()

    def versions(self, connection):
        return {
            row[0]
            for row in connection.execute("SELECT version FROM schema_migrations")
        }

    def test_public_release_databases_upgrade_with_a_backup(self):
        # Public 0.15.3-0.15.6 shipped schema 8; 0.13 betas, before Claude
        # Code, schema 7. 0.15.7 and later ship the current schema.
        for version in (7, 8):
            with self.subTest(version=version):
                self.database_at(version)
                self.database = DatabaseManager(self.path)

                self.assertTrue(self.database.start().available)
                connection = self.database.connection
                self.assertEqual(
                    self.versions(connection), set(range(1, SCHEMA_VERSION + 1))
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT value FROM app_metadata WHERE key='marker'"
                    ).fetchone()[0],
                    "keep",
                )
                backups = list(
                    self.path.parent.glob(
                        f"{self.path.name}.v{version}-to-v{SCHEMA_VERSION}.*.bak"
                    )
                )
                self.assertEqual(len(backups), 1)

    def test_failed_migration_rolls_back_and_succeeds_next_start(self):
        self.database_at(7)

        def broken(connection):
            connection.execute("CREATE TABLE half_done(value TEXT)")
            raise sqlite3.OperationalError("simulated failure")

        self.database = DatabaseManager(self.path)
        with patch(
            "watched_kettle.storage.claude_code_repository.migrate_claude_code_storage",
            broken,
        ):
            self.assertFalse(self.database.start().available)
        self.database.close()

        connection = sqlite3.connect(self.path)
        try:
            self.assertEqual(self.versions(connection), set(range(1, 8)))
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertNotIn("half_done", tables)
            self.assertNotIn("claude_code_files", tables)
        finally:
            connection.close()
        self.assertFalse(list(self.path.parent.glob(f"{self.path.name}.*.corrupt")))

        self.database = DatabaseManager(self.path)
        self.assertTrue(self.database.start().available)
        self.assertEqual(
            self.versions(self.database.connection), set(range(1, SCHEMA_VERSION + 1))
        )

    def test_sparse_database_is_compacted(self):
        connection = self.database.connection
        with connection:
            connection.execute("CREATE TABLE filler(value BLOB)")
            connection.executemany(
                "INSERT INTO filler(value) VALUES (?)",
                [(bytes(4096),) for _ in range(1000)],
            )
        self.assertFalse(self.database.compact_if_sparse())
        with connection:
            connection.execute("DELETE FROM filler")
        size = self.path.stat().st_size

        self.assertTrue(self.database.compact_if_sparse())
        self.assertLess(self.path.stat().st_size, size / 2)
        self.assertFalse(self.database.compact_if_sparse())

    def test_invalid_legacy_import_keeps_source_and_rolls_back(self):
        legacy = Path(self.temp.name) / "usage-history-v1.json"
        legacy.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "records": [{"email": "should-not-be-imported"}],
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaises(ValueError):
            self.repository.import_legacy(legacy)
        self.assertTrue(legacy.exists())
        self.assertEqual(self.repository.load_all_for_maintenance(), ())

    def test_non_object_legacy_root_is_rejected_without_deletion(self):
        legacy = Path(self.temp.name) / "usage-history-v1.json"
        legacy.write_text("[]", encoding="utf-8")

        with self.assertRaises(ValueError):
            self.repository.import_legacy(legacy)

        self.assertTrue(legacy.exists())
        self.assertEqual(self.repository.load_all_for_maintenance(), ())

    def test_post_insert_verification_failure_rolls_back_and_keeps_source(self):
        legacy = Path(self.temp.name) / "usage-history-v1.json"
        record = self.record()
        legacy.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "records": [
                        {
                            "completed_at": record.completed_at.isoformat(),
                            "account_hash": record.account_hash,
                            "thread_hash": record.thread_hash,
                            "outcome": record.outcome,
                            "input_tokens": record.input_tokens,
                            "output_tokens": record.output_tokens,
                            "total_tokens": record.total_tokens,
                            "model": record.model,
                            "data_quality": record.data_quality,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        with patch.object(self.repository, "_records_matching", return_value=()):
            with self.assertRaises(sqlite3.DatabaseError):
                self.repository.import_legacy(legacy)

        self.assertTrue(legacy.exists())
        self.assertEqual(self.repository.load_all_for_maintenance(), ())

    def test_open_failure_degrades_without_creating_a_database(self):
        self.database.close()
        blocked = Path(self.temp.name) / "blocked.sqlite3"
        manager = DatabaseManager(blocked)
        with patch(
            "watched_kettle.storage.database.sqlite3.connect",
            side_effect=sqlite3.OperationalError("unable to open database file"),
        ):
            availability = manager.start()
        self.assertFalse(availability.available)
        self.assertFalse(blocked.exists())


if __name__ == "__main__":
    unittest.main()
