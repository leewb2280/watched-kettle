"""Versioned SQLite lifecycle with recoverable corruption handling."""

from __future__ import annotations

from watched_kettle.localization import t

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = 8


def migrate_task_storage(connection: sqlite3.Connection) -> None:
    """Keep the historical ledger schema without loading retired task services."""
    for statement in (
        "CREATE TABLE task_secrets (name TEXT PRIMARY KEY, payload BLOB NOT NULL)",
        """CREATE TABLE reviewed_tasks (
            id TEXT PRIMARY KEY, account_key TEXT NOT NULL, project_key TEXT NOT NULL,
            fingerprint TEXT NOT NULL, state TEXT NOT NULL, revision INTEGER NOT NULL,
            payload BLOB, reason TEXT NOT NULL DEFAULT '', position INTEGER NOT NULL,
            batch_id TEXT NOT NULL DEFAULT '', attempt_id TEXT NOT NULL DEFAULT '',
            created REAL NOT NULL, updated REAL NOT NULL)""",
        "CREATE INDEX idx_reviewed_account ON reviewed_tasks(account_key, state, position)",
        """CREATE TABLE task_attempts (
            id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES reviewed_tasks(id),
            account_key TEXT NOT NULL, project_key TEXT NOT NULL,
            revision INTEGER NOT NULL, payload BLOB NOT NULL,
            state TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL)""",
        """CREATE TABLE task_locks (
            lock_key TEXT PRIMARY KEY, attempt_id TEXT NOT NULL REFERENCES task_attempts(id))""",
        """CREATE TABLE task_exclusions (
            account_key TEXT NOT NULL, fingerprint TEXT NOT NULL, created REAL NOT NULL,
            PRIMARY KEY(account_key, fingerprint))""",
    ):
        connection.execute(statement)


@dataclass(frozen=True)
class StorageAvailability:
    available: bool
    message: str = ""
    recovered_path: Path | None = None
    code: str = ""


class UnsupportedSchema(sqlite3.DatabaseError):
    """An intact database which this release must not modify."""


