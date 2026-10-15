import json
import os
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter

from watched_kettle.pet.bubble_frame import (
    MAX_FRAME_LAYERS,
    is_frame_style,
    parse_frame,
    register_package_frame,
    registered_frame,
)
from watched_kettle.pet.bubble_theme import (
    DEFAULT_BUBBLE_THEME,
    bubble_theme_from_dict,
    bubble_theme_from_manifest,
)
from watched_kettle.pet.preferences import PetPreferences
from watched_kettle.ui.speech_bubble_frame import content_padding, inner_border
from watched_kettle.ui.speech_bubble_paint import (
    bubble_frame_insets,
    paint_bubble_backdrop,
    paint_bubble_surface,
    build_body_path,
)
from tests.test_pet_preferences import FakeSettings


class BubbleFrameParsingTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / "pet"
        (self.root / "bubble").mkdir(parents=True)
        Image.new("RGBA", (8, 8), (255, 255, 255, 255)).save(
            self.root / "bubble" / "mask.png"
        )
        (self.root.parent / "outside.png").write_bytes(
            (self.root / "bubble" / "mask.png").read_bytes()
        )

    def test_values_are_bounded_and_invalid_layers_dropped(self):
        frame = parse_frame(
            {
                "insets": [500, -3, 4, 5],
                "contentPadding": [10, 12],
                "innerBorder": {"color": "not-a-color"},
                "halo": {"color": "nope", "alpha": 900, "width": 99},
                "overlay": [
                    {"image": "bubble/mask.png", "anchor": "top-left"},
                    {"image": "../outside.png", "anchor": "top-left"},
                    {"image": "bubble/missing.png", "anchor": "top-left"},
                    {"image": "bubble/mask.png", "anchor": "middle"},
                    {"circle": {"radius": 3}, "anchor": "top-left"},
                    {"circle": {"radius": 3, "color": "text"}, "anchor": "top-left"},
                ],
            },
            self.root,
        )

        self.assertEqual(frame.insets, (120.0, 0.0, 4.0, 5.0))
        self.assertIsNone(frame.content_padding)
        self.assertIsNone(frame.inner_border)
        self.assertEqual(frame.halo.color, "shadow")
        self.assertEqual(frame.halo.alpha, 255)
        self.assertEqual(frame.halo.width, 20.0)
        self.assertEqual(len(frame.overlay), 2)
        self.assertTrue(frame.overlay[0].image.endswith("mask.png"))
        self.assertEqual(frame.overlay[1].color, "text")

    def test_layer_count_is_capped(self):
        layer = {"circle": {"radius": 1, "color": "border"}, "anchor": "top-left"}
        frame = parse_frame({"backdrop": [layer] * 20}, self.root)

        self.assertEqual(len(frame.backdrop), MAX_FRAME_LAYERS)

    def test_manifest_frame_names_the_package_frame(self):
        manifest = {"id": "sample", "bubbleTheme": {"frame": {"insets": [1, 2, 3, 4]}}}

        self.assertEqual(register_package_frame(manifest, self.root), "pet:sample")
        self.assertEqual(bubble_theme_from_manifest(manifest).frame_style, "pet:sample")
        self.assertEqual(registered_frame("pet:sample").insets, (1, 2, 3, 4))
        explicit = {
            "id": "sample",
            "bubbleTheme": {
                "frameStyle": "standard",
                "frame": {"insets": [1, 2, 3, 4]},
            },
        }
        self.assertEqual(bubble_theme_from_manifest(explicit).frame_style, "standard")
        self.assertIsNone(register_package_frame({"id": "plain"}, self.root))

    def test_only_standard_and_package_frame_styles_are_valid(self):
        self.assertTrue(is_frame_style("standard"))
        self.assertTrue(is_frame_style("pet:mori-bot"))
        self.assertFalse(is_frame_style("pet:"))
        self.assertFalse(is_frame_style("pet:../x"))
        self.assertFalse(is_frame_style("old-built-in"))
        self.assertEqual(
            bubble_theme_from_dict({"frame_style": "old-built-in"}).frame_style,
            "standard",
        )

    def test_saved_theme_with_retired_frame_moves_to_the_pet_frame(self):
        settings = FakeSettings(
            {
                "pets/sample/bubbleCustomTheme": json.dumps(
                    {"frame_style": "old-built-in", "radius": 18}
                )
            }
        )

        theme = PetPreferences("sample", settings).load_custom_bubble_theme()

        self.assertEqual(theme.frame_style, "pet:sample")
        self.assertEqual(theme.radius, 18)


class BubbleFramePaintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        # Left half opaque, right half clear, so mirroring is observable.
        mask = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
        for x in range(10):
            for y in range(20):
                mask.putpixel((x, y), (255, 255, 255, 255))
        mask.save(root / "mask.png")
        layer = {"image": "mask.png", "anchor": "top-left", "width": 20, "height": 20}
        manifest = {
            "id": "paint-fixture",
            "bubbleTheme": {
                "border": {"color": "#00ff00"},
                "effects": {"shadow": "#ff0000", "shadowAlpha": 0},
                "fill": {"start": "#ffffff"},
                "radius": 10,
                "frame": {
                    "insets": [30, 30, 30, 30],
                    "contentPadding": [9, 8, 7],
                    "innerBorder": {"color": "#0000ff", "alpha": 200},
                    "overlay": [
                        {**layer, "x": -25, "y": -25, "tint": "border"},
                        {**layer, "x": 5, "y": -25, "mirror": True, "tint": "border"},
                        {
                            "circle": {"radius": 4, "color": "shadow"},
                            "anchor": "bottom-right",
                            "x": 10,
                            "y": 10,
                        },
                    ],
                },
            },
        }
        register_package_frame(manifest, root)
        self.theme = bubble_theme_from_manifest(manifest)

    def render(self, theme, scale=1.0):
        image = QImage(300, 200, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        left, top, _right, _bottom = bubble_frame_insets(theme, scale)
        body = QRectF(left, top, 120 * scale, 60 * scale)
        painter = QPainter(image)
        paint_bubble_backdrop(painter, body, theme, scale)
        paint_bubble_surface(painter, build_body_path(body, theme, scale), body, theme)
        painter.end()
        return image, body

    def test_frame_layers_follow_theme_colors_anchors_and_mirroring(self):
        image, body = self.render(self.theme)

        self.assertEqual(bubble_frame_insets(self.theme), (30.0, 30.0, 30.0, 30.0))
        green = QColor("#00ff00")
        # Plain layer: opaque left half starts 25 px left of the body corner.
        self.assertEqual(image.pixelColor(7, 7), green)
        self.assertEqual(image.pixelColor(22, 7).alpha(), 0)
        # Mirrored layer: the opaque half moves to the right.
        self.assertEqual(image.pixelColor(37, 7).alpha(), 0)
        self.assertEqual(image.pixelColor(52, 7), green)
        dot = image.pixelColor(round(body.right() + 10), round(body.bottom() + 10))
        self.assertEqual(dot, QColor("#ff0000"))

    def test_theme_color_edits_recolor_tinted_layers(self):
        image, _body = self.render(replace(self.theme, border="#123456"))

        self.assertEqual(image.pixelColor(7, 7), QColor("#123456"))

    def test_padding_and_inner_border_come_from_the_frame(self):
        self.assertEqual(content_padding(self.theme, 1, 2), (9, 8, 7))
        color = inner_border(self.theme)
        self.assertEqual((color.name(), color.alpha()), ("#0000ff", 200))

    def test_unregistered_frame_draws_the_standard_bubble(self):
        theme = replace(DEFAULT_BUBBLE_THEME, frame_style="pet:not-installed")

        self.assertEqual(bubble_frame_insets(theme, 1.4), (0.0, 0.0, 0.0, 0.0))
        self.assertEqual(content_padding(theme, 1, 2), (1, 2, 0))
        self.assertEqual(inner_border(theme).alpha(), 115)


if __name__ == "__main__":
    unittest.main()
