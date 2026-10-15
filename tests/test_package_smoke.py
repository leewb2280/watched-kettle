import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from watched_kettle import entrypoint, hook_bridge_entrypoint
from watched_kettle.package_smoke import run_package_smoke


class PackageSmokeTests(unittest.TestCase):
    def test_license_documents_exist(self):
        third_party = Path("THIRD_PARTY_NOTICES.md")
        font_license = Path("assets/fonts/Pretendard/OFL.txt")

        self.assertTrue(third_party.is_file())
        self.assertTrue(font_license.is_file())
        self.assertIn("Pretendard 1.3.9", third_party.read_text(encoding="utf-8"))
        self.assertIn("SIL OPEN FONT LICENSE", font_license.read_text(encoding="utf-8"))

    @unittest.skipUnless(
        Path("packaging/private-beta").is_dir(), "public snapshot has no handoff"
    )
    def test_private_beta_handoff_documents_exist(self):
        quickstart = Path("packaging/private-beta/QUICKSTART.txt")
        notice = Path("packaging/private-beta/NOTICE.txt")

        self.assertTrue(quickstart.is_file())
        self.assertTrue(notice.is_file())
        self.assertIn("EXE만 따로", quickstart.read_text(encoding="utf-8"))
        self.assertIn("재배포", quickstart.read_text(encoding="utf-8"))

    def test_bundled_pets_and_render_dependencies_pass(self):
        self.assertEqual(run_package_smoke(Path("pets")), 0)

    def test_missing_pets_fail_with_distinct_exit_code(self):
        with TemporaryDirectory() as temporary_directory:
            self.assertEqual(
                run_package_smoke(Path(temporary_directory)),
                2,
            )

    def test_missing_bundled_font_fails_with_distinct_exit_code(self):
        with TemporaryDirectory() as temporary_directory:
            self.assertEqual(
                run_package_smoke(
                    Path("pets"),
                    font_root=Path(temporary_directory),
                ),
                4,
            )

    def test_invalid_spritesheet_fails_with_distinct_exit_code(self):
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            pet = root / "broken"
            pet.mkdir()
            (pet / "pet.json").write_text(
                json.dumps({"id": "broken"}),
                encoding="utf-8",
            )
            (pet / "spritesheet.webp").write_bytes(b"not-an-image")

            self.assertEqual(run_package_smoke(root), 3)

    def test_entrypoint_dispatches_package_smoke_without_starting_pet(self):
        with (
            patch.object(
                entrypoint.sys,
                "argv",
                ["WatchedKettle.exe", "--package-smoke-test"],
            ),
            patch(
                "watched_kettle.package_smoke.run_package_smoke",
                return_value=7,
            ) as smoke,
        ):
            with self.assertRaises(SystemExit) as context:
                entrypoint.main()

        self.assertEqual(context.exception.code, 7)
        smoke.assert_called_once()

    def test_windowed_packaged_bridge_does_not_require_stdout(self):
        with (
            patch.object(
                entrypoint.sys,
                "argv",
                ["WatchedKettle.exe", "--codex-hook-bridge"],
            ),
            patch.object(
                entrypoint.sys,
                "stdout",
                None,
            ),
            patch.object(
                hook_bridge_entrypoint,
                "run_hook_bridge",
                return_value=0,
            ),
        ):
            with self.assertRaises(SystemExit) as context:
                entrypoint.main()

        self.assertEqual(context.exception.code, 0)

    def test_qt_free_bridge_executable_does_not_require_stdout(self):
        with (
            patch.object(hook_bridge_entrypoint.sys, "stdout", None),
            patch.object(hook_bridge_entrypoint, "run_hook_bridge", return_value=0),
        ):
            self.assertEqual(hook_bridge_entrypoint.main(), 0)


if __name__ == "__main__":
    unittest.main()
