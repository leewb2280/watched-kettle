import unittest

from PIL import Image

from watched_kettle.branding import APP_ICON_PATH, APPLICATION_VERSION


class BrandingTests(unittest.TestCase):
    def test_application_icon_is_transparent_and_large_enough(self):
        self.assertTrue(APP_ICON_PATH.is_file())
        with Image.open(APP_ICON_PATH) as icon:
            self.assertEqual(icon.mode, "RGBA")
            self.assertGreaterEqual(icon.width, 256)
            self.assertGreaterEqual(icon.height, 256)
            self.assertEqual(icon.getpixel((0, 0))[3], 0)

    def test_application_version_is_release_ready(self):
        self.assertRegex(APPLICATION_VERSION, r"^\d+\.\d+\.\d+$")

    def test_installer_app_guid_matches_the_installer_script(self):
        # The app updates the installer's uninstall entry after a partial update.
        from watched_kettle.branding import INSTALLER_APP_GUID, PROJECT_ROOT

        script = (PROJECT_ROOT / "packaging" / "windows-installer.iss").read_text(
            encoding="utf-8"
        )
        self.assertIn(f"AppId={{{{{INSTALLER_APP_GUID}}}", script)


if __name__ == "__main__":
    unittest.main()
