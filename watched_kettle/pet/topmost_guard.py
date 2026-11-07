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

The windows are checked every 5 seconds and healthy ones are left as they
are. A lost style or a sunk window is repaired at once: the whole group is put
back on top of the topmost band, pet first so its bubbles, caption and usage
widget stay above it, then checked again and retried up to twice. A window
covered by another topmost window (the Start menu, the taskbar, another
always-on-top app) is only raised on every 12th check, as the former 60-second
check did, so the pet does not fight them. A full-screen app in the
foreground (a game or video) and an open menu are left alone.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from watched_kettle.application.logging import log_event
from watched_kettle.integrations import windows_zorder

CHECK_INTERVAL_MS = 5_000
RETRY_MS = 1_500
MAX_RETRIES = 2
# Windows covered by another topmost window are raised on every 12th check
# (12 x 5 s, the former 60-second check).
SLOW_CHECK_EVERY = 12
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
        # Per native window, pruned on every check (including hidden windows).
        self._states = {}
        self._results = {}
        self._retries = 0
        self._ticks = 0
        self.retry_timer = QTimer(self)
        self.retry_timer.setSingleShot(True)
        self.retry_timer.setInterval(RETRY_MS)
        self.retry_timer.timeout.connect(
            lambda: self.check("retry", raise_covered=False)
        )
        self.timer = QTimer(self)
        self.timer.setInterval(CHECK_INTERVAL_MS)
        self.timer.timeout.connect(self._tick)
        self.settle_timer = QTimer(self)
        self.settle_timer.setSingleShot(True)
        self.settle_timer.setInterval(SCREEN_SETTLE_MS)
        self.settle_timer.timeout.connect(lambda: self.check("screens"))
        # Offscreen tests and other platforms have no native z-order.
        if QGuiApplication.platformName() != "windows":
            return
        app = QGuiApplication.instance()
        if not isinstance(app, QGuiApplication):
            return
        app.screenAdded.connect(self._screens_changed)
        app.screenRemoved.connect(self._screens_changed)
        app.primaryScreenChanged.connect(self._screens_changed)
        self.timer.start()

    def _screens_changed(self, *_args):
        self.settle_timer.start()

    def _tick(self):
        self._ticks = (self._ticks + 1) % SLOW_CHECK_EVERY
        self.check("timer", raise_covered=self._ticks == 0)

    def check(self, reason="timer", raise_covered=True):
        if reason != "retry":
            self.retry_timer.stop()
            self._retries = 0
        if not self.enabled() or QApplication.activePopupWidget() is not None:
            self.retry_timer.stop()
            return
        windows = [(kind, int(window.winId())) for kind, window in self.windows()]
        own = [hwnd for _kind, hwnd in windows]
        self._states = {h: s for h, s in self._states.items() if h in own}
        self._results = {h: s for h, s in self._results.items() if h in own}
        if not windows or self.zorder.foreground_is_fullscreen(own):
            self.retry_timer.stop()
            return
        # Lost or sunk: repaired, verified and retried. Covered: only raised.
        damaged = set()
        covered = set()
        for kind, hwnd in windows:
            topmost = self.zorder.is_topmost(hwnd)
            if topmost is None:
                continue
            if not topmost:
                if self._states.get(hwnd) != "lost":
                    log_event(
                        "pet.window",
                        "topmost_lost",
                        logging.WARNING,
                        window=kind,
                        reason=reason,
                    )
                self._states[hwnd] = "lost"
                damaged.add(hwnd)
            elif sunk := self.zorder.sunk_under(hwnd, own):
                damaged.add(hwnd)
                if self._states.get(hwnd) != "sunk":
                    self._states[hwnd] = "sunk"
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
                if raise_covered:
                    covered.add(hwnd)
                if self._states.get(hwnd) != "covered":
                    self._states[hwnd] = "covered"
                    log_event("pet.window", "topmost_covered", window=kind)
            else:
                self._states.pop(hwnd, None)
        if not damaged and not covered and not self._results:
            return
        # Raise the whole group in order, otherwise repairing just the pet can
        # put it above its own bubbles. Never activate or move a window.
        raised = {hwnd: self.zorder.raise_topmost(hwnd) for _kind, hwnd in windows}
        failed = False
        for kind, hwnd in windows:
            previous = self._results.get(hwnd)
            if hwnd not in damaged and previous is None:
                continue
            # Another app's topmost window coming back on top is not a failure.
            state = (
                "api_failed"
                if not raised[hwnd]
                else "unverified"
                if self.zorder.is_topmost(hwnd) is None
                else "still_obstructed"
                if (
                    not self.zorder.is_topmost(hwnd)
                    or self.zorder.sunk_under(hwnd, own)
                )
                else "restored"
            )
            if state == "restored":
                log_event("pet.window", "topmost_restored", window=kind, reason=reason)
                self._states.pop(hwnd, None)
                self._results.pop(hwnd, None)
            else:
                failed = True
                if previous != state:
                    log_event(
                        "pet.window",
                        "topmost_restore_failed",
                        logging.WARNING,
                        window=kind,
                        reason=reason,
                        error_code=state,
                    )
                self._results[hwnd] = state
        if failed and self._retries < MAX_RETRIES:
            self._retries += 1
            self.retry_timer.start()
