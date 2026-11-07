"""Pet frames kept compressed: same pixels, bounded decoding, stable keys."""

import unittest

from PIL import Image
from PySide6.QtCore import QSize
from PIL.ImageQt import ImageQt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from watched_kettle.pet.packed_frames import FrameDecodeCache, PackedFrames
from watched_kettle.pet.renderer import PetFrameRenderer


def image(index):
    picture = Image.new("RGBA", (6, 4), (0, 0, 0, 0))
    picture.putpixel((index % 6, 1), (10 * index, 200, 30, 128 + index))
    return picture


class PackedFramesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_unpacked_frames_keep_every_pixel_and_alpha(self):
        frames = PackedFrames.from_images(image(i) for i in range(3))
        self.assertEqual(len(frames), 3)
        self.assertTrue(frames)
        self.assertFalse(PackedFrames(()))
        pixmap = frames[2]
        self.assertEqual((pixmap.width(), pixmap.height()), (6, 4))
        # The same pixmap the earlier Pillow-to-QPixmap path drew, including
        # the rounding of premultiplied translucent pixels.
        expected = QPixmap.fromImage(ImageQt(image(2))).toImage()
        self.assertEqual(pixmap.toImage(), expected)
        self.assertEqual(pixmap.toImage().pixelColor(2, 1).alpha(), 130)
        self.assertEqual(pixmap.toImage().pixelColor(0, 0).alpha(), 0)
        self.assertFalse(frames[-1].isNull())
        self.assertEqual(len(list(frames)), 3)
        with self.assertRaises(IndexError):
            frames[3]

    def test_slices_share_data_keys_and_decoded_frames(self):
        frames = PackedFrames.from_images(image(i) for i in range(4))
        reverse = frames[::-1]
        self.assertIsInstance(reverse, PackedFrames)
        self.assertEqual(len(reverse), 4)
        self.assertEqual(reverse.frame_key(0), frames.frame_key(3))
        self.assertIs(reverse[0], frames[3])
        self.assertEqual(reverse.packed_bytes, frames.packed_bytes)

    def test_decoding_is_bounded_and_repeat_draws_reuse_the_pixmap(self):
        cache = FrameDecodeCache(limit=2)
        frames = PackedFrames.from_images((image(i) for i in range(4)), cache)
        first = frames[0]
        self.assertIs(frames[0], first)
        frames[1]
        frames[2]
        self.assertEqual(len(cache), 2)
        # Unpacked again once dropped: a new pixmap, the same key.
        self.assertIsNot(frames[0], first)
        self.assertEqual(frames.frame_key(0), frames.frame_key(-4))

    def test_sequences_of_one_pet_share_the_cache_with_distinct_keys(self):
        cache = FrameDecodeCache()
        idle = PackedFrames.from_images([image(0)], cache)
        wave = PackedFrames.from_images([image(0)], cache)
        self.assertIs(idle.cache, wave.cache)
        self.assertNotEqual(idle.frame_key(0), wave.frame_key(0))

    def test_renderer_finds_the_scaled_copy_of_a_frame_unpacked_again(self):
        cache = FrameDecodeCache(limit=1)
        frames = PackedFrames.from_images((image(i) for i in range(2)), cache)
        renderer = PetFrameRenderer()
        target = QSize(3, 2)
        scaled = renderer.scale(frames[0], target, frames.frame_key(0))
        frames[1]  # pushes frame 0 out of the decode cache
        again = renderer.scale(frames[0], target, frames.frame_key(0))
        self.assertIs(again, scaled)
        self.assertEqual(renderer.cache_size, 1)


if __name__ == "__main__":
    unittest.main()