class DatabaseManager:
    """Own the sole application database connection and its migrations."""

    def __init__(self, path):
        self.path = Path(path)
        self.connection = None
        self.availability = StorageAvailability(False, t("storage.not_started"))

    def start(self):
        """Open, validate and migrate the database without exposing failures upstream."""
        if self.connection is not None:
            return self.availability
        database_existed = self.path.exists()
        connection = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if database_existed:
                self._preflight()
            connection = self._connect()
            self._validate(connection)
            self._migrate(connection, backup_existing=database_existed)
        except (OSError, sqlite3.DatabaseError) as error:
            if connection is not None:
                connection.close()
                connection = None
            if not self._looks_corrupt(error):
                self.connection = None
                self.availability = StorageAvailability(
                    False,
                    t("storage.open_preserved"),
                    code=str(error)
                    if isinstance(error, UnsupportedSchema)
                    else "storage_open_failed",
                )
                return self.availability
            recovered = self._preserve_corrupt_database()
            if recovered is None:
                self.availability = StorageAvailability(
                    False,
                    t("storage.preserve_failed"),
                    code="preservation_failed",
                )
                return self.availability
            try:
                connection = self._connect()
                self._migrate(connection, backup_existing=False)
            except (OSError, sqlite3.DatabaseError):
                if connection is not None:
                    connection.close()
                self.connection = None
                self.availability = StorageAvailability(
                    False,
                    t("storage.open_failed"),
                    recovered,
                )
                return self.availability
            self.connection = connection
            self.availability = StorageAvailability(
                True,
                t("storage.recreated"),
                recovered,
            )
            return self.availability
        self.connection = connection
        self.availability = StorageAvailability(True, t("storage.available"))
        return self.availability

    def close(self):
        connection, self.connection = self.connection, None
        if connection is not None:
            connection.close()

    def require_connection(self):
        if self.connection is None:
            raise sqlite3.OperationalError(self.availability.message)
        return self.connection

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=0.25)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA busy_timeout = 250")
            return connection
        except Exception:
            connection.close()
            raise

    def _preflight(self):
        # Read the version before applying any write PRAGMA or migration.
        connection = sqlite3.connect(
            self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.25
        )
        try:
            self._versions(connection)
        finally:
            connection.close()

    @staticmethod
    def _versions(connection):
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone()
        applied = (
            {
                row[0]
                for row in connection.execute("SELECT version FROM schema_migrations")
            }
            if exists
            else set()
        )
        if any(not isinstance(v, int) or v > SCHEMA_VERSION or v < 1 for v in applied):
            raise UnsupportedSchema("unsupported_schema")
        if applied != set(range(1, max(applied, default=0) + 1)):
            raise UnsupportedSchema("incomplete_schema_history")
        return applied

    @staticmethod
    def _validate(connection):
        result = connection.execute("PRAGMA quick_check").fetchone()
        if result is None or result[0] != "ok":
            raise sqlite3.DatabaseError(
                result[0] if result else "SQLite integrity check failed"
            )

    def _migrate(
        self, connection, backup_existing=False, target_version=SCHEMA_VERSION
    ):
        """Apply migrations in order and snapshot an existing DB before changes."""
        applied = self._versions(connection)
        pending = [
            version
            for version in range(1, target_version + 1)
            if version not in applied
        ]
        # Back up before opening a write transaction so SQLite can produce a
        # consistent snapshot without contending with our own migration.
        if pending and backup_existing:
            self._backup_before_migration(
                connection,
                max(applied, default=0),
                pending[-1],
            )
        repairs = self._partial_repairs(connection, applied, pending)
        connection.execute("BEGIN IMMEDIATE")
        with connection:
            for table in repairs:
                connection.execute(f'DROP TABLE "{table}"')
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at_utc TEXT NOT NULL
                )
                """
            )
            if 1 in pending:
                statements = (
                    """CREATE TABLE app_metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )""",
                    """CREATE TABLE usage_task_records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        fingerprint TEXT NOT NULL UNIQUE,
                        account_hash TEXT NOT NULL,
                        thread_hash TEXT NOT NULL,
                        completed_at_utc TEXT NOT NULL,
                        outcome TEXT NOT NULL,
                        input_tokens INTEGER,
                        net_new_input_tokens INTEGER,
                        cached_input_tokens INTEGER,
                        output_tokens INTEGER,
                        total_tokens INTEGER,
                        estimated_credits_micros INTEGER,
                        estimated_usd_micros INTEGER,
                        model TEXT,
                        reasoning_effort TEXT,
                        speed TEXT,
                        data_quality TEXT NOT NULL
                    )""",
                    """CREATE INDEX idx_usage_account_completed
                        ON usage_task_records(account_hash, completed_at_utc DESC)""",
                    """CREATE TABLE usage_threshold_state (
                        account_hash TEXT NOT NULL,
                        limit_id TEXT NOT NULL,
                        window_slot TEXT NOT NULL,
                        reset_key TEXT NOT NULL,
                        threshold INTEGER NOT NULL,
                        PRIMARY KEY (
                            account_hash, limit_id, window_slot,
                            reset_key, threshold
                        )
                    )""",
                    """CREATE TABLE usage_daily_summary_state (
                        account_hash TEXT NOT NULL,
                        local_date TEXT NOT NULL,
                        sent_at_utc TEXT NOT NULL,
                        PRIMARY KEY (account_hash, local_date)
                    )""",
                )
                for statement in statements:
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at_utc) VALUES (?, ?)",
                    (1, datetime.now(timezone.utc).isoformat()),
                )
            if 2 in pending:
                connection.execute(
                    """CREATE TABLE usage_activity_samples (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        account_hash TEXT NOT NULL,
                        sampled_at_utc TEXT NOT NULL,
                        cumulative_tokens INTEGER NOT NULL,
                        UNIQUE(account_hash, sampled_at_utc)
                    )"""
                )
                connection.execute(
                    """CREATE INDEX idx_usage_activity_account_sampled
                        ON usage_activity_samples(account_hash, sampled_at_utc DESC)"""
                )
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at_utc) VALUES (?, ?)",
                    (2, datetime.now(timezone.utc).isoformat()),
                )

            if 3 in pending:
                for statement in (
                    "ALTER TABLE usage_task_records ADD COLUMN turn_hash TEXT NOT NULL DEFAULT ''",
                    "ALTER TABLE usage_task_records ADD COLUMN source_version INTEGER NOT NULL DEFAULT 2",
                    "ALTER TABLE usage_task_records ADD COLUMN quality_reason TEXT NOT NULL DEFAULT ''",
                    "UPDATE usage_task_records SET data_quality='legacy_unverified', quality_reason='legacy_observation'",
                    "ALTER TABLE usage_activity_samples ADD COLUMN source_version INTEGER NOT NULL DEFAULT 2",
                    "CREATE UNIQUE INDEX idx_usage_verified_turn ON usage_task_records(account_hash, thread_hash, turn_hash) WHERE source_version=3 AND turn_hash<>''",
                ):
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_migrations VALUES (?, ?)",
                    (3, datetime.now(timezone.utc).isoformat()),
                )

            if 4 in pending:
                for statement in (
                    """CREATE TABLE usage_local_token_events (
                        event_hash TEXT PRIMARY KEY,
                        account_hash TEXT NOT NULL,
                        session_hash TEXT NOT NULL,
                        occurred_at_utc TEXT NOT NULL,
                        delta_tokens INTEGER NOT NULL CHECK(delta_tokens > 0),
                        source_version INTEGER NOT NULL DEFAULT 4
                    )""",
                    """CREATE INDEX idx_usage_local_account_occurred
                        ON usage_local_token_events(account_hash, occurred_at_utc DESC)""",
                    """CREATE TABLE usage_quota_samples (
                        event_hash TEXT PRIMARY KEY,
                        account_hash TEXT NOT NULL,
                        limit_id TEXT NOT NULL,
                        window_slot TEXT NOT NULL,
                        observed_at_utc TEXT NOT NULL,
                        used_percent REAL NOT NULL,
                        window_duration_mins INTEGER,
                        resets_at_utc TEXT,
                        source_version INTEGER NOT NULL DEFAULT 4
                    )""",
                    """CREATE INDEX idx_usage_quota_account_observed
                        ON usage_quota_samples(account_hash, observed_at_utc DESC)""",
                    """CREATE TABLE usage_import_state (
                        account_hash TEXT PRIMARY KEY,
                        cleared_before_utc TEXT NOT NULL
                    )""",
                ):
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_migrations VALUES (?, ?)",
                    (4, datetime.now(timezone.utc).isoformat()),
                )

            if 5 in pending:
                from watched_kettle.storage.device_repository import (
                    migrate_device_storage,
                )

                migrate_device_storage(connection)
                connection.execute(
                    "INSERT INTO schema_migrations VALUES (?, ?)",
                    (5, datetime.now(timezone.utc).isoformat()),
                )

            if 6 in pending:
                migrate_task_storage(connection)
                connection.execute(
                    "INSERT INTO schema_migrations VALUES (?, ?)",
                    (6, datetime.now(timezone.utc).isoformat()),
                )

            if 7 in pending:
                connection.execute(
                    "ALTER TABLE reviewed_tasks ADD COLUMN origin_key TEXT NOT NULL DEFAULT ''"
                )
                connection.execute(
                    "ALTER TABLE reviewed_tasks ADD COLUMN summary_payload BLOB"
                )
                connection.execute(
                    "ALTER TABLE task_exclusions ADD COLUMN project_key TEXT NOT NULL DEFAULT ''"
                )
                connection.execute(
                    "CREATE INDEX idx_task_origin ON reviewed_tasks(account_key, origin_key)"
                )
                # Version 2 hashes are deliberately incompatible with prior review authority.
                connection.execute(
                    "UPDATE reviewed_tasks SET state='draft', reason='source_version_upgrade', batch_id='' WHERE state='queued' AND attempt_id=''"
                )
                connection.execute(
                    "INSERT INTO schema_migrations VALUES (?, ?)",
                    (7, datetime.now(timezone.utc).isoformat()),
                )

            if 8 in pending:
                from watched_kettle.storage.claude_code_repository import (
                    migrate_claude_code_storage,
                )

                migrate_claude_code_storage(connection)
                connection.execute(
                    "INSERT INTO schema_migrations VALUES (?, ?)",
                    (8, datetime.now(timezone.utc).isoformat()),
                )

    def _partial_repairs(self, connection, applied, pending):
        if not pending or min(pending) > 2:
            return ()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        candidates = (
            {
                "app_metadata",
                "usage_task_records",
                "usage_threshold_state",
                "usage_daily_summary_state",
            }
            if 1 in pending
            else set()
        )
        if 2 in pending:
            candidates.add("usage_activity_samples")
        partial = tables & candidates
        if not partial:
            return ()
        reference = sqlite3.connect(":memory:")
        try:
            self._migrate(reference, target_version=2)
            for name in partial:
                actual = list(connection.execute(f'PRAGMA table_info("{name}")'))
                expected = list(reference.execute(f'PRAGMA table_info("{name}")'))
                if [tuple(row) for row in actual] != expected or connection.execute(
                    f'SELECT 1 FROM "{name}" LIMIT 1'
                ).fetchone():
                    raise UnsupportedSchema("partial_schema_requires_recovery")
        finally:
            reference.close()
        return tuple(sorted(partial))

    def _backup_before_migration(self, connection, from_version, to_version):
        """Create a consistent SQLite backup before the first pending migration."""
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup_path = self.path.with_name(
            f"{self.path.name}.v{from_version}-to-v{to_version}.{stamp}.bak"
        )
        backup = sqlite3.connect(backup_path)
        try:
            connection.backup(backup)
        finally:
            backup.close()
        return backup_path

    def _preserve_corrupt_database(self):
        if not self.path.exists():
            return None
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        target = self.path.with_name(f"{self.path.name}.{stamp}.corrupt")
        try:
            self.path.replace(target)
            for suffix in ("-wal", "-shm"):
                sidecar = Path(str(self.path) + suffix)
                if sidecar.exists():
                    sidecar.replace(Path(str(target) + suffix))
            return target
        except OSError:
            return None

    @staticmethod
    def _looks_corrupt(error):
        message = str(error).casefold()
        return any(
            text in message
            for text in (
                "malformed",
                "file is not a database",
                "database corruption",
                "database disk image is malformed",
            )
        )
