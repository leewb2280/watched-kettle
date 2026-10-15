import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from scripts.render_installer_images import (
    LARGE_SIZE,
    SCALES,
    SMALL_SIZE,
    render_installer_images,
)


class RenderInstallerImagesTests(unittest.TestCase):
    def test_every_scale_gets_transparent_wizard_images(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / "images"

            written = render_installer_images(target)

            self.assertEqual(len(written), 2 * len(SCALES))
            for scale in SCALES:
                for name, size in (("large", LARGE_SIZE), ("small", SMALL_SIZE)):
                    with Image.open(target / f"wizard-{name}-{scale}.png") as image:
                        expected = tuple(round(value * scale / 100) for value in size)
                        self.assertEqual(image.size, expected)
                        self.assertEqual(image.mode, "RGBA")
                        # Corners stay transparent so both wizard themes show through.
                        self.assertEqual(image.getpixel((0, 0))[3], 0)

    def test_existing_directory_is_never_overwritten(self):
        with TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                render_installer_images(Path(directory))


if __name__ == "__main__":
    unittest.main()
