import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from watched_kettle.application.paths import (
    migrate_legacy_data_root,
    resolve_data_root,
)


class LegacyDataRootMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.local = Path(self.temp.name)
        self.current = self.local / "WatchedKettle"
        self.legacy = self.local / "CodexDesktopPets"

    def tearDown(self):
        self.temp.cleanup()

    def write_legacy_data(self):
        (self.legacy / "pets").mkdir(parents=True)
        (self.legacy / "settings.ini").write_text("[General]\n", encoding="utf-8")

    def test_fresh_install_uses_current_root(self):
        self.assertEqual(migrate_legacy_data_root(self.local), "none")
        self.assertEqual(resolve_data_root(self.local), self.current)

    def test_legacy_data_moves_to_current_root(self):
        self.write_legacy_data()

        self.assertEqual(migrate_legacy_data_root(self.local), "migrated")

        self.assertEqual(resolve_data_root(self.local), self.current)
        self.assertTrue((self.current / "settings.ini").is_file())
        self.assertFalse(self.legacy.exists())
        self.assertEqual(migrate_legacy_data_root(self.local), "none")

    def test_hook_runtime_created_first_does_not_block_migration(self):
        self.write_legacy_data()
        (self.current / "runtime" / "events").mkdir(parents=True)

        self.assertEqual(migrate_legacy_data_root(self.local), "migrated")
        self.assertTrue((self.current / "settings.ini").is_file())

    def test_locked_legacy_root_stays_in_use_until_next_start(self):
        self.write_legacy_data()
        with patch(
            "watched_kettle.application.paths.os.rename",
            side_effect=PermissionError,
        ):
            self.assertEqual(migrate_legacy_data_root(self.local), "kept_legacy")

        self.assertEqual(resolve_data_root(self.local), self.legacy)
        self.assertEqual(migrate_legacy_data_root(self.local), "migrated")

    def test_existing_current_data_is_never_overwritten(self):
        self.write_legacy_data()
        self.current.mkdir()
        (self.current / "settings.ini").write_text("new", encoding="utf-8")

        self.assertEqual(migrate_legacy_data_root(self.local), "none")
        self.assertEqual(resolve_data_root(self.local), self.current)
        self.assertEqual(
            (self.current / "settings.ini").read_text(encoding="utf-8"), "new"
        )
        self.assertTrue((self.legacy / "settings.ini").is_file())

    def test_legacy_runtime_alone_is_not_user_data(self):
        (self.legacy / "runtime").mkdir(parents=True)

        self.assertEqual(migrate_legacy_data_root(self.local), "none")
        self.assertEqual(resolve_data_root(self.local), self.current)


if __name__ == "__main__":
    unittest.main()
