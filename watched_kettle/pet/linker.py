"""Join installed pets into one pet with several looks; Qt-independent.

The result is the same declaration and asset set a version 2 package ships
(``appearanceSet``), so the importer stores and identifies it like any import.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import json
from pathlib import Path

from PIL import Image, ImageSequence, UnidentifiedImageError

from watched_kettle.config import FRAME_HEIGHT, FRAME_WIDTH
from watched_kettle.localization import t
from watched_kettle.pet.appearance_assets import (
    AUTO_ORDERS,
    AUTO_SECONDS,
    MAX_APPEARANCE_IMAGE_BYTES,
    MAX_APPEARANCE_VARIANTS,
    validate_appearance_image,
)
from watched_kettle.pet.import_package import package_reader, read_local


MAX_TRANSITION_FRAMES = 48
DEFAULT_TRANSITION_INTERVAL = 60
TRANSITION_SUFFIXES = frozenset({".png", ".webp", ".gif"})
# Package fields a joined pet keeps from its first look.
INHERITED_FIELDS = (
    "defaultWidth",
    "defaultLookRange",
    "lookDirectionOffset",
    "lookDirectionMirrored",
    "mirrorRightLookFromLeft",
    "idleActivities",
)


class LinkError(ValueError):
    """A user-facing problem with the looks or transition images."""


@dataclass(frozen=True)
class TransitionStrip:
    image: bytes
    frames: int
    interval: int
    # True when frames were scaled to fit a 192x208 cell.
    resized: bool


@dataclass(frozen=True)
class LinkLook:
    label: str
    directory: Path
    # A look inside a joined pet's package; None uses its main spritesheet.
    image: str | None = None


def transition_strip(paths):
    """Turn a strip, an animation or numbered stills into one strip.

    One still image must already be cells laid out side by side. Frames of
    another size keep their shape inside a cell, standing on its bottom edge.
    """
    paths = [Path(path) for path in paths]
    if not paths or len(paths) > MAX_TRANSITION_FRAMES:
        raise LinkError(t("pet.link.transition_count", max=MAX_TRANSITION_FRAMES))
    frames, durations = [], []
    for path in sorted(paths, key=lambda item: item.name.casefold()):
        image = _open(path)
        with image:
            if len(paths) > 1:
                frames.append(image.convert("RGBA"))
            elif getattr(image, "is_animated", False):
                for frame in ImageSequence.Iterator(image):
                    frames.append(frame.convert("RGBA"))
                    durations.append(int(frame.info.get("duration") or 0))
                    if len(frames) > MAX_TRANSITION_FRAMES:
                        break
            elif (
                image.height == FRAME_HEIGHT
                and image.width % FRAME_WIDTH == 0
                and image.width // FRAME_WIDTH >= 2
            ):
                strip = image.convert("RGBA")
                frames.extend(
                    strip.crop(
                        (
                            index * FRAME_WIDTH,
                            0,
                            (index + 1) * FRAME_WIDTH,
                            FRAME_HEIGHT,
                        )
                    )
                    for index in range(image.width // FRAME_WIDTH)
                )
            else:
                raise LinkError(t("pet.link.transition_not_strip"))
    if not 2 <= len(frames) <= MAX_TRANSITION_FRAMES:
        raise LinkError(t("pet.link.transition_count", max=MAX_TRANSITION_FRAMES))
    resized = any(frame.size != (FRAME_WIDTH, FRAME_HEIGHT) for frame in frames)
    cells = [_cell(frame) for frame in frames]
    for cell in cells:
        low, high = cell.getchannel("A").getextrema()
        if high == 0 or low == 255:
            raise LinkError(t("pet.link.transition_transparency"))
    strip = Image.new("RGBA", (FRAME_WIDTH * len(cells), FRAME_HEIGHT))
    for index, cell in enumerate(cells):
        strip.paste(cell, (index * FRAME_WIDTH, 0))
    output = BytesIO()
    strip.save(output, format="WEBP", lossless=True, exact=True)
    timed = [value for value in durations if value > 0]
    interval = round(sum(timed) / len(timed)) if timed else DEFAULT_TRANSITION_INTERVAL
    return TransitionStrip(
        output.getvalue(), len(cells), min(1000, max(16, interval)), resized
    )


def link_package(looks, transitions, *, default=0, bubble=None, auto=None):
    """(spritesheet, extras, assets) for a pet made of looks.

    looks are LinkLook values in order; transitions maps (from, to) look
    indexes to TransitionStrip values with their chosen interval; bubble is a
    look index whose bubble design the pet uses, or None.
    """
    if not 2 <= len(looks) <= MAX_APPEARANCE_VARIANTS:
        raise LinkError(t("pet.link.look_count", max=MAX_APPEARANCE_VARIANTS))
    if not 0 <= default < len(looks):
        raise LinkError(t("pet.appearance.invalid_package"))
    packages = [_read_look(look.directory, look.image) for look in looks]
    ids = [f"look-{index + 1}" for index in range(len(looks))]
    images, assets, variants = {}, {}, []
    for index, (look, (_raw, atlas, _extras, _assets)) in enumerate(
        zip(looks, packages)
    ):
        path = (
            "spritesheet.webp" if index == default else f"appearance/{ids[index]}.webp"
        )
        if index != default:
            assets[path] = atlas
        images[index] = atlas
        variants.append(
            {"id": ids[index], "label": look.label, "spritesheetPath": path}
        )
    declared = []
    for (source, target), strip in sorted(transitions.items()):
        if source == target or not (
            0 <= source < len(looks) and 0 <= target < len(looks)
        ):
            raise LinkError(t("pet.appearance.invalid_package"))
        path = f"appearance/{ids[source]}-{ids[target]}.webp"
        assets[path] = strip.image
        declared.append(
            {
                "from": ids[source],
                "to": ids[target],
                "spritesheetPath": path,
                "frames": strip.frames,
                "intervalMs": min(1000, max(16, int(strip.interval))),
            }
        )
    auto = auto or {}
    low, high = AUTO_SECONDS
    minimum = min(high, max(low, int(auto.get("minSeconds", 60))))
    maximum = min(high, max(minimum, int(auto.get("maxSeconds", 180))))
    order = auto.get("order") if auto.get("order") in AUTO_ORDERS else "random"
    _raw, _atlas, first, _first_assets = packages[default]
    extras = {key: first[key] for key in INHERITED_FIELDS if key in first}
    extras["appearanceSet"] = {
        "version": 2,
        "default": ids[default],
        "variants": variants,
        "transitions": declared,
        "auto": {"minSeconds": minimum, "maxSeconds": maximum, "order": order},
    }
    if bubble is not None:
        _raw, _atlas, chosen, chosen_assets = packages[bubble]
        if "bubbleTheme" in chosen:
            extras["bubbleTheme"] = chosen["bubbleTheme"]
            assets.update(
                {
                    name: data
                    for name, data in chosen_assets.items()
                    if name.startswith("bubble/")
                }
            )
    return images[default], extras, assets


def look_problem(spritesheet):
    """Why a pet cannot be a look ("" when it can), from the image header only."""
    try:
        with Image.open(spritesheet, formats=("PNG", "WEBP")) as image:
            if getattr(image, "is_animated", False) or image.size != (1536, 2288):
                return t("pet.link.not_v2")
    except OSError, UnidentifiedImageError, Image.DecompressionBombError:
        return t("pet.link.not_v2")
    return ""


def has_bubble_design(directory):
    """Whether the package declares its own bubble design."""
    try:
        raw = json.loads((Path(directory) / "pet.json").read_text(encoding="utf-8"))
    except OSError, ValueError:
        return False
    return isinstance(raw, dict) and isinstance(raw.get("bubbleTheme"), dict)


def is_joined(directory):
    """Whether the package was made by joining pets and can be edited again."""
    try:
        raw = json.loads((Path(directory) / "pet.json").read_text(encoding="utf-8"))
    except OSError, ValueError:
        return False
    return (
        isinstance(raw, dict)
        and raw.get("importSource") == "link"
        and isinstance(raw.get("appearanceSet"), dict)
    )


def _read_look(directory, name=None):
    try:
        raw, image, extras, assets, _warnings = package_reader(directory)
        if name is not None:
            image = read_local(directory, name, MAX_APPEARANCE_IMAGE_BYTES)
        with Image.open(BytesIO(image), formats=("PNG", "WEBP")) as opened:
            atlas = validate_appearance_image(opened)
    except (OSError, ValueError, UnidentifiedImageError) as error:
        raise LinkError(t("pet.link.not_v2")) from error
    output = BytesIO()
    atlas.save(output, format="WEBP", lossless=True, exact=True)
    return raw, output.getvalue(), extras, assets


def _open(path):
    try:
        if path.suffix.lower() not in TRANSITION_SUFFIXES or not path.is_file():
            raise LinkError(t("pet.link.transition_format"))
        if path.stat().st_size > MAX_APPEARANCE_IMAGE_BYTES:
            raise LinkError(t("pet.link.transition_too_large"))
        return Image.open(path, formats=("PNG", "WEBP", "GIF"))
    except LinkError:
        raise
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as error:
        raise LinkError(t("pet.link.transition_format")) from error


def _cell(frame):
    if frame.size == (FRAME_WIDTH, FRAME_HEIGHT):
        return frame
    fit = min(FRAME_WIDTH / frame.width, FRAME_HEIGHT / frame.height)
    size = (max(1, round(frame.width * fit)), max(1, round(frame.height * fit)))
    scaled = frame.resize(size, Image.Resampling.LANCZOS)
    cell = Image.new("RGBA", (FRAME_WIDTH, FRAME_HEIGHT))
    cell.paste(scaled, ((FRAME_WIDTH - size[0]) // 2, FRAME_HEIGHT - size[1]))
    return cell
