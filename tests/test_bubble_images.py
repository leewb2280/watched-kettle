"""User photo, 9-slice frame and decoration layers draw on the bubble; presets keep them."""

from dataclasses import replace
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtWidgets import QApplication

from watched_kettle.pet.bubble_decor import DecorLayer
from watched_kettle.pet.bubble_theme import (
    BACKGROUND_PATTERN_NAMES,
    DEFAULT_BUBBLE_THEME,
    PRESET_KEPT_KEYS,
    bubble_theme_from_dict,
    bubble_theme_presets,
    bubble_theme_to_dict,
)
from watched_kettle.ui.bubble_elements import (
    BubbleElementError,
    BubbleElementRegistry,
    builtin_image_path,
)
from watched_kettle.ui.bubble_theme_preview import (
    BubbleThemePreview,
    preview_geometry,
)


class BubbleImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.registry = BubbleElementRegistry(self.root / "elements")

    def element(self, kind, color, size=(64, 64)):
        source = self.root / f"{kind}.png"
        Image.new("RGBA", size, color).save(source)
        return self.registry.import_image(source, kind).reference

    def render(self, theme, sample="notice"):
        preview = BubbleThemePreview(self.registry, sample=sample)
        self.addCleanup(preview.deleteLater)
        preview.resize(600, 260)
        preview.set_theme(theme)
        return preview.grab().toImage()

    def test_huge_canvas_in_a_small_file_is_refused_before_decoding(self):
        # A flat 7000 x 7000 PNG is a few kilobytes but 49 megapixels.
        source = self.root / "wide.png"
        Image.new("L", (7000, 7000), 255).save(source, optimize=True)
        self.assertLess(source.stat().st_size, 1024 * 1024)

        with patch.object(Image.Image, "load", side_effect=AssertionError):
            with self.assertRaises(BubbleElementError):
                self.registry.import_image(source, "sticker")

    def test_photo_frame_and_decor_change_the_rendered_bubble(self):
        plain = self.render(DEFAULT_BUBBLE_THEME)
        photo = self.element("photo", (0, 0, 255, 255))
        themed = replace(
            DEFAULT_BUBBLE_THEME, background_image=photo, background_opacity=100
        )
        # The middle of the body takes the photo's color.
        center = self.render(themed).pixelColor(300, 70)
        self.assertGreater(center.blue(), 200)
        self.assertLess(center.red(), 60)
        self.assertNotEqual(plain.pixelColor(300, 70), center)

        frame = self.element("frame", (255, 0, 0, 255), size=(48, 48))
        framed = self.render(replace(DEFAULT_BUBBLE_THEME, frame_image=frame))
        # Top-left of the body is covered by the frame image's corner.
        corner = framed.pixelColor(32, 30)
        self.assertGreater(corner.red(), 200)

        sticker = self.element("sticker", (0, 200, 0, 255))
        stuck = self.render(
            replace(
                DEFAULT_BUBBLE_THEME,
                decor=(
                    DecorLayer(
                        id="a",
                        name="",
                        image=sticker,
                        anchor="top-center",
                        x=-20,
                        y=84,
                        width=40,
                        height=40,
                    ),
                ),
            )
        )
        middle = stuck.pixelColor(300, 120)
        self.assertGreater(middle.green(), 150)
        self.assertLess(middle.red(), 60)

    def test_builtin_pattern_tiles_draw_in_the_border_color(self):
        for name in BACKGROUND_PATTERN_NAMES:
            self.assertTrue(builtin_image_path(f"builtin:{name}").is_file(), name)
        self.assertIsNone(builtin_image_path("builtin:../app_icon"))
        self.assertIsNone(self.registry.get("builtin:dots"))
        self.assertFalse(self.registry.delete("builtin:dots"))
        plain = DEFAULT_BUBBLE_THEME
        tiled = replace(
            plain,
            border="#ff0000",
            background_image="builtin:gingham",
            background_fit="tile",
            background_opacity=100,
        )
        self.assertEqual(bubble_theme_from_dict(bubble_theme_to_dict(tiled)), tiled)
        image = self.render(tiled)
        reds = [image.pixelColor(x, 70) for x in range(120, 480, 4)]
        # Gingham bands take the border color; the rest stays the bubble's.
        self.assertTrue(any(c.red() - c.green() > 60 for c in reds))
        unknown = bubble_theme_from_dict(
            {**bubble_theme_to_dict(plain), "background_image": "builtin:nope"}
        )
        self.assertEqual(unknown.background_image, "none")

    def test_free_photo_draws_in_its_own_box_and_reports_it(self):
        photo = self.element("photo", (0, 0, 255, 255))
        theme = replace(
            DEFAULT_BUBBLE_THEME,
            background_image=photo,
            background_fit="free",
            background_opacity=100,
            background_x=25.0,
            background_width=60,
            background_height=40,
        )
        self.assertEqual(bubble_theme_from_dict(bubble_theme_to_dict(theme)), theme)
        preview = BubbleThemePreview(self.registry)
        self.addCleanup(preview.deleteLater)
        preview.resize(600, 260)
        preview.set_theme(theme)
        image = preview.grab().toImage()
        body = preview.body_rect()
        center_x = body.left() + body.width() / 4
        inside = image.pixelColor(round(center_x), round(body.center().y()))
        outside = image.pixelColor(round(body.right() - 40), round(body.center().y()))
        self.assertGreater(inside.blue(), 200)
        self.assertLess(inside.red(), 60)
        self.assertGreater(outside.red(), 200)
        box = preview_geometry(theme, body, preview.size(), self.registry)["background"]
        self.assertAlmostEqual(box["x"], center_x - 30)
        self.assertAlmostEqual(box["y"], body.center().y() - 20)
        self.assertEqual((box["width"], box["height"]), (60, 40))
        tiled = replace(theme, background_fit="tile")
        self.assertIsNone(
            preview_geometry(tiled, body, preview.size(), self.registry)["background"]
        )
        bounded = bubble_theme_from_dict(
            {
                **bubble_theme_to_dict(theme),
                "background_x": 140,
                "background_y": 12.345,
                "background_width": 2,
            }
        )
        self.assertEqual(bounded.background_x, 100.0)
        self.assertEqual(bounded.background_y, 12.3)
        self.assertEqual(bounded.background_width, 8)

    def test_missing_elements_draw_like_none_and_values_are_bounded(self):
        theme = bubble_theme_from_dict(
            {
                **bubble_theme_to_dict(DEFAULT_BUBBLE_THEME),
                "background_image": "user:" + "f" * 32,
                "background_opacity": 500,
                "frame_image": "C:/outside.png",
                "decor": [{"id": "a", "image": "user:" + "e" * 32, "width": 2}],
            }
        )
        self.assertEqual(theme.background_opacity, 100)
        self.assertEqual(theme.frame_image, "none")
        self.assertEqual(theme.decor[0].width, 2.0)
        self.assertEqual(
            self.render(theme).pixelColor(300, 70),
            self.render(DEFAULT_BUBBLE_THEME).pixelColor(300, 70),
        )

    def test_project_sample_and_presets_keep_user_images_and_pet_frame(self):
        notice = self.render(DEFAULT_BUBBLE_THEME)
        project = self.render(DEFAULT_BUBBLE_THEME, sample="project")
        self.assertNotEqual(notice, project)
        presets = bubble_theme_presets()
        self.assertEqual(presets[0]["label"], "기본 크림")
        for preset in presets:
            self.assertFalse(PRESET_KEPT_KEYS & set(preset["values"]))
            bubble_theme_from_dict(preset["values"])


if __name__ == "__main__":
    unittest.main()
