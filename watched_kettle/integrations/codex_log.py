"""Read-only fallback for privacy-safe Codex session activity metadata."""

from __future__ import annotations
from watched_kettle.integrations.log_tail import TailCursor
from watched_kettle.integrations.activity_recovery import RecoveryScan
from watched_kettle.integrations.usage_log_parser import UsageLogParser

from watched_kettle.integrations.log_lifecycle import (
    normalize_codex_log_record as normalize_codex_log_record,
)

import json
from collections import OrderedDict
import heapq
import re
from time import monotonic
from datetime import datetime, timedelta, timezone
from pathlib import Path

from watched_kettle.integrations.codex_paths import codex_home

from PySide6.QtCore import QObject, QTimer, Signal

from watched_kettle.integrations.codex_hooks import sanitize_pet_event
from watched_kettle.state.agent_scope import scope_from_session_source


DEFAULT_CODEX_SESSIONS_ROOT = codex_home() / "sessions"
DEFAULT_CODEX_ARCHIVED_ROOT = codex_home() / "archived_sessions"
DEFAULT_POLL_INTERVAL_MS = 250
USAGE_POLL_SECONDS = 0.750
MAX_LOG_LINE_BYTES = 4 * 1024 * 1024
MAX_TRACKED_FILES = 128
REPLAY_GRACE_SECONDS = 5
HEARTBEAT_INTERVAL_SECONDS = 10
_ROLLOUT_ID = re.compile(
    r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$"
)


def _recorded_at(record):
    value = record.get("timestamp") if isinstance(record, dict) else None
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _confirms_turn_activity(record):
    payload = record.get("payload") if isinstance(record, dict) else None
    if not isinstance(payload, dict):
        return False
    record_type = record.get("type")
    payload_type = payload.get("type")
    return (
        record_type == "response_item"
        and payload_type
        in {
            "reasoning",
            "message",
            "function_call",
            "custom_tool_call",
            "function_call_output",
            "custom_tool_call_output",
        }
    ) or (record_type == "event_msg" and payload_type == "item_completed")


def _is_activity_record(record):
    payload = record.get("payload") if isinstance(record, dict) else None
    if not isinstance(payload, dict):
        return False
    record_type = record.get("type")
    payload_type = payload.get("type")
    if record_type == "event_msg":
        return payload_type in {
            "task_started",
            "task_complete",
            "turn_aborted",
            "context_compacted",
        }
    if record_type == "response_item":
        return payload_type in {
            "compaction",
            "function_call",
            "custom_tool_call",
            "function_call_output",
            "custom_tool_call_output",
        }
    return False


def rollout_session_id(path):
    """Derive the opaque session id from a rollout filename."""
    stem = Path(path).stem
    match = _ROLLOUT_ID.search(stem)
    return match.group(1) if match else stem[-160:]


