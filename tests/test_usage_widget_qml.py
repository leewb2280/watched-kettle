"""Every usage widget layout loads without QML warnings and sizes itself."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtQuick import QQuickItem
from PySide6.QtWidgets import QApplication

from tests.test_widget_state import claude, codex, snapshot
from watched_kettle.ui.usage_widget.window import (
    LAYOUTS,
    QuickUsageWindow,
    qml_color,
    use_software_renderer,
    widget_theme,
)


class UsageWidgetQmlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        use_software_renderer()

    def setUp(self):
        self.window = QuickUsageWindow()
        self.warnings = []
        self.window.engine().warnings.connect(
            lambda items: self.warnings.extend(item.toString() for item in items)
        )
        self.addCleanup(self.window.close)

    def render(self, data, scale_percent=100, **context):
        self.window.context = lambda: context
        self.window.apply_snapshot(data, scale_percent=scale_percent)
        for _ in range(5):
            self.app.processEvents()
        return self.window.width(), self.window.height()

    def texts(self):
        """Text of every visual item; layouts and their delegates sit in a Loader."""
        found, items = [], [self.window.rootObject()]
        while items:
            item = items.pop()
            items.extend(item.childItems())
            if isinstance(item.property("text"), str):
                found.append(item.property("text"))
        return found

    def test_size_setting_lays_out_larger_instead_of_stretching(self):
        # The software scene graph stretches a scaled rounded Rectangle from
        # its own size, which left stepped corners and badge circles at 130%.
        # Layouts multiply their lengths instead, and nothing is scaled.
        data = snapshot(codex(), claude())
        context = {
            "activity": {"claude_code": {"attention": 1}},
            "today": True,
            "claude_code_hourly": tuple(range(24)),
        }

        def laid_out(scale_percent, layout):
            self.render(data, scale_percent, layout=layout, **context)
            # Positioners lay out on the next frame; a hidden view has none.
            self.window.grabWindow()
            for _ in range(5):
                self.app.processEvents()
            return self.window.width(), self.window.height()

        for layout in LAYOUTS:
            with self.subTest(layout=layout):
                normal = laid_out(100, layout)
                large = laid_out(130, layout)
                self.assertAlmostEqual(large[0] / normal[0], 1.3, delta=0.06)
                self.assertGreater(large[1] / normal[1], 1.15)
                scaled = [
                    item
                    for item in self.window.rootObject().findChildren(QQuickItem)
                    if item.scale() != 1
                ]
                self.assertEqual(scaled, [])
        self.assertEqual(self.warnings, [])

    def test_each_layout_and_theme_renders_both_providers(self):
        self.assertTrue(self.window.ready)
        sizes = {}
        for layout in LAYOUTS:
            for theme in ("light", "dark"):
                with self.subTest(layout=layout, theme=theme):
                    size = self.render(
                        snapshot(codex(), claude()),
                        layout=layout,
                        theme=theme,
                        activity={"claude_code": {"attention": 1}},
                        today=True,
                        claude_code_hourly=tuple(range(24)),
                    )
                    self.assertGreater(size[0], 150)
                    self.assertGreater(size[1], 40)
                    sizes[layout] = size
        self.assertEqual(self.warnings, [])
        # Chips stay the quietest; rings fit two cells side by side.
        self.assertLess(sizes["chips"][1], sizes["bars"][1])

    def test_edge_states_and_empty_widget_render_without_warnings(self):
        for layout in LAYOUTS:
            self.render(snapshot(state="offline"), layout=layout)
            self.render(snapshot(codex()), layout=layout, expanded=True)
            self.render(
                snapshot(codex()), layout=layout, **{"claude_code_enabled": True}
            )
        self.render(snapshot(state="offline", account=""))
        self.assertEqual(self.warnings, [])

    def test_estimated_limits_say_so_in_words(self):
        # "~100%" read as minus at widget size; big numbers stay bare.
        estimated = replace(
            claude().primary, used_percent=0.0, remaining_percent=100.0, estimated=True
        )
        data = snapshot(codex(), replace(claude(), primary=estimated))
        for layout in LAYOUTS:
            with self.subTest(layout=layout):
                self.render(data, layout=layout, expanded=True)
                texts = self.texts()
                self.assertTrue(any("100%(추정)" in text for text in texts), texts)
                self.assertFalse(any("~" in text for text in texts), texts)
                self.render(data, layout=layout, emphasis="five_hour")
                texts = self.texts()
                self.assertIn("100%", texts)
                self.assertTrue(any("5시간(추정)" in text for text in texts), texts)
        self.assertEqual(self.warnings, [])

    def test_low_opacity_outlines_text_and_custom_color_picks_readable_ink(self):
        self.assertFalse(widget_theme("light", opacity=93)["halo"])
        self.assertTrue(widget_theme("light", opacity=40)["halo"])
        # A light card at 70% over a dark desktop turns gray; secondary text
        # takes the body ink; outlines stay for very see-through cards only.
        solid, translucent = widget_theme("light"), widget_theme("light", opacity=70)
        self.assertNotEqual(solid["float_muted"], solid["float_ink"])
        self.assertEqual(translucent["float_muted"], translucent["float_ink"])
        self.assertFalse(translucent["halo"])
        self.assertFalse(solid["halo"])
        self.assertTrue(
            widget_theme("dark", opacity=0)["float_surface"].startswith("#01")
        )
        dark_custom = widget_theme("light", background="#263246")
        self.assertEqual(dark_custom["float_ink"], widget_theme("dark")["float_ink"])
        light_custom = widget_theme("dark", background="#F7EAD8")
        self.assertEqual(light_custom["float_ink"], widget_theme("light")["float_ink"])

    def test_stale_values_stay_opaque_on_a_see_through_card(self):
        # Low background opacity must not make the content itself see-through.
        # Stale values were drawn at 60% opacity and showed the desktop through
        # every digit; they now switch to the muted ink and stay opaque.
        def opaque_pixels(updated, observed):
            self.render(
                snapshot(codex(), claude(), updated=updated),
                layout=layout,
                opacity=30,
                claude_code_observed_at=observed,
            )
            image = self.window.grabWindow()
            return sum(
                image.pixelColor(x, y).alpha() >= 250
                for y in range(image.height())
                for x in range(image.width())
            )

        now = datetime.now(timezone.utc)
        old = now - timedelta(minutes=40)
        for layout in LAYOUTS:
            with self.subTest(layout=layout):
                fresh = opaque_pixels(now, now)
                stale = opaque_pixels(old, old)
                self.assertGreater(fresh, 0)
                self.assertGreaterEqual(stale, fresh)
        self.assertEqual(self.warnings, [])

    def test_token_alpha_moves_to_the_front_for_qml(self):
        self.assertEqual(qml_color("#0f1a1438"), "#380f1a14")
        self.assertEqual(qml_color("#4f7a5c"), "#4f7a5c")


if __name__ == "__main__":
    unittest.main()
