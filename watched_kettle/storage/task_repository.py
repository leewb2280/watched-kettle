"""Encrypted review and execution ledger. All reservation changes are atomic."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
import uuid
from dataclasses import replace

from watched_kettle.features.tasks.models import ReviewItem, TaskSpec, TaskState
from watched_kettle.features.tasks.candidates import candidate_key
from watched_kettle.storage.database import (
    DatabaseManager,
    migrate_task_storage as migrate_task_storage,
)
from watched_kettle.storage.task_crypto import ProtectionError, Protector


ACTIVE_STATES = ("starting", "running", "reconciling", "needs_review")


class QueueRepository:
    def __init__(
        self, database: DatabaseManager, protector: Protector, *, clock=time.time
    ):
        self.database = database
        self.protector = protector
        self.clock = clock
        self.account_key = ""
        connection = self.connection
        with connection:
            row = connection.execute(
                "SELECT payload FROM task_secrets WHERE name='fingerprints'"
            ).fetchone()
            # The DPAPI entropy predates the rename (ADR 0005); changing it
            # would make existing task keys unreadable.
            if row is None:
                key = secrets.token_bytes(32)
                encrypted = protector.protect(key, b"codex-pets/task-key/v1")
                connection.execute(
                    "INSERT OR IGNORE INTO task_secrets VALUES ('fingerprints', ?)",
                    (encrypted,),
                )
                row = connection.execute(
                    "SELECT payload FROM task_secrets WHERE name='fingerprints'"
                ).fetchone()
            self._key = protector.unprotect(bytes(row[0]), b"codex-pets/task-key/v1")

    @property
    def connection(self) -> sqlite3.Connection:
        return self.database.require_connection()

    def digest(self, domain: str, value: str) -> str:
        return hmac.new(
            self._key, (domain + "\0" + value).encode(), hashlib.sha256
        ).hexdigest()

    def set_account(self, account: str | None) -> None:
        self.account_key = self.digest("account", account) if account else ""
        if self.account_key:
            # Fill v6 candidate links under the original user's decryption context.
            with self.connection:
                rows = self.connection.execute(
                    "SELECT id,payload FROM reviewed_tasks WHERE account_key=? AND origin_key='' AND payload IS NOT NULL",
                    (self.account_key,),
                ).fetchall()
                for row in rows:
                    try:
                        spec = TaskSpec.from_dict(self._open(row["payload"], row["id"]))
                    except (ProtectionError, ValueError, TypeError, KeyError):
                        continue
                    origin = self.origin_key(spec)
                    if origin:
                        self.connection.execute(
                            "UPDATE reviewed_tasks SET origin_key=? WHERE id=? AND account_key=?",
                            (origin, row["id"], self.account_key),
                        )

    def _account(self) -> str:
        if not self.account_key:
            raise ValueError("account_required")
        return self.account_key

    def _seal(self, value: dict, identity: str) -> bytes:
        data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        return self.protector.protect(data, (self._account() + "/" + identity).encode())

    def _open(self, payload: bytes, identity: str) -> dict:
        try:
            return json.loads(
                self.protector.unprotect(
                    bytes(payload), (self._account() + "/" + identity).encode()
                )
            )
        except (ValueError, TypeError, UnicodeError):
            raise ProtectionError("protected_data_unavailable") from None

    @contextmanager
    def transaction(self):
        connection = self.connection
        connection.execute("BEGIN IMMEDIATE")
        with connection:
            yield connection

    def fingerprint(self, spec: TaskSpec) -> str:
        return self.digest(
            "candidate",
            json.dumps(
                [spec.thread_id, spec.source_refs, spec.instruction], ensure_ascii=False
            ),
        )

    def origin_key(self, spec: TaskSpec) -> str:
        value = spec.source_candidate or (
            candidate_key(spec.title) if spec.source_refs else ""
        )
        return self.digest("origin", spec.thread_id + "\0" + value) if value else ""

    def candidate_task(self, spec: TaskSpec) -> str:
        origin = self.origin_key(spec)
        row = self.connection.execute(
            "SELECT id FROM reviewed_tasks WHERE account_key=? AND (fingerprint=? OR (origin_key<>'' AND origin_key=?)) ORDER BY created DESC LIMIT 1",
            (self._account(), self.fingerprint(spec), origin),
        ).fetchone()
        return row[0] if row else ""

    def list_items(self) -> tuple[ReviewItem, ...]:
        if not self.account_key:
            return ()
        result = []
        rows = self.connection.execute(
            "SELECT * FROM reviewed_tasks WHERE account_key=? ORDER BY position, created",
            (self.account_key,),
        )
        for row in rows:
            reason = row["reason"]
            state = TaskState(row["state"])
            spec = None
            summary = {}
            if row["payload"] is not None:
                try:
                    spec = TaskSpec.from_dict(self._open(row["payload"], row["id"]))
                except (ProtectionError, ValueError, TypeError, KeyError):
                    reason, state = "decryption_failed", TaskState.NEEDS_REVIEW
            if spec is not None and reason == "source_version_upgrade":
                spec = replace(spec, source_version="")
            if row["summary_payload"] is not None:
                try:
                    summary = self._open(row["summary_payload"], row["id"] + "/summary")
                except (ProtectionError, ValueError, TypeError, KeyError):
                    reason = "decryption_failed"
            result.append(
                ReviewItem(
                    row["id"],
                    state,
                    row["revision"],
                    spec,
                    reason,
                    row["batch_id"],
                    row["position"],
                    row["attempt_id"],
                    summary,
                )
            )
        return tuple(result)

    def get(self, identity: str) -> ReviewItem | None:
        return next((i for i in self.list_items() if i.id == identity), None)

    def require(self, identity: str) -> ReviewItem:
        item = self.get(identity)
        if item is None:
            raise ValueError("task_missing")
        return item

    def save(
        self,
        spec: TaskSpec,
        *,
        registered: bool = False,
        identity: str = "",
        expected_revision: int = 0,
        allow_duplicate: bool = False,
    ) -> str:
        spec.validate(execution=registered)
        account = self._account()
        identity = identity or uuid.uuid4().hex
        payload = self._seal(spec.to_dict(), identity)
        fingerprint = self.fingerprint(spec)
        now = self.clock()
        with self.transaction() as con:
            row = con.execute(
                "SELECT * FROM reviewed_tasks WHERE id=? AND account_key=?",
                (identity, account),
            ).fetchone()
            if row:
                if (
                    row["revision"] != expected_revision
                    or row["state"] not in {"draft", "queued"}
                    or row["batch_id"]
                ):
                    raise ValueError("review_version_changed")
                revision, position = row["revision"] + 1, row["position"]
            else:
                if expected_revision:
                    raise ValueError("review_version_changed")
                revision = 1
                position = con.execute(
                    "SELECT COALESCE(MAX(position), 0)+1 FROM reviewed_tasks WHERE account_key=?",
                    (account,),
                ).fetchone()[0]
            duplicate = con.execute(
                "SELECT 1 FROM reviewed_tasks WHERE account_key=? AND (fingerprint=? OR (origin_key<>'' AND origin_key=?)) AND id<>? AND reason<>'dismissed_by_user'",
                (account, fingerprint, self.origin_key(spec), identity),
            ).fetchone()
            if duplicate and not allow_duplicate:
                raise ValueError("duplicate_task")
            con.execute(
                """INSERT INTO reviewed_tasks (id,account_key,project_key,fingerprint,state,revision,payload,position,created,updated)
                VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET project_key=excluded.project_key,
                fingerprint=excluded.fingerprint,state=excluded.state,revision=excluded.revision,
                payload=excluded.payload,reason='',updated=excluded.updated""",
                (
                    identity,
                    account,
                    self.digest("project", spec.project_id or spec.cwd),
                    fingerprint,
                    "queued" if registered else "draft",
                    revision,
                    payload,
                    position,
                    now,
                    now,
                ),
            )
            con.execute(
                "UPDATE reviewed_tasks SET origin_key=? WHERE id=? AND account_key=?",
                (self.origin_key(spec), identity, account),
            )
        return identity

    def remove(self, identity: str) -> None:
        item = self.require(identity)
        if (
            (
                item.state not in {TaskState.DRAFT, TaskState.QUEUED}
                and item.reason != "decryption_failed"
            )
            or item.batch_id
            or item.attempt_id
        ):
            raise ValueError("active_task_cannot_remove")
        with self.connection:
            self.connection.execute(
                "DELETE FROM reviewed_tasks WHERE id=? AND account_key=? AND state IN ('draft','queued') AND batch_id='' AND attempt_id=''",
                (identity, self._account()),
            )

    def exclude(self, spec: TaskSpec) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO task_exclusions (account_key,fingerprint,created,project_key) VALUES (?,?,?,?)",
                (
                    self._account(),
                    self.origin_key(spec) or self.fingerprint(spec),
                    self.clock(),
                    self.digest("project", spec.project_id),
                ),
            )

    def excluded(self, spec: TaskSpec) -> bool:
        return bool(
            self.connection.execute(
                "SELECT 1 FROM task_exclusions WHERE account_key=? AND fingerprint IN (?,?)",
                (self._account(), self.fingerprint(spec), self.origin_key(spec)),
            ).fetchone()
        )

    def reset_exclusions(self, project: str | None = None) -> None:
        with self.connection:
            self.connection.execute(
                "DELETE FROM task_exclusions WHERE account_key=? AND (? IS NULL OR project_key=?)",
                (self._account(), project, self.digest("project", project or "")),
            )

    def preferences(self) -> dict:
        identity = "preferences/" + self._account()
        row = self.connection.execute(
            "SELECT payload FROM task_secrets WHERE name=?", (identity,)
        ).fetchone()
        return self._open(row[0], identity) if row else {}

    def save_preferences(self, value: dict) -> None:
        identity = "preferences/" + self._account()
        sealed = self._seal(value, identity)
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO task_secrets VALUES (?,?)", (identity, sealed)
            )

    def create_batch(self, identities: list[str]) -> str:
        if not identities or len(set(identities)) != len(identities):
            raise ValueError("batch_selection_required")
        batch = uuid.uuid4().hex
        with self.transaction() as con:
            for position, identity in enumerate(identities):
                row = con.execute(
                    "SELECT state,batch_id FROM reviewed_tasks WHERE id=? AND account_key=?",
                    (identity, self._account()),
                ).fetchone()
                if row is None or row["state"] != "queued" or row["batch_id"]:
                    raise ValueError("batch_selection_changed")
                con.execute(
                    "UPDATE reviewed_tasks SET batch_id=?,position=? WHERE id=?",
                    (batch, position, identity),
                )
        return batch

    def reserve(
        self,
        identity: str,
        revision: int,
        lock_keys: tuple[str, ...],
        *,
        limit: int = 2,
        context: dict | None = None,
    ) -> str:
        if not lock_keys:
            raise ValueError("execution_lock_required")
        attempt = uuid.uuid4().hex
        spec = self.require(identity).spec
        if spec is None:
            raise ProtectionError("protected_data_unavailable")
        spec.validate(execution=True)
        receipt = self._seal(
            {
                "turn_id": "",
                "thread_id": spec.thread_id,
                "execution_context": context or {},
            },
            attempt,
        )
        with self.transaction() as con:
            active = con.execute(
                "SELECT COUNT(*) FROM task_attempts WHERE state IN ('starting','running','reconciling','needs_review')"
            ).fetchone()[0]
            if active >= max(1, min(4, limit)):
                raise ValueError("parallel_limit")
            row = con.execute(
                "SELECT * FROM reviewed_tasks WHERE id=? AND account_key=?",
                (identity, self._account()),
            ).fetchone()
            if (
                row is None
                or row["state"] != "queued"
                or row["revision"] != revision
                or not row["batch_id"]
            ):
                raise ValueError("execution_review_changed")
            if con.execute(
                "SELECT 1 FROM task_attempts WHERE project_key=? AND state IN ('starting','running','reconciling','needs_review')",
                (row["project_key"],),
            ).fetchone():
                raise ValueError("project_busy")
            now = self.clock()
            con.execute(
                "INSERT INTO task_attempts VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    attempt,
                    identity,
                    self.account_key,
                    row["project_key"],
                    revision,
                    receipt,
                    "starting",
                    now,
                    now,
                ),
            )
            try:
                for key in lock_keys:
                    con.execute(
                        "INSERT INTO task_locks VALUES (?,?)",
                        (self.digest("lock", key), attempt),
                    )
            except sqlite3.IntegrityError:
                raise ValueError("repository_busy") from None
            con.execute(
                "UPDATE reviewed_tasks SET state='starting',attempt_id=?,updated=? WHERE id=?",
                (attempt, now, identity),
            )
        return attempt

    def receipt(self, attempt: str) -> dict:
        row = self.connection.execute(
            "SELECT payload FROM task_attempts WHERE id=? AND account_key=?",
            (attempt, self._account()),
        ).fetchone()
        if row is None:
            raise ValueError("attempt_missing")
        return self._open(row[0], attempt)

    def update_attempt(
        self,
        attempt: str,
        state: TaskState,
        *,
        turn_id: str = "",
        reason: str = "",
        terminal_verified: bool = False,
    ) -> None:
        if state not in {
            TaskState.RUNNING,
            TaskState.RECONCILING,
            TaskState.NEEDS_REVIEW,
            TaskState.FAILED,
            TaskState.STOPPED,
            TaskState.COMPLETE,
        }:
            raise ValueError("invalid_attempt_state")
        terminal = state in {TaskState.FAILED, TaskState.STOPPED, TaskState.COMPLETE}
        if terminal and not terminal_verified:
            raise ValueError("terminal_evidence_required")
        receipt = self.receipt(attempt)
        if turn_id:
            if receipt["turn_id"] and receipt["turn_id"] != turn_id:
                raise ValueError("turn_identity_changed")
            receipt["turn_id"] = turn_id
        sealed = self._seal(receipt, attempt)
        with self.transaction() as con:
            row = con.execute(
                "SELECT state,task_id FROM task_attempts WHERE id=? AND account_key=?",
                (attempt, self._account()),
            ).fetchone()
            if row is None or row["state"] not in ACTIVE_STATES:
                raise ValueError("attempt_already_terminal")
            now = self.clock()
            con.execute(
                "UPDATE task_attempts SET state=?,payload=?,updated=? WHERE id=?",
                (state.value, sealed, now, attempt),
            )
            con.execute(
                "UPDATE reviewed_tasks SET state=?,reason=?,updated=? WHERE id=? AND attempt_id=?",
                (state.value, reason, now, row["task_id"], attempt),
            )
            if terminal:
                con.execute("DELETE FROM task_locks WHERE attempt_id=?", (attempt,))
            if state == TaskState.COMPLETE:
                task = self.require(row["task_id"])
                spec = task.spec
                if spec:
                    summary = {
                        "title": spec.title,
                        "thread_id": spec.thread_id,
                        "project_id": spec.project_id,
                        "completed_at": now,
                        "verdict": "등록한 완료 조건 충족",
                        "checks": [
                            {"description": c.description, "kind": c.kind.value}
                            for c in spec.checks
                        ],
                    }
                    con.execute(
                        "UPDATE reviewed_tasks SET summary_payload=? WHERE id=?",
                        (self._seal(summary, task.id + "/summary"), task.id),
                    )
                con.execute(
                    "UPDATE reviewed_tasks SET payload=NULL WHERE id=?",
                    (row["task_id"],),
                )

    def mark_interrupted(self) -> None:
        with self.transaction() as con:
            con.execute(
                "UPDATE reviewed_tasks SET state='reconciling',reason='restart_reconciliation' WHERE account_key=? AND state IN ('starting','running')",
                (self._account(),),
            )
            con.execute(
                "UPDATE task_attempts SET state='reconciling' WHERE account_key=? AND state IN ('starting','running')",
                (self.account_key,),
            )

    def release_unstarted_batch(self, batch: str) -> None:
        """Only withdraw unsent items; uncertain attempts retain their locks."""
        with self.transaction() as con:
            con.execute(
                "UPDATE reviewed_tasks SET batch_id='',updated=? WHERE account_key=? AND batch_id=? AND state='queued' AND attempt_id=''",
                (self.clock(), self._account(), batch),
            )

    def retry_to_draft(self, identity: str) -> str:
        item = self.require(identity)
        if item.state not in {TaskState.FAILED, TaskState.STOPPED} or item.spec is None:
            raise ValueError("terminal_evidence_required")
        # A retry has no execution authority and must acquire a fresh source version.
        draft = self.save(replace(item.spec, source_version=""), allow_duplicate=True)
        self.dismiss_terminal(identity)
        return draft

    def dismiss_terminal(self, identity: str) -> None:
        item = self.require(identity)
        if item.state not in {TaskState.FAILED, TaskState.STOPPED}:
            raise ValueError("terminal_evidence_required")
        with self.transaction() as con:
            locked = con.execute(
                "SELECT 1 FROM task_locks WHERE attempt_id=?", (item.attempt_id,)
            ).fetchone()
            if locked:
                raise ValueError("execution_response_unknown")
            con.execute(
                "UPDATE reviewed_tasks SET payload=NULL,reason='dismissed_by_user',updated=? WHERE account_key=? AND id=?",
                (self.clock(), self._account(), identity),
            )

    def reorder(self, identities: list[str]) -> None:
        if not identities or len(set(identities)) != len(identities):
            raise ValueError("batch_selection_required")
        with self.transaction() as con:
            for position, identity in enumerate(identities):
                row = con.execute(
                    "SELECT state,batch_id FROM reviewed_tasks WHERE account_key=? AND id=?",
                    (self._account(), identity),
                ).fetchone()
                if row is None or row["state"] != "queued" or row["batch_id"]:
                    raise ValueError("batch_selection_changed")
                con.execute(
                    "UPDATE reviewed_tasks SET position=? WHERE id=?",
                    (position, identity),
                )

    def prune(self, *, days: int = 30, retained: int = 500) -> int:
        """Expire only completed history and its encrypted receipts, never live work."""
        with self.transaction() as con:
            rows = con.execute(
                "SELECT id,updated FROM reviewed_tasks WHERE account_key=? AND state='complete' ORDER BY updated DESC",
                (self._account(),),
            ).fetchall()
            expired = [
                r["id"]
                for index, r in enumerate(rows)
                if index >= retained or r["updated"] < self.clock() - days * 86400
            ]
            for identity in expired:
                con.execute("DELETE FROM task_attempts WHERE task_id=?", (identity,))
                con.execute("DELETE FROM reviewed_tasks WHERE id=?", (identity,))
            con.execute(
                "DELETE FROM task_exclusions WHERE account_key=? AND created<?",
                (self.account_key, self.clock() - days * 86400),
            )
        return len(expired)
