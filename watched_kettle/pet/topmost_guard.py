"""Keep the pet's always-on-top windows above other windows on Windows.

Users saw the pet fall behind other windows after a while. Three causes look
the same on screen and are logged apart so real use can tell which one it is:

- ``topmost_lost``: Windows no longer has the topmost style on the window
  (a recreated native window, an Explorer restart, a display change).
- ``topmost_covered``: the style is there, but another topmost window that was
  activated later (another always-on-top app, the taskbar) sits above it.
- ``topmost_sunk``: the style is there, but the window sits below ordinary
  windows. Seen after a long idle stretch, with other apps' topmost windows
  sunk at the same time. The log names the class of the ordinary window above
  it, whether that window hides it, and how long input had been idle.

Every check puts the windows back on top of the topmost band, pet first so
its bubbles, caption and usage widget stay above it. A full-screen app in the
foreground (a game or video) and an open menu are left alone.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from watched_kettle.application.logging import log_event
from watched_kettle.integrations import windows_zorder

CHECK_INTERVAL_MS = 60_000
# Lets a new screen layout settle before the windows are checked again.
SCREEN_SETTLE_MS = 1_500


def app_topmost_windows(first=None):
    """(kind, QWindow) for this app's visible always-on-top windows.

    ``first`` (the pet) is listed before the rest. Kinds are class names
    only, never titles or text.
    """
    rows = []
    seen = set()
    for widget in QApplication.topLevelWidgets():
        handle = widget.windowHandle()
        if handle is not None:
            seen.add(id(handle))
            rows.append((type(widget).__name__, handle, widget is first))
    for window in QGuiApplication.topLevelWindows():
        if id(window) not in seen:
            rows.append((type(window).__name__, window, False))
    rows.sort(key=lambda row: not row[2])
    return [
        (kind, window)
        for kind, window, _first in rows
        if window.isVisible() and window.flags() & Qt.WindowType.WindowStaysOnTopHint
    ]


class TopmostGuard(QObject):
    def __init__(self, enabled, windows, parent=None, zorder=windows_zorder):
        super().__init__(parent)
        self.enabled = enabled
        self.windows = windows
        self.zorder = zorder
        # The last logged state per window kind, so a stretch is logged once.
        self._states = {}
        self.timer = QTimer(self)
        self.timer.setInterval(CHECK_INTERVAL_MS)
        self.timer.timeout.connect(lambda: self.check("timer"))
        self.settle_timer = QTimer(self)
        self.settle_timer.setSingleShot(True)
        self.settle_timer.setInterval(SCREEN_SETTLE_MS)
        self.settle_timer.timeout.connect(lambda: self.check("screens"))
        # Offscreen tests and other platforms have no native z-order.
        if QGuiApplication.platformName() != "windows":
            return
        app = QGuiApplication.instance()
        app.screenAdded.connect(self._screens_changed)
        app.screenRemoved.connect(self._screens_changed)
        app.primaryScreenChanged.connect(self._screens_changed)
        self.timer.start()

    def _screens_changed(self, *_args):
        self.settle_timer.start()

    def check(self, reason="timer"):
        if not self.enabled() or QApplication.activePopupWidget() is not None:
            return
        windows = [(kind, int(window.winId())) for kind, window in self.windows()]
        own = [hwnd for _kind, hwnd in windows]
        if not windows or self.zorder.foreground_is_fullscreen(own):
            return
        for kind, hwnd in windows:
            topmost = self.zorder.is_topmost(hwnd)
            if topmost is None:
                continue
            if not topmost:
                log_event(
                    "pet.window",
                    "topmost_lost",
                    logging.WARNING,
                    window=kind,
                    reason=reason,
                )
                self._states.pop(kind, None)
            elif sunk := self.zorder.sunk_under(hwnd, own):
                if self._states.get(kind) != "sunk":
                    self._states[kind] = "sunk"
                    above, hidden = sunk
                    log_event(
                        "pet.window",
                        "topmost_sunk",
                        logging.WARNING,
                        window=kind,
                        above=above,
                        hidden=hidden,
                        idle_s=self.zorder.idle_seconds(),
                        reason=reason,
                    )
            elif self.zorder.covered_by_topmost(hwnd, own):
                if self._states.get(kind) != "covered":
                    self._states[kind] = "covered"
                    log_event("pet.window", "topmost_covered", window=kind)
            else:
                self._states.pop(kind, None)
            self.zorder.raise_topmost(hwnd)
