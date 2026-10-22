"""Safe user-owned image elements for speech-bubble decoration."""

from __future__ import annotations

from watched_kettle.localization import t

from watched_kettle.features.pet.contracts import BubbleElement as BubbleElement

import json
import re
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError
from PySide6.QtGui import QPixmap

from watched_kettle.application.paths import AppPaths


MAX_ELEMENT_FILE_BYTES = 4 * 1024 * 1024
MAX_ELEMENT_DIMENSION = 1024
# Photos straight from a phone or camera are larger; imports are shrunk.
MAX_SOURCE_FILE_BYTES = 20 * 1024 * 1024
ELEMENT_KINDS = frozenset({"ornament", "pattern", "photo", "frame", "sticker"})
ELEMENT_SUFFIXES = frozenset({".png", ".webp"})
ELEMENT_FORMATS = ("PNG", "WEBP")
SOURCE_SUFFIXES = frozenset({".png", ".webp", ".jpg", ".jpeg"})
SOURCE_FORMATS = frozenset({"PNG", "WEBP", "JPEG"})


def default_bubble_elements_root():
    return AppPaths.default().data_root / "bubble-elements"


class BubbleElementError(ValueError):
    """A user-facing import validation error."""


class BubbleElementRegistry:
    def __init__(self, root=None):
        self.root = Path(root or default_bubble_elements_root())
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

    def pixmap(self, reference):
        element = self.get(reference)
        if element is None:
            return QPixmap()
        cached = self._pixmaps.get(element.id)
        if cached is None:
            cached = QPixmap(str(element.image_path))
            self._pixmaps[element.id] = cached
        return QPixmap(cached)

    def refresh(self):
        self._elements = {}
        self._pixmaps = {}
        try:
            metadata_paths = tuple(self.root.glob("*.json"))
        except OSError:
            metadata_paths = ()
        for metadata_path in metadata_paths:
            element = self._load_metadata(metadata_path)
            if element is not None and element.id not in self._elements:
                self._elements[element.id] = element
        return self.elements

    def import_image(self, source_path, kind, name=None):
        """Store a re-encoded copy: upright, at most 1024px, without metadata.

        Re-encoding drops EXIF data such as where a photo was taken, so
        nothing besides the pixels is kept in the user data folder.
        """
        source_path = Path(source_path)
        kind = str(kind or "").strip().lower()
        if kind not in ELEMENT_KINDS:
            raise BubbleElementError(t("message.0239"))
        image = _open_source(source_path)
        display_name = _clean_name(name or source_path.stem)
        element_id = uuid4().hex
        # Opaque photos compress far better as WebP; anything with
        # transparency stays lossless PNG.
        alpha = image.mode in {"RGBA", "LA"}
        suffix = ".webp" if kind == "photo" and not alpha else ".png"
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            image_path = self.root / f"{element_id}{suffix}"
            metadata_path = self.root / f"{element_id}.json"
            if suffix == ".webp":
                image.save(image_path, "WEBP", quality=88, method=4)
            else:
                image.save(image_path, "PNG", optimize=True)
            self._validate_image(image_path)
            metadata_path.write_text(
                json.dumps(
                    {
                        "id": element_id,
                        "name": display_name,
                        "kind": kind,
                        "image": image_path.name,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError as error:
            raise BubbleElementError(t("message.0244")) from error
        self.refresh()
        return self._elements[element_id]

    def delete(self, reference):
        element = self.get(reference)
        if element is None:
            return False
        targets = (
            element.image_path,
            self.root / f"{element.id}.json",
        )
        for target in targets:
            try:
                if target.resolve().is_relative_to(self.root.resolve()):
                    target.unlink(missing_ok=True)
            except OSError:
                return False
        self.refresh()
        return True

    def _load_metadata(self, metadata_path):
        try:
            if metadata_path.stat().st_size > 256 * 1024:
                return None
            with metadata_path.open("rb") as stream:
                raw = stream.read(256 * 1024 + 1)
            if len(raw) > 256 * 1024:
                return None
            data = json.loads(raw)
            if not isinstance(data, dict) or any(
                not isinstance(data.get(key, ""), str)
                for key in ("id", "name", "kind", "image")
            ):
                return None
            element_id = str(data.get("id") or "")
            name = _clean_name(data.get("name") or element_id)
            kind = str(data.get("kind") or "")
            image_name = str(data.get("image") or "")
            if not re.fullmatch(r"[a-f0-9]{32}", element_id):
                return None
            if kind not in ELEMENT_KINDS:
                return None
            image_path = (self.root / image_name).resolve()
            if not image_path.is_relative_to(self.root.resolve()):
                return None
            if image_path.suffix.lower() not in ELEMENT_SUFFIXES:
                return None
            self._validate_image(image_path)
        except (
            BubbleElementError,
            OSError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ):
            return None
        return BubbleElement(element_id, name, kind, image_path)

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


def _clean_name(value):
    name = " ".join(str(value or "").split())[:60]
    return name or t("message.0238")
