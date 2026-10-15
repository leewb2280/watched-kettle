import os
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QTransform
from PySide6.QtWidgets import QApplication

from watched_kettle.pet.loader import load_pet


EXPECTED_FRAME_COUNTS = {
    "idle": 6,
    "running-right": 8,
    "running-left": 8,
    "waving": 4,
    "jumping": 5,
    "failed": 8,
    "waiting": 6,
    "running": 6,
    "review": 6,
}


class ActualPetLoaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_all_bundled_pets_are_complete_v2_packages(self):
        # The public snapshot has no private-pets folder; check whatever ships.
        pet_directories = sorted(
            directory
            for root in (Path("pets"), Path("private-pets"))
            for directory in root.glob("*/")
        )
        self.assertTrue(pet_directories)

        for pet_directory in pet_directories:
            with self.subTest(pet=pet_directory.name):
                manifest, frames, look_frames, version = load_pet(pet_directory)

                self.assertEqual(manifest.get("spriteVersionNumber"), 2)
                self.assertEqual(version, 2)
                self.assertEqual(len(look_frames), 16)
                self.assertEqual(
                    {
                        state: len(state_frames)
                        for state, state_frames in frames.items()
                    },
                    EXPECTED_FRAME_COUNTS,
                )

                if manifest.get("mirrorRightLookFromLeft", False):
                    mirrored_right = (
                        look_frames[4]
                        .transformed(QTransform.fromScale(-1, 1))
                        .toImage()
                    )
                    self.assertEqual(
                        mirrored_right,
                        look_frames[12].toImage(),
                    )

    def test_manifest_must_be_an_object(self):
        with TemporaryDirectory() as temporary_directory:
            pet_directory = Path(temporary_directory)
            (pet_directory / "pet.json").write_text(
                json.dumps(["not", "an", "object"]),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "최상위 값은 객체"):
                load_pet(pet_directory)

    def test_spritesheet_must_stay_inside_pet_directory(self):
        with TemporaryDirectory() as temporary_directory:
            pet_directory = Path(temporary_directory) / "pet"
            pet_directory.mkdir()
            (pet_directory / "pet.json").write_text(
                json.dumps({"spritesheetPath": "../outside.webp"}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "펫 폴더 내부"):
                load_pet(pet_directory)


if __name__ == "__main__":
    unittest.main()
