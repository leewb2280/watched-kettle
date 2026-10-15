"""Windows window-order helpers; every call is a no-op on other platforms.

Windows only lets the foreground process bring another process's window to
the front, so the pet (which owns the click) grants that right to the
settings window before asking it to show itself.

The topmost helpers let the pet tell why an always-on-top window ended up
behind others: Windows dropped its topmost style, another topmost window was
activated later and now sits above it, or the window kept the style but sank
below ordinary windows (seen on Windows 11 together with other apps' topmost
windows, so not caused by the pet). The idle time says whether it happened
while nobody was using the computer.
"""

from __future__ import annotations

import sys

GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
HWND_TOPMOST = -1
GW_HWNDPREV = 3
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_NOOWNERZORDER = 0x0200
MONITOR_DEFAULTTONEAREST = 2
DWMWA_CLOAKED = 14
# The desktop takes the foreground when clicked and covers the whole monitor.
DESKTOP_CLASSES = {"Progman", "WorkerW"}
# Enough to pass every window above ours on a busy desktop.
MAX_WINDOWS_ABOVE = 512

_api = None


def _windows():
    """(ctypes, wintypes, user32, dwmapi, kernel32) with typed calls, or None.

    Private library handles, so these signatures do not change the ones other
    modules set on ``ctypes.windll.user32``.
    """
    global _api
    if _api is not None:
        return _api or None
    _api = False
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        dwmapi = ctypes.WinDLL("dwmapi")
        hwnd, rect = wintypes.HWND, ctypes.POINTER(wintypes.RECT)
        user32.AllowSetForegroundWindow.argtypes = (wintypes.DWORD,)
        user32.AllowSetForegroundWindow.restype = wintypes.BOOL
        user32.GetWindowLongPtrW.argtypes = (hwnd, ctypes.c_int)
        user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.SetWindowPos.argtypes = (
            (hwnd, hwnd) + (ctypes.c_int,) * 4 + (wintypes.UINT,)
        )
        user32.SetWindowPos.restype = wintypes.BOOL
        user32.GetForegroundWindow.restype = hwnd
        user32.GetWindow.argtypes = (hwnd, wintypes.UINT)
        user32.GetWindow.restype = hwnd
        user32.IsWindowVisible.argtypes = (hwnd,)
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.GetWindowRect.argtypes = (hwnd, rect)
        user32.GetWindowRect.restype = wintypes.BOOL
        user32.GetClassNameW.argtypes = (hwnd, wintypes.LPWSTR, ctypes.c_int)
        user32.MonitorFromWindow.argtypes = (hwnd, wintypes.DWORD)
        user32.MonitorFromWindow.restype = wintypes.HMONITOR
        user32.GetMonitorInfoW.argtypes = (wintypes.HMONITOR, ctypes.c_void_p)
        user32.GetMonitorInfoW.restype = wintypes.BOOL
        user32.GetLastInputInfo.argtypes = (ctypes.c_void_p,)
        user32.GetLastInputInfo.restype = wintypes.BOOL
        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.GetTickCount.restype = wintypes.DWORD
        dwmapi.DwmGetWindowAttribute.argtypes = (
            hwnd,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
        )
    except (ImportError, AttributeError, OSError):
        return None
    _api = (ctypes, wintypes, user32, dwmapi, kernel32)
    return _api


def allow_foreground(pid):
    """Let process ``pid`` take the foreground once; False when not granted."""
    api = _windows()
    if api is None or not pid:
        return False
    try:
        return bool(api[2].AllowSetForegroundWindow(int(pid)))
    except (OSError, ValueError, OverflowError):
        return False


def is_topmost(hwnd):
    """Whether the window still has the topmost style; None when unknown."""
    api = _windows()
    if api is None or not hwnd:
        return None
    ctypes = api[0]
    # Zero is both "no extended style" and failure; the last error tells.
    ctypes.set_last_error(0)
    style = api[2].GetWindowLongPtrW(int(hwnd), GWL_EXSTYLE)
    if not style and ctypes.get_last_error():
        return None
    return bool(style & WS_EX_TOPMOST)


