"""User photo, 9-slice frame and stickers draw on the bubble; presets keep them."""

from dataclasses import replace
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtWidgets import QApplication

from watched_kettle.pet.bubble_theme import (
    DEFAULT_BUBBLE_THEME,
    IMAGE_THEME_KEYS,
    bubble_theme_from_dict,
    bubble_theme_presets,
    bubble_theme_to_dict,
)
from watched_kettle.ui.bubble_elements import BubbleElementRegistry
from watched_kettle.ui.bubble_theme_preview import BubbleThemePreview


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

    def test_photo_frame_and_sticker_change_the_rendered_bubble(self):
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
                sticker_1=sticker,
                sticker_1_x=50,
                sticker_1_y=50,
                sticker_1_size=40,
            )
        )
        middle = stuck.pixelColor(300, 120)
        self.assertGreater(middle.green(), 150)
        self.assertLess(middle.red(), 60)

    def test_missing_elements_draw_like_none_and_values_are_bounded(self):
        theme = bubble_theme_from_dict(
            {
                **bubble_theme_to_dict(DEFAULT_BUBBLE_THEME),
                "background_image": "user:" + "f" * 32,
                "background_opacity": 500,
                "frame_image": "C:/outside.png",
                "sticker_2_size": 2,
            }
        )
        self.assertEqual(theme.background_opacity, 100)
        self.assertEqual(theme.frame_image, "none")
        self.assertEqual(theme.sticker_2_size, 16)
        self.assertEqual(
            self.render(theme).pixelColor(300, 70),
            self.render(DEFAULT_BUBBLE_THEME).pixelColor(300, 70),
        )

    def test_project_sample_and_presets_keep_user_images(self):
        notice = self.render(DEFAULT_BUBBLE_THEME)
        project = self.render(DEFAULT_BUBBLE_THEME, sample="project")
        self.assertNotEqual(notice, project)
        presets = bubble_theme_presets()
        self.assertEqual(presets[0]["label"], "기본 크림")
        for preset in presets:
            self.assertFalse(IMAGE_THEME_KEYS & set(preset["values"]))
            bubble_theme_from_dict(preset["values"])


if __name__ == "__main__":
    unittest.main()
