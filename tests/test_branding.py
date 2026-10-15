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


if __name__ == "__main__":
    unittest.main()
