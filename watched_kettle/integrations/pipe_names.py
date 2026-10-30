"""Per-user names for the app's local pipes.

Windows named pipes share one machine-wide namespace. With a fixed name, the
first Windows user's app held it, so another user's app could not start, and a
copy run by someone else could take the name to receive this user's events.
Each user gets a random identifier kept in their own runtime folder, which
other users cannot read, and both endpoints end with it.

Hook bridges only read the identifier; the app creates it on first start. The
installer reads the same file to ask the app to quit
(packaging/windows-installer.iss).
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import time

from watched_kettle.branding import APPLICATION_ID

# The same runtime folder as integrations/codex_spool.py, which the pet-only
# edition must not import.
PIPE_ID_PATH = (
    Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    / APPLICATION_ID
    / "runtime"
    / "pipe-id"
)
AGENT_PIPE_PREFIX = "watched-kettle-agent-v2-"
INSTANCE_PIPE_PREFIX = "watched-kettle-instance-v2-"
# Versions before 1.0 listened here; Setup still asks them to quit. The app
# also falls back to them when it cannot store an identifier.
LEGACY_INSTANCE_PIPE = "watched-kettle-instance-v1"
LEGACY_AGENT_PIPE = "watched-kettle-agent-v1"
_PIPE_ID = re.compile(r"[0-9a-f]{32}")


def read_pipe_id(path=PIPE_ID_PATH):
    """The stored identifier, or "" before the app has run."""
    try:
        value = Path(path).read_text(encoding="ascii").strip()
    except OSError, UnicodeDecodeError:
        return ""
    return value if _PIPE_ID.fullmatch(value) else ""


def ensure_pipe_id(path=PIPE_ID_PATH):
    """Return the stored identifier, creating it when missing or damaged.

    Creation and repair run under a lock on a side file, and the value is
    read back before use, so apps starting together agree on one identifier.
    Returns "" when it cannot be stored; callers then fall back to the
    shared pre-1.0 names, which every process can still agree on.
    """
    path = Path(path)
    value = read_pipe_id(path)
    if value:
        return value
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _locked(path.with_name(path.name + ".lock")):
            value = read_pipe_id(path)
            if value:
                return value
            temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
            temporary.write_text(os.urandom(16).hex(), encoding="ascii")
            _replace(temporary, path)
    except OSError:
        return ""
    return read_pipe_id(path)


def _replace(source, target):
    # Windows refuses to replace a file another process has open for a
    # moment, such as a hook bridge reading the identifier.
    for _attempt in range(40):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            time.sleep(0.025)
    os.replace(source, target)


class _locked:
    """An exclusive lock on ``path`` that Windows drops if the process dies."""

    def __init__(self, path):
        self.stream = open(path, "a+b")

    def __enter__(self):
        import msvcrt

        try:
            # LK_LOCK retries for about ten seconds before raising OSError.
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_LOCK, 1)
        except OSError:
            self.stream.close()
            raise
        return self

    def __exit__(self, *_error):
        import msvcrt

        try:
            self.stream.seek(0)
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self.stream.close()


def agent_pipe_name(path=PIPE_ID_PATH):
    """The hook pipe; "" when no identifier exists yet (nothing is listening)."""
    override = os.environ.get("WATCHED_KETTLE_SERVER_NAME")
    if override:
        return override
    value = read_pipe_id(path)
    return AGENT_PIPE_PREFIX + value if value else ""


def instance_pipe_name(path=PIPE_ID_PATH):
    override = os.environ.get("WATCHED_KETTLE_INSTANCE_SERVER_NAME")
    if override:
        return override
    value = ensure_pipe_id(path)
    return INSTANCE_PIPE_PREFIX + value if value else LEGACY_INSTANCE_PIPE