class CodexLogMonitor(QObject):
    """Tail new Codex rollout records and emit only allowlisted pet events."""

    payload_detected = Signal(dict)
    usage_detected = Signal(object)
    recovery_detected = Signal(object)

    def __init__(
        self,
        sessions_root=DEFAULT_CODEX_SESSIONS_ROOT,
        poll_interval_ms=DEFAULT_POLL_INTERVAL_MS,
        parent=None,
        now=None,
        archived_root=None,
    ):
        super().__init__(parent)
        self.sessions_root = Path(sessions_root)
        self.archived_root = Path(
            archived_root
            if archived_root is not None
            else self.sessions_root.parent / "archived_sessions"
        )
        self.poll_interval_ms = int(poll_interval_ms)
        self._now = now or (lambda: datetime.now().astimezone())
        self._positions = {}
        self._usage_positions = {}
        self._usage_file_ids = {}
        self.usage_parser = UsageLogParser(self._now, rollout_session_id, _recorded_at)
        self._usage_metadata = self.usage_parser._usage_metadata
        self._usage_totals = self.usage_parser._usage_totals
        self._usage_cursors = {}
        self._event_cursors = {}
        self._usage_round_robin = 0
        self._session_ids = {}
        self._agent_scopes = {}
        self._metadata_seen = set()
        self._history_starts = {}
        self._next_ordinals = {}
        self._startup_offsets = {}
        self._pending_user_calls = {}
        self._pending_async_questions = {}
        self._partial_lines = {}
        self._discarding = set()
        self._file_ids = {}
        self._active_turns = {}
        self._tool_turns = OrderedDict()
        self._last_heartbeats = {}
        self._replay_cutoff = None
        self._round_robin = 0
        self.budget_yields = 0
        self.replay_suppressed_count = 0
        self.usage_event_count = 0
        self.usage_regression_count = 0
        self._discovery = None
        self._recovery = OrderedDict()
        self._recovery_confirmed = set()
        self._last_usage_poll = float("-inf")
        self._started_at = 0.0
        self.event_count = 0
        self.last_event = ""
        self.last_detected_at = None
        self.last_error = ""

        self.timer = QTimer(self)
        self.timer.setInterval(self.poll_interval_ms)
        self.timer.timeout.connect(self.poll_now)

    @property
    def is_active(self):
        return self.timer.isActive()

    @property
    def tracked_file_count(self):
        return len(self._positions)

    def start(self):
        if self.timer.isActive():
            return
        current = self._now()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        self._replay_cutoff = current.astimezone(timezone.utc) - timedelta(
            seconds=REPLAY_GRACE_SECONDS
        )
        self._register_existing_files()
        self.timer.start()

    def close(self):
        self.timer.stop()
        self._discovery = None
        self._recovery.clear()
        self._recovery_confirmed.clear()
        self._last_usage_poll = float("-inf")
        self._positions.clear()
        self._usage_cursors.clear()
        self._event_cursors.clear()
        self._usage_positions.clear()
        self._usage_file_ids.clear()
        self._usage_metadata.clear()
        self._usage_totals.clear()
        self._session_ids.clear()
        self._agent_scopes.clear()
        self._metadata_seen.clear()
        self._history_starts.clear()
        self._next_ordinals.clear()
        self._startup_offsets.clear()
        self._pending_user_calls.clear()
        self._pending_async_questions.clear()
        self._partial_lines.clear()
        self._discarding.clear()
        self._file_ids.clear()
        self._active_turns.clear()
        self._tool_turns.clear()
        self._last_heartbeats.clear()
        self._replay_cutoff = None

    def clear_pending_questions(self):
        for questions in self._pending_async_questions.values():
            questions.clear()

    def poll_now(self):
        try:
            self._discover_recent_files()
            paths = tuple(self._positions)
            if paths:
                offset = self._round_robin % len(paths)
                paths = paths[offset:] + paths[:offset]
            self._budget_bytes = 1024 * 1024
            self._budget_records = 200
            self._deadline = monotonic() + 0.020
            for path in paths:
                self._read_new_records(path)
                self._round_robin += 1
                if (
                    self._budget_bytes <= 0
                    or self._budget_records <= 0
                    or monotonic() >= self._deadline
                ):
                    self.budget_yields += 1
                    break
            self._poll_recovery()
            self._poll_usage()
            self.last_error = ""
        except OSError as error:
            self.last_error = type(error).__name__

    def _poll_usage(self):
        usage_batch = []
        usage_paths = ()
        if monotonic() - self._last_usage_poll >= USAGE_POLL_SECONDS:
            self._last_usage_poll = monotonic()
            usage_paths = tuple(self._usage_positions)
        if usage_paths:
            start = self._usage_round_robin % len(usage_paths)
            usage_paths = usage_paths[start:] + usage_paths[:start]
        # Independent bounded flows: neither history nor lifecycle can
        # monopolize the worker. These are yielding budgets, not I/O deadlines.
        usage_deadline = monotonic() + 0.020
        usage_bytes = 1024 * 1024
        usage_records = 200
        for path in usage_paths:
            found, consumed_bytes, consumed_records = self._read_usage_records(
                path, usage_bytes, usage_records, usage_deadline
            )
            usage_batch.extend(found)
            usage_bytes -= consumed_bytes
            usage_records -= consumed_records
            self._usage_round_robin += 1
            if usage_bytes <= 0 or usage_records <= 0 or monotonic() >= usage_deadline:
                break
        if usage_batch:
            self.usage_event_count += len(usage_batch)
            self.usage_detected.emit(tuple(usage_batch))

    def _poll_recovery(self):
        deadline, remaining, records = monotonic() + 0.020, 1024 * 1024, 2000
        for path, scan in tuple(self._recovery.items()):
            if remaining <= 0 or records <= 0 or monotonic() >= deadline:
                break
            try:
                stat = path.stat()
                if (
                    stat.st_dev,
                    stat.st_ino,
                ) != scan.identity or stat.st_size < scan.end:
                    self._recovery.pop(path, None)
                    self._recovery_confirmed.discard(path)
                    continue
                lines, used_bytes, used_records = scan.cursor.read(
                    path,
                    remaining,
                    records,
                    deadline,
                    MAX_LOG_LINE_BYTES,
                    end_offset=scan.end,
                )
                remaining -= used_bytes
                records -= used_records
                for (_, line), ordinal in zip(lines, scan.cursor.line_ordinals):
                    try:
                        scan.consume(json.loads(line), ordinal)
                    except (UnicodeError, ValueError):
                        continue
                if scan.cursor.offset < scan.end:
                    continue
                self._recovery.pop(path, None)
                confirmed = path in self._recovery_confirmed
                self._recovery_confirmed.discard(path)
                snapshot = scan.snapshot(self._started_at, self._now().timestamp())
                if snapshot is not None:
                    self._active_turns[path] = snapshot.turn_id
                    for call in snapshot.active_tools:
                        self._tool_turns[(path, call)] = snapshot.turn_id
                        while len(self._tool_turns) > 4096:
                            self._tool_turns.popitem(last=False)
                    self._last_heartbeats.pop(path, None)
                    self.recovery_detected.emit(snapshot)
                    if confirmed:
                        self._emit_heartbeat(path)
            except OSError:
                self._recovery.pop(path, None)
                self._recovery_confirmed.discard(path)

    def diagnostics(self):
        return {
            "active": self.is_active,
            "sessions_root_exists": self.sessions_root.is_dir(),
            "tracked_files": self.tracked_file_count,
            "event_count": self.event_count,
            "last_event": self.last_event,
            "last_detected_at": self.last_detected_at,
            "last_error": self.last_error,
            "budget_yields": self.budget_yields,
            "replay_suppressed_count": self.replay_suppressed_count,
            "usage_event_count": self.usage_event_count,
            "usage_regression_count": self.usage_regression_count,
        }

    def _register_existing_files(self):
        self._started_at = self._now().timestamp()
        roots = tuple(root for root in self._usage_roots() if root.is_dir())
        if not roots:
            return
        paths = heapq.nlargest(
            MAX_TRACKED_FILES,
            (path for root in roots for path in root.rglob("rollout-*.jsonl")),
            key=self._safe_mtime,
        )
        for path in paths:
            try:
                stat = path.stat()
                self._positions[path] = stat.st_size
                self._usage_positions[path] = 0
                self._session_ids[path] = rollout_session_id(path)
                self._pending_user_calls[path] = set()
                self._pending_async_questions[path] = {}
                self._read_session_metadata(path)
                if stat.st_mtime >= self._started_at - 600:
                    self._recovery[path] = RecoveryScan(
                        stat.st_size, (stat.st_dev, stat.st_ino)
                    )
                self._event_cursors[path] = TailCursor(
                    offset=self._positions[path], identity=(stat.st_dev, stat.st_ino)
                )
            except OSError:
                continue

    def _discover_recent_files(self):
        if self._discovery is None:
            self._discovery = iter(
                path
                for directory in self._recent_directories()
                for path in directory.glob("rollout-*.jsonl")
            )
        deadline = monotonic() + 0.010
        for _ in range(128):
            if monotonic() >= deadline:
                break
            path = next(self._discovery, None)
            if path is None:
                self._discovery = None
                break
            if path in self._positions:
                continue
            self._positions[path] = 0
            self._usage_positions[path] = 0
            self._session_ids[path] = rollout_session_id(path)
            self._pending_user_calls[path] = set()
            self._pending_async_questions[path] = {}

        if len(self._positions) <= MAX_TRACKED_FILES:
            return
        ordered = sorted(
            self._positions,
            key=self._safe_mtime,
            reverse=True,
        )
        for path in ordered[MAX_TRACKED_FILES:]:
            self._forget(path)

    def session_scope(self, session_id):
        """Share known rollout identity with the hook receiver."""
        for path, known_id in self._session_ids.items():
            if known_id == session_id:
                return self._agent_scopes.get(path, "unknown")
        return "unknown"

    def _read_session_metadata(self, path):
        # Existing files are tailed from EOF, but their first record identifies
        # background agents. Read that one bounded record without replaying it.
        with path.open("rb") as stream:
            line = stream.readline(MAX_LOG_LINE_BYTES + 1)
        if len(line) > MAX_LOG_LINE_BYTES:
            return
        if not line.endswith(b"\n"):
            # The first metadata record may still be in the process of writing.
            self._positions[path] = 0
            return
        try:
            record = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        self._remember_session_metadata(path, record)
        if self._history_starts.get(path, 0):
            # Count inherited ordinals incrementally, even if startup caught a
            # fork while its copied prefix was still being written. Suppress
            # all records already present at startup without replaying a turn.
            self._startup_offsets[path] = self._positions[path]
            self._positions[path] = 0

    def _remember_session_metadata(self, path, record):
        if not isinstance(record, dict) or record.get("type") != "session_meta":
            return False
        if path in self._metadata_seen:
            return True
        # A fork can contain a second session_meta copied from the parent.
        # Only the first header owns the file, including an unknown header.
        self._metadata_seen.add(path)
        payload = record.get("payload")
        if not isinstance(payload, dict):
            self._agent_scopes[path] = "unknown"
            return True
        session_id = payload.get("id") or payload.get("session_id")
        if isinstance(session_id, str) and session_id.strip():
            self._session_ids[path] = session_id[:160]
            self._agent_scopes[path] = scope_from_session_source(payload.get("source"))
        else:
            self._agent_scopes[path] = "unknown"
        boundary = payload.get("subagent_history_start_ordinal")
        if (
            isinstance(boundary, int)
            and not isinstance(boundary, bool)
            and boundary >= 0
        ):
            self._history_starts[path] = boundary
        return True

    def _recent_directories(self):
        current = self._now()
        for day in (current, current - timedelta(days=1)):
            yield (
                self.sessions_root
                / f"{day.year:04d}"
                / f"{day.month:02d}"
                / f"{day.day:02d}"
            )
        yield self.sessions_root
        yield self.archived_root

    def _usage_roots(self):
        yield self.sessions_root
        if self.archived_root != self.sessions_root:
            yield self.archived_root

    @staticmethod
    def _safe_nonnegative_number(value, cast=int):
        if value is None or isinstance(value, bool):
            return None
        try:
            parsed = cast(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return parsed if parsed >= 0 else None

    def _read_usage_records(self, path, byte_budget, record_budget, deadline):
        cursor = self._usage_cursors.setdefault(
            path, TailCursor(offset=self._usage_positions.get(path, 0))
        )
        found = []
        lines, consumed_bytes, consumed_records = cursor.read(
            path,
            byte_budget,
            record_budget,
            deadline,
            MAX_LOG_LINE_BYTES,
            clock=monotonic,
        )
        if cursor.replaced:
            self._usage_metadata.pop(path, None)
        for line_offset, line in lines:
            try:
                record = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            found.extend(self._extract_usage_records(path, record, line_offset))
        self._usage_positions[path] = cursor.offset
        return found, consumed_bytes, consumed_records

    def _extract_usage_records(self, path, record, line_offset):
        result = self.usage_parser.extract(path, record, line_offset)
        self.usage_regression_count = self.usage_parser.usage_regression_count
        return result

    def _read_new_records(self, path):
        cursor = self._event_cursors.setdefault(
            path, TailCursor(offset=self._positions[path])
        )
        stat = path.stat()
        if stat.st_size == cursor.offset and cursor.identity == (
            stat.st_dev,
            stat.st_ino,
        ):
            return
        lines, used_bytes, used_records = cursor.read(
            path,
            self._budget_bytes,
            self._budget_records,
            self._deadline,
            MAX_LOG_LINE_BYTES,
            clock=monotonic,
        )
        self._budget_bytes -= used_bytes
        self._budget_records -= used_records
        if cursor.replaced:
            self._clear_lifecycle(path)
            self._session_ids[path] = rollout_session_id(path)
        for (offset, line), ordinal in zip(lines, cursor.line_ordinals):
            startup_offset = self._startup_offsets.get(path, 0)
            self._process_line(path, line, ordinal, replay=offset < startup_offset)
            if offset >= startup_offset:
                self._startup_offsets.pop(path, None)
        self._positions[path] = cursor.offset

    def _process_line(self, path, line, ordinal=None, replay=False):
        if ordinal is None:
            ordinal = self._next_ordinals.get(path, 0)
        self._next_ordinals[path] = ordinal + 1
        try:
            record = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return

        if self._remember_session_metadata(path, record):
            return
        # Ordinals are zero-based, including the owning header. Copied records
        # may have fresh timestamps; discard them before any turn/tool mutation.
        if replay or ordinal < self._history_starts.get(path, 0):
            if _is_activity_record(record):
                self.replay_suppressed_count += 1
            return
        if not isinstance(record, dict):
            return

        recorded_at = _recorded_at(record)
        if (
            recorded_at is not None
            and self._replay_cutoff is not None
            and recorded_at <= self._replay_cutoff
        ):
            if _is_activity_record(record):
                self.replay_suppressed_count += 1
            return

        payload = record.get("payload")
        record_type = record.get("type")
        payload_type = payload.get("type") if isinstance(payload, dict) else None
        if record_type == "event_msg" and payload_type == "task_started":
            turn_id = str(payload.get("turn_id") or "")
            if turn_id:
                if (
                    recorded_at is not None
                    and recorded_at.timestamp() < self._started_at
                ):
                    return
                self._recovery.pop(path, None)
                self._recovery_confirmed.discard(path)
                self._pending_async_questions.setdefault(path, {}).clear()
                self._active_turns[path] = turn_id[:160]
                self._last_heartbeats.pop(path, None)
                self._emit(
                    {
                        "source": "codex",
                        "event": "prompt",
                        "session_id": self._session_ids.get(
                            path, rollout_session_id(path)
                        ),
                        "turn_id": turn_id[:160],
                        "agent_scope": self._agent_scopes.get(path, "unknown"),
                        "collected_at": recorded_at.timestamp()
                        if recorded_at
                        else self._now().timestamp(),
                    }
                )
                self._last_heartbeats[path] = self._now().timestamp()
            return

        if _confirms_turn_activity(record):
            if path in self._recovery:
                self._recovery_confirmed.add(path)
            self._emit_heartbeat(path)

        event = normalize_codex_log_record(
            record,
            self._session_ids.get(path, rollout_session_id(path)),
            self._pending_user_calls.setdefault(path, set()),
            self._agent_scopes.get(path, "unknown"),
            self._pending_async_questions.setdefault(path, {}),
            self._active_turns.get(path, ""),
        )
        if event is None:
            return
        if event["event"] in {
            "prompt",
            "tool_start",
            "waiting",
            "question_wait",
            "done",
            "cancelled",
            "failed",
        }:
            self._recovery.pop(path, None)
            self._recovery_confirmed.discard(path)
        call_id = event.get("event_id")
        if event["event"] in {"tool_start", "waiting", "question_wait"} and call_id:
            turn = event.get("turn_id") or self._active_turns.get(path)
            if turn:
                event["turn_id"] = turn
                self._tool_turns[(path, call_id)] = turn
                while len(self._tool_turns) > 4096:
                    self._tool_turns.popitem(last=False)
        elif (
            event["event"] in {"tool_end", "tool_failed", "question_resolved"}
            and call_id
        ):
            turn = self._tool_turns.pop((path, call_id), None)
            if turn and not event.get("turn_id"):
                event["turn_id"] = turn
        self._emit(event)
        if event["event"] in {"done", "cancelled", "failed"}:
            self._active_turns.pop(path, None)
            self._pending_async_questions.setdefault(path, {}).clear()
            self._last_heartbeats.pop(path, None)

    def _emit_heartbeat(self, path):
        turn_id = self._active_turns.get(path)
        if not turn_id:
            return
        current = self._now()
        current_seconds = current.timestamp()
        previous = self._last_heartbeats.get(path)
        if (
            previous is not None
            and current_seconds - previous < HEARTBEAT_INTERVAL_SECONDS
        ):
            return
        self._last_heartbeats[path] = current_seconds
        self._emit(
            {
                "source": "codex",
                "event": "heartbeat",
                "session_id": self._session_ids.get(path, rollout_session_id(path)),
                "turn_id": turn_id,
                "agent_scope": self._agent_scopes.get(path, "unknown"),
            }
        )

    def _emit(self, event):
        event = sanitize_pet_event(event)
        if event is None:
            return
        self.event_count += 1
        self.last_event = event["event"]
        self.last_detected_at = self._now()
        self.payload_detected.emit(event)

    @staticmethod
    def _discard_line_remainder(stream):
        while True:
            chunk = stream.readline(MAX_LOG_LINE_BYTES + 1)
            if not chunk or chunk.endswith(b"\n"):
                return

    @staticmethod
    def _safe_mtime(path):
        try:
            return path.stat().st_mtime_ns
        except OSError:
            return 0

    def _clear_lifecycle(self, path):
        self._recovery.pop(path, None)
        self._recovery_confirmed.discard(path)
        for key in tuple(self._tool_turns):
            if key[0] == path:
                del self._tool_turns[key]
        self._metadata_seen.discard(path)
        self._history_starts.pop(path, None)
        self._next_ordinals.pop(path, None)
        self._startup_offsets.pop(path, None)
        self._session_ids.pop(path, None)
        self._agent_scopes.pop(path, None)
        self._pending_user_calls.pop(path, None)
        self._pending_async_questions.pop(path, None)
        self._active_turns.pop(path, None)
        self._last_heartbeats.pop(path, None)

    def _forget(self, path):
        self._clear_lifecycle(path)
        self._usage_cursors.pop(path, None)
        self._event_cursors.pop(path, None)
        self._partial_lines.pop(path, None)
        self._discarding.discard(path)
        self._file_ids.pop(path, None)
        self._positions.pop(path, None)
        self._usage_positions.pop(path, None)
        self._usage_file_ids.pop(path, None)
        metadata = self._usage_metadata.pop(path, None)
        if metadata and not any(
            m["owner_id"] == metadata["owner_id"] for m in self._usage_metadata.values()
        ):
            self._usage_totals.pop(metadata["owner_id"], None)
