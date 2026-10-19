"""About page data: links, bundled notices and the licenses folder."""

import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from watched_kettle.application import about
from watched_kettle.branding import APPLICATION_VERSION, RELEASE_REPOSITORY

ROOT = Path(__file__).resolve().parents[1]


class AboutTests(unittest.TestCase):
    def test_links_stay_under_the_repository_the_browser_handler_allows(self):
        external = (ROOT / "settings-ui/electron/external.cjs").read_text("utf-8")
        allowed = re.search(r'REPOSITORY_PATH = "([^"]+)"', external).group(1)
        self.assertEqual(allowed, "/" + RELEASE_REPOSITORY)
        links = about.links()
        self.assertEqual(links["repository"], "https://github.com" + allowed)
        self.assertTrue(
            links["releaseNotes"].endswith(f"/releases/tag/v{APPLICATION_VERSION}")
        )
        for url in links.values():
            self.assertTrue(
                url.startswith(links["repository"] + "/") or url == links["repository"]
            )

    def test_file_links_point_at_files_the_public_repository_has(self):
        allowlist = ROOT / "packaging/public-source-files.json"
        if allowlist.exists():
            manifest = json.loads(allowlist.read_text("utf-8"))
            published = {
                entry.get("destination", entry["source"]) for entry in manifest["files"]
            }
        blob = about.REPOSITORY_URL + "/blob/main/"
        for url in about.links().values():
            if not url.startswith(blob):
                continue
            path = url.removeprefix(blob)
            if allowlist.exists():
                self.assertIn(path, published, url)
            else:
                # The public repository has no allowlist; its files are the set.
                self.assertTrue((ROOT / path).is_file(), url)
        self.assertEqual(about.links()["changelog"], about.REPOSITORY_URL + "/releases")

    def test_notices_name_components_the_notice_file_covers(self):
        notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text("utf-8")
        for name, license_name in about.THIRD_PARTY:
            self.assertTrue(license_name, name)
            for part in name.split(" · "):
                self.assertIn(part, notices, name)

    def test_whats_new_has_text_for_this_version(self):
        self.assertEqual(about.WHATS_NEW_VERSION, APPLICATION_VERSION)
        items = about.whats_new()
        self.assertTrue(items)
        for item in items:
            self.assertFalse(item.startswith("whats_new."), item)

    def test_licenses_folder_is_only_a_bundled_one(self):
        self.assertIsNone(about.licenses_folder())
        with TemporaryDirectory() as temp:
            executable = Path(temp) / "WatchedKettle.exe"
            self.assertIsNone(about.licenses_folder(executable))
            (Path(temp) / "licenses").mkdir()
            self.assertEqual(
                about.licenses_folder(executable), (Path(temp) / "licenses").resolve()
            )
            with (
                patch.object(about.sys, "frozen", True, create=True),
                patch.object(about.sys, "executable", str(executable)),
            ):
                self.assertIsNotNone(about.licenses_folder())
                self.assertTrue(about.about_info("pet-only")["licensesAvailable"])


if __name__ == "__main__":
    unittest.main()
