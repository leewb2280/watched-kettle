"""Package lifecycle against isolated real files/settings, including interrupted I/O."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QSettings

from watched_kettle.app_preferences import ApplicationPreferences
from watched_kettle.pet.trash import PetTrashService, PetTrashError
from tests import test_pet_catalog as catalog_tests


class PetTrashTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.user = self.root / "pets"
        self.bundled = self.root / "bundled"
        self.user.mkdir()
        self.bundled.mkdir()
        self.settings = QSettings(
            str(self.root / "settings.ini"), QSettings.Format.IniFormat
        )
        self.preferences = ApplicationPreferences(self.settings)
        self.store = PetTrashService(
            self.user, (self.user, self.bundled), self.preferences
        )
        self.write = catalog_tests.PetCatalogTests.write_pet
        self.write(self.bundled, "base", "base")
        self.preferences.save_selected_pet_id("base")
        for pet_id in ("a", "b", "c"):
            self.write(self.user, pet_id, pet_id)
        self.preferences.save_pet_catalog_sort_mode("custom")
        self.preferences.save_pet_custom_order(("a", "b", "c", "base"))

    def test_move_restart_restore_preserves_settings_visibility_and_neighbors(self):
        self.preferences.save_hidden_pet_ids(("b",))
        self.settings.setValue("pets/b/width", 224)
        record = self.store.move("b")
        self.assertFalse((self.user / "b").exists())
        self.assertNotIn("b", self.preferences.load_hidden_pet_ids())
        self.assertEqual(self.settings.value("pets/b/width"), 224)
        restarted = PetTrashService(
            self.user, (self.user, self.bundled), self.preferences
        )
        self.assertEqual(restarted.recover(), [])
        self.assertEqual(len(restarted.records()), 1)
        restarted.restore(record["trashId"])
        self.assertTrue((self.user / "b" / "pet.json").is_file())
        self.assertIn("b", self.preferences.load_hidden_pet_ids())
        self.assertEqual(
            self.preferences.load_pet_custom_order(), ("a", "b", "c", "base")
        )
        self.assertEqual(self.preferences.load_selected_pet_id(), "base")
        self.assertEqual(restarted.records(), [])

    def test_restore_uses_remaining_neighbor_or_appends(self):
        record = self.store.move("b")
        self.store.move("a")
        self.store.restore(record["trashId"])
        self.assertEqual(self.preferences.load_pet_custom_order(), ("b", "c", "base"))

    def test_delete_removes_only_target_package_and_individual_settings(self):
        self.settings.setValue("pets/b/width", 192)
        self.settings.setValue("pets/c/width", 224)
        self.settings.setValue("bubble/scale", 120)
        record = self.store.move("b")
        self.store.delete(record["trashId"])
        self.assertIsNone(self.settings.value("pets/b/width"))
        self.assertEqual(self.settings.value("pets/c/width"), 224)
        self.assertEqual(self.settings.value("bubble/scale"), 120)
        self.assertEqual(self.store.records(), [])

    def test_protects_builtin_current_and_shadowed_ids(self):
        with self.assertRaises(PetTrashError):
            self.store.move("base")
        self.preferences.save_selected_pet_id("a")
        with self.assertRaises(PetTrashError):
            self.store.move("a")
        self.write(self.bundled, "shadow", "b")
        with self.assertRaisesRegex(PetTrashError, "중복 ID"):
            self.store.move("b")
        self.assertTrue((self.user / "b").is_dir())

    def test_failed_move_does_not_change_catalog_or_leave_record(self):
        with patch.object(Path, "rename", side_effect=PermissionError()):
            with self.assertRaises(PermissionError):
                self.store.move("b")
        self.assertTrue((self.user / "b").exists())
        self.assertEqual(
            self.preferences.load_pet_custom_order(), ("a", "b", "c", "base")
        )
        self.assertEqual(self.store.records(), [])

    def test_failed_save_rolls_package_and_preferences_back(self):
        original = self.store._sync
        with patch.object(
            self.store, "_sync", side_effect=[PetTrashError("save failed"), None]
        ):
            with self.assertRaisesRegex(PetTrashError, "save failed"):
                self.store.move("b")
        original()
        self.assertTrue((self.user / "b").is_dir())
        self.assertEqual(
            self.preferences.load_pet_custom_order(), ("a", "b", "c", "base")
        )
        self.assertEqual(self.store.records(), [])

    def test_recovers_interrupted_move_before_startup_catalog(self):
        with patch.object(self.store, "_forget", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.store.move("b")
        self.assertEqual(self.store.records()[0]["state"], "moving")
        self.assertEqual(self.store.recover(), [])
        self.assertEqual(self.store.records()[0]["state"], "trashed")
        self.assertNotIn("b", self.preferences.load_pet_custom_order())

    def test_recovers_interrupted_restore(self):
        record = self.store.move("b")
        with patch.object(
            self.store, "_restore_preferences", side_effect=KeyboardInterrupt
        ):
            with self.assertRaises(KeyboardInterrupt):
                self.store.restore(record["trashId"])
        self.assertTrue((self.user / "b").is_dir())
        self.assertEqual(self.store.recover(), [])
        self.assertEqual(self.store.records(), [])
        self.assertEqual(
            self.preferences.load_pet_custom_order(), ("a", "b", "c", "base")
        )

    def test_partial_delete_stays_retryable_and_restart_finishes_intent(self):
        record = self.store.move("b")
        self.settings.setValue("pets/b/width", 224)
        with patch(
            "watched_kettle.pet.trash.shutil.rmtree", side_effect=PermissionError()
        ):
            with self.assertRaises(PermissionError):
                self.store.delete(record["trashId"])
            self.assertEqual(self.store.recover(retry_deletes=False), [])
        self.assertEqual(self.store.records()[0]["state"], "deleting")
        self.assertEqual(self.settings.value("pets/b/width"), 224)
        self.assertEqual(self.store.recover(), [])
        self.assertEqual(self.store.records(), [])
        self.assertIsNone(self.settings.value("pets/b/width"))

    def test_restore_collision_never_overwrites_and_purge_protects_live_settings(self):
        record = self.store.move("b")
        self.write(self.user, "b", "b", "New")
        self.settings.setValue("pets/b/width", 224)
        self.preferences.save_hidden_pet_ids(("b",))
        self.preferences.save_pet_custom_order(("a", "b", "c", "base"))
        with self.assertRaises(PetTrashError):
            self.store.restore(record["trashId"])
        # Purging the trashed copy must not strand it: the live package and its
        # settings stay, and the live pet can then be moved to the trash.
        self.store.delete(record["trashId"])
        self.assertEqual(self.store.records(), [])
        self.assertEqual(
            json.loads((self.user / "b" / "pet.json").read_text())["displayName"], "New"
        )
        self.assertEqual(self.settings.value("pets/b/width"), 224)
        self.assertIn("b", self.preferences.load_hidden_pet_ids())
        self.assertEqual(
            self.preferences.load_pet_custom_order(), ("a", "b", "c", "base")
        )
        self.store.move("b")
        self.assertFalse((self.user / "b").exists())

    def test_unreadable_and_tampered_records_are_preserved(self):
        record = self.store.move("b")
        path = self.store.root / record["trashId"] / "record.json"
        raw = json.loads(path.read_text())
        raw["folder"] = "../outside"
        path.write_text(json.dumps(raw))
        self.assertTrue(self.store.recover())
        self.assertTrue((path.parent / "package").exists())
        with self.assertRaises(PetTrashError):
            self.store.restore(record["trashId"])
        with self.assertRaises(PetTrashError):
            self.store.delete("../outside")

    def test_links_inside_packages_are_not_followed(self):
        outside = self.root / "outside.txt"
        outside.write_text("keep")
        link = self.user / "b" / "linked.txt"
        try:
            link.symlink_to(outside)
        except OSError:
            self.skipTest("Windows symlink privilege unavailable")
        with self.assertRaises(PetTrashError):
            self.store.move("b")
        self.assertEqual(outside.read_text(), "keep")

    def test_corrupt_package_remains_available_for_permanent_delete(self):
        record = self.store.move("b")
        (self.store.root / record["trashId"] / "package" / "pet.json").write_text(
            "broken"
        )
        with self.assertRaises(PetTrashError):
            self.store.restore(record["trashId"])
        self.store.delete(record["trashId"])
        self.assertEqual(self.store.records(), [])

    def test_windows_junction_in_trash_is_preserved_without_touching_target(self):
        try:
            from _winapi import CreateJunction
        except ImportError:
            self.skipTest("Windows junction test")
        record = self.store.move("b")
        outside = self.root / "outside"
        outside.mkdir()
        sentinel = outside / "keep.txt"
        sentinel.write_text("keep")
        link = self.store.root / record["trashId"] / "package" / "outside-link"
        CreateJunction(str(outside), str(link))
        self.assertTrue(link.is_junction())
        with self.assertRaises(PetTrashError):
            self.store.delete(record["trashId"])
        self.assertTrue(self.store.recover())
        self.assertEqual(sentinel.read_text(), "keep")

    def test_unreadable_trash_root_does_not_block_startup_recovery(self):
        self.store.root.mkdir()
        with patch.object(Path, "iterdir", side_effect=PermissionError()):
            self.assertTrue(self.store.recover())
        self.assertTrue((self.user / "b" / "pet.json").is_file())

    def test_file_in_place_of_trash_root_is_preserved(self):
        self.store.root.write_text("preserve unknown data")
        self.assertTrue(self.store.recover())
        self.assertEqual(self.store.root.read_text(), "preserve unknown data")
