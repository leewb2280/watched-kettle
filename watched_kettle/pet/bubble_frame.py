"""Validated outer bubble decorations declared by a pet package.

A package's ``bubbleTheme.frame`` adds canvas around the bubble body, an
optional halo, and image or dot layers anchored to the body edges. Themes refer
to a package frame by ``frame_style = "pet:<pet id>"``; the loader registers the
frame here so painting code can look it up without re-reading the package.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import re

from PySide6.QtGui import QColor


FRAME_STYLE_PREFIX = "pet:"
FRAME_STYLE_PATTERN = re.compile(r"pet:[A-Za-z0-9_.-]{1,80}")
FRAME_ANCHORS = frozenset(
    {
        "top-left",
        "top-center",
        "top-right",
        "center-left",
        "center-right",
        "bottom-left",
        "bottom-center",
        "bottom-right",
        # The point at 45 degrees on the rounded top-left corner.
        "arc-top-left",
    }
)
# Theme colors a layer can follow so the user's color edits still apply.
THEME_COLOR_NAMES = frozenset({"border", "shadow", "background", "text"})
FRAME_IMAGE_SUFFIXES = frozenset({".png", ".webp"})
MAX_FRAME_LAYERS = 8
MAX_FRAME_IMAGE_BYTES = 4 * 1024 * 1024
MAX_FRAME_REPEATS = 256
REPEAT_Y_ANCHORS = frozenset({"top-left", "top-center", "top-right"})
_OFFSET_LIMIT = 200.0
_SIZE_LIMIT = (0.5, 200.0)


@dataclass(frozen=True)
class FrameHalo:
    color: str
    alpha: int
    width: float
    min_width: float
    offset_y: float
    grow: float
    radius_delta: float


@dataclass(frozen=True)
class FrameRepeatY:
    gap: float = 0.0
    bottom_inset: float = 0.0


@dataclass(frozen=True)
class FrameLayer:
    anchor: str
    x: float
    y: float
    # Exactly one of image (absolute path) or circle_radius is set.
    image: str = ""
    width: float = 0.0
    height: float = 0.0
    circle_radius: float = 0.0
    color: str = ""
    alpha: int = 255
    mirror: bool = False
    repeat_y: FrameRepeatY | None = None


@dataclass(frozen=True)
class BubbleFrame:
    insets: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    content_padding: tuple[int, int, int] | None = None
    inner_border: tuple[str, int] | None = None
    halo: FrameHalo | None = None
    backdrop: tuple[FrameLayer, ...] = ()
    overlay: tuple[FrameLayer, ...] = ()


_registered_frames: dict[str, BubbleFrame] = {}


def frame_style_for(pet_id):
    return f"{FRAME_STYLE_PREFIX}{pet_id}"


def is_frame_style(value):
    return value == "standard" or bool(FRAME_STYLE_PATTERN.fullmatch(str(value)))


def registered_frame(frame_style):
    return _registered_frames.get(str(frame_style or ""))


def register_package_frame(manifest, package_directory):
    """Parse and remember a package frame; return its frame style or None."""
    if not isinstance(manifest, dict):
        return None
    theme = manifest.get("bubbleTheme")
    raw_frame = theme.get("frame") if isinstance(theme, dict) else None
    style = frame_style_for(manifest.get("id") or Path(package_directory).name)
    if not isinstance(raw_frame, dict) or not is_frame_style(style):
        return None
    _registered_frames[style] = parse_frame(raw_frame, Path(package_directory))
    return style


def parse_frame(raw, package_directory):
    """Return a bounded frame; invalid parts are dropped, never raised."""
    package_directory = Path(package_directory).resolve()
    insets = _numbers(raw.get("insets"), 4, 0.0, 120.0)
    padding = _numbers(raw.get("contentPadding"), 3, 0.0, 80.0)
    inner = raw.get("innerBorder")
    return BubbleFrame(
        insets=insets or (0.0, 0.0, 0.0, 0.0),
        content_padding=tuple(round(value) for value in padding) if padding else None,
        inner_border=(
            (_color_ref(inner.get("color"), ""), _alpha(inner.get("alpha")))
            if isinstance(inner, dict) and _color_ref(inner.get("color"), "")
            else None
        ),
        halo=_halo(raw.get("halo")),
        backdrop=_layers(raw.get("backdrop"), package_directory),
        overlay=_layers(raw.get("overlay"), package_directory),
    )


def _halo(raw):
    if not isinstance(raw, dict):
        return None
    color = _color_ref(raw.get("color"), "shadow")
    return FrameHalo(
        color=color,
        alpha=_alpha(raw.get("alpha")),
        width=_number(raw.get("width"), 3.0, 0.5, 20.0),
        min_width=_number(raw.get("minWidth"), 1.0, 0.5, 20.0),
        offset_y=_number(raw.get("offsetY"), 0.0, -40.0, 40.0),
        grow=_number(raw.get("grow"), 0.0, -40.0, 40.0),
        radius_delta=_number(raw.get("radiusDelta"), 0.0, -40.0, 40.0),
    )


def _layers(raw, package_directory):
    if not isinstance(raw, (list, tuple)):
        return ()
    layers = []
    for item in raw[:MAX_FRAME_LAYERS]:
        layer = _layer(item, package_directory) if isinstance(item, dict) else None
        if layer is not None:
            layers.append(layer)
    return tuple(layers)


def _layer(raw, package_directory):
    anchor = str(raw.get("anchor") or "")
    if anchor not in FRAME_ANCHORS:
        return None
    x = _number(raw.get("x"), 0.0, -_OFFSET_LIMIT, _OFFSET_LIMIT)
    y = _number(raw.get("y"), 0.0, -_OFFSET_LIMIT, _OFFSET_LIMIT)
    circle = raw.get("circle")
    if isinstance(circle, dict):
        color = _color_ref(circle.get("color"), "")
        if not color:
            return None
        return FrameLayer(
            anchor=anchor,
            x=x,
            y=y,
            circle_radius=_number(circle.get("radius"), 2.0, 0.5, 40.0),
            color=color,
            alpha=_alpha(circle.get("alpha")),
        )
    image = _package_image(raw.get("image"), package_directory)
    if image is None:
        return None
    return FrameLayer(
        anchor=anchor,
        x=x,
        y=y,
        image=image,
        width=_number(raw.get("width"), 16.0, *_SIZE_LIMIT),
        height=_number(raw.get("height"), 16.0, *_SIZE_LIMIT),
        # An image with a tint is an alpha mask filled with that color.
        color=_color_ref(raw.get("tint"), ""),
        alpha=_alpha(raw.get("alpha")),
        mirror=raw.get("mirror") is True,
        repeat_y=_repeat_y(raw.get("repeatY"), anchor),
    )


def _repeat_y(raw, anchor):
    if not isinstance(raw, dict) or anchor not in REPEAT_Y_ANCHORS:
        return None
    values = [raw.get(key, 0) for key in ("gap", "bottomInset")]
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 0 <= value <= _OFFSET_LIMIT
        for value in values
    ):
        return None
    return FrameRepeatY(*(float(value) for value in values))


def _package_image(value, package_directory):
    if not isinstance(value, str) or not value.strip():
        return None
    path = (package_directory / value).resolve()
    if (
        not path.is_relative_to(package_directory)
        or path.suffix.lower() not in FRAME_IMAGE_SUFFIXES
        or not path.is_file()
        or path.stat().st_size > MAX_FRAME_IMAGE_BYTES
    ):
        return None
    return str(path)


def _color_ref(value, fallback):
    value = str(value or "").strip()
    if value in THEME_COLOR_NAMES:
        return value
    color = QColor(value)
    return (
        color.name(QColor.NameFormat.HexRgb) if value and color.isValid() else fallback
    )


def _alpha(value):
    return round(_number(value, 255, 0, 255))


def _number(value, fallback, minimum, maximum):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or (isinstance(value, float) and not math.isfinite(value))
    ):
        return float(fallback)
    return float(min(max(value, minimum), maximum))


def _numbers(value, count, minimum, maximum):
    if not isinstance(value, (list, tuple)) or len(value) != count:
        return None
    if any(
        isinstance(item, bool)
        or not isinstance(item, (int, float))
        or (isinstance(item, float) and not math.isfinite(item))
        for item in value
    ):
        return None
    return tuple(float(min(max(item, minimum), maximum)) for item in value)
