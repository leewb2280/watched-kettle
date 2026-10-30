import json
import os
import shutil
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

    def test_images_folder_holds_only_images_and_one_library_lists_them(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.png"
            self.write_image(source)
            registry = BubbleElementRegistry(root / "elements")

            first = registry.import_image(source, "ornament", "first")
            second = registry.import_image(source, "photo", "second")

            images = registry.images_root
            self.assertEqual(
                sorted(path.name for path in images.iterdir()),
                sorted([first.image_path.name, second.image_path.name]),
            )
            library = json.loads(
                (root / "elements" / "library.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                [entry["name"] for entry in library["elements"]], ["first", "second"]
            )
            self.assertEqual(
                sorted(path.name for path in (root / "elements").iterdir()),
                ["images", "library.json"],
            )
            self.assertTrue(registry.delete(first.reference))
            self.assertFalse(first.image_path.exists())
            library = json.loads(
                (root / "elements" / "library.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                [entry["id"] for entry in library["elements"]], [second.id]
            )

    def test_old_notes_beside_images_move_into_the_library_once(self):
        with TemporaryDirectory() as directory:
            elements = Path(directory) / "elements"
            elements.mkdir()
            kept, orphan = "b" * 32, "c" * 32
            self.write_image(elements / f"{kept}.png")
            for element_id in (kept, orphan):
                (elements / f"{element_id}.json").write_text(
                    json.dumps(
                        {
                            "id": element_id,
                            "name": element_id[:4],
                            "kind": "photo",
                            "image": f"{element_id}.png",
                        }
                    ),
                    encoding="utf-8",
                )
            (elements / "notes.json").write_text("{}", encoding="utf-8")

            registry = BubbleElementRegistry(elements)

            element = registry.get(f"user:{kept}")
            self.assertEqual((element.name, element.kind), ("bbbb", "photo"))
            self.assertEqual(element.image_path, registry.images_root / f"{kept}.png")
            self.assertFalse(registry.pixmap(element.reference).isNull())
            # The note whose image was deleted by hand is cleaned up; files
            # the app did not write are left alone.
            self.assertEqual(
                sorted(path.name for path in elements.iterdir()),
                ["images", "library.json", "notes.json"],
            )
            self.assertEqual(
                [item.id for item in BubbleElementRegistry(elements).elements], [kept]
            )

    def test_an_image_deleted_in_the_folder_leaves_the_library(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.png"
            other = root / "other.png"
            self.write_image(source)
            self.write_image(other, color=(0, 0, 255, 180))
            registry = BubbleElementRegistry(root / "elements")
            gone = registry.import_image(source, "ornament", "gone")
            kept = registry.import_image(other, "ornament", "kept")

            gone.image_path.unlink()
            registry.refresh()

            self.assertEqual([item.id for item in registry.elements], [kept.id])
            library = json.loads(
                (root / "elements" / "library.json").read_text(encoding="utf-8")
            )
            self.assertEqual([entry["id"] for entry in library["elements"]], [kept.id])

    def test_the_same_pixels_reuse_one_element_per_kind(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.png"
            self.write_image(source)
            registry = BubbleElementRegistry(root / "elements")
            first = registry.import_image(source, "sticker", "first")
            again = registry.import_image(source, "sticker", "again")
            other_kind = registry.import_image(source, "ornament")
            self.assertEqual(again.id, first.id)
            self.assertEqual(again.name, "first")
            self.assertNotEqual(other_kind.id, first.id)
            # The match survives a restart; deleting the element forgets it.
            reopened = BubbleElementRegistry(root / "elements")
            self.assertEqual(reopened.import_image(source, "sticker").id, first.id)
            reopened.delete(first.reference)
            self.assertNotEqual(reopened.import_image(source, "sticker").id, first.id)

    def test_old_copies_get_digests_and_are_found_as_duplicates(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.png"
            self.write_image(source)
            elements = root / "elements"
            images = elements / "images"
            images.mkdir(parents=True)
            ids = ["a" * 32, "b" * 32, "c" * 32]
            for element_id in ids:
                shutil.copyfile(source, images / f"{element_id}.png")
            # Stored before pixel digests: no "pixels" key.
            (elements / "library.json").write_text(
                json.dumps(
                    dict(
                        format=1,
                        elements=[
                            dict(
                                id=ids[0],
                                name="old",
                                kind="sticker",
                                image=f"{ids[0]}.png",
                            ),
                            dict(
                                id=ids[1],
                                name="copy",
                                kind="sticker",
                                image=f"{ids[1]}.png",
                            ),
                            dict(
                                id=ids[2],
                                name="other kind",
                                kind="ornament",
                                image=f"{ids[2]}.png",
                            ),
                        ],
                    )
                ),
                encoding="utf-8",
            )

            registry = BubbleElementRegistry(elements)

            library = json.loads(
                (elements / "library.json").read_text(encoding="utf-8")
            )
            self.assertTrue(all(entry.get("pixels") for entry in library["elements"]))
            self.assertEqual(registry.duplicates(), [(ids[0], [ids[1]])])
            # The picture is matched to the oldest copy, so saving adds nothing.
            self.assertEqual(registry.import_image(source, "sticker").id, ids[0])
            registry.delete(f"user:{ids[1]}")
            self.assertEqual(registry.duplicates(), [])

    def test_an_unreadable_library_is_kept_aside_not_written_over(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.png"
            self.write_image(source)
            elements = root / "elements"
            elements.mkdir()
            (elements / "library.json").write_text("{broken", encoding="utf-8")
            registry = BubbleElementRegistry(elements)
            self.assertEqual(registry.elements, ())
            self.assertEqual(
                (elements / "library.json").read_text(encoding="utf-8"), "{broken"
            )

            element = registry.import_image(source, "ornament", "new")

            self.assertEqual(
                (elements / "library.json.bak").read_text(encoding="utf-8"), "{broken"
            )
            self.assertEqual([item.id for item in registry.elements], [element.id])


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
