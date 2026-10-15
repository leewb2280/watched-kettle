"""Per-turn token totals from Claude Code transcript files (stage 13).

Claude Code writes one JSONL transcript per session under
``<config>/projects/<folder>/<session>.jsonl`` and its subagents under
``<session>/subagents/agent-*.jsonl``. Every user entry carries the turn's
``promptId``; assistant entries follow it and repeat their message ``usage`` on
each content block. This module reads only identifiers, timestamps, the model
name, the stop reason and token counts. Prompts, outputs, tool data and paths
never leave it; the working folder becomes a hash and a display name.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path

from watched_kettle.integrations.claude_code_hooks import project_identity
from watched_kettle.usage.identifiers import hash_identifier


MAIN_PART = "main"
# Lines larger than this are tool payloads; they are skipped unparsed.
MAX_PARSED_LINE_BYTES = 4 * 1024 * 1024
_TOKEN_FIELDS = (
    "input_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "output_tokens",
)


@dataclass
class TurnPart:
    """One file's share of a turn; subagent files add their own parts."""

    session_hash: str
    turn_hash: str
    part: str
    project_hash: str = ""
    started_at: datetime | None = None
    completed_at: datetime | None = None
    outcome: str = ""
    model: str | None = None
    stop_reason: str | None = None
    tokens: dict = field(default_factory=lambda: dict.fromkeys(_TOKEN_FIELDS, 0))
    _messages: dict = field(default_factory=dict)

    def add_usage(self, key, usage):
        # Each content block of one message repeats the same usage; keep the
        # largest value per field instead of adding the repeats.
        previous = self._messages.get(key, dict.fromkeys(_TOKEN_FIELDS, 0))
        merged = {
            name: max(previous[name], _count(usage.get(name))) for name in _TOKEN_FIELDS
        }
        for name in _TOKEN_FIELDS:
            self.tokens[name] += merged[name] - previous[name]
        self._messages[key] = merged

    @property
    def input_tokens(self):
        return (
            self.tokens["input_tokens"]
            + self.tokens["cache_creation_input_tokens"]
            + self.tokens["cache_read_input_tokens"]
        )

    @property
    def total_tokens(self):
        return self.input_tokens + self.tokens["output_tokens"]


@dataclass
class FilePass:
    """Resumable parse of one transcript from a turn boundary."""

    path: Path
    session_id: str
    part: str
    offset: int
    turns: dict = field(default_factory=dict)
    order: list = field(default_factory=list)
    current: str = ""
    current_offset: int = 0
    titles: dict = field(default_factory=dict)
    project_label: str = ""
    project_hash: str = ""
    pending: bytes = b""
    skipping: bool = False

    @property
    def session_hash(self):
        return hash_identifier(self.session_id)

    @property
    def title(self):
        return self.titles.get("custom-title") or self.titles.get("ai-title") or ""

    def read(self, budget_bytes):
        """Parse up to ``budget_bytes``; return True at the end of the file."""
        with self.path.open("rb") as stream:
            stream.seek(self.offset)
            data = stream.read(budget_bytes)
        if not data:
            return True
        pieces = (self.pending + data).split(b"\n")
        line_start = self.offset - len(self.pending)
        self.pending = pieces.pop()
        for piece in pieces:
            if self.skipping:
                self.skipping = False
            elif piece.strip():
                self._line(piece, line_start)
            line_start += len(piece) + 1
        self.offset += len(data)
        if len(self.pending) > MAX_PARSED_LINE_BYTES:
            self.pending = b""
            self.skipping = True
        return len(data) < budget_bytes

    def _line(self, raw, line_start):
        if len(raw) > MAX_PARSED_LINE_BYTES:
            return
        try:
            entry = json.loads(raw)
        except (UnicodeDecodeError, ValueError):
            return
        if not isinstance(entry, dict):
            return
        kind = entry.get("type")
        if kind in {"custom-title", "ai-title"}:
            value = entry.get("customTitle" if kind == "custom-title" else "aiTitle")
            if isinstance(value, str) and value.strip():
                self.titles[kind] = " ".join(value.split())[:120]
            return
        if kind not in {"user", "assistant"}:
            return
        if not self.project_hash and isinstance(entry.get("cwd"), str):
            identity = project_identity(entry["cwd"])
            self.project_hash = identity.get("project_ref", "")
            self.project_label = identity.get("project_label", "")
        stamp = _timestamp(entry.get("timestamp"))
        prompt = entry.get("promptId")
        if kind == "user" and isinstance(prompt, str) and prompt != self.current:
            self.current = prompt
            self.current_offset = line_start
            if prompt not in self.turns:
                self.order.append(prompt)
                self.turns[prompt] = TurnPart(
                    self.session_hash, hash_identifier(prompt), self.part
                )
        part = self.turns.get(self.current)
        if part is None:
            return
        if stamp is not None:
            part.started_at = min(filter(None, (part.started_at, stamp)))
            part.completed_at = max(filter(None, (part.completed_at, stamp)))
        if kind != "assistant":
            return
        message = entry.get("message")
        if not isinstance(message, dict):
            return
        usage = message.get("usage")
        if isinstance(usage, dict):
            part.add_usage((message.get("id"), entry.get("requestId")), usage)
        if isinstance(message.get("model"), str) and not message["model"].startswith(
            "<"
        ):
            part.model = message["model"][:80]
        if isinstance(message.get("stop_reason"), str):
            part.stop_reason = message["stop_reason"]

    def finish(self, idle):
        """Settle outcomes once the file end is reached.

        A turn ends with ``end_turn``. A later turn means the earlier one was
        interrupted or denied; the last turn is still running until the file
        has been idle for the inactivity limit.
        """
        for index, prompt in enumerate(self.order):
            part = self.turns[prompt]
            part.project_hash = self.project_hash
            if self.part != MAIN_PART:
                continue
            if part.stop_reason == "end_turn":
                part.outcome = "completed"
            elif index < len(self.order) - 1 or idle:
                part.outcome = "cancelled"
            else:
                part.outcome = "running"
        return [self.turns[prompt] for prompt in self.order]

    @property
    def resume_offset(self):
        """Where the next pass must start to recompute the last turn."""
        return self.current_offset if self.order else self.offset - len(self.pending)


def transcript_files(config_dir):
    """Yield ``(path, session_id, part)`` for main and subagent transcripts."""
    projects = Path(config_dir) / "projects"
    try:
        folders = [path for path in projects.iterdir() if path.is_dir()]
    except OSError:
        return
    for folder in folders:
        try:
            entries = list(folder.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.suffix == ".jsonl" and entry.is_file():
                yield entry, entry.stem, MAIN_PART
            elif entry.is_dir():
                subagents = entry / "subagents"
                try:
                    agents = sorted(subagents.glob("*.jsonl"))
                except OSError:
                    continue
                for agent in agents:
                    yield agent, entry.name, agent.stem


def read_custom_title(session_folder):
    """``<session>/custom-title.json`` holds a rename made outside the log."""
    try:
        value = json.loads(
            (Path(session_folder) / "custom-title.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError, UnicodeDecodeError):
        return ""
    title = value.get("customTitle") if isinstance(value, dict) else None
    return " ".join(title.split())[:120] if isinstance(title, str) else ""


def _count(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
