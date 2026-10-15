"""Detect silent Claude Code turn ends and session titles from transcripts.

Claude Code sends no hook when the user denies a permission request or
interrupts a turn. Both append a user text entry to the session transcript
without a matching ``UserPromptSubmit`` hook. This monitor watches only
sessions with an active turn and classifies newly appended lines by entry type
and content item types. The only content it reads is the session title
(``custom-title`` set by the user, else ``ai-title``), kept in memory for the
bubble and never logged or stored (stage 13).
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import time

from PySide6.QtCore import QObject, QTimer, Signal


POLL_INTERVAL_MS = 1_000
# A prompt hook and its transcript line arrive within the same second in
# either order; a user text line without a hook in this window ended the turn.
PROMPT_GRACE_SECONDS = 2.0
MAX_READ_BYTES_PER_POLL = 1024 * 1024
# Interrupt markers are tiny. Larger lines are tool results and stay unparsed.
MAX_CLASSIFIED_LINE_BYTES = 64 * 1024
MAX_LOCATE_ATTEMPTS = 30
# Titles are rewritten every turn; the newest ones sit near the end of the file.
TITLE_SCAN_BYTES = 256 * 1024
MAX_TITLE_LENGTH = 120
_TITLE_FIELDS = {"custom-title": "customTitle", "ai-title": "aiTitle"}
_SESSION_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")
_TURN_EVENTS = frozenset(
    {
        "prompt",
        "tool_start",
        "tool_end",
        "tool_failed",
        "permission",
        "waiting",
        "task_start",
    }
)
# Compaction (review) writes hookless user entries, so it never starts a watch.
_TURN_END_EVENTS = frozenset({"done", "cancelled", "failed", "session_end"})


def claude_config_dir():
    value = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    return Path(value).expanduser() if value else Path.home() / ".claude"


def locate_transcript(session_id, config_dir=None):
    """The session's transcript file, or None. Sessions live per project folder."""
    if not isinstance(session_id, str) or not _SESSION_ID.match(session_id):
        return None
    projects = Path(config_dir or claude_config_dir()) / "projects"
    try:
        return next(iter(projects.glob(f"*/{session_id}.jsonl")), None)
    except OSError:
        return None


def _parse_line(line):
    if len(line) > MAX_CLASSIFIED_LINE_BYTES:
        return None
    try:
        entry = json.loads(line)
    except (UnicodeDecodeError, ValueError):
        return None
    return entry if isinstance(entry, dict) else None


def title_from_entry(entry):
    """Return ``(kind, title)`` for a title entry, else None."""
    kind = entry.get("type") if isinstance(entry, dict) else None
    field = _TITLE_FIELDS.get(kind)
    value = entry.get(field) if field else None
    if not isinstance(value, str):
        return None
    title = " ".join(
        "".join(" " if ord(c) < 32 or 127 <= ord(c) < 160 else c for c in value).split()
    )[:MAX_TITLE_LENGTH]
    return (kind, title) if title else None


def classify_transcript_line(line):
    """Return ``"user_text"`` for a plain user text entry, else ``"other"``."""
    return _classify_entry(_parse_line(line))


def _classify_entry(entry):
    if entry is None or entry.get("type") != "user":
        return "other"
    if entry.get("isMeta") or entry.get("isSidechain") or entry.get("isCompactSummary"):
        return "other"
    # A background command's result is written as user text by Claude Code
    # itself (2.1.288) and starts a turn without a prompt hook. It is not the
    # user interrupting or denying anything.
    if entry.get("promptSource") == "system" or entry.get("turnOrigin") == (
        "task_notification"
    ):
        return "other"
    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    # The CLI stores user text as a string; the VS Code panel as text items.
    if isinstance(content, str):
        return "user_text" if content.strip() else "other"
    if (
        isinstance(content, list)
        and content
        and all(
            isinstance(item, dict) and item.get("type") == "text" for item in content
        )
    ):
        return "user_text"
    return "other"


