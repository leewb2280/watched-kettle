"""Bring a registered desktop app forward, or start it, on an explicit request.

The target is the executable an app registered for its URI scheme or package,
never a window title or process name. Among its windows the one nearest the
top of the Z order wins; a refused activation is reported, not retried on
another window. Nothing is navigated, resumed, or passed as an argument.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

from watched_kettle.localization import t


@dataclass(frozen=True)
class AppInstallation:
    executable: Path
    aumid: str = ""


@dataclass(frozen=True)
class AppOpenResult:
    opened: bool
    message: str = ""
    operation: str = ""


def open_app(name, backend_factory, backend=None):
    """Activate the frontmost window of ``name`` or start its first install."""
    try:
        if backend is None:
            if sys.platform != "win32":
                return AppOpenResult(False, t("launcher.unsupported", app=name))
            backend = backend_factory()
        installations = backend.installations()
        if not installations:
            return AppOpenResult(False, t("launcher.not_found", app=name))
        paths = {os.path.normcase(str(item.executable)) for item in installations}
        for hwnd, executable in backend.windows():
            if os.path.normcase(str(executable)) in paths:
                if backend.activate(hwnd):
                    return AppOpenResult(True, operation="activated")
                return AppOpenResult(False, t("launcher.activate_failed", app=name))
        if backend.start(installations[0]):
            return AppOpenResult(True, operation="started")
        return AppOpenResult(False, t("launcher.start_failed", app=name))
    except (OSError, ValueError, AttributeError, ET.ParseError):
        return AppOpenResult(False, t("launcher.access_failed", app=name))


class WindowsApps:
    """Bounded, on-demand Win32 operations; no title or process-name matching."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        self.ctypes, self.w = ctypes, wintypes
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.callback_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )
        self.user.EnumWindows.argtypes = (self.callback_type, wintypes.LPARAM)
        self.user.EnumWindows.restype = wintypes.BOOL
        for name in ("IsWindowVisible", "IsIconic", "SetForegroundWindow"):
            function = getattr(self.user, name)
            function.argtypes, function.restype = (wintypes.HWND,), wintypes.BOOL
        self.user.GetWindow.argtypes = (wintypes.HWND, wintypes.UINT)
        self.user.GetWindow.restype = wintypes.HWND
        self.user.GetForegroundWindow.restype = wintypes.HWND
        self.user.GetWindowThreadProcessId.argtypes = (
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        )
        self.user.GetWindowThreadProcessId.restype = wintypes.DWORD
        self.user.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
        self.user.ShowWindow.restype = wintypes.BOOL
        self.kernel.OpenProcess.argtypes = (
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        )
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.kernel.QueryFullProcessImageNameW.argtypes = (
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        )
        self.kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL

    def registered_executable(self, scheme):
        """The absolute .exe a URI scheme's open command names, if any."""
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CLASSES_ROOT, scheme + r"\shell\open\command"
            ) as key:
                registered = winreg.QueryValueEx(key, "")[0]
        except OSError:
            return None
        command = os.path.expandvars(registered) if isinstance(registered, str) else ""
        executable = self.command_executable(command)
        return executable if executable and executable.is_file() else None

    def command_executable(self, command):
        if not isinstance(command, str) or not command.strip():
            return None
        c, w = self.ctypes, self.w
        shell = c.WinDLL("shell32")
        shell.CommandLineToArgvW.argtypes = (w.LPCWSTR, c.POINTER(c.c_int))
        shell.CommandLineToArgvW.restype = c.POINTER(w.LPWSTR)
        self.kernel.LocalFree.argtypes = (w.HLOCAL,)
        self.kernel.LocalFree.restype = w.HLOCAL
        argc = c.c_int()
        argv = shell.CommandLineToArgvW(command, c.byref(argc))
        if not argv:
            return None
        try:
            executable = Path(argv[0]) if argc.value else None
            return (
                executable
                if executable
                and executable.is_absolute()
                and executable.suffix.casefold() == ".exe"
                else None
            )
        finally:
            self.kernel.LocalFree(argv)

    def windows(self):
        """Visible unowned top-level windows and their executables, front first."""
        c, w = self.ctypes, self.w
        found = []
        visited = 0

        def visit(hwnd, _parameter):
            nonlocal visited
            visited += 1
            if visited > 4096:
                return False
            if not self.user.IsWindowVisible(hwnd) or self.user.GetWindow(hwnd, 4):
                return True
            pid = w.DWORD()
            self.user.GetWindowThreadProcessId(hwnd, c.byref(pid))
            handle = self.kernel.OpenProcess(0x1000, False, pid.value)
            if not handle:
                return True
            try:
                size = w.DWORD(32768)
                buffer = c.create_unicode_buffer(size.value)
                if self.kernel.QueryFullProcessImageNameW(
                    handle, 0, buffer, c.byref(size)
                ):
                    found.append((int(hwnd), Path(buffer.value)))
            finally:
                self.kernel.CloseHandle(handle)
            return True

        self.user.EnumWindows(self.callback_type(visit), 0)
        return tuple(found)

    def activate(self, hwnd):
        if self.user.IsIconic(hwnd):
            self.user.ShowWindow(hwnd, 9)
        self.user.SetForegroundWindow(hwnd)
        return self.user.GetForegroundWindow() == hwnd

    def start(self, installation):
        # The child gets no console, so a source run's terminal stays clean.
        subprocess.Popen(
            [str(installation.executable)],
            close_fds=True,
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
        )
        return True
