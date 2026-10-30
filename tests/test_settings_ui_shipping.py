"""What the packaged settings window ships with: Electron fuses and the CSP."""

from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest

from scripts.set_electron_fuses import SENTINEL, FuseError, disable_fuses

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ElectronFuseTests(unittest.TestCase):
    def write(self, wire, *, sentinels=1, version=1):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "WatchedKettleSettings.exe"
        block = SENTINEL + bytes([version, len(wire)]) + wire
        path.write_bytes(b"MZ-before" + block * sentinels + b"after")
        return path

    def test_run_as_node_node_options_and_inspect_are_turned_off(self):
        # Electron 44's defaults; cookie encryption and later fuses stay as built.
        path = self.write(b"101100011")

        self.assertEqual(disable_fuses(path), "000000011")
        data = path.read_bytes()
        self.assertTrue(data.startswith(b"MZ-before"))
        self.assertTrue(data.endswith(b"after"))

    def test_unknown_layouts_fail_the_build(self):
        for wire, options in (
            (b"101100011", {"sentinels": 2}),
            (b"101100011", {"version": 2}),
            (b"10", {}),
            (b"10r100011", {}),
        ):
            with self.subTest(wire=wire, options=options):
                with self.assertRaises(FuseError):
                    disable_fuses(self.write(wire, **options))

    def test_installed_electron_still_has_the_expected_wire(self):
        electron = (
            PROJECT_ROOT / "settings-ui" / "node_modules" / "electron" / "dist"
        ) / "electron.exe"
        if not electron.is_file():
            self.skipTest("Electron runtime not installed")
        data = electron.read_bytes()
        index = data.find(SENTINEL)
        self.assertGreaterEqual(index, 0)
        start = index + len(SENTINEL)
        self.assertEqual(data[start], 1)
        wire = data[start + 2 : start + 2 + data[start + 1]]
        self.assertEqual(wire[:4], b"1011")


class ShippedPolicyTests(unittest.TestCase):
    def test_built_page_has_no_dev_server_socket(self):
        page = PROJECT_ROOT / "settings-ui" / "dist" / "index.html"
        if not page.is_file():
            self.skipTest("settings UI not built")
        policy = re.search(
            r'http-equiv="Content-Security-Policy"\s+content="([^"]*)"',
            page.read_text(encoding="utf-8"),
        )
        self.assertIsNotNone(policy)
        self.assertNotIn("ws:", policy.group(1))
        self.assertIn("connect-src 'self'", policy.group(1))
        self.assertIn("script-src 'self';", policy.group(1))


if __name__ == "__main__":
    unittest.main()
