import json
import tempfile
import unittest

from pathlib import Path

from watched_kettle.app import resolve_startup_pet
from watched_kettle.app_preferences import ApplicationPreferences
from watched_kettle.pet.catalog import (
    discover_pets,
    discover_pets_in_roots,
    order_pet_entries,
    personalize_pet_catalog,
)
from tests.test_pet_preferences import FakeSettings


class PetCatalogTests(unittest.TestCase):
    @staticmethod
    def write_pet(root, folder, pet_id, display_name=None):
        pet = root / folder
        pet.mkdir()
        (pet / "pet.json").write_text(
            json.dumps(
                {
                    "id": pet_id,
                    "displayName": display_name or pet_id,
                }
            ),
            encoding="utf-8",
        )
        (pet / "spritesheet.webp").write_bytes(b"placeholder")
        return pet

    def test_discovers_valid_packages_and_uses_display_name(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            valid = root / "valid"
            valid.mkdir()
            (valid / "pet.json").write_text(
                json.dumps(
                    {
                        "id": "valid-id",
                        "displayName": "Visible Name",
                    }
                ),
                encoding="utf-8",
            )
            (valid / "spritesheet.webp").write_bytes(b"placeholder")
            invalid = root / "invalid"
            invalid.mkdir()
            (invalid / "pet.json").write_text("{}", encoding="utf-8")

            entries = discover_pets(root)

            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].id, "valid-id")
            self.assertEqual(entries[0].display_name, "Visible Name")
            self.assertEqual(entries[0].description, "")

    def test_merges_user_and_bundled_roots_with_user_duplicate_first(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            user_root = root / "user"
            bundled_root = root / "bundled"
            user_root.mkdir()
            bundled_root.mkdir()
            self.write_pet(user_root, "custom", "same", "사용자 펫")
            self.write_pet(bundled_root, "builtin", "same", "내장 펫")
            self.write_pet(bundled_root, "other", "other", "다른 펫")

            entries = discover_pets_in_roots((user_root, bundled_root))

            by_id = {entry.id: entry for entry in entries}
            self.assertEqual(set(by_id), {"same", "other"})
            self.assertEqual(by_id["same"].display_name, "사용자 펫")

    def test_name_order_uses_id_to_break_duplicate_display_names(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.write_pet(root, "z-folder", "z-id", "Same")
            self.write_pet(root, "a-folder", "a-id", "Same")

            entries = order_pet_entries(discover_pets(root))

            self.assertEqual([entry.id for entry in entries], ["a-id", "z-id"])

    def test_custom_order_appends_unknown_pets_in_name_order(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.write_pet(root, "alpha", "alpha", "Alpha")
            self.write_pet(root, "beta", "beta", "Beta")
            self.write_pet(root, "gamma", "gamma", "Gamma")

            entries = order_pet_entries(
                discover_pets(root),
                "custom",
                ("gamma",),
            )

            self.assertEqual(
                [entry.id for entry in entries],
                ["gamma", "alpha", "beta"],
            )

    def test_hidden_pets_are_filtered_and_empty_catalog_recovers(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.write_pet(root, "alpha", "alpha", "Alpha")
            self.write_pet(root, "beta", "beta", "Beta")
            entries = discover_pets(root)

            visible = personalize_pet_catalog(
                entries,
                hidden_ids={"alpha"},
            )
            recovered = personalize_pet_catalog(
                entries,
                hidden_ids={"alpha", "beta"},
                fallback_pet_id="beta",
            )

            self.assertEqual([entry.id for entry in visible], ["beta"])
            self.assertEqual([entry.id for entry in recovered], ["beta"])

    def test_required_current_pet_stays_visible(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.write_pet(root, "alpha", "alpha", "Alpha")
            self.write_pet(root, "beta", "beta", "Beta")

            visible = personalize_pet_catalog(
                discover_pets(root),
                hidden_ids={"alpha"},
                required_visible_id="alpha",
            )

            self.assertEqual(
                [entry.id for entry in visible],
                ["alpha", "beta"],
            )

    def test_saved_pet_is_used_for_normal_startup(self):
        preferences = ApplicationPreferences(FakeSettings({"selectedPetId": "beta"}))

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.write_pet(root, "alpha", "alpha")
            self.write_pet(root, "beta", "beta")

            selected = resolve_startup_pet(preferences=preferences, pets_root=root)

            self.assertEqual(selected, root / "beta")

    def test_missing_saved_pet_falls_back_to_default_pet(self):
        preferences = ApplicationPreferences(FakeSettings({"selectedPetId": "missing"}))

        self.assertEqual(
            resolve_startup_pet(
                preferences=preferences,
                pets_root=Path("pets"),
            ),
            Path("pets/mori-bot"),
        )

    def test_explicit_developer_path_overrides_saved_pet(self):
        preferences = ApplicationPreferences(FakeSettings({"selectedPetId": "beta"}))

        self.assertEqual(
            resolve_startup_pet(
                Path("pets/mori-bot"),
                preferences,
            ),
            Path("pets/mori-bot"),
        )

    def test_hidden_selected_pet_falls_back_to_visible_pet(self):
        preferences = ApplicationPreferences(
            FakeSettings(
                {
                    "selectedPetId": "beta",
                    "petCatalog/hiddenIds": '["beta"]',
                }
            )
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.write_pet(root, "beta", "beta")
            self.write_pet(root, "gamma", "gamma")

            selected = resolve_startup_pet(preferences=preferences, pets_root=root)

            self.assertEqual(selected, root / "gamma")


if __name__ == "__main__":
    unittest.main()
