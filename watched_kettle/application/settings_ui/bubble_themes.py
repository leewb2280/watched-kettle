"""Saved bubble designs, shareable theme files and pet package export.

Library themes and theme files only name images by reference: saving turns
package images into library images, and files carry their images inside, so
no local path ever leaves the user's data folder.
"""

from __future__ import annotations

import base64
from dataclasses import replace
from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path, PurePosixPath
import re
from tempfile import TemporaryDirectory
from uuid import uuid4
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from PIL import Image, UnidentifiedImageError

from watched_kettle.localization import t
from watched_kettle.pet.bubble_decor import (
    decor_overflow,
    image_path,
    ornament_kind,
)
from watched_kettle.pet.bubble_frame import (
    FRAME_STYLE_PREFIX,
    package_directory,
    registered_frame,
)
from watched_kettle.pet.bubble_theme import (
    FRAME_THEME_KEYS,
    bubble_theme_from_dict,
    bubble_theme_to_dict,
)
from watched_kettle.ui.speech_bubble_frame import halo_reach, theme_halo


# Element and package images are stored as PNG or WebP only.
STORED_FORMATS = ("PNG", "WEBP")

THEME_FORMAT = "watched-kettle-bubble-theme"
MAX_LIBRARY_THEMES = 64
MAX_FILE_IMAGES = 40
MAX_FILE_IMAGE_BYTES = 4 * 1024 * 1024
MAX_FILE_BYTES = 48 * 1024 * 1024
# Theme fields that name one library image each.
IMAGE_FIELDS = (
    "background_image",
    "frame_image",
    "pattern",
    "ornament_left",
    "ornament_right",
)
_ID = re.compile(r"[a-f0-9]{32}")


class ThemeFileError(ValueError):
    """A user-facing problem with a theme file or export."""


def default_themes_root(data_root):
    return Path(data_root) / "bubble-themes"


