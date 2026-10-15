import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.stage_private_pets import stage_private_pets


def write_pet(root, folder, distribution, frame_image=None):
    pet = root / folder
    pet.mkdir(parents=True)
    manifest = {"id": folder, "distribution": distribution}
    if frame_image:
        (pet / "bubble").mkdir()
        (pet / "bubble" / frame_image).write_bytes(b"png")
        layer = {"image": f"bubble/{frame_image}", "anchor": "top-left"}
        manifest["bubbleTheme"] = {"frame": {"overlay": [layer]}}
    (pet / "pet.json").write_text(json.dumps(manifest), encoding="utf-8")
    (pet / "spritesheet.webp").write_bytes(b"sprite")
    (pet / "README.md").write_text("notes", encoding="utf-8")


class StagePrivatePetsTests(unittest.TestCase):
    def test_only_private_runtime_files_are_staged(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_pet(root / "pets", "guide", "public")
            write_pet(root / "private-pets", "sample", "private-beta", "corner.png")
            target = root / "stage"

            staged = stage_private_pets(root, target)

            self.assertEqual(staged, ["sample"])
            self.assertEqual(
                sorted(
                    path.relative_to(target).as_posix()
                    for path in target.rglob("*")
                    if path.is_file()
                ),
                [
                    "sample/bubble/corner.png",
                    "sample/pet.json",
                    "sample/spritesheet.webp",
                ],
            )
            with self.assertRaises(ValueError):
                stage_private_pets(root, target)

    def test_missing_private_packages_fail(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_pet(root / "pets", "guide", "public")

            with self.assertRaises(ValueError):
                stage_private_pets(root, root / "stage")
            self.assertFalse((root / "stage").exists())


if __name__ == "__main__":
    unittest.main()
