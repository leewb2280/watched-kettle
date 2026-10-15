"""Filesystem fallback for Codex hooks running in a Windows sandbox."""

from __future__ import annotations

import json
from itertools import islice
import os
from pathlib import Path
import time
from uuid import uuid4
from datetime import datetime, timezone

from watched_kettle.branding import APPLICATION_ID
from watched_kettle.integrations.codex_hooks import (
    MAX_IPC_EVENT_BYTES,
    encode_pet_event,
    sanitize_pet_event,
)


DEFAULT_SPOOL_DIRECTORY = (
    Path(__file__).resolve().parents[2] / ".watched-kettle-runtime" / "events"
)
DEFAULT_HOOK_HEALTH_PATH = (
    Path(__file__).resolve().parents[2] / ".watched-kettle-runtime" / "hook-health.json"
)
DEFAULT_USER_RUNTIME_ROOT = (
    Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    / APPLICATION_ID
    / "runtime"
)
DEFAULT_USER_SPOOL_DIRECTORY = DEFAULT_USER_RUNTIME_ROOT / "events"
DEFAULT_USER_HOOK_HEALTH_PATH = DEFAULT_USER_RUNTIME_ROOT / "hook-health.json"
DEFAULT_USER_CLAUDE_CODE_HOOK_HEALTH_PATH = (
    DEFAULT_USER_RUNTIME_ROOT / "claude-code-hook-health.json"
)
MAX_QUEUED_EVENTS = 512
MAX_EVENT_AGE_SECONDS = 60
HOOK_DELIVERY_OUTCOMES = frozenset(
    {
        "delivered",
        "queued",
        "undelivered",
        "ignored",
    }
)


def spool_pet_event(payload, spool_directory=DEFAULT_SPOOL_DIRECTORY):
    """Atomically queue one filtered event inside the project workspace."""
    encoded = encode_pet_event(payload)
    if encoded is None:
        return False

    spool_directory = Path(spool_directory)
    try:
        spool_directory.mkdir(parents=True, exist_ok=True)
        if (
            sum(1 for _ in islice(spool_directory.glob("*.json"), MAX_QUEUED_EVENTS))
            >= MAX_QUEUED_EVENTS
        ):
            return False

        event_name = f"{time.time_ns()}-{os.getpid()}-{uuid4().hex}.json"
        temporary = spool_directory / f".{event_name}.tmp"
        destination = spool_directory / event_name
        with temporary.open("xb") as stream:
            stream.write(encoded)
        temporary.replace(destination)
        return True
    except OSError:
        return False


def drain_spooled_events(
    spool_directory=DEFAULT_SPOOL_DIRECTORY,
    now=None,
):
    """Yield valid fresh events and remove every consumed or stale file."""
    spool_directory = Path(spool_directory)
    now = time.time() if now is None else now
    try:
        paths = sorted(islice(spool_directory.glob("*.json"), MAX_QUEUED_EVENTS))
    except OSError:
        return

    for path in paths[:32]:
        payload = None
        try:
            if now - path.stat().st_mtime <= MAX_EVENT_AGE_SECONDS:
                if path.stat().st_size > MAX_IPC_EVENT_BYTES:
                    continue
                with path.open("rb") as stream:
                    raw = stream.read(MAX_IPC_EVENT_BYTES + 1)
                if len(raw) <= MAX_IPC_EVENT_BYTES:
                    decoded = json.loads(raw.decode("utf-8"))
                    payload = sanitize_pet_event(decoded)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            payload = None
        finally:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

        if payload is not None:
            yield payload


def record_hook_health(payload, outcome, path=DEFAULT_HOOK_HEALTH_PATH):
    """Atomically record that the bridge ran, without storing raw hook input."""
    sanitized = sanitize_pet_event(payload) if payload is not None else None
    if outcome not in HOOK_DELIVERY_OUTCOMES:
        outcome = "undelivered"
    health = {
        "event": sanitized["event"] if sanitized is not None else "ignored",
        "outcome": outcome,
        "recorded_at": datetime.now(timezone.utc)
        .isoformat()
        .replace(
            "+00:00",
            "Z",
        ),
    }
    path = Path(path)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps(health, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(path)
        return True
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def read_hook_health(path=DEFAULT_HOOK_HEALTH_PATH):
    """Return the bounded privacy-safe bridge heartbeat, if valid."""
    path = Path(path)
    empty = {
        "exists": False,
        "valid": False,
        "event": "",
        "outcome": "",
        "recorded_at": None,
    }
    if not path.is_file():
        return empty
    try:
        if path.stat().st_size > 4096:
            return {**empty, "exists": True}
        with path.open("rb") as stream:
            raw = stream.read(4097)
        if len(raw) > 4096:
            raise ValueError("hook health is too large")
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("invalid hook health object")
        event = payload.get("event")
        outcome = payload.get("outcome")
        recorded_at = payload.get("recorded_at")
        if not isinstance(event, str) or not isinstance(recorded_at, str):
            raise ValueError("invalid hook health fields")
        if outcome not in HOOK_DELIVERY_OUTCOMES:
            raise ValueError("invalid hook health outcome")
        parsed_at = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
    ):
        return {**empty, "exists": True}
    return {
        "exists": True,
        "valid": True,
        "event": event[:160],
        "outcome": outcome,
        "recorded_at": parsed_at.astimezone(),
    }