class BubbleThemeLibrary:
    """Named designs kept in the user data folder, one JSON file each."""

    def __init__(self, root, registry):
        self.root = Path(root)
        self.registry = registry

    def entries(self):
        rows = []
        try:
            paths = sorted(self.root.glob("*.json"))
        except OSError:
            paths = []
        for path in paths[:MAX_LIBRARY_THEMES]:
            record = self._read(path)
            if record is None:
                continue
            thumbnail = path.with_suffix(".png")
            rows.append(
                dict(
                    id=record["id"],
                    name=record["name"],
                    savedAt=record["savedAt"],
                    thumbnail=_png_data(thumbnail) if thumbnail.is_file() else "",
                )
            )
        return sorted(rows, key=lambda row: row["savedAt"], reverse=True)

    def save(self, name, theme, thumbnail=None):
        name = " ".join(str(name or "").split())[:60]
        if not name:
            raise ThemeFileError(t("bubble.theme.name_required"))
        if len(self.entries()) >= MAX_LIBRARY_THEMES:
            raise ThemeFileError(t("bubble.theme.library_full", max=MAX_LIBRARY_THEMES))
        theme = portable(theme, self.registry)
        theme_id = uuid4().hex
        self.root.mkdir(parents=True, exist_ok=True)
        record = dict(
            id=theme_id,
            name=name,
            savedAt=datetime.now(timezone.utc).isoformat(),
            theme=bubble_theme_to_dict(theme),
        )
        (self.root / f"{theme_id}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if thumbnail is not None:
            thumbnail.save(str(self.root / f"{theme_id}.png"), "PNG")
        return theme_id

    def load(self, theme_id):
        record = self._read(self.root / f"{_checked_id(theme_id)}.json")
        if record is None:
            raise ThemeFileError(t("bubble.theme.missing"))
        return bubble_theme_from_dict(record["theme"])

    def delete(self, theme_id):
        theme_id = _checked_id(theme_id)
        for suffix in (".json", ".png"):
            (self.root / f"{theme_id}{suffix}").unlink(missing_ok=True)

    def names_using(self, reference):
        """Names of saved designs that draw a library image."""
        names = []
        try:
            paths = sorted(self.root.glob("*.json"))
        except OSError:
            paths = []
        for path in paths[:MAX_LIBRARY_THEMES]:
            record = self._read(path)
            if record is not None and reference in _theme_images(record["theme"]):
                names.append(record["name"])
        return names

    def replace_images(self, replacements):
        """Point saved designs at other library images; raises OSError.

        replacements maps an old image reference to the new one.
        """
        try:
            paths = sorted(self.root.glob("*.json"))
        except OSError:
            paths = []
        for path in paths[:MAX_LIBRARY_THEMES]:
            record = self._read(path)
            if record is None or not (
                _theme_images(record["theme"]) & set(replacements)
            ):
                continue
            theme = dict(record["theme"])
            for key in IMAGE_FIELDS:
                value = str(theme.get(key) or "")
                if value in replacements:
                    theme[key] = replacements[value]
            layers = theme.get("decor")
            if isinstance(layers, list):
                theme["decor"] = [
                    {
                        **layer,
                        "image": replacements.get(
                            layer.get("image"), layer.get("image")
                        ),
                    }
                    if isinstance(layer, dict)
                    else layer
                    for layer in layers
                ]
            temporary = path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps({**record, "theme": theme}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(path)

    @staticmethod
    def _read(path):
        try:
            if path.stat().st_size > 1024 * 1024:
                return None
            record = json.loads(path.read_text(encoding="utf-8"))
        except OSError, ValueError:
            return None
        if (
            not isinstance(record, dict)
            or not _ID.fullmatch(str(record.get("id", "")))
            or not isinstance(record.get("name"), str)
            or not isinstance(record.get("savedAt"), str)
            or not isinstance(record.get("theme"), dict)
        ):
            return None
        return record


def portable(theme, registry):
    """The theme with package images copied into the library.

    A package image only draws while that pet's package is registered; a
    library copy works with any pet.
    """
    layers = []
    for layer in theme.decor:
        if layer.image.startswith("pkg:"):
            path = image_path(layer.image)
            if path is None:
                continue
            name = layer.name or PurePosixPath(layer.image).stem
            element = registry.import_image(Path(path), "sticker", name)
            layer = replace(layer, image=element.reference)
        layers.append(layer)
    return replace(theme, decor=tuple(layers))


def export_theme_file(path, name, theme, registry):
    """Write a shareable .zip: theme.json plus the images it uses."""
    data = bubble_theme_to_dict(theme)
    # reference -> (path inside the file, source image)
    images: dict[str, tuple[str, str]] = {}

    def bundle(reference):
        if not reference.startswith(("user:", "pkg:")):
            return reference
        if reference not in images:
            source = image_path(reference, registry)
            if source is None:
                return "none"
            images[reference] = (f"images/{len(images) + 1}.png", source)
        return images[reference][0]

    for key in IMAGE_FIELDS:
        data[key] = bundle(str(data[key]))
    layers = [{**layer, "image": bundle(layer["image"])} for layer in data["decor"]]
    data["decor"] = [layer for layer in layers if layer["image"] != "none"]
    # A pet's own frame does not travel with a theme file.
    if str(data["frame_style"]).startswith(FRAME_STYLE_PREFIX):
        data["frame_style"] = "standard"
    try:
        with ZipFile(path, "w", ZIP_DEFLATED) as archive:
            archive.writestr(
                "theme.json",
                json.dumps(
                    dict(format=THEME_FORMAT, version=1, name=name, theme=data),
                    ensure_ascii=False,
                    indent=2,
                ),
            )
            for target, source in images.values():
                archive.writestr(target, _clean_png(Path(source)))
    except OSError as error:
        raise ThemeFileError(t("bubble.theme.write_failed")) from error


def import_theme_file(path, registry):
    """(name, theme) from a theme file; its images join the library."""
    try:
        with ZipFile(path) as archive:
            infos = archive.infolist()
            entries = {entry.filename: entry for entry in infos}
            # Count and size every member: a repeated name would otherwise
            # hide all but its last copy from these limits.
            if (
                len(entries) != len(infos)
                or len(infos) > MAX_FILE_IMAGES + 1
                or sum(entry.file_size for entry in infos) > MAX_FILE_BYTES
            ):
                raise ThemeFileError(t("bubble.theme.invalid_file"))
            manifest = entries.get("theme.json")
            if manifest is None or manifest.file_size > 1024 * 1024:
                raise ThemeFileError(t("bubble.theme.invalid_file"))
            record = json.loads(archive.read(manifest).decode("utf-8"))
            if (
                not isinstance(record, dict)
                or record.get("format") != THEME_FORMAT
                or record.get("version") != 1
                or not isinstance(record.get("theme"), dict)
            ):
                raise ThemeFileError(t("bubble.theme.invalid_file"))
            name = " ".join(str(record.get("name") or "").split())[:60]
            data = dict(record["theme"])
            imported: dict[str, str] = {}
            with TemporaryDirectory(prefix="bubble-theme-") as folder:

                def library(reference):
                    reference = str(reference or "")
                    # Ornaments are drawn in code and need no image.
                    if ornament_kind(reference):
                        return reference
                    if not re.fullmatch(r"images/[0-9]{1,3}\.png", reference):
                        return reference if reference in ("", "none") else "none"
                    if reference not in imported:
                        entry = entries.get(reference)
                        if entry is None or entry.file_size > MAX_FILE_IMAGE_BYTES:
                            return "none"
                        temp = Path(folder) / f"{len(imported)}.png"
                        temp.write_bytes(archive.read(entry))
                        element = registry.import_image(
                            temp, "sticker", f"{name or 'theme'} {len(imported) + 1}"
                        )
                        imported[reference] = element.reference
                    return imported[reference]

                for key in IMAGE_FIELDS:
                    if key in data and str(data[key]).startswith("images/"):
                        data[key] = library(data[key])
                raw_layers = data.get("decor")
                layers: list = raw_layers if isinstance(raw_layers, list) else []
                data["decor"] = [
                    {**layer, "image": library(layer.get("image"))}
                    for layer in layers
                    if isinstance(layer, dict)
                ]
    except (BadZipFile, OSError, ValueError, UnicodeDecodeError) as error:
        if isinstance(error, ThemeFileError):
            raise
        raise ThemeFileError(t("bubble.theme.invalid_file")) from error
    data["frame_style"] = "standard"
    return name, bubble_theme_from_dict(data)


def export_package_theme(folder, theme, registry):
    """Write bubble-theme.json and bubble/ images a pet package can ship.

    The JSON is the package's "bubbleTheme": the design values plus "frame"
    layers made from the pet's own frame (when shown) and the decoration
    layers. Library-only fields (photo, pattern image, frame image, image
    ornaments) cannot travel in a package and are left out; their names are
    returned so the caller can say so.
    """
    folder = Path(folder)
    data = bubble_theme_to_dict(theme)
    omitted = [key for key in IMAGE_FIELDS if str(data[key]).startswith("user:")]
    for key in omitted:
        data[key] = "none"
    frame: dict = {"backdrop": [], "overlay": []}
    written: dict[str, str] = {}
    # Decoration layers as drawn in the package, for the canvas they need.
    fitted_layers: list = []

    def bundle(source, stem):
        if source not in written:
            name = f"bubble/{_slug(stem)}-{len(written) + 1}.png"
            written[source] = name
        return written[source]

    style = str(data.pop("frame_style"))
    if style.startswith(FRAME_STYLE_PREFIX) and registered_frame(style) is not None:
        raw = _package_frame(style)
        for key in ("insets", "contentPadding", "innerBorder", "halo"):
            if key in raw:
                frame[key] = raw[key]
        if theme.package_layers:
            directory = package_directory(style)
            for group in ("backdrop", "overlay"):
                for layer in raw.get(group, []):
                    layer = dict(layer)
                    if "image" in layer:
                        source = (directory / layer["image"]).resolve()
                        layer["image"] = bundle(
                            str(source), PurePosixPath(layer["image"]).stem
                        )
                    frame[group].append(layer)
    # The theme's own inner line, halo and spacing replace the pet frame's.
    if theme.inner_border_custom:
        frame["innerBorder"] = {
            "color": theme.inner_border_color,
            "alpha": theme.inner_border_alpha,
        }
    halo = theme_halo(theme) if theme.halo_custom else None
    if theme.halo_custom:
        frame.pop("halo", None)
    if halo is not None:
        frame["halo"] = {
            "color": halo.color,
            "alpha": halo.alpha,
            "width": halo.width,
            "minWidth": halo.min_width,
            "offsetY": halo.offset_y,
            "grow": halo.grow,
            "radiusDelta": halo.radius_delta,
        }
    if theme.content_custom:
        frame["contentPadding"] = [
            theme.content_top,
            theme.content_bottom,
            theme.content_left,
        ]
    for key in FRAME_THEME_KEYS:
        data.pop(key, None)
    for layer in theme.decor:
        if layer.hidden:
            continue
        # A package frame takes image files; ornaments are drawn in code.
        if ornament_kind(layer.image):
            if "decor_ornaments" not in omitted:
                omitted.append("decor_ornaments")
            continue
        source = image_path(layer.image, registry)
        if source is None:
            continue
        width, height, x, y = layer.width, layer.height, layer.x, layer.y
        # Package layers stretch the image; fit the box to the image so the
        # result looks like the editor.
        with Image.open(source, formats=STORED_FORMATS) as image:
            fit = min(width / image.width, height / image.height)
            fitted = (image.width * fit, image.height * fit)
        x += (width - fitted[0]) / 2
        y += (height - fitted[1]) / 2
        entry = {
            "image": bundle(source, layer.name or PurePosixPath(layer.image).stem),
            "anchor": layer.anchor,
            "x": round(x, 1),
            "y": round(y, 1),
            "width": round(fitted[0], 1),
            "height": round(fitted[1], 1),
        }
        if layer.rotation:
            entry["rotation"] = layer.rotation
        if layer.mirror:
            entry["mirror"] = True
        if layer.flip_y:
            entry["flipY"] = True
        if layer.alpha != 255:
            entry["alpha"] = layer.alpha
        if layer.tint:
            entry["tint"] = layer.tint
        if layer.repeat == "y":
            entry["repeatY"] = {
                "gap": layer.repeat_gap,
                "bottomInset": layer.repeat_inset,
            }
        elif layer.repeat == "x":
            entry["repeatX"] = {
                "gap": layer.repeat_gap,
                "rightInset": layer.repeat_inset,
            }
        frame["backdrop" if layer.placement == "back" else "overlay"].append(entry)
        fitted_layers.append(
            replace(layer, x=x, y=y, width=fitted[0], height=fitted[1])
        )
    if any(frame[group] for group in ("backdrop", "overlay")) or len(frame) > 2:
        overflow = decor_overflow(
            fitted_layers, max(48.0, theme.minimum_width), 40.0, theme.radius
        )
        if halo is not None:
            overflow = tuple(max(a, b) for a, b in zip(overflow, halo_reach(halo)))
        insets = frame.get("insets", [0, 0, 0, 0])
        frame["insets"] = [round(max(float(a), b), 1) for a, b in zip(insets, overflow)]
        data["frame"] = {key: value for key, value in frame.items() if value != []}
    for key in ("decor", "package_layers"):
        data.pop(key, None)
    try:
        (folder / "bubble").mkdir(parents=True, exist_ok=True)
        for source, name in written.items():
            (folder / name).write_bytes(_clean_png(Path(source)))
        (folder / "bubble-theme.json").write_text(
            json.dumps({"bubbleTheme": data}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as error:
        raise ThemeFileError(t("bubble.theme.write_failed")) from error
    return omitted


def _package_frame(style):
    directory = package_directory(style)
    try:
        raw = json.loads((directory / "pet.json").read_text(encoding="utf-8"))
        frame = raw["bubbleTheme"]["frame"]
    except OSError, ValueError, KeyError, TypeError:
        return {}
    return frame if isinstance(frame, dict) else {}


def _clean_png(path):
    """Pixels only, re-encoded, so no metadata leaves with a shared file."""
    try:
        with Image.open(path, formats=STORED_FORMATS) as image:
            clean = Image.frombytes("RGBA", image.size, image.convert("RGBA").tobytes())
    except (OSError, UnidentifiedImageError) as error:
        raise ThemeFileError(t("bubble.theme.write_failed")) from error
    output = BytesIO()
    clean.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _theme_images(data):
    """Every image reference a stored theme names, valid or not."""
    images = {str(data.get(key) or "") for key in IMAGE_FIELDS}
    layers = data.get("decor")
    for layer in layers if isinstance(layers, list) else ():
        if isinstance(layer, dict):
            images.add(str(layer.get("image") or ""))
    return images


def _png_data(path):
    try:
        return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode(
            "ascii"
        )
    except OSError:
        return ""


def _slug(value):
    value = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value)).strip("-").lower()
    return value[:40] or "image"


def _checked_id(value):
    value = str(value or "")
    if not _ID.fullmatch(value):
        raise ThemeFileError(t("bubble.theme.missing"))
    return value
