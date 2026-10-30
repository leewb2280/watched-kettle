"""Safe user-owned image elements for speech-bubble decoration."""

from __future__ import annotations

from watched_kettle.localization import t

from watched_kettle.features.pet.contracts import BubbleElement as BubbleElement

import hashlib
import json
import re
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageDraw, ImageFilter, ImageOps, UnidentifiedImageError
from PySide6.QtGui import QImage, QPixmap

from watched_kettle.application.paths import AppPaths
from watched_kettle.branding import PROJECT_ROOT
from watched_kettle.pet.bubble_theme import (
    BACKGROUND_PATTERN_NAMES,
    BUILTIN_BACKGROUND_PREFIX,
)


MAX_ELEMENT_FILE_BYTES = 4 * 1024 * 1024
MAX_ELEMENT_DIMENSION = 1024
# Photos straight from a phone or camera are larger; imports are shrunk.
MAX_SOURCE_FILE_BYTES = 20 * 1024 * 1024
# A small compressed file can still decode to a huge canvas; Pillow's own
# limit (about 179 megapixels) would allow several gigabytes of memory.
MAX_SOURCE_PIXELS = 40_000_000
# Images this module stored itself, re-encoded on import.
STORED_FORMATS = ("PNG", "WEBP")
ELEMENT_KINDS = frozenset({"ornament", "pattern", "photo", "frame", "sticker"})
ELEMENT_SUFFIXES = frozenset({".png", ".webp"})
ELEMENT_FORMATS = ("PNG", "WEBP")
SOURCE_SUFFIXES = frozenset({".png", ".webp", ".jpg", ".jpeg"})
SOURCE_FORMATS = frozenset({"PNG", "WEBP", "JPEG"})
# The images sit alone in images/ so the folder the user opens holds nothing
# else; their names and kinds are in one library file beside it.
IMAGES_FOLDER = "images"
LIBRARY_NAME = "library.json"
LIBRARY_FORMAT = 1
MAX_LIBRARY_BYTES = 4 * 1024 * 1024
_ELEMENT_ID = re.compile(r"[a-f0-9]{32}")
_ENTRY_KEYS = ("id", "name", "kind", "image")
# Optional SHA-256 of the stored pixels; an import with the same pixels and
# kind reuses that element instead of adding a copy.
_PIXELS = re.compile(r"[a-f0-9]{64}")


BUILTIN_PATTERN_ROOT = PROJECT_ROOT / "assets" / "bubble-patterns"


def default_bubble_elements_root():
    return AppPaths.default().data_root / "bubble-elements"


def builtin_image_path(reference):
    """The bundled tile a "builtin:<name>" reference names, or None."""
    reference = str(reference or "")
    if not reference.startswith(BUILTIN_BACKGROUND_PREFIX):
        return None
    name = reference[len(BUILTIN_BACKGROUND_PREFIX) :]
    if name not in BACKGROUND_PATTERN_NAMES:
        return None
    return BUILTIN_PATTERN_ROOT / f"{name}.png"


class BubbleElementError(ValueError):
    """A user-facing import validation error."""


