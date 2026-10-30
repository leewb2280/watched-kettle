"""Absolute program paths that never come from the current folder.

``CreateProcess``, ``cmd`` and ``shutil.which`` look in the working directory
before ``PATH``. Hooks and the status line run with the user's project as that
directory, so a ``bash.cmd`` or ``powershell.exe`` placed in a repository would
run instead of the real program. Callers name programs by absolute path, and
``find_on_path`` reads only absolute ``PATH`` entries.

The hook bridge imports this module, so it stays free of heavy imports
(ADR 0004).
"""

from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath

DEFAULT_SYSTEM_ROOT = r"C:\Windows"
_DEFAULT_PATHEXT = ".COM;.EXE;.BAT;.CMD"


def environment_value(environment, name):
    """Read ``name`` case-insensitively; ``dict(os.environ)`` keeps upper case."""
    environment = os.environ if environment is None else environment
    value = environment.get(name)
    if value is None:
        value = environment.get(name.upper())
    return value if isinstance(value, str) else ""


def system_root(environment=None):
    value = environment_value(environment, "SystemRoot").strip()
    return value if _is_absolute(value) else DEFAULT_SYSTEM_ROOT


def system_program(*parts, environment=None):
    """``%SystemRoot%`` joined with ``parts``, e.g. ``("System32", "rundll32.exe")``."""
    return str(PureWindowsPath(system_root(environment), *parts))


def powershell_path(environment=None):
    return system_program(
        "System32",
        "WindowsPowerShell",
        "v1.0",
        "powershell.exe",
        environment=environment,
    )


def find_on_path(name, environment=None, *, extensions=None):
    """First ``name`` (with ``extensions``, default ``PATHEXT``) on ``PATH``.

    Relative entries resolve against the current folder, so they are skipped.
    """
    if extensions is None:
        pathext = environment_value(environment, "PATHEXT") or _DEFAULT_PATHEXT
        extensions = [value for value in pathext.split(";") if value]
    names = [name] if Path(name).suffix else [name + ext for ext in extensions]
    for entry in environment_value(environment, "PATH").split(os.pathsep):
        entry = entry.strip().strip('"')
        if not _is_absolute(entry):
            continue
        for candidate in names:
            path = Path(entry) / candidate
            if path.is_file():
                return str(path)
    return ""


def is_absolute_file(value):
    return isinstance(value, str) and _is_absolute(value) and Path(value).is_file()


def _is_absolute(value):
    # PureWindowsPath treats "\\server\share" as absolute; callers that must
    # stay local check is_network_path separately.
    return bool(value) and PureWindowsPath(value).is_absolute()


def is_network_path(value):
    """UNC, device (``\\\\?\\``, ``\\\\.\\``) and other non-drive paths."""
    text = str(value).replace("/", "\\")
    if text.startswith("\\\\"):
        return True
    drive = PureWindowsPath(text).drive
    return bool(drive) and not (len(drive) == 2 and drive[1] == ":")
