import json
import tempfile
import unittest

from pathlib import Path

from watched_kettle.build_profiles import (
    BuildProfileError,
    PRIVATE_BETA_BUILD_PROFILE,
    PUBLIC_BUILD_PROFILE,
    collect_pet_build_sources,
    normalize_build_profile,
)


class BuildProfileTests(unittest.TestCase):
    @staticmethod
    def write_pet(root, folder, pet_id, distribution=None):
        pet = root / folder
        pet.mkdir(parents=True)
        manifest = {"id": pet_id, "spritesheetPath": "spritesheet.webp"}
        if distribution is not None:
            manifest["distribution"] = distribution
        (pet / "pet.json").write_text(
            json.dumps(manifest),
            encoding="utf-8",
        )
        (pet / "spritesheet.webp").write_bytes(b"fixture")

    def test_profile_aliases_are_normalized(self):
        self.assertEqual(
            normalize_build_profile("PrivateBeta"),
            PRIVATE_BETA_BUILD_PROFILE,
        )
        self.assertEqual(
            normalize_build_profile("public"),
            PUBLIC_BUILD_PROFILE,
        )

    def test_public_profile_never_collects_private_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_pet(
                root / "pets",
                "guide",
                "guide",
                PUBLIC_BUILD_PROFILE,
            )
            self.write_pet(
                root / "private-pets",
                "private",
                "private",
                PRIVATE_BETA_BUILD_PROFILE,
            )

            public = collect_pet_build_sources(root, PUBLIC_BUILD_PROFILE)
            private = collect_pet_build_sources(
                root,
                PRIVATE_BETA_BUILD_PROFILE,
            )

            self.assertEqual([source.pet_id for source in public], ["guide"])
            self.assertEqual(
                {source.pet_id for source in private},
                {"guide", "private"},
            )
            self.assertTrue(
                all(source.destination.startswith("pets/") for source in private)
            )

    def test_private_marker_in_public_root_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_pet(
                root / "pets",
                "leak",
                "leak",
                PRIVATE_BETA_BUILD_PROFILE,
            )

            with self.assertRaises(BuildProfileError):
                collect_pet_build_sources(root, PUBLIC_BUILD_PROFILE)

    def test_missing_distribution_marker_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_pet(root / "pets", "unmarked", "unmarked")

            with self.assertRaises(BuildProfileError):
                collect_pet_build_sources(root, PUBLIC_BUILD_PROFILE)

    def test_current_public_profile_contains_only_original_guide_pet(self):
        sources = collect_pet_build_sources(Path("."), PUBLIC_BUILD_PROFILE)
        self.assertEqual({source.pet_id for source in sources}, {"mori-bot"})

    def test_frame_images_ship_with_their_pet(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_pet(root / "pets", "guide", "guide", PUBLIC_BUILD_PROFILE)
            pet = root / "pets" / "guide"
            (pet / "bubble").mkdir()
            (pet / "bubble" / "corner.png").write_bytes(b"fixture")
            manifest = json.loads((pet / "pet.json").read_text(encoding="utf-8"))
            layer = {"image": "bubble/corner.png", "anchor": "top-left"}
            manifest["bubbleTheme"] = {"frame": {"overlay": [layer, layer]}}
            (pet / "pet.json").write_text(json.dumps(manifest), encoding="utf-8")

            (source,) = collect_pet_build_sources(root, PUBLIC_BUILD_PROFILE)

            self.assertEqual(
                source.frame_images,
                ((pet.resolve() / "bubble" / "corner.png", "pets/guide/bubble"),),
            )

    def test_frame_image_outside_the_pet_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_pet(root / "pets", "guide", "guide", PUBLIC_BUILD_PROFILE)
            (root / "outside.png").write_bytes(b"fixture")
            manifest_path = root / "pets" / "guide" / "pet.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            layer = {"image": "../../outside.png", "anchor": "top-left"}
            manifest["bubbleTheme"] = {"frame": {"backdrop": [layer]}}
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaises(BuildProfileError):
                collect_pet_build_sources(root, PUBLIC_BUILD_PROFILE)


if __name__ == "__main__":
    unittest.main()
