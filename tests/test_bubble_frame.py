import json
import os
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from watched_kettle.pet.bubble_frame import (
    MAX_FRAME_LAYERS,
    MAX_FRAME_REPEATS,
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
from watched_kettle.ui.speech_bubble_frame import (
    content_padding,
    inner_border,
    paint_frame_overlay,
)
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

    def test_repeat_y_only_accepts_bounded_image_options_and_top_anchors(self):
        image = {"image": "bubble/mask.png", "anchor": "top-left"}
        for anchor in ("top-left", "top-center", "top-right"):
            frame = parse_frame(
                {
                    "overlay": [
                        {
                            **image,
                            "anchor": anchor,
                            "repeatY": {"gap": 3, "bottomInset": 10},
                        }
                    ]
                },
                self.root,
            )
            self.assertEqual(frame.overlay[0].repeat_y.gap, 3)
            self.assertEqual(frame.overlay[0].repeat_y.bottom_inset, 10)
        for options in (
            True,
            [],
            "y",
            {"gap": -1},
            {"gap": True},
            {"gap": 201},
            {"bottomInset": -1},
            {"bottomInset": "10"},
            {"gap": float("nan")},
            {"gap": float("inf")},
            {"gap": 10**1000},
        ):
            with self.subTest(options=options):
                frame = parse_frame(
                    {"overlay": [{**image, "repeatY": options}]}, self.root
                )
                self.assertEqual(len(frame.overlay), 1)
                self.assertIsNone(frame.overlay[0].repeat_y)
        for anchor in ("center-left", "bottom-left", "arc-top-left"):
            frame = parse_frame(
                {"overlay": [{**image, "anchor": anchor, "repeatY": {}}]}, self.root
            )
            self.assertIsNone(frame.overlay[0].repeat_y)
        frame = parse_frame(
            {
                "overlay": [
                    {
                        "anchor": "top-left",
                        "circle": {"radius": 2, "color": "text"},
                        "repeatY": {},
                    }
                ]
            },
            self.root,
        )
        self.assertIsNone(frame.overlay[0].repeat_y)
        frame = parse_frame({"overlay": [{**image, "repeatY": {}}]}, self.root)
        self.assertEqual(frame.overlay[0].repeat_y.gap, 0)

    def test_nonfinite_dimensions_and_padding_do_not_escape_validation(self):
        frame = parse_frame(
            {
                "contentPadding": [float("nan"), 2, 3],
                "overlay": [
                    {
                        "image": "bubble/mask.png",
                        "anchor": "top-left",
                        "width": float("inf"),
                        "height": float("nan"),
                        "x": 10**1000,
                    }
                ],
            },
            self.root,
        )
        self.assertIsNone(frame.content_padding)
        self.assertEqual((frame.overlay[0].width, frame.overlay[0].height), (16, 16))
        self.assertEqual(frame.overlay[0].x, 200)

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
        cls.app = QApplication.instance() or QApplication([])

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


class RepeatedFramePaintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        tile = Image.new("RGBA", (8, 6), (0, 0, 0, 0))
        for x in range(4):
            for y in range(6):
                tile.putpixel((x, y), (30, 70, 130, 255))
        tile.save(self.root / "tile.png")

    def render(self, body_height, scale=1.0, **options):
        layer = {
            "image": "tile.png",
            "anchor": "top-left",
            "x": 2,
            "y": 3,
            "width": 8,
            "height": 6,
            "repeatY": {"gap": 4, "bottomInset": 5},
            **options,
        }
        manifest = {
            "id": "repeated-fixture",
            "bubbleTheme": {"frame": {"overlay": [layer]}},
        }
        register_package_frame(manifest, self.root)
        theme = bubble_theme_from_manifest(manifest)
        self.theme = theme
        image = QImage(
            round(180 * scale),
            round((body_height + 40) * scale),
            QImage.Format.Format_ARGB32,
        )
        image.fill(Qt.GlobalColor.transparent)
        body = QRectF(10 * scale, 10 * scale, 120 * scale, body_height * scale)
        painter = QPainter(image)
        paint_frame_overlay(painter, body, theme, scale)
        painter.end()
        return image

    @staticmethod
    def runs(image, x):
        active = [image.pixelColor(x, y).alpha() > 32 for y in range(image.height())]
        return sum(
            value and (i == 0 or not active[i - 1]) for i, value in enumerate(active)
        )

    def test_height_controls_whole_tiles_at_exact_boundaries(self):
        for height, expected in (
            (13, 0),
            (14, 1),
            (23, 1),
            (24, 2),
            (40, 3),
            (24, 2),
            (14, 1),
        ):
            with self.subTest(height=height):
                image = self.render(height)
                self.assertEqual(self.runs(image, 13), expected)
                # No fragment occupies the reserved bottom margin.
                self.assertTrue(
                    all(
                        image.pixelColor(13, y).alpha() == 0
                        for y in range(10 + height - 5, image.height())
                    )
                )

    def test_scales_and_top_anchors_keep_count_and_spacing(self):
        for scale in (0.8, 1, 1.25, 1.4, 1.5, 2):
            for anchor, x, sample_x in (
                ("top-left", 2, 13),
                ("top-center", -4, 67),
                ("top-right", -8, 123),
            ):
                with self.subTest(scale=scale, anchor=anchor):
                    image = self.render(34, scale, anchor=anchor, x=x)
                    self.assertEqual(self.runs(image, round(sample_x * scale)), 3)

    def test_tint_opacity_and_mirror_apply_to_every_copy(self):
        image = self.render(40, tint="#123456", alpha=128, mirror=True)
        for y in (15, 25, 35):
            self.assertEqual(image.pixelColor(13, y).alpha(), 0)
            self.assertEqual(image.pixelColor(18, y), QColor(18, 52, 86, 128))

    def test_invalid_repeat_keeps_single_layer_and_outside_button(self):
        for repeat in (None, {"gap": -1}, {"bottomInset": float("nan")}):
            image = self.render(40, repeatY=repeat, y=-4)
            self.assertEqual(self.runs(image, 13), 1)
            self.assertGreater(image.pixelColor(13, 7).alpha(), 0)

    def test_negative_start_skips_partial_top_and_repeat_count_is_bounded(self):
        image = self.render(40, y=-2)
        self.assertEqual(image.pixelColor(13, 9).alpha(), 0)
        self.assertEqual(self.runs(image, 13), 3)
        image = self.render(1000, height=1, y=0, repeatY={"gap": 1})
        self.assertEqual(self.runs(image, 13), MAX_FRAME_REPEATS)

    def test_existing_theme_preview_repeats_and_resizes_without_changing_theme(self):
        from watched_kettle.ui.bubble_theme_preview import BubbleThemePreview

        self.render(40)
        preview = BubbleThemePreview(None)
        self.addCleanup(preview.close)
        preview.set_theme(self.theme)
        counts = []
        for height in (205, 305, 205):
            preview.resize(460, height)
            image = QImage(preview.size(), QImage.Format.Format_ARGB32)
            image.fill(Qt.GlobalColor.transparent)
            preview.render(image)
            active = [
                image.pixelColor(21, y) == QColor(30, 70, 130)
                for y in range(image.height())
            ]
            counts.append(
                sum(v and (i == 0 or not active[i - 1]) for i, v in enumerate(active))
            )
        self.assertGreater(counts[0], 1)
        self.assertGreater(counts[1], counts[0])
        self.assertEqual(counts[0], counts[2])
        self.assertIs(preview.theme, self.theme)


if __name__ == "__main__":
    unittest.main()
