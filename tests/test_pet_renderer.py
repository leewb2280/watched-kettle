import unittest

from PySide6.QtCore import QSize, Qt

from watched_kettle.pet.renderer import PetFrameRenderer


class FakePixmap:
    def __init__(self, size, cache_key=1):
        self._size = QSize(size)
        self._cache_key = cache_key
        self.scaled_calls = []

    def size(self):
        return self._size

    def cacheKey(self):
        return self._cache_key

    def scaled(self, target_size, aspect_mode, transformation_mode):
        self.scaled_calls.append((QSize(target_size), aspect_mode, transformation_mode))
        return FakePixmap(target_size, self._cache_key + 1)


class PetFrameRendererTests(unittest.TestCase):
    def test_scaled_frames_use_smooth_transformation_and_cache(self):
        renderer = PetFrameRenderer()
        source = FakePixmap(QSize(192, 208))
        target_size = QSize(224, 243)

        rendered = renderer.scale(source, target_size)
        cached = renderer.scale(source, target_size)

        self.assertEqual(len(source.scaled_calls), 1)
        self.assertEqual(
            source.scaled_calls[0],
            (
                target_size,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ),
        )
        self.assertIs(cached, rendered)
        self.assertEqual(renderer.cache_size, 1)

    def test_original_size_returns_source_without_caching(self):
        renderer = PetFrameRenderer()
        source = FakePixmap(QSize(192, 208))

        rendered = renderer.scale(source, source.size())

        self.assertIs(rendered, source)
        self.assertEqual(source.scaled_calls, [])
        self.assertEqual(renderer.cache_size, 0)


if __name__ == "__main__":
    unittest.main()
