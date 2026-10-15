"""The pet's always-on-top windows are put back on top and the cause logged."""

import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

from watched_kettle.pet.topmost_guard import TopmostGuard, app_topmost_windows


class FakeZorder:
    def __init__(self, topmost=True, covered=False, fullscreen=False, sunk=None):
        self.topmost = topmost
        self.covered = covered
        self.fullscreen = fullscreen
        self.sunk = sunk
        self.raised = []

    def foreground_is_fullscreen(self, own):
        return self.fullscreen

    def is_topmost(self, hwnd):
        return self.topmost

    def covered_by_topmost(self, hwnd, own):
        return self.covered

    def sunk_under(self, hwnd, own):
        return self.sunk

    def idle_seconds(self):
        return 1800

    def raise_topmost(self, hwnd):
        self.raised.append(hwnd)
        return True


def window(hwnd):
    return SimpleNamespace(winId=lambda: hwnd)


class TopmostGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def guard(self, zorder, enabled=True):
        windows = [("DesktopPet", window(11)), ("SpeechBubbleWindow", window(12))]
        guard = TopmostGuard(lambda: enabled, lambda: windows, zorder=zorder)
        self.addCleanup(guard.deleteLater)
        return guard

    def test_lost_topmost_is_logged_and_put_back_in_order(self):
        zorder = FakeZorder(topmost=False)
        with patch("watched_kettle.pet.topmost_guard.log_event") as log:
            self.guard(zorder).check("screens")

        self.assertEqual(zorder.raised, [11, 12])
        self.assertEqual(
            [call.args[1] for call in log.call_args_list], ["topmost_lost"] * 2
        )
        self.assertEqual(log.call_args.kwargs["reason"], "screens")
        self.assertEqual(log.call_args.kwargs["window"], "SpeechBubbleWindow")

    def test_covered_is_logged_once_while_it_lasts(self):
        zorder = FakeZorder(covered=True)
        guard = self.guard(zorder)
        with patch("watched_kettle.pet.topmost_guard.log_event") as log:
            guard.check()
            guard.check()
            zorder.covered = False
            guard.check()
            zorder.covered = True
            guard.check()

        events = [call.args[1] for call in log.call_args_list]
        self.assertEqual(events, ["topmost_covered"] * 4)
        self.assertEqual(len(zorder.raised), 8)

    def test_sinking_below_ordinary_windows_is_logged_once_per_stretch(self):
        # Covered by a topmost window too, but sinking is the one that matters.
        zorder = FakeZorder(covered=True, sunk=("Chrome_WidgetWin_1", True))
        guard = self.guard(zorder)
        with patch("watched_kettle.pet.topmost_guard.log_event") as log:
            guard.check()
            guard.check()
            zorder.sunk = None
            zorder.covered = False
            guard.check()
            zorder.sunk = ("Chrome_WidgetWin_1", False)
            guard.check("screens")

        events = [call.args[1] for call in log.call_args_list]
        self.assertEqual(events, ["topmost_sunk"] * 4)
        self.assertEqual(len(zorder.raised), 8)
        first, last = log.call_args_list[0].kwargs, log.call_args.kwargs
        self.assertEqual(
            first,
            {
                "window": "DesktopPet",
                "above": "Chrome_WidgetWin_1",
                "hidden": True,
                "idle_s": 1800,
                "reason": "timer",
            },
        )
        self.assertEqual((last["hidden"], last["reason"]), (False, "screens"))

    def test_full_screen_app_or_switched_off_leaves_windows_alone(self):
        for zorder, enabled in (
            (FakeZorder(topmost=False, fullscreen=True), True),
            (FakeZorder(topmost=False), False),
        ):
            with patch("watched_kettle.pet.topmost_guard.log_event") as log:
                self.guard(zorder, enabled).check()
            self.assertEqual(zorder.raised, [])
            log.assert_not_called()

    def test_unknown_style_is_skipped(self):
        zorder = FakeZorder(topmost=None)
        with patch("watched_kettle.pet.topmost_guard.log_event") as log:
            self.guard(zorder).check()

        self.assertEqual(zorder.raised, [])
        log.assert_not_called()

    def test_app_windows_list_the_pet_first_and_only_topmost_ones(self):
        flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
        bubble, pet, plain = QWidget(), QWidget(), QWidget()
        bubble.setWindowFlags(flags | Qt.WindowType.WindowStaysOnTopHint)
        pet.setWindowFlags(flags | Qt.WindowType.WindowStaysOnTopHint)
        plain.setWindowFlags(flags)
        for widget in (bubble, pet, plain):
            widget.show()
            self.addCleanup(widget.close)
        self.app.processEvents()

        rows = app_topmost_windows(first=pet)

        handles = [handle for _kind, handle in rows]
        self.assertIs(handles[0], pet.windowHandle())
        self.assertIn(bubble.windowHandle(), handles)
        self.assertNotIn(plain.windowHandle(), handles)


if __name__ == "__main__":
    unittest.main()
