"""Agent hook bridge entry point without Qt (ADR 0004).

Codex and Claude Code run the managed hook for every tool call, so the packaged
``WatchedKettleHookBridge.exe`` imports only the bridge path. The main executable
keeps ``--codex-hook-bridge`` for hooks registered before the split.
"""

from __future__ import annotations

from functools import partial
import os
from pathlib import Path
import sys

from watched_kettle.integrations.claude_code_hooks import (
    claude_code_client,
    normalize_claude_code_hook,
)
from watched_kettle.integrations.codex_bridge import run_hook_bridge
from watched_kettle.integrations.codex_spool import (
    DEFAULT_USER_CLAUDE_CODE_HOOK_HEALTH_PATH,
    DEFAULT_USER_HOOK_HEALTH_PATH,
    DEFAULT_USER_SPOOL_DIRECTORY,
    record_hook_health,
    spool_pet_event,
)


CODEX_HOOK_BRIDGE_FLAG = "--codex-hook-bridge"
CLAUDE_CODE_HOOK_BRIDGE_FLAG = "--claude-code-hook-bridge"
CLAUDE_CODE_STATUS_LINE_FLAG = "--claude-code-status-line"
HOOK_BRIDGE_FLAGS = (
    CODEX_HOOK_BRIDGE_FLAG,
    CLAUDE_CODE_HOOK_BRIDGE_FLAG,
    CLAUDE_CODE_STATUS_LINE_FLAG,
)
DEFAULT_STATUS_LINE_CONFIG_PATH = (
    DEFAULT_USER_SPOOL_DIRECTORY.parent / "claude-code-status-line.json"
)
# The built-in line's items, saved by the settings window; JSON, no Qt.
DEFAULT_STATUS_LINE_LAYOUT_PATH = DEFAULT_STATUS_LINE_CONFIG_PATH.with_name(
    "claude-code-status-line-layout.json"
)


def main(arguments=None):
    arguments = sys.argv[1:] if arguments is None else list(arguments)
    if CLAUDE_CODE_STATUS_LINE_FLAG in arguments:
        return run_status_line()
    claude_code = CLAUDE_CODE_HOOK_BRIDGE_FLAG in arguments
    user_spool_directory = Path(
        os.environ.get("WATCHED_KETTLE_SPOOL_DIRECTORY") or DEFAULT_USER_SPOOL_DIRECTORY
    )
    hook_health_path = Path(
        os.environ.get("WATCHED_KETTLE_HOOK_HEALTH_PATH")
        or (
            DEFAULT_USER_CLAUDE_CODE_HOOK_HEALTH_PATH
            if claude_code
            else DEFAULT_USER_HOOK_HEALTH_PATH
        )
    )
    options = {}
    if claude_code:
        options["normalize"] = partial(
            normalize_claude_code_hook,
            hook_name=_option_value(arguments, "--event"),
            session_id=os.environ.get("CLAUDE_CODE_SESSION_ID") or None,
            client=claude_code_client(os.environ),
        )
    exit_code = run_hook_bridge(
        server_name=os.environ.get("WATCHED_KETTLE_SERVER_NAME") or None,
        fallback=partial(
            spool_pet_event,
            spool_directory=user_spool_directory,
        ),
        health_recorder=partial(
            record_hook_health,
            path=hook_health_path,
        ),
        **options,
    )
    # Claude Code reads SessionStart/UserPromptSubmit stdout as context and
    # PermissionRequest JSON as a decision, so it must stay silent there.
    if not claude_code and sys.stdout is not None:
        sys.stdout.write("{}\n")
    return exit_code


