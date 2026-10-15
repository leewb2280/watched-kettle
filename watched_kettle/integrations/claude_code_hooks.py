"""Filter Claude Code lifecycle hook input into privacy-safe pet events.

The hook bridge imports this module, so it stays free of Qt, dataclasses and
inspect (ADR 0004). Event semantics follow docs/support-claude-code.md.
"""

from __future__ import annotations

import hashlib
import ntpath
import time

from watched_kettle.integrations.codex_hooks import (
    CLAUDE_CODE_CLIENTS,
    _safe_id,
    safe_project_label,
    sanitize_pet_event,
)


CLAUDE_CODE_HOOK_EVENTS = {
    "SessionStart": "idle",
    "SessionEnd": "session_end",
    "UserPromptSubmit": "prompt",
    "PreToolUse": "tool_start",
    "PermissionRequest": "permission",
    "PostToolUse": "tool_end",
    "PostToolUseFailure": "tool_failed",
    "Notification": "waiting",
    "SubagentStart": "task_start",
    "SubagentStop": "done",
    "Stop": "done",
    "StopFailure": "failed",
    "PreCompact": "review",
    "PostCompact": "review",
}
# Events that need payload fields to be interpreted safely. Without them a
# minimal event would show a false wait or a false subagent completion.
_PAYLOAD_REQUIRED = frozenset({"Notification", "SubagentStart", "SubagentStop"})
MAX_BACKGROUND_COUNT = 99
_ENDED_BACKGROUND_STATUSES = frozenset({"completed", "failed", "killed", "paused"})
_TIMESTAMPED = frozenset(
    {"UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure"}
)


def claude_code_client(environ):
    """Where the session runs, from the environment Claude Code gives hooks.

    The VS Code panel reports ``claude-vscode``; the CLI reports ``cli`` with
    ``TERM_PROGRAM=vscode`` inside VS Code's terminal. Anything else (``claude
    -p``, unknown values) is None so the app falls back to the activity list.
    """
    entrypoint = environ.get("CLAUDE_CODE_ENTRYPOINT")
    if entrypoint == "claude-vscode":
        return "vscode-panel"
    if entrypoint == "cli":
        return (
            "vscode-terminal" if environ.get("TERM_PROGRAM") == "vscode" else "terminal"
        )
    return None


def normalize_claude_code_hook(payload, hook_name=None, session_id=None, client=None):
    """Return a minimal pet event without prompt, path, command, or output data.

    ``payload`` is None when the hook input was oversized or invalid. The
    caller then supplies the hook name from the managed command line and the
    session from ``CLAUDE_CODE_SESSION_ID`` so the turn state still advances.
    """
    if not isinstance(payload, dict):
        payload = None
    name = (payload or {}).get("hook_event_name") or hook_name
    event = CLAUDE_CODE_HOOK_EVENTS.get(name)
    if event is None:
        return None
    if payload is None and name in _PAYLOAD_REQUIRED:
        return None
    payload = payload or {}

    if name == "Notification" and payload.get("notification_type") != (
        "permission_prompt"
    ):
        return None
    # Background work wakes the session with its result in a turn of its own:
    # the turn waits for it, and that later turn's Stop completes the work.
    background = (
        _waking_background_count(payload.get("background_tasks"))
        if name == "Stop"
        else 0
    )

    parent_session_id = _safe_id(
        payload.get("session_id") or session_id,
        fallback="default",
    )
    agent_type = payload.get("agent_type")
    agent_id = payload.get("agent_id")
    if name in {"SubagentStart", "SubagentStop"} and agent_type == "":
        # Claude Code runs unnamed internal agents (titles, compaction) that
        # report SubagentStop without being user-visible work.
        return None

    normalized = {
        "source": "claude_code",
        "event": "background_wait" if background else event,
        "session_id": parent_session_id,
        "agent_scope": "main",
    }
    if agent_id:
        normalized["session_id"] = _safe_id(
            agent_id,
            fallback=f"{parent_session_id}:subagent",
        )
        normalized["parent_session_id"] = parent_session_id
        normalized["agent_scope"] = "internal" if agent_type == "" else "subagent"

    if name in {"PreCompact", "PostCompact"} or (
        name == "SessionStart" and payload.get("source") == "compact"
    ):
        normalized["event"] = "review"
        normalized["compaction_phase"] = "start" if name == "PreCompact" else "end"
        normalized["collected_at"] = time.time()
    elif name in _TIMESTAMPED or name == "PermissionRequest":
        normalized["collected_at"] = time.time()

    normalized.update(project_identity(payload.get("cwd")))
    if client in CLAUDE_CODE_CLIENTS:
        normalized["client"] = client
    if background:
        normalized["background_count"] = background
    prompt_id = payload.get("prompt_id")
    if prompt_id:
        normalized["turn_id"] = _safe_id(prompt_id, fallback="turn")
    tool_use_id = payload.get("tool_use_id")
    if tool_use_id:
        normalized["event_id"] = _safe_id(tool_use_id, fallback="event")

    if name == "PreToolUse":
        normalized["tool_status"] = "started"
    elif name == "PermissionRequest":
        # The hook fires only when Claude Code shows the user a dialog.
        normalized["approval_actor"] = "user"
    elif name == "PostToolUse":
        normalized["success"] = True
        normalized["tool_status"] = "succeeded"
    elif name == "PostToolUseFailure":
        normalized["success"] = False
        normalized["tool_status"] = "failed"
        if payload.get("is_interrupt") is True:
            normalized["event"] = "cancelled"

    return sanitize_pet_event(normalized)


def project_identity(cwd):
    """Return the working folder's name and path hash; never the path itself.

    The app groups a session's card by the hash and shows the folder name.
    """
    if not isinstance(cwd, str) or not cwd.strip():
        return {}
    path = ntpath.normpath(cwd.strip())
    key = ntpath.normcase(path).rstrip("\\") or ntpath.normcase(path)
    identity = {
        "project_ref": hashlib.sha256(key.encode("utf-8", "replace")).hexdigest()[:16]
    }
    label = safe_project_label(ntpath.basename(path.rstrip("\\")))
    if label:
        identity["project_label"] = label
    return identity


def _waking_background_count(value):
    """How many background tasks are still running that will wake the session.

    Monitors and MCP tasks only watch (a live subscription may never end), so
    they never hold a finished turn open; seen in Claude Code 2.1.288-289.
    Unknown types fall back to Claude Code's raw names and count as work, as
    do entries without a type. Only the type and status are read.
    """
    if not isinstance(value, list):
        return 0
    count = 0
    for task in value:
        if isinstance(task, dict):
            kind = str(task.get("type") or "").lower()
            status = str(task.get("status") or "running").lower()
            if "monitor" in kind or "mcp" in kind:
                continue
            if status in _ENDED_BACKGROUND_STATUSES:
                continue
        count += 1
    return min(count, MAX_BACKGROUND_COUNT)