def raise_topmost(hwnd):
    """Make the window topmost and the top of the topmost windows."""
    api = _windows()
    if api is None or not hwnd:
        return False
    flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER
    return bool(api[2].SetWindowPos(int(hwnd), HWND_TOPMOST, 0, 0, 0, 0, flags))


def _rect(api, hwnd):
    ctypes, wintypes, user32 = api[:3]
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return rect.left, rect.top, rect.right, rect.bottom


def _cloaked(api, hwnd):
    ctypes, wintypes, _user32, dwmapi = api[:4]
    value = wintypes.DWORD()
    result = dwmapi.DwmGetWindowAttribute(
        hwnd, DWMWA_CLOAKED, ctypes.byref(value), ctypes.sizeof(value)
    )
    return result == 0 and bool(value.value)


def _class_name(api, hwnd):
    ctypes, _wintypes, user32 = api[:3]
    name = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(hwnd, name, len(name))
    return name.value


def _windows_above(api, hwnd, own):
    """(hwnd, topmost, overlaps) for other visible windows above this one."""
    user32 = api[2]
    mine = _rect(api, int(hwnd))
    if mine is None:
        return
    own = {int(item) for item in own}
    above = user32.GetWindow(int(hwnd), GW_HWNDPREV)
    for _ in range(MAX_WINDOWS_ABOVE):
        if not above:
            return
        if (
            above not in own
            and user32.IsWindowVisible(above)
            and not _cloaked(api, above)
        ):
            other = _rect(api, above)
            if other is not None and other[0] < other[2] and other[1] < other[3]:
                overlaps = (
                    other[0] < mine[2]
                    and mine[0] < other[2]
                    and other[1] < mine[3]
                    and mine[1] < other[3]
                )
                topmost = user32.GetWindowLongPtrW(above, GWL_EXSTYLE) & WS_EX_TOPMOST
                yield above, bool(topmost), overlaps
        above = user32.GetWindow(above, GW_HWNDPREV)


def covered_by_topmost(hwnd, own=()):
    """Whether another visible topmost window above this one overlaps it."""
    api = _windows()
    if api is None or not hwnd:
        return False
    return any(
        topmost and overlaps
        for _above, topmost, overlaps in _windows_above(api, hwnd, own)
    )


def sunk_under(hwnd, own=()):
    """(class name, overlaps) of an ordinary window above this one, or None.

    Ordinary windows always sit below topmost ones, so any of them above a
    window that still has the topmost style means the window sank. One that
    overlaps it, and so actually hides it, is reported first.
    """
    api = _windows()
    if api is None or not hwnd:
        return None
    first = None
    for above, topmost, overlaps in _windows_above(api, hwnd, own):
        if topmost:
            continue
        if overlaps:
            return _class_name(api, above), True
        if first is None:
            first = above
    if first is None:
        return None
    return _class_name(api, first), False


def idle_seconds():
    """Seconds since the last keyboard or mouse input; None when unknown."""
    api = _windows()
    if api is None:
        return None
    ctypes, wintypes, user32, _dwmapi, kernel32 = api

    class LastInputInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    info = LastInputInfo()
    info.cbSize = ctypes.sizeof(LastInputInfo)
    if not user32.GetLastInputInfo(ctypes.byref(info)):
        return None
    # Both are 32-bit tick counts that wrap after 49.7 days.
    return ((kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) // 1000


def foreground_is_fullscreen(own=()):
    """Whether another app's foreground window fills its whole monitor.

    Games and full-screen video are left alone instead of having the pet
    raised above them.
    """
    api = _windows()
    if api is None:
        return False
    ctypes, wintypes, user32 = api[:3]
    foreground = user32.GetForegroundWindow()
    if not foreground or foreground in {int(item) for item in own}:
        return False
    if _class_name(api, foreground) in DESKTOP_CLASSES:
        return False
    window = _rect(api, foreground)

    class MonitorInfo(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    info = MonitorInfo()
    info.cbSize = ctypes.sizeof(MonitorInfo)
    monitor = user32.MonitorFromWindow(foreground, MONITOR_DEFAULTTONEAREST)
    if window is None or not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return False
    screen = info.rcMonitor
    return (
        window[0] <= screen.left
        and window[1] <= screen.top
        and window[2] >= screen.right
        and window[3] >= screen.bottom
    )
