"""Bounded package inputs; never extract archives or follow filesystem links."""

from copy import deepcopy
from io import BytesIO
import json
import math
from pathlib import Path, PurePosixPath
import stat
from zipfile import BadZipFile, ZipFile

from PIL import Image

from watched_kettle.config import ANIMATIONS
from watched_kettle.localization import t

MAX_MANIFEST_BYTES = 256 * 1024
MAX_PACKAGE_BYTES = 96 * 1024 * 1024
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_PACKAGE_FILES = 64
MAX_DECORATION_BYTES = 4 * 1024 * 1024


class PackageError(ValueError):
    pass


def invalid():
    return PackageError(t("pet.import.invalid_package"))


def relative_name(value):
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise invalid()
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise invalid()
    reserved = {"CON", "PRN", "AUX", "NUL"} | {
        f"{name}{number}" for name in ("COM", "LPT") for number in range(1, 10)
    }
    if any(ord(char) < 32 or ord(char) == 127 for char in value) or any(
        part != part.rstrip(" .") or part.split(".", 1)[0].upper() in reserved
        for part in path.parts
    ):
        raise invalid()
    return path.as_posix()


def linked(path):
    return path.is_symlink() or path.is_junction()


def read_local(root, name, limit):
    name = relative_name(name)
    root = Path(root)
    current = root
    if linked(root):
        raise invalid()
    for part in PurePosixPath(name).parts:
        current = current / part
        if linked(current):
            raise invalid()
    if not current.resolve().is_relative_to(root.resolve()):
        raise invalid()
    with current.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise invalid()
    return raw


def json_object(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise invalid()
            result[key] = value
        return result

    if len(raw) > MAX_MANIFEST_BYTES:
        raise invalid()
    value = json.loads(
        raw.decode("utf-8-sig"),
        object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(invalid()),
    )
    if not isinstance(value, dict):
        raise invalid()
    return value


def package_reader(path):
    """Read only declared assets; root ZIP or one wrapper folder, never a batch."""
    path = Path(path)
    if path.is_dir():
        return read_package(lambda name, limit: read_local(path, name, limit))
    if linked(path) or path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise invalid()
    try:
        with ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_PACKAGE_FILES:
                raise invalid()
            names = {}
            total = 0
            for entry in entries:
                relative_name(entry.orig_filename.rstrip("/"))
                name = relative_name(entry.filename.rstrip("/"))
                if name.casefold() in names or entry.flag_bits & 1:
                    raise invalid()
                mode = entry.external_attr >> 16
                if stat.S_ISLNK(mode) or (
                    stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}
                ):
                    raise invalid()
                names[name.casefold()] = entry
                total += entry.file_size
            if total > MAX_PACKAGE_BYTES:
                raise invalid()
            roots = [
                entry.filename[:-8]
                for entry in entries
                if not entry.is_dir()
                and PurePosixPath(entry.filename).name == "pet.json"
            ]
            if len(roots) != 1 or roots[0].count("/") > 1:
                raise invalid()
            prefix = roots[0]
            if any(
                not entry.filename.startswith(prefix)
                for entry in entries
                if not entry.is_dir()
            ):
                raise invalid()

            def read(name, limit):
                entry = names.get((prefix + relative_name(name)).casefold())
                if entry is None or entry.is_dir() or entry.file_size > limit:
                    raise invalid()
                with archive.open(entry) as stream:
                    raw = stream.read(limit + 1)
                if len(raw) > limit:
                    raise invalid()
                return raw

            return read_package(read)
    except (BadZipFile, KeyError, RuntimeError) as error:
        raise invalid() from error


def read_package(read):
    raw = json_object(read("pet.json", MAX_MANIFEST_BYTES))
    image = read(
        relative_name(raw.get("spritesheetPath", "spritesheet.webp")), 20 * 1024 * 1024
    )
    extras, assets, warnings = normalize_manifest(raw, read)
    if sum(map(len, assets.values())) + len(image) > MAX_PACKAGE_BYTES:
        raise invalid()
    return raw, image, extras, assets, warnings


