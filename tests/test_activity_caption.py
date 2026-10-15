"""The pet's activity caption uses the floating-surface colors and source dots."""

import os
from types import SimpleNamespace
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from watched_kettle.ui import design_tokens
from watched_kettle.ui.activity_caption import caption_html, caption_theme


class ActivityCaptionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_each_working_source_gets_a_dot_in_its_color(self):
        tokens = design_tokens.LIGHT_THEME
        html = caption_html("<작업> 중", ("codex", "claude_code", "other"), tokens)
        self.assertEqual(html.count("●"), 2)
        self.assertIn(tokens["source-codex"], html)
        self.assertIn(tokens["source-claude-code"], html)
        # The message itself is escaped, not rich text.
        self.assertTrue(html.endswith("&lt;작업&gt; 중"))
        self.assertEqual(caption_html("걷는 중", (), tokens), "걷는 중")

    def test_app_theme_wins_over_the_system(self):
        dark = SimpleNamespace(
            app_preferences=SimpleNamespace(load_app_theme=lambda: "dark")
        )
        self.assertIs(caption_theme(dark), design_tokens.DARK_THEME)
        system = SimpleNamespace(
            app_preferences=SimpleNamespace(load_app_theme=lambda: None)
        )
        self.assertIn(
            caption_theme(system),
            (design_tokens.LIGHT_THEME, design_tokens.DARK_THEME),
        )


if __name__ == "__main__":
    unittest.main()
