"""Bring VS Code forward for the pet's "Open Claude Code" double-click.

Claude Code runs inside VS Code here (panel or terminal), so the gesture
returns to the frontmost VS Code window as it is. It never opens the Claude
Code extension's ``/open`` link: without a session that link creates a new
conversation tab on every call (extension 2.1.301, read 2026-10-18). Nor does
it pick a session or folder from recent hook events. With no window open,
VS Code starts with no arguments and restores its last workspace itself.
"""

from __future__ import annotations

import os

from watched_kettle.integrations.windows_apps import (
    AppInstallation,
    WindowsApps,
    open_app,
)


def installed_vscode():
    """Whether the stable VS Code registered its ``vscode`` URI scheme."""
    if os.name != "nt":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "vscode"):
            return True
    except OSError:
        return False


def open_vscode(backend=None):
    return open_app("VS Code", WindowsVSCodeLauncher, backend)


class WindowsVSCodeLauncher(WindowsApps):
    def installations(self):
        executable = self.registered_executable("vscode")
        return (AppInstallation(executable),) if executable else ()
