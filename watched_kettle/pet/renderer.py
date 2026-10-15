from PySide6.QtCore import Qt


class PetFrameRenderer:
    """Smoothly scale pet frames and cache the rendered result."""

    def __init__(self, cache_limit=32):
        if cache_limit < 1:
            raise ValueError("렌더링 캐시 크기는 1 이상이어야 합니다.")

        self.cache_limit = cache_limit
        self._cache = {}

    @property
    def cache_size(self):
        return len(self._cache)

    def clear(self):
        self._cache.clear()

    def scale(self, pixmap, target_size):
        if pixmap.size() == target_size:
            return pixmap

        cache_key = (
            pixmap.cacheKey(),
            target_size.width(),
            target_size.height(),
        )
        cached_pixmap = self._cache.get(cache_key)

        if cached_pixmap is not None:
            return cached_pixmap

        scaled_pixmap = pixmap.scaled(
            target_size,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        if len(self._cache) >= self.cache_limit:
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]

        self._cache[cache_key] = scaled_pixmap
        return scaled_pixmap
