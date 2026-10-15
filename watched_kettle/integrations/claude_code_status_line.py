"""Claude Code status line bridge: forward rate limits, keep the user's line.

Claude Code runs the configured ``statusLine`` command with session JSON on
stdin after assistant messages. The official ``rate_limits`` object (Pro/Max)
is the only supported source of the 5-hour and 7-day usage percentages
(docs/support-claude-code.md). This mode sends only those numbers to the
app and then runs the status line command the user had before, unchanged.
Users without one get a local line of context, limits and connections.

The hook bridge imports this module, so it stays free of Qt, dataclasses and
inspect (ADR 0004).
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import time
import unicodedata

from watched_kettle.integrations.codex_hooks import _safe_id, sanitize_pet_event


STATUS_LINE_EVENT = "rate_limits"
WINDOWS = ("five_hour", "seven_day")
# What the built-in line can show, and the layout used when the app saved none.
STATUS_LINE_ITEMS = ("pet", "ide", "model", "context", "five_hour", "seven_day")
DEFAULT_STATUS_LINE_LAYOUT = {
    "lines": [["pet", "ide", "model"], ["context", "five_hour", "seven_day"]],
    "color": True,
    "reset_times": True,
}
# Next to the original-command sidecar in the app runtime folder.
LAYOUT_FILE_NAME = "claude-code-status-line-layout.json"
MAX_STATUS_LINE_LINES = 2
MAX_LAYOUT_BYTES = 4096
# Lower priority is dropped first when the terminal is narrow.
_PRIORITY = {
    "pet": 9,
    "ide": 2,
    "model": 1,
    "context": 9,
    "five_hour": 8,
    "seven_day": 7,
}
ORIGINAL_TIMEOUT_SECONDS = 10
MAX_ORIGINAL_OUTPUT_BYTES = 64 * 1024


def normalize_status_line(payload):
    """Return a numbers-only rate limit event, or None without limits."""
    if not isinstance(payload, dict):
        return None
    limits = payload.get("rate_limits")
    if not isinstance(limits, dict):
        return None
    event = {
        "source": "claude_code",
        "event": STATUS_LINE_EVENT,
        "session_id": _safe_id(payload.get("session_id"), fallback="default"),
        "collected_at": time.time(),
    }
    for name in WINDOWS:
        window = limits.get(name)
        if not isinstance(window, dict):
            continue
        percent = window.get("used_percentage")
        resets = window.get("resets_at")
        if (
            isinstance(percent, (int, float))
            and not isinstance(percent, bool)
            and math.isfinite(percent)
            and 0 <= percent <= 1000
        ):
            event[f"{name}_percent"] = float(percent)
            if isinstance(resets, (int, float)) and not isinstance(resets, bool):
                if math.isfinite(resets) and resets > 0:
                    event[f"{name}_resets_at"] = int(resets)
    if not any(f"{name}_percent" in event for name in WINDOWS):
        return None
    return sanitize_pet_event(event)


def normalize_layout(value):
    """A valid layout, or the default one; unknown or repeated items are dropped."""
    if not isinstance(value, dict) or not isinstance(value.get("lines"), list):
        return _default_layout()
    seen = set()
    lines = []
    for line in value["lines"][:MAX_STATUS_LINE_LINES]:
        if not isinstance(line, list):
            return _default_layout()
        items = []
        for item in line:
            if item in STATUS_LINE_ITEMS and item not in seen:
                seen.add(item)
                items.append(item)
        lines.append(items)
    flags = {
        key: value.get(key, default)
        for key, default in (("color", True), ("reset_times", True))
    }
    if not all(isinstance(flag, bool) for flag in flags.values()):
        return _default_layout()
    return {"lines": lines, **flags}


def _default_layout():
    return json.loads(json.dumps(DEFAULT_STATUS_LINE_LAYOUT))


def read_layout(path):
    """The layout the app saved; the default when it is missing or damaged."""
    try:
        with open(path, "rb") as stream:
            data = stream.read(MAX_LAYOUT_BYTES + 1)
        if len(data) > MAX_LAYOUT_BYTES:
            return _default_layout()
        return normalize_layout(json.loads(data.decode("utf-8")))
    except (OSError, UnicodeDecodeError, ValueError):
        return _default_layout()


def write_layout(path, layout):
    """Save a normalized layout atomically so the bridge never reads half."""
    layout = normalize_layout(layout)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(layout, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)
    return layout


def status_text(
    payload, event, pet_connected=None, ide_name=None, columns=None, layout=None
):
    """Short lines for users without their own status line.

    By default the first line is connections and model, the second is usage;
    the app's status line settings can reorder, move or hide each part. Only
    what Claude Code passes in or what this machine shows locally is printed;
    nothing here is sent anywhere. The pet appears only when the last send
    failed, so a working setup stays quiet. The session name is left out
    because Claude Code already shows it on the prompt's top border. Each
    line drops its low-priority parts first when the terminal is narrow, and
    an empty line is not printed.
    """
    payload = payload if isinstance(payload, dict) else {}
    event = event if isinstance(event, dict) else {}
    layout = normalize_layout(layout) if layout is not None else _default_layout()
    texts = {
        "pet": _color("펫 꺼짐", _YELLOW) if pet_connected is False else "",
        "ide": ide_name or "",
        "model": _model_text(payload),
        "context": _context_text(payload.get("context_window")),
        "five_hour": "",
        "seven_day": "",
    }
    five = event.get("five_hour_percent")
    if isinstance(five, (int, float)):
        reset = (
            _clock(event.get("five_hour_resets_at")) if layout["reset_times"] else ""
        )
        texts["five_hour"] = f"5시간 {five:.0f}%{reset}"
    seven = event.get("seven_day_percent")
    if isinstance(seven, (int, float)):
        texts["seven_day"] = f"7일 {seven:.0f}%"
    lines = []
    for line in layout["lines"]:
        parts = [(_PRIORITY[item], texts[item]) for item in line if texts[item]]
        if parts:
            text = _fit(parts, columns)
            lines.append(text if layout["color"] else _ANSI.sub("", text))
    return "".join(line + "\n" for line in lines)


def _fit(parts, columns):
    parts = list(parts)
    if columns:
        while len(parts) > 1 and _width(" · ".join(t for _, t in parts)) > columns:
            parts.remove(min(parts, key=lambda part: part[0]))
    return " · ".join(text for _, text in parts)


_GREEN, _YELLOW, _RED = "32", "33", "31"
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _color(text, code):
    return f"\x1b[{code}m{text}\x1b[0m"


def _width(text):
    return sum(
        2 if unicodedata.east_asian_width(character) in "WF" else 1
        for character in _ANSI.sub("", text)
    )


def _clock(timestamp):
    """(14:30) for a reset time; Windows rejects out-of-range timestamps."""
    if not isinstance(timestamp, int):
        return ""
    try:
        return f" ({time.strftime('%H:%M', time.localtime(timestamp))})"
    except (OSError, OverflowError, ValueError):
        return ""


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def _clean_text(value, limit):
    """Printable text only, so a session name cannot move the cursor."""
    if not isinstance(value, str):
        return ""
    text = "".join(
        character
        for character in value
        if not unicodedata.category(character).startswith("C")
    ).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _model_text(payload):
    model = payload.get("model")
    name = _clean_text(model.get("display_name"), 32) if isinstance(model, dict) else ""
    effort = payload.get("effort")
    level = _clean_text(effort.get("level"), 8) if isinstance(effort, dict) else ""
    return " ".join(part for part in (name, level) if part)


def _tokens(value):
    if value >= 1_000_000:
        return f"{value / 1_000_000:.3g}M"
    return f"{value / 1000:.0f}k"


def _context_text(window):
    """컨텍스트 10% (104k/1M), green below half, red from 80%."""
    if not isinstance(window, dict):
        return ""
    percent = _number(window.get("used_percentage"))
    if percent is None:
        return ""
    color = _GREEN if percent < 50 else _YELLOW if percent < 80 else _RED
    text = f"컨텍스트 {percent:.0f}%"
    size = _number(window.get("context_window_size"))
    if size:
        # Same input-only sum as used_percentage; null right after /compact.
        usage = window.get("current_usage")
        used = None
        if isinstance(usage, dict):
            counts = [
                _number(usage.get(key))
                for key in (
                    "input_tokens",
                    "cache_creation_input_tokens",
                    "cache_read_input_tokens",
                )
            ]
            if all(count is not None for count in counts):
                used = sum(counts)
        if used is None:
            used = size * percent / 100
        text += f" ({_tokens(used)}/{_tokens(size)})"
    return _color(text, color)


def detected_ide(current_dir, config_dir=None):
    """Name of a running IDE that offers Claude Code a connection here.

    The IDE extension writes ``<config>/ide/<port>.lock`` with its process ID
    and workspace folders. This only shows the IDE is listening for this
    folder; whether this session is attached right now is not visible.
    """
    if not isinstance(current_dir, str) or not current_dir:
        return None
    if config_dir is None:
        value = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
        config_dir = Path(value).expanduser() if value else Path.home() / ".claude"
    here = os.path.normcase(os.path.normpath(current_dir))
    try:
        locks = sorted(Path(config_dir, "ide").glob("*.lock"))[:MAX_IDE_LOCKS]
    except OSError:
        return None
    for lock in locks:
        try:
            if lock.stat().st_size > MAX_IDE_LOCK_BYTES:
                continue
            value = json.loads(lock.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        if not isinstance(value, dict):
            continue
        folders = value.get("workspaceFolders")
        if not isinstance(folders, list) or not any(
            _inside(here, folder) for folder in folders
        ):
            continue
        pid = value.get("pid")
        if not (isinstance(pid, int) and not isinstance(pid, bool) and _alive(pid)):
            continue
        name = _clean_text(value.get("ideName"), 24)
        return "VS Code" if name in ("", "Visual Studio Code") else name
    return None


MAX_IDE_LOCKS = 16
MAX_IDE_LOCK_BYTES = 64 * 1024


def _inside(here, folder):
    if not isinstance(folder, str) or not folder:
        return False
    root = os.path.normcase(os.path.normpath(folder))
    return here == root or here.startswith(root.rstrip("\\/") + os.sep)


def _alive(pid):
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except PermissionError:
            return True
        except OSError:
            return False
        return True
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    )
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    process_query_limited_information, still_active = 0x1000, 259
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def read_original(path):
    """The status line configuration replaced at install time, if any."""
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    original = value.get("original") if isinstance(value, dict) else None
    if not isinstance(original, dict):
        return None
    command = original.get("command")
    return command if isinstance(command, str) and command.strip() else None


def run_original(command, data, environment=None):
    """Run the user's status line the way Claude Code would and return stdout.

    Claude Code uses Git Bash when it is installed and PowerShell otherwise.
    Failures return empty output; the agent is never blocked.
    """
    # Only users with their own status line pay for these imports; the line
    # runs after every assistant message, so startup time matters (ADR 0004).
    import shutil
    import subprocess

    environment = dict(os.environ if environment is None else environment)
    shell = environment.get("SHELL") or ""
    if not (shell and Path(shell).is_file()):
        shell = shutil.which("bash") or ""
    arguments = (
        [shell, "-c", command]
        if shell
        else ["powershell.exe", "-NoProfile", "-Command", command]
    )
    try:
        completed = subprocess.run(
            arguments,
            input=data,
            capture_output=True,
            timeout=ORIGINAL_TIMEOUT_SECONDS,
            env=environment,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return b""
    return completed.stdout[:MAX_ORIGINAL_OUTPUT_BYTES]
