"""Every usage widget layout loads without QML warnings and sizes itself."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import os
import unittest
from unittest.mock import patch

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
        from watched_kettle.ui.fonts import configure_application_font

        old_font = cls.app.font()
        cls.addClassCleanup(cls.app.setFont, old_font)
        configure_application_font(cls.app)

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

    def visual_items(self):
        found, pending = [], [self.window.rootObject()]
        while pending:
            item = pending.pop()
            found.append(item)
            pending.extend(item.childItems())
        return found

    def visible_texts(self):
        return [
            item.property("text")
            for item in self.visual_items()
            if item.isVisible() and isinstance(item.property("text"), str)
        ]

    def test_compact_activity_dots_use_the_same_rules_for_each_provider(self):
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QColor

        for theme in ("light", "dark"):
            for running, attention, token in (
                (0, 0, "float_muted"),
                (2, 0, "status_running"),
                (0, 1, "status_attention"),
                (2, 1, "status_attention"),
            ):
                counts = {"running": running, "attention": attention}
                for visible in (True, False, True):
                    self.render(
                        snapshot(
                            codex(five_hour=9, seven_day=100),
                            claude(five_hour=100, seven_day=80),
                        ),
                        layout="chips",
                        theme=theme,
                        activity={"codex": counts, "claude_code": counts},
                        tasks_visible=visible,
                    )
                    self.window.grabWindow()
                    dots = [
                        item
                        for item in self.visual_items()
                        if item.objectName().startswith("activityDot_")
                    ]
                    self.assertEqual(len(dots), 2)
                    self.assertEqual(
                        {d.objectName() for d in dots},
                        {"activityDot_codex", "activityDot_claude_code"},
                    )
                    for dot in dots:
                        self.assertEqual(dot.isVisible(), visible)
                        if visible:
                            self.assertEqual(
                                dot.property("color"),
                                QColor(self.window.model.theme[token]),
                            )
                            self.assertEqual((dot.width(), dot.height()), (7, 7))
                    self.assertEqual(
                        dots[0].mapToScene(QPointF()).x(),
                        dots[1].mapToScene(QPointF()).x(),
                    )
        self.assertEqual(self.warnings, [])

    def test_compact_expansion_shows_activity_even_without_limits(self):
        from watched_kettle.localization import (
            Translator,
            get_translator,
            set_translator,
        )
        from watched_kettle.localization.catalog import RESOURCE_ROOT
        from watched_kettle.localization.packs import load_pack

        original = get_translator()
        self.addCleanup(set_translator, original)
        for translator, empty_text in (
            (Translator(), "표시할 작업 없음"),
            (
                load_pack(RESOURCE_ROOT / "en", official=True).translator(),
                "No tasks to show",
            ),
        ):
            set_translator(translator)
            for limited in (True, False):
                buckets = (codex(), claude())
                if not limited:
                    buckets = tuple(
                        replace(b, primary=None, secondary=None) for b in buckets
                    )
                for bucket in buckets:
                    for counts in (
                        {},
                        {"running": 2},
                        {"attention": 1},
                        {"running": 2, "attention": 1},
                    ):
                        with self.subTest(
                            locale=translator.locale, limited=limited, counts=counts
                        ):
                            for visible in (True, False):
                                self.render(
                                    snapshot(bucket, account=""),
                                    layout="chips",
                                    expanded=True,
                                    tasks_visible=visible,
                                    activity={bucket.limit_id: counts},
                                )
                                self.window.grabWindow()
                                texts = self.visible_texts()
                                provider = self.window.model.state["providers"][0]
                                expected = [
                                    provider["workingText"]
                                    if counts.get("running")
                                    else "",
                                    provider["attentionText"]
                                    if counts.get("attention")
                                    else "",
                                ]
                                expected = [text for text in expected if text]
                                summary = (
                                    " · ".join(expected) if expected else empty_text
                                )
                                if visible:
                                    self.assertIn(summary, texts)
                                else:
                                    self.assertNotIn(summary, texts)
        self.assertEqual(self.warnings, [])

    def test_english_text_is_complete_in_every_real_qml_layout(self):
        from watched_kettle.localization import get_translator, set_translator
        from watched_kettle.localization.catalog import RESOURCE_ROOT
        from watched_kettle.localization.packs import load_pack
        from watched_kettle.usage.widget_state import widget_state

        original = get_translator()
        self.addCleanup(set_translator, original)
        set_translator(load_pack(RESOURCE_ROOT / "en", official=True).translator())
        self.window.close()
        self.window = QuickUsageWindow()
        self.addCleanup(self.window.close)
        self.window.engine().warnings.connect(
            lambda items: self.warnings.extend(item.toString() for item in items)
        )
        now = datetime.now(timezone.utc)
        old = now - timedelta(minutes=20)
        bucket = replace(
            codex(),
            primary=replace(
                codex().primary, resets_at=now + timedelta(hours=2, minutes=10)
            ),
        )
        for layout in LAYOUTS:
            for expanded in (False, True):
                with self.subTest(layout=layout, expanded=expanded):
                    with patch(
                        "watched_kettle.ui.usage_widget.window.widget_state",
                        side_effect=lambda data, **kwargs: widget_state(
                            data, now=now, **kwargs
                        ),
                    ):
                        self.render(
                            snapshot(bucket, updated=old),
                            layout=layout,
                            expanded=expanded,
                            emphasis="five_hour",
                        )
                    text = "\n".join(self.texts())
                    self.assertFalse(any("\uac00" <= c <= "\ud7a3" for c in text), text)
                    self.assertNotIn("message.", text)
                    if layout != "chips" or expanded:
                        self.assertIn("Resets in 2h 10m", text)
                        self.assertIn("Sample from 20m ago", text)
                        self.assertIn("left", text)
        self.assertEqual(self.warnings, [])

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
