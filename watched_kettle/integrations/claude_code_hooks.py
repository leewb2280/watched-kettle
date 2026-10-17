"""Filter Claude Code lifecycle hook input into privacy-safe pet events.

The hook bridge imports this module, so it stays free of Qt, dataclasses and
inspect (ADR 0004). Event semantics follow docs/support-claude-code.md.
"""

from __future__ import annotations

import hashlib
import ntpath
import os
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
# project_root: folders climbed looking for .git, and bytes read of a git file.
GIT_SEARCH_DEPTH = 32
GIT_FILE_LIMIT = 4096
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
    """Return the project folder's name and path hash; never the path itself.

    The app groups a session's card by the hash and shows the folder name. A
    folder inside a git repository counts as the repository's main folder, so
    its worktrees and subfolders share one card (``project_root``).
    """
    if not isinstance(cwd, str) or not cwd.strip():
        return {}
    path = project_root(ntpath.normpath(cwd.strip()))
    key = ntpath.normcase(path).rstrip("\\") or ntpath.normcase(path)
    identity = {
        "project_ref": hashlib.sha256(key.encode("utf-8", "replace")).hexdigest()[:16]
    }
    name = ntpath.basename(path.rstrip("\\"))
    if name.lower().endswith(".git") and len(name) > 4:
        # A bare repository's folder.
        name = name[:-4]
    label = safe_project_label(name)
    if label:
        identity["project_label"] = label
    return identity


def project_root(path):
    """Return the main folder of the git repository holding ``path``, or ``path``.

    A linked worktree's ``.git`` file names a gitdir with a ``commondir``;
    the main repository owns it. A submodule's gitdir has none, so it keeps
    its own folder. A repository at the home folder or a drive root (dotfiles)
    does not take in the folders below it. Anything unreadable keeps ``path``.
    The hook bridge runs this on every tool call: a few stats, two small reads.
    """
    current = path
    for _ in range(GIT_SEARCH_DEPTH):
        marker = ntpath.join(current, ".git")
        try:
            if os.path.lexists(marker):
                if current != path and _broad_folder(current):
                    return path
                return _repository_root(current, marker) or path
        except (OSError, ValueError, UnicodeError):
            return path
        parent = ntpath.dirname(current)
        if parent == current:
            break
        current = parent
    return path


def _broad_folder(folder):
    if ntpath.dirname(folder) == folder:
        return True
    home = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    return bool(home) and ntpath.normcase(ntpath.normpath(home)) == ntpath.normcase(
        folder
    )


def _repository_root(folder, marker):
    if os.path.isdir(marker):
        return folder
    text = _read_small(marker)
    if not text or not text.startswith("gitdir:"):
        return None
    gitdir = ntpath.normpath(ntpath.join(folder, _windows_path(text[7:].strip())))
    common = _read_small(ntpath.join(gitdir, "commondir"))
    if common is None:
        return folder
    common = ntpath.normpath(ntpath.join(gitdir, _windows_path(common.strip())))
    if ntpath.basename(common).lower() == ".git":
        return ntpath.dirname(common)
    return common


def _read_small(path):
    """The first line of a small git file, or None when it is missing."""
    try:
        with open(path, "rb") as handle:
            data = handle.read(GIT_FILE_LIMIT)
    except FileNotFoundError:
        return None
    lines = data.decode("utf-8").splitlines()
    return lines[0] if lines else ""


def _windows_path(value):
    # Git for Windows may write an MSYS path such as /c/Users/...
    if len(value) > 2 and value[0] == "/" and value[2] == "/" and value[1].isalpha():
        return value[1] + ":" + value[2:]
    return value


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
