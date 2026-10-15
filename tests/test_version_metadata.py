import unittest

from watched_kettle.branding import APPLICATION_VERSION
from scripts.generate_windows_version_info import render_version_info


class VersionMetadataTests(unittest.TestCase):
    def test_generated_metadata_uses_application_version(self):
        metadata = render_version_info()
        self.assertIn(f'ProductVersion", "{APPLICATION_VERSION}"', metadata)
        self.assertIn(f'FileVersion", "{APPLICATION_VERSION}.0"', metadata)

    def test_invalid_version_is_rejected(self):
        with self.assertRaises(ValueError):
            render_version_info("1.2")


if __name__ == "__main__":
    unittest.main()
