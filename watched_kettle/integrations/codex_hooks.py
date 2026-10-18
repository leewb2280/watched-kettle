"""Filter Codex lifecycle hook input into privacy-safe pet events.

``sanitize_pet_event`` is the shared gate for every agent source's events.
"""

from __future__ import annotations

from watched_kettle.localization import t

import json
import re
import math
import time

from watched_kettle.state.agent_scope import normalize_agent_scope
from watched_kettle.state.event_names import (
    AGENT_SOURCES,
    approval_actor,
    normalize_agent_source,
    normalize_event_name,
    normalize_urgency,
)


MAX_HOOK_INPUT_BYTES = 256 * 1024
MAX_IPC_EVENT_BYTES = 2 * 1024

CODEX_HOOK_EVENTS = {
    "SessionStart": "idle",
    "SessionEnd": "session_end",
    "SubagentStart": "task_start",
    "SubagentStop": "done",
    "PreToolUse": "tool_start",
    "PermissionRequest": "permission",
    "PostToolUse": "tool_end",
    "PreCompact": "review",
    "PostCompact": "review",
    "UserPromptSubmit": "prompt",
    "Stop": "done",
}

ALLOWED_PET_EVENTS = frozenset(CODEX_HOOK_EVENTS.values()) | {
    "waiting",
    "question_wait",
    "question_resolved",
    "cancelled",
    "failed",
    "ended",
    "heartbeat",
    "tool_failed",
    "permission_resolved",
    "background_wait",
}
ALLOWED_TOOL_STATUSES = frozenset({"started", "waiting", "succeeded", "failed"})
_SAFE_ID_CHARACTER = re.compile(r"[^A-Za-z0-9._:-]")
_PROJECT_REF = re.compile(r"[0-9a-f]{16}")
# Where a Claude Code session runs; decides how its conversation opens.
CLAUDE_CODE_CLIENTS = frozenset({"vscode-panel", "vscode-terminal", "terminal"})


def read_hook_payload(stream):
    """Read one bounded JSON object from a binary input stream."""
    raw = stream.read(MAX_HOOK_INPUT_BYTES + 1)
    if len(raw) > MAX_HOOK_INPUT_BYTES:
        return None

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def normalize_codex_hook(payload):
    """Return a minimal pet event without prompt, path, command, or output data."""
    if not isinstance(payload, dict):
        return None

    hook_name = payload.get("hook_event_name")
    event = CODEX_HOOK_EVENTS.get(hook_name)
    if event is None:
        return None
    if hook_name == "SessionStart" and payload.get("source") == "compact":
        event = "review"

    session_id = _safe_id(payload.get("session_id"), fallback="default")
    is_subagent = hook_name in {"SubagentStart", "SubagentStop"}
    parent_session_id = session_id
    if is_subagent:
        # Codex's agent_id is also the child rollout's session id. Using it
        # directly lets hook and JSONL events clean up the same session.
        session_id = _safe_id(
            payload.get("agent_id"),
            fallback=f"{parent_session_id}:subagent",
        )

    normalized = {
        "source": "codex",
        "event": event,
        "session_id": session_id,
        "agent_scope": "subagent" if is_subagent else "unknown",
    }
    if hook_name in {"PreCompact", "PostCompact"} or (
        hook_name == "SessionStart" and payload.get("source") == "compact"
    ):
        normalized["compaction_phase"] = "start" if hook_name == "PreCompact" else "end"
        normalized["collected_at"] = time.time()
    elif hook_name in {
        "UserPromptSubmit",
        "PreToolUse",
        "PostToolUse",
        "PermissionRequest",
    }:
        normalized["collected_at"] = time.time()
    if is_subagent:
        normalized["parent_session_id"] = parent_session_id

    turn_id = payload.get("turn_id")
    if turn_id:
        normalized["turn_id"] = _safe_id(turn_id, fallback="turn")
    event_id = payload.get("tool_use_id") or payload.get("event_id")
    if event_id:
        normalized["event_id"] = _safe_id(event_id, fallback="event")

    if hook_name == "PreToolUse":
        normalized["tool_status"] = "started"
    elif hook_name == "PermissionRequest":
        normalized["approval_actor"] = approval_actor(payload)
    elif hook_name == "PostToolUse":
        success = _tool_succeeded(payload.get("tool_response"))
        normalized["success"] = success
        normalized["tool_status"] = "succeeded" if success else "failed"
        if not success:
            normalized["event"] = "tool_failed"

    return sanitize_pet_event(normalized)


