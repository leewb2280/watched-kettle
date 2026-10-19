"""System-wide shortcuts that toggle the pet's and widget's click-through.

A shortcut is a thread hotkey (``RegisterHotKey`` with no window): the pet
window is recreated when its flags change, so a window-bound hotkey would be
lost. ``WM_HOTKEY`` then arrives in the GUI thread's queue, where Qt hands it
to a native event filter. The accepted spelling is in ``preferences.hotkeys``.
Logs name the shortcut and its status, never the keys.
"""

from __future__ import annotations

import itertools
import logging
import sys
import weakref

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication, QObject
from PySide6.QtCore import QTimer, Signal
from shiboken6 import isValid

from watched_kettle.application.logging import log_event
from watched_kettle.preferences.hotkeys import parse_hotkey

MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
ERROR_HOTKEY_ALREADY_REGISTERED = 1409

UNASSIGNED = "unassigned"
REGISTERED = "registered"
IN_USE = "in_use"
INVALID = "invalid"
UNAVAILABLE = "unavailable"


def _user32():
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.RegisterHotKey.argtypes = (
        wintypes.HWND,
        ctypes.c_int,
        wintypes.UINT,
        wintypes.UINT,
    )
    user32.RegisterHotKey.restype = wintypes.BOOL
    user32.UnregisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int)
    user32.UnregisterHotKey.restype = wintypes.BOOL
    return user32


def _last_error():
    import ctypes

    return ctypes.get_last_error()


class _HotkeyFilter(QAbstractNativeEventFilter):
    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) != b"windows_generic_MSG":
            return False, 0
        from ctypes import wintypes

        msg = wintypes.MSG.from_address(int(message))
        if msg.message != WM_HOTKEY or msg.hWnd is not None:
            return False, 0
        identifier = int(msg.wParam)
        for owner in tuple(_owners):
            if isValid(owner) and owner._dispatch(identifier):
                return True, 0
        return False, 0


# Qt keeps only a raw pointer to a native filter, so one filter serves every
# owner and is never freed: a filter collected with its owner would crash the
# next native event. Identifiers are unique per thread across owners.
_filter = None
_owners: "weakref.WeakSet[GlobalHotkeys]" = weakref.WeakSet()
_identifiers = itertools.count(1)


def _install_filter(app):
    global _filter
    if _filter is None:
        _filter = _HotkeyFilter()
        app.installNativeEventFilter(_filter)


class GlobalHotkeys(QObject):
    """Named shortcuts; ``triggered(name)`` fires on the GUI thread."""

    triggered = Signal(str)

    def __init__(self, parent=None, *, api=None, last_error=_last_error):
        super().__init__(parent)
        self.api = api if api is not None else _user32()
        self.last_error = last_error
        self.statuses = {}
        self._ids = {}
        self._names = {}
        app = QCoreApplication.instance()
        if self.api is not None and app is not None:
            _install_filter(app)
            _owners.add(self)

    def status(self, name):
        return self.statuses.get(name, UNASSIGNED)

    def register(self, name, text):
        """Replace ``name``'s shortcut with ``text`` and return its status."""
        self.unregister(name)
        parsed = parse_hotkey(text) if text else None
        if not text:
            status = UNASSIGNED
        elif parsed is None:
            status = INVALID
        elif self.api is None:
            status = UNAVAILABLE
        else:
            identifier = next(_identifiers)
            modifiers, virtual_key = parsed
            if self.api.RegisterHotKey(
                None, identifier, modifiers | MOD_NOREPEAT, virtual_key
            ):
                self._ids[name] = identifier
                self._names[identifier] = name
                status = REGISTERED
            elif self.last_error() == ERROR_HOTKEY_ALREADY_REGISTERED:
                status = IN_USE
            else:
                status = UNAVAILABLE
        self.statuses[name] = status
        log_event(
            "hotkeys",
            "registered",
            logging.INFO if status in (REGISTERED, UNASSIGNED) else logging.WARNING,
            operation=name,
            state=status,
        )
        return status

    def unregister(self, name):
        identifier = self._ids.pop(name, None)
        self.statuses.pop(name, None)
        if identifier is None:
            return
        self._names.pop(identifier, None)
        self.api.UnregisterHotKey(None, identifier)

    def close(self):
        for name in tuple(self._ids):
            self.unregister(name)
        self.statuses.clear()
        _owners.discard(self)

    def _dispatch(self, identifier):
        name = self._names.get(identifier)
        if name is None:
            return False
        # Leave the native filter before any window flag changes.
        QTimer.singleShot(0, self, lambda: self.triggered.emit(name))
        return True
