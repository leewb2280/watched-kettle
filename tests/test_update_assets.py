"""Partial update assets: the builder's output and staging a runtime from it."""

import json
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest
import zipfile

from watched_kettle.application.update_assets import (
    MANIFEST_NAME,
    READY_MARKER,
    StagingError,
    UpdateIndexError,
    asset_name_allowed,
    changed_paths,
    delta_name,
    index_name,
    installer_name,
    manifest_entries,
    parse_index,
    read_result,
    safe_relative_path,
    stage_runtime,
)
from tests.update_bundle_support import CHANNEL, KIND, build_release, release_files


def tree(root):
    root = Path(root)
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class RuleTests(unittest.TestCase):
    def test_paths_stay_inside_the_bundle(self):
        for path in ("a.txt", "_internal/PySide6/Qt6Core.dll"):
            self.assertTrue(safe_relative_path(path), path)
        for path in ("", "/abs", "../up", "a/../b", "C:/x", "a\\b", "./a", "a//b"):
            self.assertFalse(safe_relative_path(path), path)

    def test_asset_names_follow_the_channel(self):
        name = delta_name("1.0.1", "public", "pet-only", "1.0.0")
        self.assertTrue(
            asset_name_allowed(name, "1.0.1", "official", "delta", "pet-only", "1.0.0")
        )
        # Another base, edition, version or a test asset is never accepted.
        for args in (
            (name, "1.0.1", "official", "delta", "pet-only", "0.9.0"),
            (name, "1.0.1", "official", "delta", "pet-assistant", "1.0.0"),
            (name, "1.0.2", "official", "delta", "pet-only", "1.0.0"),
            (
                delta_name("1.0.1", "public-update-test", "pet-only", "1.0.0"),
                "1.0.1",
                "official",
                "delta",
                "pet-only",
                "1.0.0",
            ),
            ("../" + name, "1.0.1", "official", "delta", "pet-only", "1.0.0"),
        ):
            self.assertFalse(asset_name_allowed(*args), args)

    def test_manifest_rejects_escaping_duplicate_or_miscounted_entries(self):
        def manifest(*files, count=None):
            rows = [{"path": p, "size": 1, "sha256": "0" * 64} for p in files]
            return json.dumps(
                {"schemaVersion": 1, "fileCount": count or len(rows), "files": rows}
            )

        self.assertEqual(set(manifest_entries(manifest("a", "b/c"))), {"a", "b/c"})
        for bad in (
            manifest("../a"),
            manifest("A.txt", "a.txt"),
            manifest(MANIFEST_NAME),
            manifest("a", count=2),
            "[]",
        ):
            with self.assertRaises(UpdateIndexError):
                manifest_entries(bad)

    def test_changed_paths_are_new_or_different(self):
        base = {"a": (1, "1" * 64), "b": (1, "2" * 64)}
        target = {"a": (1, "1" * 64), "b": (1, "3" * 64), "c": (1, "4" * 64)}
        self.assertEqual(changed_paths(base, target), ["b", "c"])

    def test_launcher_result_is_read_without_trusting_other_lines(self):
        with TemporaryDirectory() as directory:
            self.assertIsNone(read_result(directory))
            (Path(directory) / "update-result.txt").write_text(
                "state=failed\nversion=9.9.9\nreason=in_use\npath=C:/x\n"
            )
            self.assertEqual(
                read_result(directory),
                {"state": "failed", "version": "9.9.9", "reason": "in_use"},
            )


class BuildAndStageTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.old = build_release(self.root, "1.0.0")
        self.new = build_release(self.root, "1.0.1", bases=self.old)

    def index(self, version="1.0.1", folder=None):
        folder = folder or self.new
        return parse_index(
            (folder / index_name(version)).read_bytes(), version, CHANNEL
        )

    def test_first_release_has_no_delta_and_later_ones_only_changed_files(self):
        self.assertEqual(self.index("1.0.0", self.old).editions["pet-only"].deltas, {})
        index = self.index()
        self.assertEqual(index.installer_revision, 1)
        delta = index.editions["pet-assistant"].deltas["1.0.0"]
        self.assertEqual(
            delta.name, delta_name("1.0.1", KIND, "pet-assistant", "1.0.0")
        )
        with zipfile.ZipFile(self.new / delta.name) as archive:
            names = set(archive.namelist())
        # The shared library did not change, so it is not in the zip.
        self.assertEqual(
            names,
            {
                "WatchedKettle.exe",
                "settings-ui/resources/app/index.js",
                "BUILD_PROFILE.txt",
                MANIFEST_NAME,
            },
        )
        checksum = (self.new / (index_name("1.0.1") + ".sha256")).read_text()
        self.assertTrue(checksum.strip().endswith(index_name("1.0.1")))

    def test_a_moved_update_address_travels_in_the_delta(self):
        # 0.15.4 installs reach the update repository of ADR 0008 this way.
        def files(version, repository):
            content = release_files(version)
            content["UPDATE_SOURCE.json"] = json.dumps(
                {
                    "api_url": f"https://api.github.com/repos/{repository}/releases/latest",
                    "release_url": f"https://github.com/{repository}/releases",
                }
            ).encode()
            return content

        root = self.root / "moved"
        old = build_release(root, "1.0.0", files=files("1.0.0", "o/app"))
        new = build_release(
            root, "1.0.1", bases=old, files=files("1.0.1", "o/app-updates")
        )
        delta = self.index("1.0.1", new).editions["pet-only"].deltas["1.0.0"]
        with zipfile.ZipFile(new / delta.name) as archive:
            self.assertIn("app-updates", archive.read("UPDATE_SOURCE.json").decode())

    def test_a_different_installer_revision_gets_no_delta(self):
        newer = build_release(self.root / "r2", "1.0.2", bases=self.new, revision=2)
        self.assertEqual(self.index("1.0.2", newer).editions["pet-only"].deltas, {})

    def test_a_signed_release_names_its_signed_update_installer(self):
        signed = build_release(self.root / "s", "1.0.2", bases=self.new, signed=True)
        installer = self.index("1.0.2", signed).editions["pet-only"].installer
        self.assertEqual(
            installer.name, installer_name("1.0.2", KIND, "pet-only", True)
        )
        # A folder with both names is ambiguous, so the builder stops.
        (signed / installer_name("1.0.2", KIND, "pet-only")).write_bytes(b"setup")
        with self.assertRaises(SystemExit):
            build_release(self.root / "s", "1.0.2", bases=self.new, signed=True)

    def test_only_the_three_newest_earlier_releases_get_a_delta(self):
        bases = self.root / "bases"
        bases.mkdir()
        for version in ("1.0.0", "1.0.1", "1.0.2", "1.0.3"):
            folder = self.root / f"release-{version}"
            if not folder.exists():
                build_release(self.root, version)
            for path in folder.glob("*.json"):
                shutil.copy2(path, bases)
        newest = build_release(self.root / "new", "1.0.4", bases=bases)
        for edition in ("pet-only", "pet-assistant"):
            self.assertEqual(
                set(self.index("1.0.4", newest).editions[edition].deltas),
                {"1.0.1", "1.0.2", "1.0.3"},
            )

    def stage(self, current, delta=None, staged=None):
        delta = (
            delta or self.new / self.index().editions["pet-only"].deltas["1.0.0"].name
        )
        staged = staged or self.root / "runtime" / "pet-only.next"
        return stage_runtime(current, staged, delta, "1.0.1"), staged

    def current(self):
        current = self.root / "runtime" / "pet-only"
        shutil.copytree(self.root / "bundle-1.0.0-pet-only", current)
        return current

    def test_staging_rebuilds_the_new_bundle_from_links_and_the_zip(self):
        current = self.current()
        counts, staged = self.stage(current)
        expected = tree(self.root / "bundle-1.0.1-pet-only")
        self.assertEqual((staged / READY_MARKER).read_text().strip(), "1.0.1")
        (staged / READY_MARKER).unlink()
        self.assertEqual(tree(staged), expected)
        self.assertEqual(counts["extracted"], 3)
        self.assertEqual(counts["linked"] + counts["copied"], 2)
        # Unchanged files are hard links where the file system allows it.
        if counts["linked"]:
            self.assertGreater(os.stat(staged / "_internal" / "shared.dll").st_nlink, 1)

    def test_a_changed_base_file_or_a_foreign_zip_entry_stops_staging(self):
        current = self.current()
        (current / "_internal" / "shared.dll").write_bytes(
            b"x" * len(release_files("x")["_internal/shared.dll"])
        )
        with self.assertRaises(StagingError) as raised:
            self.stage(current)
        self.assertEqual(raised.exception.reason, "base_mismatch")

        current = self.root / "other" / "pet-only"
        shutil.copytree(self.root / "bundle-1.0.0-pet-only", current)
        foreign = self.root / "foreign.zip"
        source = self.new / self.index().editions["pet-only"].deltas["1.0.0"].name
        with zipfile.ZipFile(source) as archive, zipfile.ZipFile(foreign, "w") as out:
            for name in archive.namelist():
                out.writestr(name, archive.read(name))
            out.writestr("../evil.dll", b"x")
        with self.assertRaises(StagingError) as raised:
            self.stage(current, foreign, self.root / "other" / "pet-only.next")
        self.assertEqual(raised.exception.reason, "unexpected_file")
        self.assertFalse((self.root / "other" / "evil.dll").exists())

    def test_index_rejects_names_and_versions_it_was_not_asked_for(self):
        payload = (self.new / index_name("1.0.1")).read_bytes()
        with self.assertRaises(UpdateIndexError):
            parse_index(payload, "1.0.2", CHANNEL)
        with self.assertRaises(UpdateIndexError):
            # Test assets are never accepted from the official channel.
            parse_index(payload, "1.0.1", "official")
        row = json.loads(payload)
        row["editions"]["pet-only"]["installer"]["name"] = "evil.exe"
        with self.assertRaises(UpdateIndexError):
            parse_index(json.dumps(row), "1.0.1", CHANNEL)


if __name__ == "__main__":
    unittest.main()