class TranscriptTail:
    """Classify lines appended after construction, with bounded reads."""

    def __init__(self, path):
        self.path = Path(path)
        self.offset = self.path.stat().st_size
        self._pending = bytearray()
        self._skipping = False
        self.titles = {}
        self._scan_titles()

    @property
    def title(self):
        """The user's title wins over Claude Code's generated one."""
        return self.titles.get("custom-title") or self.titles.get("ai-title") or ""

    def _scan_titles(self):
        start = max(0, self.offset - TITLE_SCAN_BYTES)
        with self.path.open("rb") as stream:
            stream.seek(start)
            data = stream.read(self.offset - start)
        lines = data.split(b"\n")
        if start:
            lines = lines[1:]  # The first piece may be a partial line.
        for line in lines:
            if b"title" in line:
                self._remember_title(_parse_line(line))

    def read_kinds(self):
        size = self.path.stat().st_size
        if size < self.offset:
            self.offset = 0
            self._pending.clear()
            self._skipping = False
        if size == self.offset:
            return []
        with self.path.open("rb") as stream:
            stream.seek(self.offset)
            data = stream.read(MAX_READ_BYTES_PER_POLL)
        self.offset += len(data)
        pieces = data.split(b"\n")
        remainder = pieces.pop()
        kinds = []
        for piece in pieces:
            if self._skipping:
                self._skipping = False
                kinds.append("other")
                continue
            line = bytes(self._pending) + piece
            self._pending.clear()
            if line.strip():
                entry = _parse_line(line)
                self._remember_title(entry)
                kinds.append(_classify_entry(entry))
        if not self._skipping:
            self._pending.extend(remainder)
            if len(self._pending) > MAX_CLASSIFIED_LINE_BYTES:
                self._pending.clear()
                self._skipping = True
        return kinds

    def _remember_title(self, entry):
        found = title_from_entry(entry)
        if found is not None:
            self.titles[found[0]] = found[1]


@dataclass
class _WatchedSession:
    tail: TranscriptTail | None = None
    locate_attempts: int = 0
    last_prompt_at: float = float("-inf")
    unmatched_since: float | None = None
    title: str = ""


class ClaudeCodeTranscriptMonitor(QObject):
    """Emit ``cancelled`` when a watched turn ends without any hook."""

    payload_detected = Signal(dict)
    # (session_id, title): display-only, never logged or stored.
    title_detected = Signal(str, str)

    def __init__(
        self,
        config_dir=None,
        parent=None,
        now=time.monotonic,
        poll_interval_ms=POLL_INTERVAL_MS,
    ):
        super().__init__(parent)
        self.config_dir = Path(config_dir) if config_dir else claude_config_dir()
        self._now = now
        self._sessions = {}
        self.detected_count = 0
        self.timer = QTimer(self)
        self.timer.setInterval(max(100, int(poll_interval_ms)))
        self.timer.timeout.connect(self.poll)

    @property
    def watched_sessions(self):
        return tuple(self._sessions)

    def observe(self, payload):
        """Track turns from hook events that already passed sanitization."""
        if not isinstance(payload, dict) or payload.get("source") != "claude_code":
            return
        session_id = payload.get("parent_session_id") or payload.get("session_id")
        if not isinstance(session_id, str) or not _SESSION_ID.match(session_id):
            return
        event = payload.get("event")
        main = not payload.get("parent_session_id")
        if main and event in _TURN_END_EVENTS:
            self._sessions.pop(session_id, None)
        elif event in _TURN_EVENTS:
            watched = self._sessions.setdefault(session_id, _WatchedSession())
            if main and event == "prompt":
                watched.last_prompt_at = self._now()
        self._update_timer()

    def poll(self):
        now = self._now()
        for session_id, watched in tuple(self._sessions.items()):
            try:
                ended = self._poll_session(session_id, watched, now)
            except OSError:
                ended = False
                watched.tail = None
            if watched.tail is not None and watched.tail.title != watched.title:
                watched.title = watched.tail.title
                self.title_detected.emit(session_id, watched.title)
            if ended:
                self._sessions.pop(session_id, None)
                self.detected_count += 1
                self.payload_detected.emit(
                    {
                        "source": "claude_code",
                        "event": "cancelled",
                        "session_id": session_id,
                        "agent_scope": "main",
                        "collected_at": time.time(),
                    }
                )
        self._update_timer()

    def close(self):
        self.timer.stop()
        self._sessions.clear()

    def _poll_session(self, session_id, watched, now):
        if watched.tail is None:
            path = self._locate(session_id)
            if path is None:
                watched.locate_attempts += 1
                if watched.locate_attempts >= MAX_LOCATE_ATTEMPTS:
                    self._sessions.pop(session_id, None)
                return False
            watched.tail = TranscriptTail(path)
            return False
        if "user_text" in watched.tail.read_kinds():
            if now - watched.last_prompt_at > PROMPT_GRACE_SECONDS:
                if watched.unmatched_since is None:
                    watched.unmatched_since = now
        if watched.unmatched_since is None:
            return False
        if watched.last_prompt_at >= watched.unmatched_since - PROMPT_GRACE_SECONDS:
            watched.unmatched_since = None
            return False
        return now - watched.unmatched_since >= PROMPT_GRACE_SECONDS

    def _locate(self, session_id):
        return locate_transcript(session_id, self.config_dir)

    def _update_timer(self):
        if self._sessions and not self.timer.isActive():
            self.timer.start()
        elif not self._sessions and self.timer.isActive():
            self.timer.stop()
