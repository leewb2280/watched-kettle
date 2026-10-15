"""Fractional shaped text widths must not trigger premature wrapping."""

from dataclasses import replace
import unittest

from PySide6.QtGui import QFont

from watched_kettle.ui.fonts import register_bundled_fonts
from watched_kettle.ui.wrapped_title_button import WrappedTitleButton, title_text_width
from tests import test_actionable_bubbles as helpers


class BubbleTitleWidthTests(unittest.TestCase):
    setUpClass = classmethod(helpers.CardTests.setUpClass.__func__)

    def setUp(self):
        self.old_font = QFont(self.app.font())
        font = QFont(self.old_font)
        font.setFamily(register_bundled_fonts())
        font.setPointSizeF(9)
        self.app.setFont(font)
        helpers.CardTests.setUp(self)

    def tearDown(self):
        helpers.CardTests.tearDown(self)
        self.app.setFont(self.old_font)

    def show_title(self, text):
        self.projects.observe(
            dict(source="codex", event="prompt", session_id="a", turn_id="1")
        )
        self.projects.set_metadata(
            helpers.ThreadMetadata("a", "p", "Demo_tool", title=text),
            self.projects.generation,
        )
        self.controller._render()
        self.app.processEvents()
        window = self.controller.visible_windows[0]
        return window, window.project_rows.rows["a"]

    def test_fractional_width_reproducer_stays_on_one_line(self):
        text = "말풍선 제목 너비 규칙 정하기"
        button = WrappedTitleButton()
        font = QFont(self.app.font())
        font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
        button.setFont(font)
        rounded = button.fontMetrics().horizontalAdvance(text)
        button.set_title(text, rounded + 8)
        self.assertIn("\n", button.text())  # Reproduce the old rounding error.
        button.set_title(text, title_text_width(text, font) + 8)
        self.assertEqual(button.text(), text)
        button.close()

    def test_title_expands_card_before_wrapping_and_caps_long_titles(self):
        for scale in (100, 125, 150, 200):
            self.controller.set_scale_percent(scale)
            short, _ = self.show_title("프로그램 점검")
            short_width = short.width()
            medium, row = self.show_title("말풍선 제목 너비 규칙 정하기")
            self.assertNotIn("\n", row.title.text())
            self.assertGreater(medium.width(), short_width)
            self.assertLess(row.title.geometry().right(), row.badge.geometry().left())
            long, row = self.show_title("말풍선 제목 너비 규칙 정하기 " * 5)
            self.assertIn("\n", row.title.text())
            capped_width = long.width()
            longer, _ = self.show_title("말풍선 제목 너비 규칙 정하기 " * 10)
            self.assertEqual(longer.width(), capped_width)

    def test_maximum_width_change_reflows_existing_row(self):
        text = "말풍선 제목 너비 규칙 정하기"
        window, row = self.show_title(text)
        self.assertNotIn("\n", row.title.text())
        self.controller.set_theme(
            replace(self.controller.theme, maximum_width=180, minimum_width=120)
        )
        self.controller._render()
        self.app.processEvents()
        self.assertIn("\n", row.title.text())
        self.controller.set_theme(replace(self.controller.theme, maximum_width=320))
        self.controller._render()
        self.app.processEvents()
        self.assertEqual(row.title.text(), text)


if __name__ == "__main__":
    unittest.main()
