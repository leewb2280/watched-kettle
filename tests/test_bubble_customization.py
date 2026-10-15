import json
import os
import unittest
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtWidgets import QApplication

from watched_kettle.pet.preferences import PetPreferences
from watched_kettle.pet.window import DesktopPet
from watched_kettle.ui.bubble_elements import (
    BubbleElementError,
    BubbleElementRegistry,
)
from watched_kettle.pet.bubble_theme import SpeechBubbleTheme
from tests.test_pet_preferences import FakeSettings


class BubbleElementRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def write_image(path, size=(32, 32), color=(255, 0, 0, 180)):
        Image.new("RGBA", size, color).save(path)

    def test_imported_element_is_copied_loaded_and_deleted(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.png"
            self.write_image(source)
            registry = BubbleElementRegistry(root / "elements")

            element = registry.import_image(source, "ornament", "빨간 별")

            self.assertEqual(element.name, "빨간 별")
            self.assertEqual(element.kind, "ornament")
            self.assertTrue(element.image_path.is_file())
            self.assertFalse(registry.pixmap(element.reference).isNull())
            self.assertTrue(registry.delete(element.reference))
            self.assertIsNone(registry.get(element.reference))

    def test_invalid_images_are_rejected_and_large_ones_shrunk(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            invalid = root / "invalid.png"
            invalid.write_text("not an image", encoding="utf-8")
            oversized = root / "large.png"
            self.write_image(oversized, size=(2048, 512))
            registry = BubbleElementRegistry(root / "elements")

            with self.assertRaises(BubbleElementError):
                registry.import_image(invalid, "ornament")
            with self.assertRaises(BubbleElementError):
                registry.import_image(root / "missing.gif", "pattern")
            element = registry.import_image(oversized, "pattern")
            with Image.open(element.image_path) as stored:
                self.assertEqual(stored.size, (1024, 256))
            with patch("watched_kettle.ui.bubble_elements.MAX_SOURCE_FILE_BYTES", 10):
                with self.assertRaises(BubbleElementError):
                    registry.import_image(oversized, "pattern")

    def test_photo_import_drops_location_metadata_and_keeps_orientation(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "photo.jpg"
            exif = Image.Exif()
            # Orientation 6: the camera was turned; GPS says where it was.
            exif[0x0112] = 6
            exif[0x8825] = {1: "N", 2: (37.0, 33.0, 0.0)}
            Image.new("RGB", (1600, 1200), (40, 120, 200)).save(
                source, "JPEG", exif=exif.tobytes()
            )
            registry = BubbleElementRegistry(root / "elements")

            element = registry.import_image(source, "photo", "바다")

            self.assertEqual(element.kind, "photo")
            self.assertEqual(element.image_path.suffix, ".webp")
            with Image.open(element.image_path) as stored:
                self.assertEqual(stored.size, (768, 1024))
                self.assertEqual(len(stored.getexif()), 0)
                self.assertNotIn("exif", stored.info)
            self.assertNotIn(b"Exif", element.image_path.read_bytes())

    def test_metadata_cannot_escape_the_element_root(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            elements = root / "elements"
            elements.mkdir()
            element_id = "a" * 32
            (elements / f"{element_id}.json").write_text(
                json.dumps(
                    {
                        "id": element_id,
                        "name": "escape",
                        "kind": "ornament",
                        "image": "../outside.png",
                    }
                ),
                encoding="utf-8",
            )
            self.write_image(root / "outside.png")

            registry = BubbleElementRegistry(elements)

            self.assertEqual(registry.elements, ())


class BubbleCustomizerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary_directory = TemporaryDirectory()
        self.settings = FakeSettings()
        self.pet = DesktopPet(
            Path("pets/mori-bot"),
            settings=self.settings,
            bubble_elements_root=(Path(self.temporary_directory.name) / "elements"),
        )

    def tearDown(self):
        self.pet.close()
        self.temporary_directory.cleanup()

    def test_custom_theme_round_trips_per_pet(self):
        theme = SpeechBubbleTheme(
            background="#112233",
            border="#445566",
            text="#ffffff",
            shadow="#000000",
            shape="jelly",
            tail="droplet",
            pattern="stars",
        )

        self.pet.set_custom_bubble_theme(theme)
        loaded = PetPreferences(
            self.pet.pet_id,
            self.settings,
        ).load_custom_bubble_theme()

        self.assertEqual(self.pet.bubble_theme_mode, "custom")
        self.assertEqual(self.pet.bubble_controller.theme, theme)
        self.assertEqual(loaded, theme)


if __name__ == "__main__":
    unittest.main()
