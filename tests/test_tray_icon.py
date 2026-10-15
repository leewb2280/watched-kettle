"""The tray icon shows the pet's face with a dot for work or attention."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication

from watched_kettle.ui import design_tokens
from watched_kettle.ui.assistant_tray import (
    TRAY_ICON_SIZES,
    badged_icon,
    source_dot_icon,
)


class TrayIconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def frame(self):
        pixmap = QPixmap(192, 208)
        pixmap.fill(QColor("#808080"))
        return pixmap

    def corner(self, icon, size=32):
        image = icon.pixmap(QSize(size, size)).toImage()
        return image.pixelColor(size - 6, size - 6)

    def test_each_size_is_square_and_states_pick_their_badge_color(self):
        plain = badged_icon(self.frame(), None)
        self.assertEqual(
            sorted(size.width() for size in plain.availableSizes()),
            list(TRAY_ICON_SIZES),
        )
        self.assertEqual(self.corner(plain), QColor("#808080"))
        for state, token in (
            ("running", "status-running"),
            ("waiting", "status-attention"),
            ("failed", "status-failed"),
        ):
            with self.subTest(state=state):
                color = self.corner(badged_icon(self.frame(), state))
                self.assertEqual(
                    color.name(), QColor(design_tokens.LIGHT_THEME[token]).name()
                )

    def test_missing_pixmap_gives_an_empty_icon(self):
        self.assertTrue(badged_icon(None, "running").isNull())
        empty = QPixmap(1, 1)
        empty.fill(Qt.GlobalColor.transparent)
        self.assertFalse(badged_icon(empty, None).isNull())

    def test_project_entries_get_a_dot_only_for_agent_sources(self):
        icon = source_dot_icon("claude_code")
        center = icon.pixmap(QSize(16, 16)).toImage().pixelColor(8, 8)
        self.assertEqual(
            center.name(),
            QColor(design_tokens.LIGHT_THEME["source-claude-code"]).name(),
        )
        self.assertTrue(source_dot_icon("").isNull())
        self.assertTrue(source_dot_icon("schedule").isNull())


if __name__ == "__main__":
    unittest.main()
