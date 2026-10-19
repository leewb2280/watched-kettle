"""Global shortcuts: a strict spelling, honest statuses and a clean shutdown."""

import sys
import unittest
from unittest.mock import Mock

from PySide6.QtWidgets import QApplication

from watched_kettle.integrations import windows_hotkeys
from watched_kettle.integrations.windows_hotkeys import (
    ERROR_HOTKEY_ALREADY_REGISTERED,
    MOD_NOREPEAT,
    GlobalHotkeys,
)
from watched_kettle.preferences.hotkeys import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_SHIFT,
    format_hotkey,
    parse_hotkey,
)


class HotkeyTextTests(unittest.TestCase):
    def test_accepts_ctrl_or_alt_with_one_letter_digit_or_function_key(self):
        self.assertEqual(parse_hotkey("Ctrl+Alt+P"), (MOD_CONTROL | MOD_ALT, ord("P")))
        self.assertEqual(parse_hotkey("Alt+7"), (MOD_ALT, ord("7")))
        self.assertEqual(
            parse_hotkey("Ctrl+Shift+F24"), (MOD_CONTROL | MOD_SHIFT, 0x87)
        )
        self.assertEqual(parse_hotkey("Ctrl+F1"), (MOD_CONTROL, 0x70))

    def test_rejects_shift_only_unknown_repeated_and_malformed_shortcuts(self):
        for text in (
            "",
            "P",
            "Shift+P",
            "Win+P",
            "Ctrl+Ctrl+P",
            "Ctrl+Alt",
            "Ctrl+Space",
            "Ctrl+F25",
            "Ctrl++",
            "Ctrl+" + "A" * 40,
            None,
            123,
        ):
            self.assertIsNone(parse_hotkey(text), text)

    def test_format_is_canonical_order_and_case(self):
        self.assertEqual(format_hotkey("shift+alt+ctrl+p"), "Ctrl+Alt+Shift+P")
        self.assertEqual(format_hotkey("alt+f5"), "Alt+F5")
        self.assertEqual(format_hotkey("Shift+P"), "")


class GlobalHotkeyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make(self, error=0):
        api = Mock()
        api.RegisterHotKey.return_value = True
        hotkeys = GlobalHotkeys(api=api, last_error=lambda: error)
        self.addCleanup(hotkeys.close)
        return hotkeys, api

    def test_register_replaces_previous_shortcut_and_reports_status(self):
        hotkeys, api = self.make()
        self.assertEqual(hotkeys.register("pet_lock", "Ctrl+Alt+P"), "registered")
        first = hotkeys._ids["pet_lock"]
        api.RegisterHotKey.assert_called_once_with(
            None, first, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, ord("P")
        )
        self.assertEqual(hotkeys.register("pet_lock", "Ctrl+Alt+L"), "registered")
        api.UnregisterHotKey.assert_called_once_with(None, first)
        self.assertNotEqual(hotkeys._ids["pet_lock"], first)
        self.assertEqual(hotkeys.status("pet_lock"), "registered")

    def test_empty_invalid_and_taken_shortcuts_are_not_registered(self):
        hotkeys, api = self.make(error=ERROR_HOTKEY_ALREADY_REGISTERED)
        self.assertEqual(hotkeys.register("pet_lock", ""), "unassigned")
        self.assertEqual(hotkeys.register("pet_lock", "Shift+P"), "invalid")
        api.RegisterHotKey.assert_not_called()
        api.RegisterHotKey.return_value = False
        self.assertEqual(hotkeys.register("pet_lock", "Ctrl+Alt+P"), "in_use")
        self.assertEqual(hotkeys.status("pet_lock"), "in_use")
        hotkeys.last_error = lambda: 5
        self.assertEqual(hotkeys.register("pet_lock", "Ctrl+Alt+P"), "unavailable")
        hotkeys.close()
        api.UnregisterHotKey.assert_not_called()

    def test_dispatch_emits_the_name_after_leaving_the_filter(self):
        hotkeys, _api = self.make()
        hotkeys.register("pet_lock", "Ctrl+Alt+P")
        hotkeys.register("widget_lock", "Ctrl+Alt+W")
        seen = []
        hotkeys.triggered.connect(seen.append)
        self.assertTrue(hotkeys._dispatch(hotkeys._ids["widget_lock"]))
        self.assertFalse(hotkeys._dispatch(0))
        self.assertEqual(seen, [])
        self.app.processEvents()
        self.assertEqual(seen, ["widget_lock"])

    def test_close_unregisters_everything_once(self):
        hotkeys, api = self.make()
        hotkeys.register("pet_lock", "Ctrl+Alt+P")
        hotkeys.register("widget_lock", "Ctrl+Alt+W")
        identifier = hotkeys._ids["pet_lock"]
        hotkeys.close()
        hotkeys.close()
        self.assertEqual(api.UnregisterHotKey.call_count, 2)
        self.assertFalse(hotkeys._dispatch(identifier))

    def test_owners_share_one_filter_and_never_reuse_identifiers(self):
        first, _api = self.make()
        second, _api = self.make()
        first.register("pet_lock", "Ctrl+Alt+P")
        second.register("pet_lock", "Ctrl+Alt+L")
        self.assertNotEqual(first._ids["pet_lock"], second._ids["pet_lock"])
        self.assertIsNotNone(windows_hotkeys._filter)
        filter_before = windows_hotkeys._filter
        third, _api = self.make()
        self.assertIs(windows_hotkeys._filter, filter_before)
        del third
        import gc

        gc.collect()
        self.app.processEvents()

    def test_without_windows_api_shortcuts_are_unavailable(self):
        hotkeys = GlobalHotkeys(api=None)
        hotkeys.api = None
        self.addCleanup(hotkeys.close)
        self.assertEqual(hotkeys.register("pet_lock", "Ctrl+Alt+P"), "unavailable")
        self.assertEqual(hotkeys.register("pet_lock", ""), "unassigned")

    def test_logs_never_contain_the_keys(self):
        hotkeys, _api = self.make()
        with self.assertLogs("watched_kettle", level="INFO") as logs:
            hotkeys.register("pet_lock", "Ctrl+Alt+P")
        record = logs.records[-1].structured_event
        self.assertEqual(record["operation"], "pet_lock")
        self.assertNotIn("Ctrl", str(record))


@unittest.skipUnless(sys.platform == "win32", "Windows thread hotkeys")
class WindowsHotkeyTests(unittest.TestCase):
    """A real thread hotkey on an unused combination; no keys are pressed."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_thread_hotkey_message_reaches_the_native_filter(self):
        import ctypes
        from ctypes import wintypes

        hotkeys = GlobalHotkeys()
        self.addCleanup(hotkeys.close)
        status = hotkeys.register("pet_lock", "Ctrl+Alt+Shift+F24")
        if status == "in_use":
            self.skipTest("another app owns the probe shortcut")
        self.assertEqual(status, "registered")
        rival = GlobalHotkeys()
        self.addCleanup(rival.close)
        self.assertEqual(rival.register("other", "Ctrl+Alt+Shift+F24"), "in_use")
        seen = []
        hotkeys.triggered.connect(seen.append)
        user32 = ctypes.WinDLL("user32")
        user32.PostThreadMessageW.argtypes = (
            wintypes.DWORD,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )
        user32.PostThreadMessageW(
            ctypes.WinDLL("kernel32").GetCurrentThreadId(),
            windows_hotkeys.WM_HOTKEY,
            hotkeys._ids["pet_lock"],
            0,
        )
        for _ in range(5):
            self.app.processEvents()
        self.assertEqual(seen, ["pet_lock"])
