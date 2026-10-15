import json
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.release_artifacts import (
    check_bundle_state,
    generate_manifest,
    verify_archive,
)


class ReleaseArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bundle = self.root / "WatchedKettle"
        self.bundle.mkdir()
        (self.bundle / "app.exe").write_bytes(b"binary")
        (self.bundle / "pets").mkdir()
        (self.bundle / "pets" / "pet.json").write_text("{}", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def archive(self):
        archive_path = self.root / "release.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            for path in self.bundle.rglob("*"):
                if path.is_file():
                    archive.write(path, path.relative_to(self.root).as_posix())
        return archive_path

    def test_manifest_records_relative_paths_sizes_and_hashes(self):
        target = generate_manifest(self.bundle)
        manifest = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(manifest["fileCount"], 2)
        self.assertEqual(
            {entry["path"] for entry in manifest["files"]},
            {"app.exe", "pets/pet.json"},
        )
        self.assertTrue(all(len(entry["sha256"]) == 64 for entry in manifest["files"]))

    def test_archive_verification_checks_crc_inventory_and_hashes(self):
        generate_manifest(self.bundle)
        self.assertEqual(verify_archive(self.archive()), 2)

    def test_archive_verification_rejects_unlisted_file(self):
        generate_manifest(self.bundle)
        (self.bundle / "unexpected.txt").write_text("extra", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "differ"):
            verify_archive(self.archive())


class BundleStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bundle = self.root / "WatchedKettle"
        self.home = self.root / "Users" / "builder"
        (self.bundle / "_internal" / "pets" / "mori-bot").mkdir(parents=True)
        (self.bundle / "_internal" / "pets" / "mori-bot" / "pet.json").write_text(
            "{}", encoding="utf-8"
        )
        (self.bundle / "_internal" / "VCRUNTIME140.dll").write_bytes(b"dll")
        (self.bundle / "settings-ui" / "resources" / "app" / "dist").mkdir(parents=True)
        (
            self.bundle / "settings-ui" / "resources" / "app" / "dist" / "index.html"
        ).write_text("<html></html>", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def check(self):
        return check_bundle_state(self.bundle, forbidden_roots=[self.home])

    def write(self, relative, text="x"):
        path = self.bundle / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_clean_bundle_passes(self):
        self.assertEqual(self.check(), [])

    def test_user_state_files_and_folders_are_reported(self):
        self.write("settings.ini")
        self.write("assistant-v1.sqlite3-wal")
        self.write("logs/app.log")
        self.write("_internal/.watched-kettle-runtime/events/x.json")

        self.assertCountEqual(
            self.check(),
            [
                "user state directory: _internal/.watched-kettle-runtime/",
                "user state file: assistant-v1.sqlite3-wal",
                "user state directory: logs/",
                "user state file: settings.ini",
            ],
        )

    def test_build_machine_path_in_text_is_reported_in_any_spelling(self):
        escaped = str(self.home).replace("\\", "\\\\")
        self.write("licenses/DEPENDENCIES.json", f'{{"path": "{escaped}\\pkg"}}')
        self.write("README.txt", self.home.as_posix().upper() + "/notes")

        self.assertCountEqual(
            self.check(),
            [
                "build machine path in: README.txt",
                "build machine path in: licenses/DEPENDENCIES.json",
            ],
        )


if __name__ == "__main__":
    unittest.main()