class BubbleElementRegistry:
    def __init__(self, root=None):
        self.root = Path(root or default_bubble_elements_root())
        self.images_root = self.root / IMAGES_FOLDER
        self._library_unreadable = False
        self._elements = {}
        self._pixmaps = {}
        self.refresh()

    @property
    def elements(self):
        return tuple(
            sorted(
                self._elements.values(),
                key=lambda item: (item.kind, item.name.casefold(), item.id),
            )
        )

    def elements_for(self, kind):
        return tuple(item for item in self.elements if item.kind == kind)

    def get(self, reference):
        element_id = str(reference or "")
        if element_id.startswith("user:"):
            element_id = element_id[5:]
        return self._elements.get(element_id)

    def _image_path(self, reference):
        """A user element's image or a built-in tile; never anything else."""
        element = self.get(reference)
        return element.image_path if element else builtin_image_path(reference)

    def pixmap(self, reference):
        path = self._image_path(reference)
        if path is None:
            return QPixmap()
        cached = self._pixmaps.get(path)
        if cached is None:
            cached = QPixmap(str(path))
            self._pixmaps[path] = cached
        return QPixmap(cached)

    def blurred_pixmap(self, reference, amount):
        """The image blurred by amount 1..20, relative to the image size."""
        path = self._image_path(reference)
        if path is None:
            return QPixmap()
        key = (path, int(amount))
        cached = self._blurred.get(key)
        if cached is None:
            cached = QPixmap()
            try:
                with Image.open(path, formats=STORED_FORMATS) as source:
                    image = source.convert("RGBA")
                radius = max(0.5, amount * max(image.size) / 256)
                image = image.filter(ImageFilter.GaussianBlur(radius))
                cached = QPixmap.fromImage(
                    QImage(
                        image.tobytes(),
                        image.width,
                        image.height,
                        image.width * 4,
                        QImage.Format.Format_RGBA8888,
                    ).copy()
                )
            except OSError, ValueError, Image.DecompressionBombError:
                pass
            self._blurred[key] = cached
        return QPixmap(cached)

    def refresh(self):
        self._elements = {}
        self._pixmaps = {}
        self._blurred = {}
        self._by_pixels: dict = {}
        entries = self._read_library()
        if entries is None:
            return self.elements
        entries = self._adopt_legacy(entries)
        kept = []
        backfilled = False
        for entry in entries:
            element = self._element(entry, self.images_root)
            if element is None:
                # An image deleted in Explorer leaves nothing to show; forget
                # it. A file that is there but unreadable keeps its entry.
                if (
                    _bare_name(entry["image"])
                    and not (self.images_root / entry["image"]).exists()
                ):
                    continue
            elif element.id in self._elements:
                continue
            else:
                self._elements[element.id] = element
                if not entry.get("pixels"):
                    # Images stored before pixel digests get one from the file.
                    pixels = _stored_digest(element.image_path)
                    if pixels:
                        entry = {**entry, "pixels": pixels}
                        backfilled = True
                if entry.get("pixels"):
                    # The oldest copy of a picture is the one imports reuse.
                    self._by_pixels.setdefault(
                        (element.kind, entry["pixels"]), element.id
                    )
            kept.append(entry)
        if backfilled or len(kept) != len(entries):
            try:
                self._write_library(kept)
            except OSError:
                pass
        return self.elements

    def import_image(self, source_path, kind, name=None, trim=False, clear_white=False):
        """Store a re-encoded copy: upright, at most 1024px, without metadata.

        Re-encoding drops EXIF data such as where a photo was taken, so
        nothing besides the pixels is kept in the user data folder. clear_white
        makes white touching the image edges transparent; trim then cuts
        transparent margins. An image whose pixels and kind match a library
        image returns that element, so saving or importing the same picture
        again adds no copy.
        """
        source_path = Path(source_path)
        kind = str(kind or "").strip().lower()
        if kind not in ELEMENT_KINDS:
            raise BubbleElementError(t("message.0239"))
        image = _open_source(source_path)
        if clear_white:
            image = _clear_edge_white(image)
        if trim:
            image = _trim(image)
        display_name = _clean_name(name or source_path.stem)
        pixels = _pixel_digest(image)
        existing = self._elements.get(self._by_pixels.get((kind, pixels), ""))
        if existing is not None:
            return existing
        element_id = uuid4().hex
        # Opaque photos compress far better as WebP; anything with
        # transparency stays lossless PNG.
        alpha = image.mode in {"RGBA", "LA"}
        suffix = ".webp" if kind == "photo" and not alpha else ".png"
        image_path = self.images_root / f"{element_id}{suffix}"
        try:
            self.images_root.mkdir(parents=True, exist_ok=True)
            if suffix == ".webp":
                image.save(image_path, "WEBP", quality=88, method=4)
            else:
                image.save(image_path, "PNG", optimize=True)
            self._validate_image(image_path)
            entry = dict(
                id=element_id,
                name=display_name,
                kind=kind,
                image=image_path.name,
                pixels=pixels,
            )
            self._write_library([*(self._read_library() or []), entry])
        except (BubbleElementError, OSError) as error:
            image_path.unlink(missing_ok=True)
            if isinstance(error, BubbleElementError):
                raise
            raise BubbleElementError(t("message.0244")) from error
        self.refresh()
        return self._elements[element_id]

    def duplicates(self):
        """[(kept id, [copy ids])] for pictures stored more than once.

        The kept one is the oldest copy, the one imports already reuse.
        """
        copies: dict = {}
        entries = self._read_library() or []
        for entry in entries:
            element = self._elements.get(entry["id"])
            if element is None or not entry.get("pixels"):
                continue
            kept = self._by_pixels.get((element.kind, entry["pixels"]))
            if kept and kept != element.id:
                copies.setdefault(kept, []).append(element.id)
        return list(copies.items())

    def delete(self, reference):
        element = self.get(reference)
        entries = self._read_library()
        if element is None or entries is None:
            return False
        try:
            self._write_library([item for item in entries if item["id"] != element.id])
        except OSError:
            return False
        try:
            if element.image_path.resolve().is_relative_to(self.images_root.resolve()):
                element.image_path.unlink(missing_ok=True)
        except OSError:
            pass  # Out of the library already; a leftover file shows nothing.
        self.refresh()
        return True

    def _read_library(self):
        """The library entries, [] when there is none, None when unreadable."""
        path = self.root / LIBRARY_NAME
        self._library_unreadable = False
        try:
            if path.stat().st_size > MAX_LIBRARY_BYTES:
                raise ValueError
            data = json.loads(path.read_bytes())
            items = data["elements"]
            if not isinstance(items, list):
                raise ValueError
        except FileNotFoundError:
            return []
        except OSError, KeyError, TypeError, ValueError:
            self._library_unreadable = True
            return None
        return [entry for entry in map(_entry, items) if entry is not None]

    def _write_library(self, entries):
        path = self.root / LIBRARY_NAME
        self.root.mkdir(parents=True, exist_ok=True)
        if self._library_unreadable and path.exists():
            # Keep what could not be read instead of writing over it.
            path.replace(path.with_name(f"{LIBRARY_NAME}.bak"))
        temporary = path.with_name(f"{LIBRARY_NAME}.tmp")
        temporary.write_text(
            json.dumps(
                dict(format=LIBRARY_FORMAT, elements=entries),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        temporary.replace(path)
        self._library_unreadable = False

    def _adopt_legacy(self, entries):
        """Move the old layout, a note beside each image, into images/ once."""
        try:
            notes = sorted(
                path
                for path in self.root.glob("*.json")
                if _ELEMENT_ID.fullmatch(path.stem)
            )
        except OSError:
            return entries
        moves, stale = [], []
        for note_path in notes:
            note = self._read_note(note_path)
            if note is None:
                continue
            element = self._element(note, self.root)
            if element is not None:
                moves.append((note_path, element))
            elif _bare_name(note["image"]) and not (self.root / note["image"]).exists():
                stale.append(note_path)
        if not moves and not stale:
            return entries
        known = {entry["id"] for entry in entries}
        adopted = list(entries)
        moved = []
        try:
            self.images_root.mkdir(parents=True, exist_ok=True)
            for _, element in moves:
                target = self.images_root / element.image_path.name
                element.image_path.replace(target)
                moved.append((element.image_path, target))
                if element.id not in known:
                    known.add(element.id)
                    adopted.append(
                        dict(
                            id=element.id,
                            name=element.name,
                            kind=element.kind,
                            image=target.name,
                        )
                    )
            self._write_library(adopted)
        except OSError:
            # Put the images back so the old notes still find them next time.
            for original, target in reversed(moved):
                try:
                    target.replace(original)
                except OSError:
                    pass
            return entries
        for note_path in [path for path, _ in moves] + stale:
            try:
                note_path.unlink(missing_ok=True)
            except OSError:
                pass
        return adopted

    def _read_note(self, metadata_path):
        """An old per-image note as an entry, or None. It is never changed."""
        try:
            if metadata_path.stat().st_size > 256 * 1024:
                return None
            with metadata_path.open("rb") as stream:
                raw = stream.read(256 * 1024 + 1)
            if len(raw) > 256 * 1024:
                return None
            return _entry(json.loads(raw))
        except OSError, ValueError:
            return None

    def _load_metadata(self, metadata_path):
        note = self._read_note(metadata_path)
        return None if note is None else self._element(note, self.root)

    def _element(self, entry, folder):
        element_id = entry["id"]
        if not _ELEMENT_ID.fullmatch(element_id):
            return None
        if entry["kind"] not in ELEMENT_KINDS:
            return None
        if not _bare_name(entry["image"]):
            return None
        image_path = folder / entry["image"]
        if image_path.suffix.lower() not in ELEMENT_SUFFIXES:
            return None
        try:
            self._validate_image(image_path)
        except BubbleElementError:
            return None
        name = _clean_name(entry["name"] or element_id)
        return BubbleElement(element_id, name, entry["kind"], image_path)

    @staticmethod
    def _validate_image(path):
        try:
            if not path.is_file():
                raise BubbleElementError(t("message.0240"))
            if path.suffix.lower() not in ELEMENT_SUFFIXES:
                raise BubbleElementError(t("message.0245"))
            if path.stat().st_size > MAX_ELEMENT_FILE_BYTES:
                raise BubbleElementError(t("message.0246"))
            with Image.open(path, formats=ELEMENT_FORMATS) as image:
                image_format = str(image.format or "").upper()
                width, height = image.size
                image.verify()
            if image_format not in {"PNG", "WEBP"}:
                raise BubbleElementError(t("message.0247"))
            if not (1 <= width <= MAX_ELEMENT_DIMENSION):
                raise BubbleElementError(t("message.0248"))
            if not (1 <= height <= MAX_ELEMENT_DIMENSION):
                raise BubbleElementError(t("message.0249"))
        except BubbleElementError:
            raise
        except (
            Image.DecompressionBombError,
            OSError,
            UnidentifiedImageError,
            ValueError,
        ) as error:
            raise BubbleElementError(t("message.0243")) from error


def _open_source(path):
    """Decode an import into a fresh, upright image with no metadata."""
    try:
        if not path.is_file():
            raise BubbleElementError(t("message.0240"))
        if path.suffix.lower() not in SOURCE_SUFFIXES:
            raise BubbleElementError(t("message.0241"))
        if path.stat().st_size > MAX_SOURCE_FILE_BYTES:
            raise BubbleElementError(t("message.0242"))
        with Image.open(path, formats=tuple(SOURCE_FORMATS)) as source:
            if str(source.format or "").upper() not in SOURCE_FORMATS:
                raise BubbleElementError(t("message.0250"))
            if source.width * source.height > MAX_SOURCE_PIXELS:
                raise BubbleElementError(t("message.0243"))
            image = ImageOps.exif_transpose(source)
            image.load()
        image.thumbnail((MAX_ELEMENT_DIMENSION, MAX_ELEMENT_DIMENSION))
        transparent = image.mode in {"RGBA", "LA", "PA"} or (
            "transparency" in image.info
        )
        clean = image.convert("RGBA" if transparent else "RGB")
        clean.info.clear()
        return clean
    except BubbleElementError:
        raise
    except (
        Image.DecompressionBombError,
        OSError,
        UnidentifiedImageError,
        ValueError,
    ) as error:
        raise BubbleElementError(t("message.0243")) from error


# Distance from white, summed over the colour channels, still counted as white.
EDGE_WHITE_TOLERANCE = 60


def _clear_edge_white(image):
    """Make near-white regions connected to the border transparent.

    Only regions reached from the corners and edge midpoints are cleared, so
    white inside a drawing (eyes, highlights) stays.
    """
    image = image.convert("RGBA")
    width, height = image.size
    seeds = {
        (x, y)
        for x in (0, width // 2, width - 1)
        for y in (0, height // 2, height - 1)
        if x in (0, width - 1) or y in (0, height - 1)
    }
    for seed in seeds:
        red, green, blue, alpha = image.getpixel(seed)
        if alpha and min(red, green, blue) >= 235:
            ImageDraw.floodfill(
                image, seed, (255, 255, 255, 0), thresh=EDGE_WHITE_TOLERANCE
            )
    return image


def _trim(image):
    """Cut fully transparent margins, keeping one pixel around the drawing."""
    if image.mode != "RGBA":
        return image
    box = image.getchannel("A").getbbox()
    if box is None:
        return image
    left, top, right, bottom = box
    return image.crop(
        (
            max(0, left - 1),
            max(0, top - 1),
            min(image.width, right + 1),
            min(image.height, bottom + 1),
        )
    )


def _entry(data):
    """A library entry with string fields, or None for anything else."""
    if not isinstance(data, dict) or any(
        not isinstance(data.get(key, ""), str) for key in _ENTRY_KEYS
    ):
        return None
    entry = {key: str(data.get(key) or "") for key in _ENTRY_KEYS}
    if _PIXELS.fullmatch(str(data.get("pixels") or "")):
        entry["pixels"] = data["pixels"]
    return entry


def _pixel_digest(image):
    """SHA-256 of an image's size, mode and pixels."""
    digest = hashlib.sha256(f"{image.mode} {image.width}x{image.height}".encode())
    digest.update(image.tobytes())
    return digest.hexdigest()


def _stored_digest(path):
    """The pixel digest of a stored image, as its import would have made it."""
    try:
        with Image.open(path, formats=ELEMENT_FORMATS) as image:
            image.load()
            transparent = image.mode in {"RGBA", "LA", "PA"} or (
                "transparency" in image.info
            )
            return _pixel_digest(image.convert("RGBA" if transparent else "RGB"))
    except Image.DecompressionBombError, OSError, UnidentifiedImageError, ValueError:
        return ""


def _bare_name(value):
    """A file name with no folder part, so it stays in its folder."""
    return bool(value) and value not in {".", ".."} and Path(value).name == value


def _clean_name(value):
    name = " ".join(str(value or "").split())[:60]
    return name or t("message.0238")
