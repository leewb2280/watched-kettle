"""Tool connection alerts (features/integrations/watch.py)."""

import os
from types import SimpleNamespace as N
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from watched_kettle.features.integrations.watch import (
    KNOWN_TOOLS_KEY,
    ConnectionAlert,
    ConnectionWatch,
)
from watched_kettle.ui.assistant_tray import (
    AssistantSystemTray,
    connection_action_text,
)
from tests.test_pet_preferences import FakeSettings


class Tools:
    def __init__(self):
        self.enabled = {"codex": True, "claude_code": False}
        self.detected = {"codex": True, "claude_code": False}
        self.states = {"codex": "installed", "claude_code": "installed"}
        self.inspected = []

    def inspect(self, tool):
        self.inspected.append(tool)
        state = self.states[tool]
        if isinstance(state, Exception):
            raise state
        return N(state=state)


class ConnectionWatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.settings = FakeSettings()
        self.tools = Tools()
        self.watch = self.make()

    def make(self):
        watch = ConnectionWatch(
            self.settings,
            self.tools.enabled.__getitem__,
            self.tools.inspect,
            self.tools.detected.__getitem__,
        )
        self.announced = []
        watch.announce_ready.connect(self.announced.append)
        self.addCleanup(watch.close)
        return watch

    def test_first_check_only_records_the_tools_already_here(self):
        self.tools.detected["claude_code"] = True

        self.assertEqual(self.watch.check(), ())

        self.assertEqual(self.announced, [])
        self.assertEqual(self.settings.values[KNOWN_TOOLS_KEY], "claude_code,codex")

    def test_broken_hooks_are_told_once_per_run_and_again_after_recovery(self):
        self.watch.check()
        self.tools.states["codex"] = "drifted"

        self.watch.check()
        self.watch.check()
        self.assertEqual(
            self.announced, [ConnectionAlert("codex", "broken", "drifted")]
        )
        self.assertEqual(self.watch.alert("codex").kind, "broken")

        self.tools.states["codex"] = "installed"
        self.watch.check()
        self.assertEqual(self.watch.snapshot, ())
        self.tools.states["codex"] = "not_installed"
        self.watch.check()
        self.assertEqual(len(self.announced), 2)

        # A new run tells a lasting break again.
        self.make().check()
        self.assertEqual(self.announced[0].state, "not_installed")

    def test_turned_off_or_missing_tools_are_not_broken(self):
        self.tools.states["codex"] = "disabled"
        self.tools.states["claude_code"] = "not_installed"
        self.watch.check()
        self.assertEqual(self.announced, [])
        # A switched-off tool's files are not read.
        self.assertEqual(self.tools.inspected, ["codex"])

        self.tools.detected["codex"] = False
        self.tools.states["codex"] = "not_installed"
        self.watch.check()
        self.assertEqual(self.announced, [])

    def test_unreadable_hooks_count_as_broken(self):
        self.tools.states["codex"] = OSError("locked")
        self.watch.check()
        self.assertEqual(self.announced[0].state, "invalid")

    def test_a_tool_installed_later_is_found_once(self):
        self.watch.check()
        self.tools.detected["claude_code"] = True

        self.watch.check()
        self.watch.check()
        self.assertEqual(self.announced, [ConnectionAlert("claude_code", "found")])
        self.assertIn("Claude Code를 찾았어요", self.announced[0].message)
        self.assertEqual(self.watch.alert("claude_code").kind, "found")

        # Turning it on clears the offer; a later run does not offer it again.
        self.tools.enabled["claude_code"] = True
        self.watch.check()
        self.assertIsNone(self.watch.alert("claude_code"))
        self.tools.enabled["claude_code"] = False
        self.make().check()
        self.assertEqual(self.announced, [])

    def test_changed_is_emitted_only_for_a_new_snapshot(self):
        changes = []
        self.watch.changed.connect(changes.append)
        self.watch.check()
        self.tools.states["codex"] = "partial"
        self.watch.check()
        self.watch.check()
        self.assertEqual(changes, [(ConnectionAlert("codex", "broken", "partial"),)])


class TrayConnectionLineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_text_names_each_kind(self):
        self.assertEqual(connection_action_text(()), "")
        self.assertEqual(
            connection_action_text(
                (
                    ConnectionAlert("codex", "broken"),
                    ConnectionAlert("claude_code", "found"),
                )
            ),
            "Codex 다시 연결 필요 · Claude Code 연결 가능",
        )

    def test_tray_line_follows_the_watch_and_opens_connections(self):
        class Watch(QObject):
            changed = Signal(object)
            snapshot = ()

        watch = Watch()
        opened = []
        tray = AssistantSystemTray(
            N(
                refresh=lambda: N(visual_state="idle", active_count=0, visible=True),
                snooze_bubbles=lambda _: None,
                resume_bubbles=lambda: None,
                toggle_visibility=lambda: None,
            ),
            N(enabled=False, snapshot=N(account_hash=""), tray_summary=lambda: ""),
            N(projects=None, router=None, snapshot=N(recent=(), last_message="")),
            opened.append,
            QPixmap(16, 16),
            connections=watch,
        )
        self.addCleanup(tray.close)
        self.assertFalse(tray.connection_action.isVisible())

        watch.snapshot = (ConnectionAlert("claude_code", "broken"),)
        tray.refresh()

        self.assertTrue(tray.connection_action.isVisible())
        self.assertEqual(tray.connection_action.text(), "Claude Code 다시 연결 필요")
        self.assertIn("Claude Code 다시 연결 필요", tray.tray.toolTip())
        tray.connection_action.trigger()
        self.assertEqual(
            [route.value for route in opened], ["integrations_diagnostics"]
        )


if __name__ == "__main__":
    unittest.main()