def run_status_line(stdin=None, stdout=None):
    """Forward Claude Code rate limits, then print the user's own status line.

    Rate limits are only useful live, so an absent app is not queued for.
    Prints the original command's output, or a short line with context,
    limits and connections when the user had no status line. Always exits 0.
    """
    # Imported here so ordinary hook calls do not load subprocess.
    import json

    from watched_kettle.integrations.claude_code_status_line import (
        MAX_LANGUAGE_SNAPSHOT_BYTES,
        MAX_LANGUAGE_TEMPLATE_CHARS,
        detected_ide,
        normalize_status_line,
        read_layout,
        read_original,
        run_original,
        status_text,
    )
    from watched_kettle.integrations.codex_client import send_pet_event
    from watched_kettle.integrations.codex_hooks import MAX_HOOK_INPUT_BYTES

    stdin = stdin if stdin is not None else getattr(sys.stdin, "buffer", None)
    stdout = stdout if stdout is not None else getattr(sys.stdout, "buffer", None)
    try:
        data = stdin.read(MAX_HOOK_INPUT_BYTES + 1) if stdin is not None else b""
    except (OSError, ValueError):
        data = b""
    if len(data) > MAX_HOOK_INPUT_BYTES:
        data = b""
    try:
        payload = json.loads(data.decode("utf-8")) if data else None
    except (UnicodeDecodeError, ValueError):
        payload = None
    event = normalize_status_line(payload)
    # None until there are limits to send: no send, no answer about the pet.
    pet_connected = None
    if event is not None:
        try:
            server = os.environ.get("WATCHED_KETTLE_SERVER_NAME")
            if server:
                pet_connected = bool(send_pet_event(event, server))
            else:
                pet_connected = bool(send_pet_event(event))
        except Exception:
            pet_connected = False
    command = read_original(
        os.environ.get("WATCHED_KETTLE_STATUS_LINE_CONFIG")
        or DEFAULT_STATUS_LINE_CONFIG_PATH
    )
    if command and data:
        output = run_original(command, data)
    else:
        # Without a status line of the user's own, a blank line would remain;
        # show context, limits and connections instead.
        workspace = payload.get("workspace") if isinstance(payload, dict) else None
        current_dir = (
            workspace.get("current_dir") if isinstance(workspace, dict) else None
        )
        try:
            ide_name = detected_ide(current_dir)
        except Exception:
            ide_name = None
        language = {}
        try:
            language_path = (
                DEFAULT_USER_SPOOL_DIRECTORY.parent / "language-statusline.json"
            )
            with language_path.open("rb") as stream:
                raw_language = stream.read(MAX_LANGUAGE_SNAPSHOT_BYTES + 1)
            decoded = (
                json.loads(raw_language)
                if len(raw_language) <= MAX_LANGUAGE_SNAPSHOT_BYTES
                else {}
            )
            allowed = {
                "statusline.pet_off",
                "statusline.context",
                "statusline.five_hour",
                "statusline.seven_day",
            }
            language = {
                key: value
                for key, value in decoded.items()
                if key in allowed
                and isinstance(value, str)
                and len(value) <= MAX_LANGUAGE_TEMPLATE_CHARS
            }
            for value in language.values():
                value.encode("utf-8")
        except (
            OSError,
            ValueError,
            TypeError,
            AttributeError,
            UnicodeError,
            RecursionError,
        ):
            language = {}
        output = status_text(
            payload,
            event,
            pet_connected=pet_connected,
            ide_name=ide_name,
            columns=_columns(),
            language=language,
            layout=read_layout(
                os.environ.get("WATCHED_KETTLE_STATUS_LINE_LAYOUT")
                or DEFAULT_STATUS_LINE_LAYOUT_PATH
            ),
        ).encode("utf-8")
    if output and stdout is not None:
        try:
            stdout.write(output)
            stdout.flush()
        except (OSError, ValueError):
            pass
    return 0


def _columns():
    """Terminal width Claude Code passes to status line commands, if any."""
    try:
        value = int(os.environ.get("COLUMNS", ""))
    except ValueError:
        return None
    return value if value > 0 else None


def _option_value(arguments, name):
    try:
        return arguments[arguments.index(name) + 1]
    except (ValueError, IndexError):
        return None
