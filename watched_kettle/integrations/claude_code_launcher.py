"""Open a Claude Code conversation where it runs (stage 14).

A VS Code panel session opens through the Claude Code extension's URI handler,
``vscode://anthropic.claude-code/open?session=<id>`` (read from extension
2.1.288; Claude Code does not document it, so a failure falls back). A CLI
session is never reopened elsewhere: the CLI still owns the session after a
turn ends, and two processes would write to it. A CLI session in VS Code's
terminal brings its folder's window forward instead. One in another terminal
has no target, so the caller shows the activity list.

The folder is the one the session started in: the user ran ``claude`` there,
so it is the VS Code window the session lives in, even after the session moves
into a worktree. It is read from the transcript only to build the folder URL
and is never stored or logged.
"""

from __future__ import annotations

from watched_kettle.localization import t
from watched_kettle.localization.collections import MessageId, MessageMapping

import json
import os
import re
import subprocess

from PySide6.QtCore import QUrl

from watched_kettle.integrations.claude_code_transcript import locate_transcript
from watched_kettle.integrations.vscode_launcher import installed_vscode


CLAUDE_CODE_EXTENSION = "anthropic.claude-code"
# The first entries carry the folder the session started in. When they do not
# fit (a very long first message), the newest folder at the end is used.
CWD_SCAN_BYTES = 64 * 1024
_SESSION_UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
# A local folder with a drive letter; network shares are not opened.
_DRIVE_PATH = re.compile(r"[A-Za-z]:[\\/]")

OPEN_SESSION = "session"
OPEN_FOLDER = "folder"
OPEN_LIST = "list"
CLIENT_ACTIONS = {"vscode-panel": OPEN_SESSION, "vscode-terminal": OPEN_FOLDER}
ACTION_LABELS = MessageMapping(
    {
        OPEN_SESSION: MessageId("message.0077"),
        OPEN_FOLDER: MessageId("message.0078"),
        OPEN_LIST: MessageId("message.0079"),
    }
)


# The child gets no console, so nothing it starts can attach to ours.
DETACHED_PROCESS = 0x00000008


def has_console():
    """Whether this process runs in a console (a source run from a terminal)."""
    if os.name != "nt":
        return False
    try:
        import ctypes

        return bool(ctypes.windll.kernel32.GetConsoleWindow())
    except (AttributeError, OSError):
        return False


def open_url(url, shell_open, console=None, popen=subprocess.Popen):
    """Open a VS Code link without touching the terminal of a source run.

    VS Code's link handler (``Code.exe --open-url``) attaches to the caller's
    console and leaves a blank line there (2026-10-04, measured). From a
    console the link goes through ``rundll32`` started without one. The
    installed app has no console and uses ``shell_open`` as before.
    """
    if console is None:
        console = has_console()
    if console:
        try:
            popen(
                [
                    "rundll32.exe",
                    "url.dll,FileProtocolHandler",
                    url.toString(QUrl.ComponentFormattingOption.FullyEncoded),
                ],
                creationflags=DETACHED_PROCESS,
                close_fds=True,
            )
            return True
        except OSError:
            pass
    return bool(shell_open(url))


def session_url(session_id):
    if not isinstance(session_id, str) or not _SESSION_UUID.fullmatch(session_id):
        return None
    url = QUrl()
    url.setScheme("vscode")
    url.setHost(CLAUDE_CODE_EXTENSION)
    url.setPath("/open")
    url.setQuery("session=" + session_id)
    return url


def folder_url(cwd):
    if not isinstance(cwd, str) or not _DRIVE_PATH.match(cwd):
        return None
    url = QUrl()
    url.setScheme("vscode")
    url.setHost("file")
    url.setPath("/" + cwd.replace("\\", "/").rstrip("/"))
    return url


def transcript_cwd(session_id, config_dir=None):
    """The folder the session started in from its transcript, or None."""
    path = locate_transcript(session_id, config_dir)
    if path is None:
        return None
    try:
        with open(path, "rb") as file:
            head = file.read(CWD_SCAN_BYTES)
            size = file.seek(0, os.SEEK_END)
            file.seek(max(0, size - CWD_SCAN_BYTES))
            tail = file.read(CWD_SCAN_BYTES)
    except OSError:
        return None
    return _first_cwd(head.splitlines()) or _first_cwd(reversed(tail.splitlines()))


def _first_cwd(lines):
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        cwd = entry.get("cwd") if isinstance(entry, dict) else None
        if isinstance(cwd, str) and cwd:
            return cwd
    return None


class ClaudeCodeLauncher:
    """Pick and open a Claude Code row's target from where its session runs."""

    def __init__(self, opener, vscode_available=None, cwd_reader=transcript_cwd):
        self.opener = opener
        self._vscode_available = vscode_available
        self.cwd_reader = cwd_reader

    @property
    def vscode_available(self):
        if self._vscode_available is None:
            self._vscode_available = installed_vscode()
        return self._vscode_available

    def action(self, client):
        action = CLIENT_ACTIONS.get(client, OPEN_LIST)
        if action == OPEN_LIST or not self.vscode_available:
            return OPEN_LIST
        return action

    def label(self, client):
        return ACTION_LABELS[self.action(client)]

    def open(self, session_id, client):
        """Return (opened, message); the message tells the user what happened."""
        action = self.action(client)
        if action == OPEN_SESSION and self._open(session_url(session_id)):
            return True, ""
        if action in {OPEN_SESSION, OPEN_FOLDER}:
            if self._open(folder_url(self.cwd_reader(session_id))):
                if action == OPEN_FOLDER:
                    return True, ""
                return True, t("message.0082")
            return False, t("message.0080")
        if client == "terminal":
            return False, t("message.0081")
        return False, ""

    def _open(self, url):
        if url is None:
            return False
        try:
            return bool(self.opener(url))
        except (OSError, RuntimeError, ValueError):
            return False