def sanitize_pet_event(payload):
    """Validate an already-filtered event before it crosses the local pipe."""
    if not isinstance(payload, dict):
        return None
    source = normalize_agent_source(payload.get("source"))
    if source == "schedule":
        event = normalize_event_name(payload.get("event"))
        if event != "notification":
            return None
        message = str(payload.get("message") or payload.get("title") or "").strip()[
            :120
        ]
        if not message:
            message = t("message.0109")
        sanitized = {
            "source": "schedule",
            "event": "notification",
            "session_id": _safe_id(
                payload.get("session_id"),
                fallback="reminder",
            ),
            "message": message,
            "urgency": normalize_urgency(
                payload.get("urgency") or payload.get("priority")
            ),
        }
        if payload.get("event_id"):
            sanitized["event_id"] = _safe_id(
                payload["event_id"],
                fallback="event",
            )
        return _bounded_event(sanitized)

    if source not in AGENT_SOURCES:
        return None

    event = payload.get("event")
    if source == "claude_code" and event == "rate_limits":
        return _rate_limit_event(payload)
    if event not in ALLOWED_PET_EVENTS:
        return None
    if event == "ended" and source != "codex":
        return None
    if event in {"question_wait", "question_resolved"} and not payload.get("event_id"):
        return None

    sanitized = {
        "source": source,
        "event": event,
        "session_id": _safe_id(payload.get("session_id"), fallback="default"),
    }
    if "agent_scope" in payload:
        sanitized["agent_scope"] = normalize_agent_scope(payload["agent_scope"])
    if source == "codex" and event in {"ended", "failed", "cancelled"}:
        from watched_kettle.state.event_names import outcome_reason

        sanitized["outcome_reason"] = outcome_reason(payload.get("outcome_reason"))
    if event == "review" and payload.get("compaction_phase") in ("start", "end"):
        sanitized["compaction_phase"] = payload["compaction_phase"]
    collected_at = payload.get("collected_at")
    if (
        isinstance(collected_at, (int, float))
        and not isinstance(collected_at, bool)
        and math.isfinite(collected_at)
        and collected_at > 0
    ):
        sanitized["collected_at"] = collected_at
    if payload.get("parent_session_id"):
        sanitized["parent_session_id"] = _safe_id(
            payload["parent_session_id"],
            fallback="parent",
        )

    tool_status = payload.get("tool_status")
    if event == "permission":
        sanitized["approval_actor"] = approval_actor(payload)
    if tool_status in ALLOWED_TOOL_STATUSES:
        sanitized["tool_status"] = tool_status
    if isinstance(payload.get("success"), bool):
        sanitized["success"] = payload["success"]
    for key, fallback in (("turn_id", "turn"), ("event_id", "event")):
        if payload.get(key):
            sanitized[key] = _safe_id(payload[key], fallback=fallback)
    # Claude Code has no project API; the bridge sends only the working
    # folder's name and path hash (docs/support-claude-code.md).
    if source == "claude_code":
        reference = payload.get("project_ref")
        if isinstance(reference, str) and _PROJECT_REF.fullmatch(reference):
            sanitized["project_ref"] = reference
        label = safe_project_label(payload.get("project_label"))
        if label:
            sanitized["project_label"] = label
        if payload.get("client") in CLAUDE_CODE_CLIENTS:
            sanitized["client"] = payload["client"]
        count = payload.get("background_count")
        if event == "background_wait":
            if not (isinstance(count, int) and not isinstance(count, bool)):
                return None
            sanitized["background_count"] = max(1, min(99, count))
    elif event == "background_wait":
        return None

    return _bounded_event(sanitized)


def _rate_limit_event(payload):
    """Claude Code status line usage: window percentages and reset times only."""
    sanitized = {
        "source": "claude_code",
        "event": "rate_limits",
        "session_id": _safe_id(payload.get("session_id"), fallback="default"),
    }
    collected_at = payload.get("collected_at")
    if _finite(collected_at) and collected_at > 0:
        sanitized["collected_at"] = collected_at
    for window in ("five_hour", "seven_day"):
        percent = payload.get(f"{window}_percent")
        resets = payload.get(f"{window}_resets_at")
        if not (_finite(percent) and 0 <= percent <= 1000):
            continue
        sanitized[f"{window}_percent"] = float(percent)
        if _finite(resets) and 0 < resets < 2**40:
            sanitized[f"{window}_resets_at"] = int(resets)
    if "five_hour_percent" not in sanitized and "seven_day_percent" not in sanitized:
        return None
    return _bounded_event(sanitized)


def _finite(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def safe_project_label(value):
    """Return a single-line folder name, or "" when it could carry a path."""
    if not isinstance(value, str):
        return ""
    text = " ".join(
        "".join(" " if ord(c) < 32 or 127 <= ord(c) < 160 else c for c in value).split()
    )
    if not text or "/" in text or "\\" in text:
        return ""
    return text[:64]


def _bounded_event(sanitized):
    encoded = json.dumps(
        sanitized,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > MAX_IPC_EVENT_BYTES:
        return None
    return sanitized


def encode_pet_event(payload):
    """Encode one validated newline-delimited IPC event."""
    sanitized = sanitize_pet_event(payload)
    if sanitized is None:
        return None
    return (
        json.dumps(sanitized, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        + b"\n"
    )


def _safe_id(value, fallback):
    text = str(value or fallback).strip()
    text = _SAFE_ID_CHARACTER.sub("_", text)
    return (text or fallback)[:160]


def _tool_succeeded(response):
    if not isinstance(response, dict):
        return True

    if response.get("isError") is True or response.get("is_error") is True:
        return False
    if response.get("success") is False:
        return False

    status = response.get("status")
    if isinstance(status, str) and status.lower() in {
        "error",
        "failed",
        "failure",
        "cancelled",
        "canceled",
    }:
        return False

    exit_code = response.get("exit_code")
    if isinstance(exit_code, int) and exit_code != 0:
        return False
    if response.get("error") not in (None, "", False):
        return False
    return True