def normalize_manifest(raw, read):
    """Keep supported runtime fields, normalize images, report omitted fields."""
    result, assets, warnings = {}, {}, []
    if isinstance(raw.get("id"), str) and len(raw["id"]) <= 200:
        result["importOriginalId"] = raw["id"]
    for key, limit in (("description", 1000), ("author", 200), ("license", 200)):
        if key in raw:
            if not isinstance(raw[key], str) or len(raw[key]) > limit:
                raise invalid()
            result[key] = raw[key]
    if "localizedDescriptions" in raw:
        values = raw["localizedDescriptions"]
        if (
            not isinstance(values, dict)
            or len(values) > 64
            or any(
                not isinstance(k, str)
                or len(k) > 80
                or not isinstance(v, str)
                or len(v) > 1000
                for k, v in values.items()
            )
        ):
            raise invalid()
        result["localizedDescriptions"] = values
    for key, low, high in (
        ("defaultWidth", 32, 768),
        ("defaultLookRange", 0, 1000),
        ("lookDirectionOffset", 0, 15),
    ):
        if key in raw:
            value = raw[key]
            if (
                type(value) not in {int, float}
                or not math.isfinite(value)
                or not low <= value <= high
            ):
                raise invalid()
            result[key] = value
    for key in ("lookDirectionMirrored", "mirrorRightLookFromLeft"):
        if key in raw:
            if type(raw[key]) is not bool:
                raise invalid()
            result[key] = raw[key]
    if "idleActivities" in raw:
        values = raw["idleActivities"]
        if not isinstance(values, list) or len(values) > 32:
            raise invalid()
        for item in values:
            if isinstance(item, str) and item in ANIMATIONS:
                continue
            if not isinstance(item, dict) or item.get("state") not in ANIMATIONS:
                raise invalid()
            for key in ("weight", "duration"):
                value = item.get(key, 1)
                if (
                    type(value) not in {float, int}
                    or not math.isfinite(value)
                    or not 0 < value <= 86400000
                ):
                    raise invalid()
        result["idleActivities"] = values
    if "bubbleTheme" in raw:
        from watched_kettle.pet.bubble_theme import (
            bubble_theme_from_dict,
            bubble_theme_to_dict,
        )

        theme = raw["bubbleTheme"]
        if not isinstance(theme, dict):
            raise invalid()
        normalized = bubble_theme_to_dict(bubble_theme_from_dict(theme))
        for key, value in list(normalized.items()):
            if isinstance(value, str) and (
                value.startswith("user:") or value.startswith("pet:")
            ):
                normalized[key] = "standard" if key == "frame_style" else "none"
                warnings.append("bubbleTheme." + key)
        if "frame" in theme:
            frame = deepcopy(theme["frame"])
            if not isinstance(frame, dict):
                raise invalid()
            for group in ("backdrop", "overlay"):
                layers = frame.get(group, [])
                if not isinstance(layers, list) or len(layers) > 8:
                    raise invalid()
                for layer in layers:
                    if not isinstance(layer, dict):
                        raise invalid()
                    if "image" in layer:
                        name = relative_name(layer["image"])
                        if PurePosixPath(name).suffix.lower() not in {".png", ".webp"}:
                            raise invalid()
                        data = read(name, MAX_DECORATION_BYTES)
                        with Image.open(BytesIO(data)) as image:
                            if (
                                image.format not in {"PNG", "WEBP"}
                                or image.width * image.height > 4000000
                            ):
                                raise invalid()
                            clean = Image.frombytes(
                                "RGBA", image.size, image.convert("RGBA").tobytes()
                            )
                            output = BytesIO()
                            clean.save(output, format="PNG")
                        if len(output.getvalue()) > MAX_DECORATION_BYTES:
                            raise invalid()
                        import hashlib

                        target = (
                            "bubble/"
                            + hashlib.sha256(output.getvalue()).hexdigest()
                            + ".png"
                        )
                        assets[target] = output.getvalue()
                        layer["image"] = target
            normalized["frame"] = frame
            normalized.pop("frame_style", None)
        result["bubbleTheme"] = normalized
    known = set(result) | {
        "id",
        "name",
        "displayName",
        "spritesheetPath",
        "spriteVersionNumber",
        "formatVersion",
        "rows",
        "distribution",
        "importSource",
    }
    warnings.extend(key for key in raw if key not in known)
    return result, assets, sorted(set(warnings))
