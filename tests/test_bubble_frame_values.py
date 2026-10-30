"""A user theme's own inner line, halo and text spacing (FRAME_THEME_KEYS)."""

from dataclasses import replace
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from watched_kettle.application.settings_ui import bubble_assets
from watched_kettle.application.settings_ui.bubble_themes import export_package_theme
from watched_kettle.pet.bubble_decor import ORNAMENT_KINDS
from watched_kettle.pet.bubble_frame import register_package_frame
from watched_kettle.pet.bubble_theme import (
    DEFAULT_BUBBLE_THEME,
    FRAME_THEME_KEYS,
    PRESET_KEPT_KEYS,
    bubble_theme_from_dict,
    bubble_theme_from_manifest,
    bubble_theme_presets,
    bubble_theme_to_dict,
)
from watched_kettle.ui.bubble_elements import BubbleElementRegistry
from watched_kettle.ui.speech_bubble_decorations import ornament_pixmap
from watched_kettle.ui.speech_bubble_frame import (
    content_padding,
    frame_insets,
    inner_border,
    theme_halo,
)

PET = "frame-values-pet"


class FrameValueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.manifest = {
            "id": PET,
            "bubbleTheme": {
                "effects": {"shadow": "#123456"},
                "frame": {
                    "insets": [4, 6, 4, 6],
                    "contentPadding": [18, 20, 4],
                    "innerBorder": {"color": "#eec98f", "alpha": 220},
                    "halo": {
                        "color": "shadow",
                        "alpha": 92,
                        "width": 4.5,
                        "offsetY": 2.5,
                        "grow": 1,
                    },
                },
            },
        }
        register_package_frame(self.manifest, self.root)
        self.pet_theme = bubble_theme_from_manifest(self.manifest)

    def test_saved_themes_keep_the_pet_values_until_switched_on(self):
        # Themes saved before these fields read them as off.
        saved = bubble_theme_to_dict(self.pet_theme)
        theme = bubble_theme_from_dict(
            {key: value for key, value in saved.items() if key not in FRAME_THEME_KEYS}
        )
        self.assertFalse(theme.inner_border_custom)
        self.assertEqual(content_padding(theme, 12, 14), (18, 20, 4))
        color = inner_border(theme)
        self.assertEqual((color.name(), color.alpha()), ("#eec98f", 220))
        self.assertEqual(theme_halo(theme).width, 4.5)
        plain = DEFAULT_BUBBLE_THEME
        self.assertEqual(content_padding(plain, 12, 14), (12, 14, 0))
        self.assertIsNone(theme_halo(plain))
        self.assertEqual(frame_insets(plain), (0.0, 0.0, 0.0, 0.0))

    def test_switched_on_values_replace_the_pet_frame(self):
        theme = replace(
            self.pet_theme,
            inner_border_custom=True,
            inner_border_color="#ff0000",
            inner_border_alpha=40,
            content_custom=True,
            content_top=3,
            content_bottom=5,
            content_left=7,
            halo_custom=True,
            halo_width=0.0,
        )
        color = inner_border(theme)
        self.assertEqual((color.name(), color.alpha()), ("#ff0000", 40))
        self.assertEqual(content_padding(theme, 12, 14), (3, 5, 7))
        # Width 0 turns the pet's halo off.
        self.assertIsNone(theme_halo(theme))

    def test_a_theme_halo_widens_the_canvas(self):
        theme = replace(
            DEFAULT_BUBBLE_THEME,
            halo_custom=True,
            halo_width=4.0,
            halo_offset_y=3.0,
            halo_grow=2.0,
        )
        halo = theme_halo(theme)
        self.assertEqual((halo.grow, halo.radius_delta), (2.0, 2.0))
        # 2 grow + 2 half-stroke + 1 antialiasing, shifted down 3.
        self.assertEqual(frame_insets(theme), (5.0, 2.0, 5.0, 8.0))
        self.assertEqual(frame_insets(theme, 2.0), (10.0, 4.0, 10.0, 16.0))

    def test_values_round_trip_within_their_limits(self):
        theme = bubble_theme_from_dict(
            {
                "halo_custom": True,
                "halo_width": 99,
                "halo_offset_y": 2.3,
                "halo_color": "not a color",
                "content_custom": 1,
                "content_top": -4,
                "inner_border_alpha": 999,
            }
        )
        self.assertTrue(theme.halo_custom and theme.content_custom)
        self.assertEqual(theme.halo_width, 12.0)
        self.assertEqual(theme.halo_offset_y, 2.5)
        self.assertEqual(theme.halo_color, DEFAULT_BUBBLE_THEME.halo_color)
        self.assertEqual(theme.content_top, 0)
        self.assertEqual(theme.inner_border_alpha, 255)
        data = json.loads(json.dumps(bubble_theme_to_dict(theme)))
        self.assertEqual(bubble_theme_from_dict(data), theme)

    def test_presets_keep_frame_values(self):
        self.assertTrue(FRAME_THEME_KEYS <= PRESET_KEPT_KEYS)
        for preset in bubble_theme_presets():
            self.assertFalse(FRAME_THEME_KEYS & set(preset["values"]))

    def test_editor_gets_the_pet_frame_values_with_colors_resolved(self):
        values = bubble_assets.package_frame_values(PET, self.pet_theme)
        self.assertEqual(
            values,
            {
                "inner_border_color": "#eec98f",
                "inner_border_alpha": 220,
                "halo_color": "#123456",
                "halo_alpha": 92,
                "halo_width": 4.5,
                "halo_offset_y": 2.5,
                "halo_grow": 1.0,
                "content_top": 18,
                "content_bottom": 20,
                "content_left": 4,
            },
        )
        self.assertEqual(bubble_assets.package_frame_values("no-such-pet", None), {})

    def test_package_export_writes_the_theme_values_into_the_frame(self):
        registry = BubbleElementRegistry(self.root / "elements")
        theme = replace(
            self.pet_theme,
            inner_border_custom=True,
            inner_border_color="#00ff00",
            inner_border_alpha=10,
            halo_custom=True,
            halo_color="#0000ff",
            halo_width=6.0,
            halo_offset_y=0.0,
            halo_grow=0.0,
            content_custom=True,
            content_top=1,
            content_bottom=2,
            content_left=3,
        )
        folder = self.root / "export"
        export_package_theme(folder, theme, registry)
        data = json.loads((folder / "bubble-theme.json").read_text("utf-8"))
        bubble = data["bubbleTheme"]
        self.assertFalse(FRAME_THEME_KEYS & set(bubble))
        frame = bubble["frame"]
        self.assertEqual(frame["innerBorder"], {"color": "#00ff00", "alpha": 10})
        self.assertEqual(frame["contentPadding"], [1, 2, 3])
        self.assertEqual(
            (frame["halo"]["color"], frame["halo"]["width"]), ("#0000ff", 6.0)
        )
        # The canvas covers the 6px halo: 3 half-stroke + 1 antialiasing.
        self.assertTrue(all(value >= 4 for value in frame["insets"]))

    def test_dot_ornament_draws_in_the_border_color(self):
        self.assertIn("dot", ORNAMENT_KINDS)
        image = ornament_pixmap("dot", DEFAULT_BUBBLE_THEME).toImage()
        self.assertFalse(image.isNull())
        center = image.pixelColor(image.width() // 2, image.height() // 2)
        self.assertEqual(center.name(), QColor(DEFAULT_BUBBLE_THEME.border).name())
        self.assertEqual(image.width(), image.height())


if __name__ == "__main__":
    unittest.main()
