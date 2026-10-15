"""SQLite records of Claude Code turns and rate-limit samples (stage 13).

Turns are device-level observations read from local transcripts, so they are
not keyed by an account. Each transcript file stores its own share of a turn
(``part``); a subagent file adds tokens to its parent turn. Only hashes,
timestamps, outcome, model and token counts are stored. Titles and folder names
stay in the service's memory.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import sqlite3


def migrate_claude_code_storage(connection: sqlite3.Connection) -> None:
    for statement in (
        """CREATE TABLE claude_code_turn_parts (
            file_hash TEXT NOT NULL,
            session_hash TEXT NOT NULL,
            turn_hash TEXT NOT NULL,
            part TEXT NOT NULL,
            project_hash TEXT NOT NULL DEFAULT '',
            started_at_utc TEXT NOT NULL,
            completed_at_utc TEXT NOT NULL,
            outcome TEXT NOT NULL DEFAULT '',
            input_tokens INTEGER NOT NULL DEFAULT 0,
            net_new_input_tokens INTEGER NOT NULL DEFAULT 0,
            cached_input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            total_tokens INTEGER NOT NULL DEFAULT 0,
            model TEXT,
            PRIMARY KEY (file_hash, turn_hash)
        )""",
        """CREATE INDEX idx_claude_code_turn
            ON claude_code_turn_parts(session_hash, turn_hash)""",
        """CREATE INDEX idx_claude_code_completed
            ON claude_code_turn_parts(completed_at_utc DESC)""",
        """CREATE TABLE claude_code_files (
            file_hash TEXT PRIMARY KEY,
            size INTEGER NOT NULL,
            mtime_ns INTEGER NOT NULL,
            resume_offset INTEGER NOT NULL,
            open_turn INTEGER NOT NULL DEFAULT 0
        )""",
        """CREATE TABLE claude_code_state (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            cleared_before_utc TEXT NOT NULL
        )""",
        """CREATE TABLE claude_code_quota_samples (
            account_hash TEXT NOT NULL,
            window TEXT NOT NULL,
            observed_at_utc TEXT NOT NULL,
            used_percent REAL NOT NULL,
            resets_at_utc TEXT,
            PRIMARY KEY (account_hash, window, observed_at_utc)
        )""",
    ):
        connection.execute(statement)


@dataclass(frozen=True)
class FileState:
    size: int
    mtime_ns: int
    resume_offset: int
    open_turn: bool


@dataclass(frozen=True)
class ClaudeCodeTurnRow:
    session_hash: str
    turn_hash: str
    project_hash: str
    started_at: datetime
    completed_at: datetime
    outcome: str
    input_tokens: int
    net_new_input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    total_tokens: int
    model: str | None


_TURNS = """
    SELECT session_hash, turn_hash,
        MAX(CASE WHEN part = 'main' THEN project_hash END) AS project_hash,
        MIN(started_at_utc) AS started_at_utc,
        MAX(completed_at_utc) AS completed_at_utc,
        MAX(CASE WHEN part = 'main' THEN outcome END) AS outcome,
        SUM(input_tokens) AS input_tokens,
        SUM(net_new_input_tokens) AS net_new_input_tokens,
        SUM(cached_input_tokens) AS cached_input_tokens,
        SUM(output_tokens) AS output_tokens,
        SUM(total_tokens) AS total_tokens,
        MAX(CASE WHEN part = 'main' THEN model END) AS model
    FROM claude_code_turn_parts
    {where}
    GROUP BY session_hash, turn_hash
    HAVING MAX(part = 'main') = 1
