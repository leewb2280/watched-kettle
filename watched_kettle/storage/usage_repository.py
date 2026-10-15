"""Privacy-limited SQLite repository for Work·Codex usage state."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, replace
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path

from watched_kettle.storage.legacy_usage import read_legacy_usage
from watched_kettle.storage.device_repository import (
    DeviceRepository,
    VolatileDeviceRepository,
)
from watched_kettle.usage.models import (
    LocalTokenEvent,
    QuotaUsageSample,
    TaskUsageRecord,
    UsageActivitySample,
)
from watched_kettle.usage.identifiers import hash_identifier
from watched_kettle.usage.task_query import ORDERS, PAGE_SIZE, TaskPage, search_text
from watched_kettle.usage.conversation_models import (
    ConversationPage,
    ConversationUsage,
    label_for,
    ProjectUsageSummary,
    ProjectPage,
    sort_projects,
)


RECORD_COLUMNS = (
    "account_hash",
    "thread_hash",
    "outcome",
    "input_tokens",
    "net_new_input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "total_tokens",
    "estimated_credits_micros",
    "estimated_usd_micros",
    "model",
    "reasoning_effort",
    "speed",
    "data_quality",
    "turn_hash",
    "source_version",
    "quality_reason",
)


def record_fingerprint(record):
    values = asdict(record)
    values["completed_at"] = record.completed_at.astimezone(timezone.utc).isoformat()
    encoded = json.dumps(
        values, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def require_account(account_hash):
    if not isinstance(account_hash, str) or not account_hash.strip():
        raise ValueError("account_required")


def _with_recovery_reason(record, reason):
    original = record.quality_reason.split("|original:", 1)[-1]
    return replace(record, quality_reason=f"recovery:{reason}|original:{original}")


def _enriched_record(record, evidence):
    if (
        record.data_quality != "unavailable"
        or record.source_version != 3
        or not record.turn_hash
        or record.thread_hash != hash_identifier(evidence.thread_id)
        or record.turn_hash != hash_identifier(evidence.turn_id)
        or abs((record.completed_at - evidence.completed_at).total_seconds()) > 600
    ):
        return None
    cached = evidence.cached_input_tokens
    input_tokens = evidence.input_tokens
    net_new = (
        input_tokens - cached
        if input_tokens is not None and cached is not None and cached <= input_tokens
        else None
    )
    partial = evidence.partial or (
        input_tokens is not None and cached is not None and cached > input_tokens
    )
    return replace(
        record,
        total_tokens=evidence.total_tokens,
        input_tokens=input_tokens,
        cached_input_tokens=cached,
        net_new_input_tokens=net_new,
        output_tokens=evidence.output_tokens,
        model=evidence.model,
        reasoning_effort=evidence.reasoning_effort,
        data_quality="partial" if partial else "estimated",
        quality_reason="local_log_partial" if partial else "local_log_observed",
    )


class SqliteUsageRepository:
    def __init__(
        self,
        database,
        retention_days=90,
        maximum_records=500,
        activity_retention_days=8,
        maximum_activity_samples=2500,
    ):
        self.database = database
        self.device = DeviceRepository(database)
        self.retention_days = int(retention_days)
        self.maximum_records = int(maximum_records)
        self.activity_retention_days = int(activity_retention_days)
        self.maximum_activity_samples = int(maximum_activity_samples)
        self.thread_labels = {}

    def set_thread_labels(self, account, labels):
        changed = False
        for thread, label in labels.items():
            key = (account, thread)
            if self.thread_labels.get(key) != label:
                self.thread_labels[key] = label
                changed = True
        return changed

    def clear_thread_labels(self):
        self.thread_labels.clear()

    def project_summaries(self, account_hash, search=""):
        require_account(account_hash)
        self._register_labels(account_hash)
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        ).isoformat()
        rows = self.connection.execute(
            """
            SELECT usage_project_key(thread_hash) AS project_key,
                   usage_project_name(thread_hash) AS name,
                   COUNT(*) AS conversation_count,
                   SUM(CASE WHEN instr(lower(usage_title(thread_hash) || char(31) || usage_project_name(thread_hash)), ?) > 0 THEN 1 ELSE 0 END) AS matched_count,
                   MAX(completed_at_utc) AS completed_at
            FROM (SELECT thread_hash, MAX(completed_at_utc) AS completed_at_utc
                  FROM usage_task_records WHERE account_hash=? AND (source_version<3 OR completed_at_utc>=?)
                  GROUP BY thread_hash)
            GROUP BY project_key
        """,
            (search.casefold(), account_hash, cutoff),
        )
        return tuple(
            ProjectUsageSummary(
                r["project_key"],
                r["name"],
                r["conversation_count"],
                r["matched_count"],
                datetime.fromisoformat(r["completed_at"]),
            )
            for r in rows
        )

    def query_projects(
        self, account_hash, search="", order="recent", custom=(), offset=0, limit=100
    ):
        records = sort_projects(
            [
                r
                for r in self.project_summaries(account_hash, search)
                if r.matched_count
            ],
            order,
            custom,
        )
        offset = max(0, offset)
        limit = max(1, min(100, limit))
        return ProjectPage(
            tuple(records[offset : offset + limit]),
            len(records) > offset + limit,
            len(records),
        )

    def _register_labels(self, account_hash):
        for index, name in enumerate(
            ("usage_title", "usage_project_key", "usage_project_name")
        ):
            self.connection.create_function(
                name,
                1,
                lambda thread, i=index: label_for(
                    self.thread_labels, account_hash, thread
                )[i],
            )

    def query_conversations(
        self,
        account_hash,
        search="",
        order="recent",
        offset=0,
        limit=100,
        thread_hash=None,
        project_key=None,
    ):
        require_account(account_hash)
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        ).isoformat()
        # Labels live only in Python memory. SQL aggregates before returning a
        # bounded page; no titles, paths, previews or prompts are written to DB.
        self._register_labels(account_hash)
        where = "account_hash=? AND (source_version<3 OR completed_at_utc>=?)"
        args = [account_hash, cutoff]
        if thread_hash is not None:
            where += " AND thread_hash=?"
            args.append(thread_hash)
        if project_key is not None:
            where += " AND usage_project_key(thread_hash)=?"
            args.append(project_key)
        known = "source_version=3 AND data_quality!='unavailable' AND total_tokens IS NOT NULL"
        sql = f"""SELECT *, usage_title(thread_hash) AS title,
            usage_project_key(thread_hash) AS project_key,
            usage_project_name(thread_hash) AS project_name FROM (
            SELECT thread_hash, MAX(completed_at_utc) AS completed_at,
            COUNT(*) AS task_count, SUM(CASE WHEN {known} THEN 1 ELSE 0 END) AS measured_count,
            SUM(CASE WHEN source_version=3 AND NOT ({known}) THEN 1 ELSE 0 END) AS unavailable_count,
            SUM(CASE WHEN source_version<3 THEN 1 ELSE 0 END) AS legacy_count,
            SUM(CASE WHEN {known} THEN total_tokens ELSE NULL END) AS total_tokens
            FROM usage_task_records WHERE {where} GROUP BY thread_hash)"""
        if search:
            sql += " WHERE instr(lower(title || char(31) || project_name), ?) > 0"
            args.append(search.casefold())
        sql += (
            " ORDER BY "
            + ("total_tokens DESC, " if order == "top" else "")
            + "completed_at DESC, thread_hash ASC LIMIT ? OFFSET ?"
        )
        args.extend((limit + 1, offset))
        rows = self.connection.execute(sql, args).fetchall()
        return ConversationPage(
            tuple(
                ConversationUsage(
                    r["thread_hash"],
                    r["title"],
                    r["project_key"],
                    r["project_name"],
                    datetime.fromisoformat(r["completed_at"]),
                    r["task_count"],
                    r["measured_count"],
                    r["unavailable_count"],
                    r["legacy_count"],
                    r["total_tokens"],
                )
                for r in rows[:limit]
            ),
            len(rows) > limit,
        )

    @property
    def connection(self):
        return self.database.require_connection()

    def load(self, account_hash):
        require_account(account_hash)
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        ).isoformat()
        rows = self.connection.execute(
            "SELECT * FROM usage_task_records WHERE account_hash=? AND source_version=3 AND completed_at_utc>=? ORDER BY completed_at_utc DESC LIMIT ?",
            (account_hash, cutoff, self.maximum_records),
        ).fetchall()
        return tuple(self._decode(row) for row in rows)

    def load_legacy(self, account_hash):
        require_account(account_hash)
        rows = self.connection.execute(
            "SELECT * FROM usage_task_records WHERE account_hash=? AND source_version<3 ORDER BY completed_at_utc DESC LIMIT ?",
            (account_hash, self.maximum_records),
        )
        return tuple(self._decode(row) for row in rows)

    def query_tasks(
        self,
        account_hash,
        limit=PAGE_SIZE,
        search="",
        order="recent",
        pending=frozenset(),
        offset=0,
        thread_hash=None,
    ):
        require_account(account_hash)
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        ).isoformat()
        where = "account_hash=? AND (source_version<3 OR completed_at_utc>=?)"
        args = [account_hash, cutoff]
        if thread_hash is not None:
            where += " AND thread_hash=?"
            args.append(thread_hash)
        if order in ("top", "input", "output"):
            where += " AND source_version=3 AND data_quality!='unavailable' AND total_tokens IS NOT NULL"
        if search:
            # Execute matching inside the worker-owned DB; only result rows are
            # materialized. Escape LIKE metacharacters for literal search.
            checking = "0"
            if pending:
                checking = (
                    "(thread_hash,turn_hash) IN ("
                    + ",".join("(?,?)" for _ in pending)
                    + ")"
                )
                for thread, turn in sorted(pending):
                    args.extend((thread, turn))
            where += (
                " AND lower(strftime('%m/%d %H:%M:%S',completed_at_utc,'localtime') || char(31) || CASE outcome WHEN 'done' THEN '완료' WHEN 'completed' THEN '완료' WHEN 'failed' THEN '실패' WHEN 'aborted' THEN '중단' WHEN 'cancelled' THEN '중단' ELSE outcome END || char(31) || CASE WHEN source_version<3 THEN '이전 기록 · 집계 제외' WHEN data_quality='unavailable' THEN CASE WHEN "
                + checking
                + " THEN '확인 중' ELSE '측정 불가' END WHEN data_quality='partial' THEN '부분 측정' ELSE '측정됨' END || char(31) || coalesce(model,'—')) LIKE ? ESCAPE '\\'"
            )
            args.append(
                "%"
                + search.casefold()
                .replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
                + "%"
            )
        args.extend((max(1, int(limit)) + 1, max(0, int(offset))))
        rows = self.connection.execute(
            "SELECT * FROM usage_task_records WHERE "
            + where
            + " ORDER BY "
            + ORDERS.get(order, ORDERS["recent"])
            + " LIMIT ? OFFSET ?",
            args,
        ).fetchall()
        return TaskPage(
            tuple(self._decode(row) for row in rows[:limit]), len(rows) > limit
        )

    def recovery_page(self, account_hash, after=0, limit=200):
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        ).isoformat()
        rows = self.connection.execute(
            "SELECT * FROM usage_task_records WHERE account_hash=? AND source_version=3 AND data_quality='unavailable' AND length(turn_hash)>0 AND completed_at_utc>=? AND id>? ORDER BY id LIMIT ?",
            (account_hash, cutoff, after, limit),
        ).fetchall()
        return tuple(self._decode(row) for row in rows), rows[-1][
            "id"
        ] if rows else after

    def load_all_for_maintenance(self):
        return tuple(
            self._decode(row)
            for row in self.connection.execute(
                "SELECT * FROM usage_task_records ORDER BY completed_at_utc DESC"
            )
        )

    def append(self, record):
        self._insert(record)
        self._prune(record.account_hash)

    def apply_recovery_batch(self, account_hash, evidence, reasons):
        before = self.connection.total_changes
        with self.connection:
            self._recovery_batching = True
            try:
                for item in evidence:
                    self.enrich_unavailable(account_hash, item)
                for thread, turn, reason in reasons:
                    self.update_recovery_reason(account_hash, thread, turn, reason)
            finally:
                self._recovery_batching = False
        return self.connection.total_changes != before

    def enrich_unavailable(self, account_hash, evidence):
        require_account(account_hash)
        thread_hash = hash_identifier(evidence.thread_id)
        turn_hash = hash_identifier(evidence.turn_id)
        if not thread_hash or not turn_hash:
            return False
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        ).isoformat()
        with (
            nullcontext()
            if getattr(self, "_recovery_batching", False)
            else self.connection
        ):
            owners = self.connection.execute(
                """SELECT COUNT(DISTINCT account_hash) FROM usage_task_records
                   WHERE thread_hash=? AND turn_hash=? AND source_version=3""",
                (thread_hash, turn_hash),
            ).fetchone()[0]
            if owners != 1:
                self.update_recovery_reason(
                    account_hash, thread_hash, turn_hash, "account_ambiguous"
                )
                return False
            row = self.connection.execute(
                """SELECT * FROM usage_task_records
                   WHERE account_hash=? AND thread_hash=? AND turn_hash=?
                   AND source_version=3 AND data_quality='unavailable'
                   AND completed_at_utc>=?""",
                (account_hash, thread_hash, turn_hash, cutoff),
            ).fetchone()
            if row is None:
                return False
            enriched = _enriched_record(self._decode(row), evidence)
            if enriched is None:
                self.update_recovery_reason(
                    account_hash, thread_hash, turn_hash, "completion_time_mismatch"
                )
                return False
            self.connection.execute(
                """UPDATE usage_task_records SET fingerprint=?, input_tokens=?,
                   net_new_input_tokens=?, cached_input_tokens=?, output_tokens=?,
                   total_tokens=?, model=?, reasoning_effort=?, data_quality=?,
                   quality_reason=? WHERE id=? AND data_quality='unavailable'""",
                (
                    record_fingerprint(enriched),
                    enriched.input_tokens,
                    enriched.net_new_input_tokens,
                    enriched.cached_input_tokens,
                    enriched.output_tokens,
                    enriched.total_tokens,
                    enriched.model,
                    enriched.reasoning_effort,
                    enriched.data_quality,
                    enriched.quality_reason,
                    row["id"],
                ),
            )
        return True

    def update_recovery_reason(self, account_hash, thread_hash, turn_hash, reason):
        require_account(account_hash)
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        ).isoformat()
        with (
            nullcontext()
            if getattr(self, "_recovery_batching", False)
            else self.connection
        ):
            rows = self.connection.execute(
                """SELECT * FROM usage_task_records WHERE account_hash=? AND thread_hash=?
                   AND turn_hash=? AND source_version=3 AND data_quality='unavailable'
                   AND completed_at_utc>=?""",
                (account_hash, thread_hash, turn_hash, cutoff),
            ).fetchall()
            owners = self.connection.execute(
                """SELECT COUNT(DISTINCT account_hash) FROM usage_task_records
                   WHERE thread_hash=? AND turn_hash=? AND source_version=3""",
                (thread_hash, turn_hash),
            ).fetchone()[0]
            if owners > 1:
                reason = "account_ambiguous"
            for row in rows:
                updated = _with_recovery_reason(self._decode(row), reason)
                if updated.quality_reason == row["quality_reason"]:
                    continue
                self.connection.execute(
                    "UPDATE usage_task_records SET quality_reason=?, fingerprint=? WHERE id=?",
                    (updated.quality_reason, record_fingerprint(updated), row["id"]),
                )

    def load_activity_samples(self, account_hash):
        require_account(account_hash)
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=self.activity_retention_days)
        ).isoformat()
        rows = self.connection.execute(
            """
            SELECT account_hash, sampled_at_utc, cumulative_tokens
            FROM usage_activity_samples
            WHERE account_hash = ? AND source_version=3 AND sampled_at_utc>=? ORDER BY sampled_at_utc DESC LIMIT ?
            """,
            (account_hash, cutoff, self.maximum_activity_samples),
        ).fetchall()
        return tuple(
            UsageActivitySample(
                row["account_hash"],
                datetime.fromisoformat(row["sampled_at_utc"].replace("Z", "+00:00")),
                int(row["cumulative_tokens"]),
            )
            for row in reversed(rows)
        )

    def append_activity_sample(self, sample):
        require_account(sample.account_hash)
        sampled_at = sample.sampled_at.astimezone(timezone.utc).isoformat()
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO usage_activity_samples(
                    account_hash, sampled_at_utc, cumulative_tokens, source_version
                ) VALUES (?, ?, ?, 3)
                ON CONFLICT(account_hash, sampled_at_utc) DO UPDATE SET
                    cumulative_tokens = excluded.cumulative_tokens, source_version=3
                """,
                (sample.account_hash, sampled_at, int(sample.cumulative_tokens)),
            )
        self._prune_activity(sample.account_hash)

    def append_local_usage_batch(self, account_hash, token_events=(), quota_samples=()):
        return self._append_usage_batch(
            account_hash, token_events, quota_samples, "legacy_unverified"
        )

    def append_server_quota_samples(self, account_hash, samples=()):
        return self._append_usage_batch(account_hash, (), samples, "app_server")

    def _append_usage_batch(self, account_hash, token_events, quota_samples, source):
        require_account(account_hash)
        cleared_before = self.load_clear_watermark(account_hash)
        token_rows = [
            (
                item.event_hash,
                account_hash,
                item.session_hash,
                item.occurred_at.astimezone(timezone.utc).isoformat(),
                int(item.delta_tokens),
            )
            for item in token_events
            if isinstance(item, LocalTokenEvent)
            and item.account_hash == account_hash
            and item.delta_tokens > 0
            and (cleared_before is None or item.occurred_at > cleared_before)
        ]
        quota_rows = [
            (
                item.event_hash,
                account_hash,
                item.limit_id,
                item.window_slot,
                item.observed_at.astimezone(timezone.utc).isoformat(),
                float(item.used_percent),
                item.window_duration_mins,
                item.resets_at.astimezone(timezone.utc).isoformat()
                if item.resets_at
                else None,
            )
            for item in quota_samples
            if isinstance(item, QuotaUsageSample)
            and item.account_hash == account_hash
            and (cleared_before is None or item.observed_at > cleared_before)
        ]
        with self.connection:
            self.connection.executemany(
                """INSERT OR IGNORE INTO usage_local_token_events(
                    event_hash, account_hash, session_hash, occurred_at_utc,
                    delta_tokens, source_version
                ) VALUES (?, ?, ?, ?, ?, 4)""",
                token_rows,
            )
            self.connection.executemany(
                """INSERT OR IGNORE INTO usage_quota_samples(
                    event_hash, account_hash, limit_id, window_slot,
                    observed_at_utc, used_percent, window_duration_mins,
                    resets_at_utc, source_version, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (*row, 5 if source == "app_server" else 4, source)
                    for row in quota_rows
                ],
            )
        self._prune_local_activity(account_hash)

    def load_local_token_events(self, account_hash):
        require_account(account_hash)
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=self.activity_retention_days)
        ).isoformat()
        rows = self.connection.execute(
            """SELECT * FROM usage_local_token_events
               WHERE account_hash=? AND occurred_at_utc>=?
               ORDER BY occurred_at_utc""",
            (account_hash, cutoff),
        )
        return tuple(
            LocalTokenEvent(
                row["account_hash"],
                row["event_hash"],
                row["session_hash"],
                datetime.fromisoformat(row["occurred_at_utc"].replace("Z", "+00:00")),
                int(row["delta_tokens"]),
            )
            for row in rows
        )

    def load_quota_samples(self, account_hash):
        require_account(account_hash)
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=self.activity_retention_days)
        ).isoformat()
        rows = self.connection.execute(
            """SELECT * FROM usage_quota_samples
               WHERE account_hash=? AND source='app_server' AND observed_at_utc>=?
               ORDER BY observed_at_utc""",
            (account_hash, cutoff),
        )
        return tuple(
            QuotaUsageSample(
                row["account_hash"],
                row["event_hash"],
                row["limit_id"],
                row["window_slot"],
                datetime.fromisoformat(row["observed_at_utc"].replace("Z", "+00:00")),
                float(row["used_percent"]),
                row["window_duration_mins"],
                datetime.fromisoformat(row["resets_at_utc"].replace("Z", "+00:00"))
                if row["resets_at_utc"]
                else None,
            )
            for row in rows
        )

    def load_clear_watermark(self, account_hash):
        require_account(account_hash)
        row = self.connection.execute(
            "SELECT cleared_before_utc FROM usage_import_state WHERE account_hash=?",
            (account_hash,),
        ).fetchone()
        return datetime.fromisoformat(row[0].replace("Z", "+00:00")) if row else None

    def clear(self, account_hash, cleared_at=None):
        require_account(account_hash)
        cleared_at = (cleared_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
        with self.connection:
            for table in (
                "usage_task_records",
                "usage_threshold_state",
                "usage_daily_summary_state",
                "usage_activity_samples",
                "usage_quota_samples",
            ):
                self.connection.execute(
                    f"DELETE FROM {table} WHERE account_hash=?"
                    + (
                        " AND source='app_server'"
                        if table == "usage_quota_samples"
                        else ""
                    ),
                    (account_hash,),
                )
            self.connection.execute(
                """INSERT INTO usage_import_state(account_hash, cleared_before_utc)
                   VALUES (?, ?) ON CONFLICT(account_hash) DO UPDATE SET
                   cleared_before_utc=excluded.cleared_before_utc""",
                (account_hash, cleared_at.isoformat()),
            )
        return True

    def clear_all_for_maintenance(self):
        with self.connection:
            for table in (
                "usage_task_records",
                "usage_threshold_state",
                "usage_daily_summary_state",
                "usage_activity_samples",
                "usage_quota_samples",
                "usage_import_state",
            ):
                self.connection.execute(f"DELETE FROM {table}")
        return True

    def load_threshold_markers(self, account_hash):
        require_account(account_hash)
        rows = self.connection.execute(
            """
            SELECT limit_id, window_slot, reset_key, threshold
            FROM usage_threshold_state WHERE account_hash = ?
            """,
            (account_hash,),
        )
        return frozenset(
            f"{account_hash}|{row['limit_id']}|{row['window_slot']}|"
            f"{row['reset_key']}|{row['threshold']}"
            for row in rows
        )

    def replace_threshold_markers(self, account_hash, markers):
        require_account(account_hash)
        parsed = []
        for marker in markers:
            parts = str(marker).split("|", 4)
            if len(parts) != 5 or parts[0] != account_hash:
                continue
            try:
                threshold = int(parts[4])
            except ValueError:
                continue
            parsed.append((*parts[1:4], threshold))
        with self.connection:
            self.connection.execute(
                "DELETE FROM usage_threshold_state WHERE account_hash = ?",
                (account_hash,),
            )
            self.connection.executemany(
                """
                INSERT OR IGNORE INTO usage_threshold_state(
                    account_hash, limit_id, window_slot, reset_key, threshold
                ) VALUES (?, ?, ?, ?, ?)
                """,
                ((account_hash, *row) for row in parsed),
            )

    def was_daily_summary_sent(self, account_hash, local_date):
        require_account(account_hash)
        row = self.connection.execute(
            """
            SELECT 1 FROM usage_daily_summary_state
            WHERE account_hash = ? AND local_date = ?
            """,
            (account_hash, str(local_date)),
        ).fetchone()
        return row is not None

    def mark_daily_summary_sent(self, account_hash, local_date, sent_at):
        require_account(account_hash)
        with self.connection:
            self.connection.execute(
                """
                INSERT OR REPLACE INTO usage_daily_summary_state(
                    account_hash, local_date, sent_at_utc
                ) VALUES (?, ?, ?)
                """,
                (
                    account_hash,
                    str(local_date),
                    sent_at.astimezone(timezone.utc).isoformat(),
                ),
            )

    def import_legacy(self, path):
        path = Path(path)
        if not path.is_file():
            return 0
        records = tuple(
            replace(
                record,
                source_version=1,
                data_quality="legacy_unverified",
                quality_reason="legacy_observation",
                turn_hash="",
            )
            for record in read_legacy_usage(path)
        )
        before = self.connection.total_changes
        with self.connection:
            for record in records:
                self._insert(record, commit=False)
            # Verify before commit so an unexpected partial import rolls back
            # while the legacy source remains available for another attempt.
            if len(records) != len(tuple(self._records_matching(records))):
                raise sqlite3.DatabaseError("기존 사용량 기록 검증 실패")
        imported = self.connection.total_changes - before
        # Preserve the original; a successful import is idempotent.
        preserved = path.with_name(path.name + ".imported.bak")
        if not preserved.exists():
            path.rename(preserved)
        for account_hash in {record.account_hash for record in records}:
            self._prune(account_hash)
        return imported

    def _records_matching(self, records):
        fingerprints = [record_fingerprint(record) for record in records]
        if not fingerprints:
            return ()
        placeholders = ",".join("?" for _ in fingerprints)
        return self.connection.execute(
            f"SELECT fingerprint FROM usage_task_records WHERE fingerprint IN ({placeholders})",
            fingerprints,
        ).fetchall()

    def _insert(self, record, commit=True):
        require_account(record.account_hash)
        values = asdict(record)
        completed = record.completed_at.astimezone(timezone.utc).isoformat()
        statement = f"""
            INSERT OR IGNORE INTO usage_task_records(
                fingerprint, completed_at_utc, {", ".join(RECORD_COLUMNS)}
            ) VALUES ({", ".join("?" for _ in range(len(RECORD_COLUMNS) + 2))})
        """
        params = (
            record_fingerprint(record),
            completed,
            *(values[column] for column in RECORD_COLUMNS),
        )
        if commit:
            with self.connection:
                self.connection.execute(statement, params)
        else:
            self.connection.execute(statement, params)

    def maintenance(self):
        self.device.maintenance()
        accounts = self.connection.execute(
            """SELECT account_hash FROM usage_task_records WHERE source_version=3
               UNION SELECT account_hash FROM usage_activity_samples WHERE source_version=3
               UNION SELECT account_hash FROM usage_local_token_events
               UNION SELECT account_hash FROM usage_quota_samples"""
        ).fetchall()
        for row in accounts:
            self._prune(row[0])
            self._prune_activity(row[0])
            self._prune_local_activity(row[0])

    def _prune_local_activity(self, account_hash):
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=self.activity_retention_days)
        ).isoformat()
        with self.connection:
            self.connection.execute(
                "DELETE FROM usage_quota_samples WHERE account_hash=? AND source='app_server' AND observed_at_utc<?",
                (account_hash, cutoff),
            )

    def _prune(self, account_hash):
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        ).isoformat()
        with self.connection:
            self.connection.execute(
                "DELETE FROM usage_task_records WHERE account_hash = ? AND source_version=3 AND completed_at_utc < ?",
                (account_hash, cutoff),
            )

    def _prune_activity(self, account_hash):
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=self.activity_retention_days)
        ).isoformat()
        with self.connection:
            self.connection.execute(
                """
                DELETE FROM usage_activity_samples
                WHERE account_hash = ? AND source_version=3 AND sampled_at_utc < ?
                """,
                (account_hash, cutoff),
            )
            self.connection.execute(
                """
                DELETE FROM usage_activity_samples
                WHERE account_hash = ? AND source_version=3 AND id NOT IN (
                    SELECT id FROM usage_activity_samples WHERE account_hash = ? AND source_version=3
                    ORDER BY sampled_at_utc DESC LIMIT ?
                )
                """,
                (account_hash, account_hash, self.maximum_activity_samples),
            )

    @staticmethod
    def _decode(row):
        completed = datetime.fromisoformat(
            row["completed_at_utc"].replace("Z", "+00:00")
        )
        values = {column: row[column] for column in RECORD_COLUMNS}
        return TaskUsageRecord(completed_at=completed, **values)


class VolatileUsageRepository:
    """Non-persistent fallback that keeps the pet operational."""

    def __init__(self, now=None):
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.device = VolatileDeviceRepository(self._now)
        self.records = []
        self.activity_samples = []
        self.markers = {}
        self.summaries = set()
        self.local_token_events = []
        self.quota_samples = []
        self.clear_watermarks = {}
        self.thread_labels = {}

    set_thread_labels = SqliteUsageRepository.set_thread_labels
    clear_thread_labels = SqliteUsageRepository.clear_thread_labels
    query_projects = SqliteUsageRepository.query_projects

    def project_summaries(self, account_hash, search=""):
        groups: dict[str, list[ConversationUsage]] = {}
        # Fallback storage is already memory resident; no task rows reach the UI.
        for row in self.query_conversations(
            account_hash, limit=max(1, len(self.records))
        ).records:
            groups.setdefault(row.project_key, []).append(row)
        return tuple(
            ProjectUsageSummary(
                key,
                rows[0].project_name,
                len(rows),
                sum(
                    search.casefold() in (r.title + "\0" + r.project_name).casefold()
                    for r in rows
                ),
                max(r.completed_at for r in rows),
            )
            for key, rows in groups.items()
        )

    def query_conversations(
        self,
        account_hash,
        search="",
        order="recent",
        offset=0,
        limit=100,
        thread_hash=None,
        project_key=None,
    ):
        groups: dict[str, list[TaskUsageRecord]] = {}
        cutoff = self._now() - timedelta(days=90)
        for r in self.records:
            if (
                r.account_hash == account_hash
                and (r.source_version < 3 or r.completed_at >= cutoff)
                and (thread_hash is None or r.thread_hash == thread_hash)
            ):
                groups.setdefault(r.thread_hash, []).append(r)
        summaries = []
        for thread, rows in groups.items():
            title, key, name = label_for(self.thread_labels, account_hash, thread)
            if project_key is not None and project_key != key:
                continue
            if search and search.casefold() not in (title + "\0" + name).casefold():
                continue
            known = [
                r
                for r in rows
                if r.source_version == 3
                and r.data_quality != "unavailable"
                and r.total_tokens is not None
            ]
            legacy = sum(r.source_version < 3 for r in rows)
            summaries.append(
                ConversationUsage(
                    thread,
                    title,
                    key,
                    name,
                    max(r.completed_at for r in rows),
                    len(rows),
                    len(known),
                    len(rows) - len(known) - legacy,
                    legacy,
                    sum(r.total_tokens for r in known if r.total_tokens is not None)
                    if known
                    else None,
                )
            )
        summaries.sort(key=lambda r: r.thread_hash)
        summaries.sort(
            key=lambda r: (
                r.total_tokens if r.total_tokens is not None else -1,
                r.completed_at,
            )
            if order == "top"
            else (r.completed_at,),
            reverse=True,
        )
        return ConversationPage(
            tuple(summaries[offset : offset + limit]), len(summaries) > offset + limit
        )

    def load(self, account_hash):
        require_account(account_hash)
        cutoff = self._now() - timedelta(days=90)
        return tuple(
            sorted(
                (
                    r
                    for r in self.records
                    if r.account_hash == account_hash
                    and r.source_version == 3
                    and r.completed_at >= cutoff
                ),
                key=lambda r: r.completed_at,
                reverse=True,
            )[:500]
        )

    def load_legacy(self, account_hash):
        require_account(account_hash)
        return tuple(
            r
            for r in self.records
            if r.account_hash == account_hash and r.source_version < 3
        )

    def load_all_for_maintenance(self):
        return tuple(self.records)

    def query_tasks(
        self,
        account_hash,
        limit=PAGE_SIZE,
        search="",
        order="recent",
        pending=frozenset(),
        offset=0,
        thread_hash=None,
    ):
        require_account(account_hash)
        cutoff = self._now() - timedelta(days=90)
        records = [
            r
            for r in self.records
            if r.account_hash == account_hash
            and (r.source_version < 3 or r.completed_at >= cutoff)
            and (thread_hash is None or r.thread_hash == thread_hash)
        ]
        if order in ("top", "input", "output"):
            records = [
                r
                for r in records
                if r.source_version == 3
                and r.data_quality != "unavailable"
                and r.total_tokens is not None
            ]
        if search:
            records = [
                r for r in records if search.casefold() in search_text(r, pending)
            ]
        field = {
            "top": "total_tokens",
            "input": "input_tokens",
            "output": "output_tokens",
        }.get(order)
        direction = order != "time_asc"
        if order.startswith("column_") and order in ORDERS:
            column = int(order.split("_")[1])
            field = (
                "completed_at",
                "outcome",
                "data_quality",
                "total_tokens",
                "input_tokens",
                "output_tokens",
                "model",
            )[column]
            direction = order.endswith("desc")

        def key(r):
            value = getattr(r, field) if field else None
            return (
                (value is not None, value if value is not None else 0, r.completed_at)
                if field
                else (r.completed_at,)
            )

        records.sort(key=key, reverse=direction)
        return TaskPage(
            tuple(records[offset : offset + limit]), len(records) > offset + limit
        )

    def recovery_page(self, account_hash, after=0, limit=200):
        cutoff = self._now() - timedelta(days=90)
        rows = [
            (i, r)
            for i, r in enumerate(self.records, 1)
            if i > after
            and r.account_hash == account_hash
            and r.source_version == 3
            and r.data_quality == "unavailable"
            and r.turn_hash
            and r.completed_at >= cutoff
        ][:limit]
        return tuple(r for _, r in rows), rows[-1][0] if rows else after

    def append(self, record):
        require_account(record.account_hash)
        if record.turn_hash and any(
            (r.account_hash, r.thread_hash, r.turn_hash)
            == (record.account_hash, record.thread_hash, record.turn_hash)
            for r in self.records
        ):
            return
        if record_fingerprint(record) not in {
            record_fingerprint(r) for r in self.records
        }:
            self.records.append(record)
        cutoff = self._now() - timedelta(days=90)
        self.records = [
            r
            for r in self.records
            if r.account_hash != record.account_hash
            or r.source_version < 3
            or r.completed_at >= cutoff
        ]

    def apply_recovery_batch(self, account_hash, evidence, reasons):
        before = tuple(self.records)
        for item in evidence:
            self.enrich_unavailable(account_hash, item)
        for thread, turn, reason in reasons:
            self.update_recovery_reason(account_hash, thread, turn, reason)
        return tuple(self.records) != before

    def enrich_unavailable(self, account_hash, evidence):
        require_account(account_hash)
        thread_hash = hash_identifier(evidence.thread_id)
        turn_hash = hash_identifier(evidence.turn_id)
        if any(
            record.source_version == 3
            and record.thread_hash == thread_hash
            and record.turn_hash == turn_hash
            and record.account_hash != account_hash
            for record in self.records
        ):
            self.update_recovery_reason(
                account_hash, thread_hash, turn_hash, "account_ambiguous"
            )
            return False
        for index, record in enumerate(self.records):
            if (
                record.account_hash != account_hash
                or record.completed_at < self._now() - timedelta(days=90)
            ):
                continue
            enriched = _enriched_record(record, evidence)
            if enriched is not None:
                self.records[index] = enriched
                return True
        self.update_recovery_reason(
            account_hash, thread_hash, turn_hash, "completion_time_mismatch"
        )
        return False

    def update_recovery_reason(self, account_hash, thread_hash, turn_hash, reason):
        require_account(account_hash)
        owners = {
            r.account_hash
            for r in self.records
            if r.source_version == 3
            and (r.thread_hash, r.turn_hash) == (thread_hash, turn_hash)
        }
        if len(owners) > 1:
            reason = "account_ambiguous"
        retained = [
            r
            for r in self.records
            if r.account_hash == account_hash
            and r.source_version == 3
            and r.completed_at >= self._now() - timedelta(days=90)
        ]
        self.records = [
            _with_recovery_reason(r, reason)
            if r in retained
            and r.data_quality == "unavailable"
            and (r.thread_hash, r.turn_hash) == (thread_hash, turn_hash)
            else r
            for r in self.records
        ]

    def load_activity_samples(self, account_hash):
        require_account(account_hash)
        return tuple(
            sorted(
                (
                    item
                    for item in self.activity_samples
                    if item.account_hash == account_hash
                    and item.sampled_at >= self._now() - timedelta(days=8)
                ),
                key=lambda item: item.sampled_at,
            )
        )

    def append_activity_sample(self, sample):
        require_account(sample.account_hash)
        self.activity_samples = [
            item
            for item in self.activity_samples
            if not (
                item.account_hash == sample.account_hash
                and item.sampled_at == sample.sampled_at
            )
        ]
        self.activity_samples.append(sample)
        account_samples = sorted(
            (
                item
                for item in self.activity_samples
                if item.account_hash == sample.account_hash
            ),
            key=lambda item: item.sampled_at,
            reverse=True,
        )
        retained = set(account_samples[:2500])
        self.activity_samples = [
            item
            for item in self.activity_samples
            if item.account_hash != sample.account_hash or item in retained
        ]

    def append_local_usage_batch(self, account_hash, token_events=(), quota_samples=()):
        return self._append_usage_batch(
            account_hash, token_events, quota_samples, "legacy_unverified"
        )

    def append_server_quota_samples(self, account_hash, samples=()):
        return self._append_usage_batch(account_hash, (), samples, "app_server")

    def _append_usage_batch(self, account_hash, token_events, quota_samples, source):
        require_account(account_hash)
        watermark = self.clear_watermarks.get(account_hash)
        token_hashes = {item.event_hash for item in self.local_token_events}
        quota_hashes = {item.event_hash for item in self.quota_samples}
        self.local_token_events.extend(
            item
            for item in token_events
            if item.account_hash == account_hash
            and item.delta_tokens > 0
            and item.event_hash not in token_hashes
            and (watermark is None or item.occurred_at > watermark)
        )
        self.quota_samples.extend(
            item
            for item in quota_samples
            if source == "app_server"
            and item.account_hash == account_hash
            and item.event_hash not in quota_hashes
            and (watermark is None or item.observed_at > watermark)
        )

    def load_local_token_events(self, account_hash):
        require_account(account_hash)
        cutoff = self._now() - timedelta(days=8)
        return tuple(
            sorted(
                (
                    item
                    for item in self.local_token_events
                    if item.account_hash == account_hash and item.occurred_at >= cutoff
                ),
                key=lambda item: item.occurred_at,
            )
        )

    def load_quota_samples(self, account_hash):
        require_account(account_hash)
        cutoff = self._now() - timedelta(days=8)
        return tuple(
            sorted(
                (
                    item
                    for item in self.quota_samples
                    if item.account_hash == account_hash and item.observed_at >= cutoff
                ),
                key=lambda item: item.observed_at,
            )
        )

    def load_clear_watermark(self, account_hash):
        require_account(account_hash)
        return self.clear_watermarks.get(account_hash)

    def clear(self, account_hash, cleared_at=None):
        require_account(account_hash)
        self.records = [
            item
            for item in self.records
            if account_hash and item.account_hash != account_hash
        ]
        self.activity_samples = [
            item
            for item in self.activity_samples
            if account_hash and item.account_hash != account_hash
        ]
        self.local_token_events = [
            item
            for item in self.local_token_events
            if item.account_hash != account_hash
        ]
        self.quota_samples = [
            item for item in self.quota_samples if item.account_hash != account_hash
        ]
        self.clear_watermarks[account_hash] = cleared_at or self._now()
        if account_hash:
            self.markers.pop(account_hash, None)
            self.summaries = {
                item for item in self.summaries if item[0] != account_hash
            }
        else:
            self.markers.clear()
            self.summaries.clear()
        return True

    def load_threshold_markers(self, account_hash):
        require_account(account_hash)
        return frozenset(self.markers.get(account_hash, ()))

    def replace_threshold_markers(self, account_hash, markers):
        require_account(account_hash)
        self.markers[account_hash] = set(markers)

    def was_daily_summary_sent(self, account_hash, local_date):
        require_account(account_hash)
        return (account_hash, str(local_date)) in self.summaries

    def mark_daily_summary_sent(self, account_hash, local_date, _sent_at):
        require_account(account_hash)
        self.summaries.add((account_hash, str(local_date)))
