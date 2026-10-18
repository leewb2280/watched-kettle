"""Optional current-user Windows startup registration."""

from __future__ import annotations

from watched_kettle.localization import t

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys

from watched_kettle.branding import APPLICATION_ID, LEGACY_APPLICATION_ID


RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = APPLICATION_ID
LEGACY_RUN_VALUE_NAME = LEGACY_APPLICATION_ID
LAUNCHER_NAME = f"{APPLICATION_ID}.exe"


def installed_launcher(executable):
    """Return the installer's stable launcher for ``executable``, if any.

    The installer puts the selected edition in ``{app}/runtime/<edition>`` and a
    launcher at ``{app}/WatchedKettle.exe``. Switching editions moves the real
    executable, so the startup entry points at the launcher instead.
    """
    runtime = Path(executable).parent.parent
    if runtime.name.lower() != "runtime":
        return None
    launcher = runtime.parent / LAUNCHER_NAME
    return launcher if launcher.is_file() else None


@dataclass(frozen=True)
class StartupRegistrationStatus:
    supported: bool
    enabled: bool
    matches_current_app: bool
    expected_command: str
    current_command: str = ""


class WindowsRunRegistry:
    def read(self, name):
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                RUN_KEY_PATH,
                0,
                winreg.KEY_READ,
            ) as key:
                value, _ = winreg.QueryValueEx(key, name)
                return str(value or "")
        except FileNotFoundError:
            return ""

    def write(self, name, command):
        import winreg

        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            RUN_KEY_PATH,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(command))

    def delete(self, name):
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                RUN_KEY_PATH,
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.DeleteValue(key, name)
        except FileNotFoundError:
            return


class WindowsStartupRegistration:
    """Inspect and explicitly toggle one current-user Run entry."""

    def __init__(
        self,
        registry=None,
        platform=None,
        executable=None,
        source_entry=None,
        frozen=None,
    ):
        self.platform = str(platform if platform is not None else os.name)
        self.registry = registry or WindowsRunRegistry()
        self.executable = Path(executable or sys.executable).resolve()
        self.source_entry = Path(
            source_entry or Path(__file__).resolve().parents[2] / "main.py"
        ).resolve()
        self.frozen = bool(getattr(sys, "frozen", False) if frozen is None else frozen)

    @property
    def supported(self):
        return self.platform == "nt"

    def expected_command(self):
        if self.frozen:
            arguments = [str(installed_launcher(self.executable) or self.executable)]
        else:
            pythonw = self.executable.with_name("pythonw.exe")
            launcher = pythonw if pythonw.exists() else self.executable
            arguments = [str(launcher), str(self.source_entry)]
        return subprocess.list2cmdline(arguments)

    def inspect(self):
        expected = self.expected_command()
        if not self.supported:
            return StartupRegistrationStatus(
                supported=False,
                enabled=False,
                matches_current_app=False,
                expected_command=expected,
            )
        current = self.registry.read(RUN_VALUE_NAME).strip()
        return StartupRegistrationStatus(
            supported=True,
            enabled=bool(current),
            matches_current_app=(current == expected),
            expected_command=expected,
            current_command=current,
        )

    def set_enabled(self, enabled):
        if not self.supported:
            raise OSError(t("message.0130"))
        if enabled:
            self.registry.write(RUN_VALUE_NAME, self.expected_command())
        else:
            self.registry.delete(RUN_VALUE_NAME)
        return self.inspect()

    def migrate_legacy_entry(self):
        """Move a Private Beta Run value to the current name (ADR 0005)."""
        if not self.supported or not self.registry.read(LEGACY_RUN_VALUE_NAME).strip():
            return False
        if not self.registry.read(RUN_VALUE_NAME).strip():
            self.registry.write(RUN_VALUE_NAME, self.expected_command())
        self.registry.delete(LEGACY_RUN_VALUE_NAME)
        return True
