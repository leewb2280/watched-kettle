"""Pet frames kept compressed and decoded only while they are drawn.

A decoded 192x208 frame is about 156 KiB, and a pet keeps 73 of them plus
those of every look variant. Each frame is kept here as zlib-compressed RGBA
(level 1: fast to pack at load, about 0.25 ms to unpack), and a small LRU
shared by one pet holds the frames drawn recently, so the frames of the
playing animation are unpacked once.
"""

from __future__ import annotations

from collections import OrderedDict
from itertools import count
import zlib

from PySide6.QtGui import QImage, QPixmap

# Enough for the longest animation (8 frames) plus the look pose in use.
DECODED_FRAME_LIMIT = 12
_sequence_ids = count(1)


class FrameDecodeCache:
    """Recently drawn frames of one pet, least recently used dropped first."""

    def __init__(self, limit=DECODED_FRAME_LIMIT):
        self.limit = max(1, int(limit))
        self._frames: OrderedDict[tuple[int, int], QPixmap] = OrderedDict()

    def __len__(self):
        return len(self._frames)

    def get(self, key, decode):
        pixmap = self._frames.get(key)
        if pixmap is not None:
            self._frames.move_to_end(key)
            return pixmap
        pixmap = decode()
        self._frames[key] = pixmap
        while len(self._frames) > self.limit:
            self._frames.popitem(last=False)
        return pixmap

    def clear(self):
        self._frames.clear()


def pack_image(image):
    """Compressed RGBA bytes and size of a Pillow image."""
    image = image if image.mode == "RGBA" else image.convert("RGBA")
    return zlib.compress(image.tobytes(), 1), image.width, image.height


class PackedFrames:
    """A read-only sequence of frames; indexing returns a QPixmap.

    Slicing returns another PackedFrames over the same compressed data, so
    reversing a transition strip copies nothing. ``frame_key`` names a frame
    for caches that must survive the frame being unpacked again.
    """

    def __init__(self, blobs, cache=None, *, _keys=None):
        self._blobs = tuple(blobs)
        self._cache = cache if cache is not None else FrameDecodeCache()
        if _keys is None:
            sequence = next(_sequence_ids)
            _keys = tuple((sequence, index) for index in range(len(self._blobs)))
        self._keys = tuple(_keys)

    @classmethod
    def from_images(cls, images, cache=None):
        return cls((pack_image(image) for image in images), cache)

    @property
    def cache(self):
        return self._cache

    @property
    def packed_bytes(self):
        return sum(len(blob[0]) for blob in self._blobs)

    def __len__(self):
        return len(self._blobs)

    def __bool__(self):
        return bool(self._blobs)

    def __iter__(self):
        for index in range(len(self._blobs)):
            yield self[index]

    def __getitem__(self, index):
        if isinstance(index, slice):
            positions = range(len(self._blobs))[index]
            return PackedFrames(
                (self._blobs[i] for i in positions),
                self._cache,
                _keys=(self._keys[i] for i in positions),
            )
        if index < 0:
            index += len(self._blobs)
        if not 0 <= index < len(self._blobs):
            raise IndexError(index)
        data, width, height = self._blobs[index]
        return self._cache.get(self._keys[index], lambda: _decode(data, width, height))

    def frame_key(self, index):
        if index < 0:
            index += len(self._blobs)
        return self._keys[index]


def _decode(data, width, height):
    image = QImage(
        zlib.decompress(data), width, height, width * 4, QImage.Format.Format_RGBA8888
    )
    # The QImage borrows the bytes; copy before they are released.
    return QPixmap.fromImage(image.copy())
