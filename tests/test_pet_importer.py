"""Downloaded atlases must become complete, independent local packages."""

from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from watched_kettle.config import ANIMATIONS, FRAME_HEIGHT, FRAME_WIDTH
from watched_kettle.pet.catalog import discover_pets
from watched_kettle.pet.importer import MAX_IMPORT_BYTES, PetImportError, PetImporter


def make_atlas(version=2):
    image = Image.new("RGBA", (1536, 1872 if version == 1 else 2288))
    draw = ImageDraw.Draw(image)
    rows = [(item["row"], item["frames"]) for item in ANIMATIONS.values()]
    if version == 2:
        rows += [(9, 8), (10, 8)]
    for row, count in rows:
        for column in range(count):
            x, y = column * FRAME_WIDTH, row * FRAME_HEIGHT
            draw.rectangle((x + 30, y + 30, x + 150, y + 170), fill=(40, 120, 200, 255))
    return image


class PetImporterTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pets = self.root / "pets"
        self.now = 0
        self.importer = PetImporter(self.pets, clock=lambda: self.now)

    def source(self, version=2, format="PNG", name="웹 펫"):
        path = self.root / f"{name}.{format.lower()}"
        make_atlas(version).save(path, format=format, lossless=True, exact=True)
        return path

    def test_formats_versions_and_independent_lossless_packages(self):
        for version in (1, 2):
            for format in ("PNG", "WEBP"):
                with self.subTest(version=version, format=format):
                    source = self.source(version, format)
                    with Image.open(source) as image:
                        expected = image.convert("RGBA").tobytes()
                    prepared = self.importer.prepare(source)
                    self.assertEqual(prepared.name, "웹 펫")
                    self.assertEqual(prepared.version, version)
                    self.assertLess(len(prepared.thumbnail), 512 * 1024)
                    result = self.importer.commit(prepared.token, "  수정한 이름  ")
                    source.unlink()
                    manifest = json.loads(
                        (self.pets / result.id / "pet.json").read_text("utf-8")
                    )
                    self.assertEqual(manifest["displayName"], "수정한 이름")
                    self.assertEqual(manifest["distribution"], "private")
                    self.assertEqual(manifest["spriteVersionNumber"], version)
                    with Image.open(
                        self.pets / result.id / "spritesheet.webp"
                    ) as saved:
                        self.assertEqual(saved.convert("RGBA").tobytes(), expected)
                    self.assertTrue(
                        any(entry.id == result.id for entry in discover_pets(self.pets))
                    )

    def test_equivalent_images_deduplicate_without_renaming(self):
        first = self.importer.prepare(self.source(format="PNG"))
        added = self.importer.commit(first.token, "첫 이름")
        second = self.importer.prepare(self.source(format="WEBP"))
        self.assertEqual(first.pet_id, second.pet_id)
        duplicate = self.importer.commit(second.token, "다른 이름")
        self.assertTrue(duplicate.already_exists)
        self.assertEqual(duplicate.name, "첫 이름")
        self.assertEqual(added.id, duplicate.id)
        self.assertEqual(len(discover_pets(self.pets)), 1)

    def test_hidden_rgb_and_metadata_are_handled_without_pixel_changes(self):
        image = make_atlas()
        image.putpixel((0, 0), (13, 27, 89, 0))
        source = self.root / "metadata.png"
        image.save(source, exif=b"test-metadata")
        prepared = self.importer.prepare(source)
        result = self.importer.commit(prepared.token, "metadata")
        with Image.open(self.pets / result.id / "spritesheet.webp") as saved:
            self.assertEqual(saved.convert("RGBA").tobytes(), image.tobytes())
            self.assertNotIn("exif", saved.info)

    def test_same_name_different_pixels_get_distinct_ids(self):
        source = self.source()
        prepared = self.importer.prepare(source)
        first = self.importer.commit(prepared.token, "동일 이름")
        image = make_atlas()
        image.putpixel((31, 31), (255, 0, 0, 255))
        image.save(source)
        prepared = self.importer.prepare(source)
        second = self.importer.commit(prepared.token, "동일 이름")
        self.assertNotEqual(first.id, second.id)

    def test_cancel_reselect_and_expiration_do_not_publish_packages(self):
        first = self.importer.prepare(self.source())
        second = self.importer.prepare(self.source(version=1))
        with self.assertRaisesRegex(PetImportError, "바뀌었습니다"):
            self.importer.commit(first.token, "old")
        self.importer.cancel(first.token)
        self.assertIsNotNone(self.importer.prepared)
        self.now = 600
        with self.assertRaisesRegex(PetImportError, "만료"):
            self.importer.commit(second.token, "expired")
        self.assertIsNone(self.importer.prepared)
        prepared = self.importer.prepare(self.source())
        self.importer.cancel(prepared.token)
        with self.assertRaises(PetImportError):
            self.importer.commit(prepared.token, "cancelled")
        self.assertFalse(self.pets.exists())

    def test_invalid_images_and_frames_are_actionable(self):
        cases = [
            (Image.new("RGBA", (12, 12)), "크기"),
            (Image.new("RGBA", (1536, 1872), "red"), "투명"),
            (Image.new("RGBA", (1536, 1872)), "1행 1열"),
        ]
        missing = make_atlas()
        missing.paste((0, 0, 0, 0), (0, 2080, 192, 2288))
        cases.append((missing, "11행 1열"))
        for image, message in cases:
            with self.subTest(message=message):
                source = self.root / "invalid.png"
                image.save(source)
                with self.assertRaisesRegex(PetImportError, message):
                    self.importer.prepare(source)
        source.write_bytes(b"broken")
        with self.assertRaisesRegex(PetImportError, "손상"):
            self.importer.prepare(source)
        Image.new("RGB", (12, 12)).save(source, format="JPEG")
        with self.assertRaisesRegex(PetImportError, "PNG"):
            self.importer.prepare(source)
        next_frame = make_atlas()
        next_frame.putpixel((31, 31), (255, 0, 0, 255))
        make_atlas().save(
            source, save_all=True, append_images=[next_frame], duration=100
        )
        with self.assertRaisesRegex(PetImportError, "정지"):
            self.importer.prepare(source)

    def test_input_size_is_bounded_and_errors_do_not_expose_paths(self):
        with patch.object(
            Path, "open", return_value=BytesIO(b"x" * (MAX_IMPORT_BYTES + 1))
        ):
            with self.assertRaisesRegex(PetImportError, "20MiB"):
                self.importer.prepare(self.root / "private.png")
        with self.assertRaises(PetImportError) as caught:
            self.importer.prepare(self.root / "private.png")
        self.assertNotIn(str(self.root), str(caught.exception))

    def test_storage_failure_is_atomic_and_retryable(self):
        prepared = self.importer.prepare(self.source())
        with patch.object(Path, "rename", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(PetImportError, "저장"):
                self.importer.commit(prepared.token, "retry")
        self.assertEqual(list(self.pets.iterdir()), [])
        self.assertEqual(list(self.root.glob("pet-import-*")), [])
        result = self.importer.commit(prepared.token, "retry")
        self.assertFalse(result.already_exists)

    def test_bad_names_and_corrupted_duplicate_never_overwrite(self):
        prepared = self.importer.prepare(self.source())
        for name in (" ", "x" * 101, None):
            with self.assertRaises(PetImportError):
                self.importer.commit(prepared.token, name)
        result = self.importer.commit(prepared.token, "valid")
        path = self.pets / result.id / "spritesheet.webp"
        path.write_bytes(b"broken")
        with self.assertRaisesRegex(PetImportError, "손상"):
            self.importer.commit(prepared.token, "overwrite")
        self.assertEqual(path.read_bytes(), b"broken")