"""


class ClaudeCodeRepository:
    def __init__(self, database, retention_days=90):
        self.database = database
        self.retention_days = int(retention_days)

    @property
    def connection(self):
        return self.database.require_connection()

    @property
    def cutoff(self):
        return datetime.now(timezone.utc) - timedelta(days=self.retention_days)

    def file_state(self, file_hash):
        row = self.connection.execute(
            "SELECT size, mtime_ns, resume_offset, open_turn FROM claude_code_files WHERE file_hash = ?",
            (file_hash,),
        ).fetchone()
        return FileState(row[0], row[1], row[2], bool(row[3])) if row else None

    def cleared_before(self):
        row = self.connection.execute(
            "SELECT cleared_before_utc FROM claude_code_state WHERE id = 1"
        ).fetchone()
        return datetime.fromisoformat(row[0]) if row else None

    def save_pass(self, file_hash, parts, state, rewritten=False):
        """Replace this file's share of the parsed turns in one transaction."""
        floor = max(filter(None, (self.cutoff, self.cleared_before())))
        with self.connection:
            if rewritten:
                self.connection.execute(
                    "DELETE FROM claude_code_turn_parts WHERE file_hash = ?",
                    (file_hash,),
                )
            for part in parts:
                if part.started_at is None or part.completed_at is None:
                    continue
                if part.completed_at < floor:
                    continue
                self.connection.execute(
                    """INSERT OR REPLACE INTO claude_code_turn_parts(
                        file_hash, session_hash, turn_hash, part, project_hash,
                        started_at_utc, completed_at_utc, outcome, input_tokens,
                        net_new_input_tokens, cached_input_tokens, output_tokens,
                        total_tokens, model
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        file_hash,
                        part.session_hash,
                        part.turn_hash,
                        part.part,
                        part.project_hash,
                        _utc(part.started_at),
                        _utc(part.completed_at),
                        part.outcome,
                        part.input_tokens,
                        part.input_tokens - part.tokens["cache_read_input_tokens"],
                        part.tokens["cache_read_input_tokens"],
                        part.tokens["output_tokens"],
                        part.total_tokens,
                        part.model,
                    ),
                )
            self.connection.execute(
                """INSERT OR REPLACE INTO claude_code_files(
                    file_hash, size, mtime_ns, resume_offset, open_turn
                ) VALUES (?, ?, ?, ?, ?)""",
                (
                    file_hash,
                    state.size,
                    state.mtime_ns,
                    state.resume_offset,
                    int(state.open_turn),
                ),
            )

    def turns(self, session_hash=None, project_hash=None, since=None):
        clauses, values = ["completed_at_utc >= ?"], [_utc(since or self.cutoff)]
        if session_hash is not None:
            clauses.append("session_hash = ?")
            values.append(session_hash)
        query = _TURNS.format(where="WHERE " + " AND ".join(clauses))
        if project_hash is not None:
            query = f"SELECT * FROM ({query}) WHERE project_hash = ?"
            values.append(project_hash)
        rows = self.connection.execute(
            query + " ORDER BY completed_at_utc DESC", values
        ).fetchall()
        return tuple(_turn(row) for row in rows)

    def latest_turns(self, limit=20):
        rows = self.connection.execute(
            _TURNS.format(where="WHERE completed_at_utc >= ?")
            + " ORDER BY completed_at_utc DESC LIMIT ?",
            (_utc(self.cutoff), int(limit)),
        ).fetchall()
        return tuple(_turn(row) for row in rows)

    def clear(self, cleared_at=None):
        cleared_at = cleared_at or datetime.now(timezone.utc)
        with self.connection:
            self.connection.execute("DELETE FROM claude_code_turn_parts")
            self.connection.execute(
                "INSERT OR REPLACE INTO claude_code_state(id, cleared_before_utc) VALUES (1, ?)",
                (_utc(cleared_at),),
            )

    def prune(self):
        with self.connection:
            self.connection.execute(
                "DELETE FROM claude_code_turn_parts WHERE completed_at_utc < ?",
                (_utc(self.cutoff),),
            )

    def append_quota_samples(self, account_hash, samples):
        with self.connection:
            self.connection.executemany(
                """INSERT OR IGNORE INTO claude_code_quota_samples(
                    account_hash, window, observed_at_utc, used_percent, resets_at_utc
                ) VALUES (?, ?, ?, ?, ?)""",
                [
                    (
                        account_hash,
                        sample.window,
                        _utc(sample.observed_at),
                        float(sample.used_percent),
                        _utc(sample.resets_at) if sample.resets_at else None,
                    )
                    for sample in samples
                ],
            )
            self.connection.execute(
                "DELETE FROM claude_code_quota_samples WHERE observed_at_utc < ?",
                (_utc(datetime.now(timezone.utc) - timedelta(days=8)),),
            )

    def quota_samples(self, account_hash, since):
        rows = self.connection.execute(
            """SELECT window, observed_at_utc, used_percent, resets_at_utc
            FROM claude_code_quota_samples
            WHERE account_hash = ? AND observed_at_utc >= ?
            ORDER BY observed_at_utc""",
            (account_hash, _utc(since)),
        ).fetchall()
        return tuple(
            (
                window,
                datetime.fromisoformat(observed),
                percent,
                datetime.fromisoformat(resets) if resets else None,
            )
            for window, observed, percent, resets in rows
        )


def _utc(value):
    return value.astimezone(timezone.utc).isoformat()


def _turn(row):
    return ClaudeCodeTurnRow(
        session_hash=row[0],
        turn_hash=row[1],
        project_hash=row[2] or "",
        started_at=datetime.fromisoformat(row[3]),
        completed_at=datetime.fromisoformat(row[4]),
        outcome=row[5] or "running",
        input_tokens=row[6],
        net_new_input_tokens=row[7],
        cached_input_tokens=row[8],
        output_tokens=row[9],
        total_tokens=row[10],
        model=row[11],
    )
