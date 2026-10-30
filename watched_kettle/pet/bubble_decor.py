"""User decoration layers placed around a speech bubble.

A theme's ``decor`` uses the same anchors and painting as a package frame
(``pet/bubble_frame.py``) but names images by reference: ``user:<id>`` for the
user's image library or ``pkg:<pet id>/<path>`` for an image a pet package
ships. References are resolved only when painting, so saved themes and wire
data never hold local paths.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
import re

from PySide6.QtGui import QColor

from watched_kettle.pet.bubble_frame import (
    FRAME_ANCHORS,
    REPEAT_X_ANCHORS,
    REPEAT_Y_ANCHORS,
    THEME_COLOR_NAMES,
    FrameLayer,
    FrameRepeatX,
    FrameRepeatY,
    package_image_path,
)


MAX_DECOR_LAYERS = 24
DECOR_PLACEMENTS = frozenset({"front", "back"})
DECOR_REPEATS = frozenset({"none", "x", "y"})
# Inclusive bounds in 100% pixels; the editor uses the same numbers.
DECOR_LIMITS = {
    "x": (-240.0, 240.0),
    "y": (-240.0, 240.0),
    "width": (1.0, 320.0),
    "height": (1.0, 320.0),
    "rotation": (-180.0, 180.0),
    "alpha": (0, 255),
    "repeat_gap": (0.0, 200.0),
    "repeat_inset": (0.0, 200.0),
}
_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,40}")
_USER_PATTERN = re.compile(r"user:[a-f0-9]{32}")
# A built-in ornament drawn as a layer in the theme's colors; no image file.
ORNAMENT_PREFIX = "ornament:"
# Drawn in code by ui/speech_bubble_decorations.py.
ORNAMENT_KINDS = frozenset(
    {
        "cat-ear",
        "small-wing",
        "horn",
        "bat-wing",
        "star",
        "sparkle",
        "ribbon",
        "goggles",
        "magnet",
        "dot",
    }
)
_PACKAGE_PATTERN = re.compile(r"pkg:[A-Za-z0-9_.-]{1,80}/[^\\\0]{1,200}")


@dataclass(frozen=True)
class DecorLayer:
    id: str
    name: str
    image: str
    placement: str = "front"
    anchor: str = "top-left"
    x: float = 0.0
    y: float = 0.0
    width: float = 32.0
    height: float = 32.0
    rotation: float = 0.0
    mirror: bool = False
    flip_y: bool = False
    alpha: int = 255
    tint: str = ""
    repeat: str = "none"
    repeat_gap: float = 0.0
    repeat_inset: float = 0.0
    hidden: bool = False


def decor_from_list(raw):
    """Return valid layers in order; invalid entries are dropped, never raised."""
    if not isinstance(raw, (list, tuple)):
        return ()
    layers: list = []
    seen: set = set()
    for index, item in enumerate(raw):
        if len(layers) >= MAX_DECOR_LAYERS:
            break
        layer = _layer(item, index) if isinstance(item, dict) else None
        if layer is None:
            continue
        if layer.id in seen:
            layer = _with_id(layer, f"layer-{index + 1}", seen)
        seen.add(layer.id)
        layers.append(layer)
    return tuple(layers)


def ornament_kind(reference):
    """The built-in ornament an "ornament:<kind>" reference names, or ""."""
    reference = str(reference or "")
    kind = reference.removeprefix(ORNAMENT_PREFIX)
    return kind if kind != reference and kind in ORNAMENT_KINDS else ""


def is_image_reference(value):
    value = str(value or "")
    return bool(
        _USER_PATTERN.fullmatch(value)
        or ornament_kind(value)
        or (
            _PACKAGE_PATTERN.fullmatch(value)
            and ".." not in value.split("/")
            and value.lower().endswith((".png", ".webp"))
        )
    )


def frame_layers(layers, registry=None, placement="front"):
    """Paintable package-style layers for one placement, skipping missing images."""
    result = []
    for layer in layers:
        if layer.hidden or layer.placement != placement:
            continue
        # The painter draws an ornament itself from its reference.
        path = (
            layer.image
            if ornament_kind(layer.image)
            else image_path(layer.image, registry)
        )
        if path is None:
            continue
        repeat_y = repeat_x = None
        if layer.repeat == "y" and layer.anchor in REPEAT_Y_ANCHORS:
            repeat_y = FrameRepeatY(layer.repeat_gap, layer.repeat_inset)
        elif layer.repeat == "x" and layer.anchor in REPEAT_X_ANCHORS:
            repeat_x = FrameRepeatX(layer.repeat_gap, layer.repeat_inset)
        result.append(
            FrameLayer(
                anchor=layer.anchor,
                x=layer.x,
                y=layer.y,
                image=path,
                width=layer.width,
                height=layer.height,
                color=layer.tint,
                alpha=layer.alpha,
                mirror=layer.mirror,
                repeat_y=repeat_y,
                repeat_x=repeat_x,
                rotation=layer.rotation,
                flip_y=layer.flip_y,
                keep_aspect=True,
            )
        )
    return tuple(result)


def image_path(reference, registry=None):
    reference = str(reference or "")
    if reference.startswith("pkg:"):
        return package_image_path(reference)
    if registry is None or not _USER_PATTERN.fullmatch(reference):
        return None
    element = registry.get(reference)
    return None if element is None else str(element.image_path)


# Old themes placed up to three stickers by percent of the body. Layers keep a
# fixed distance from an anchor instead; this body size converts the old
# percentages to a nearby anchor and offset.
_STICKER_REFERENCE_BODY = (240.0, 72.0)


def stickers_as_layers(raw_theme):
    """Convert the old sticker_1..3 fields of a saved theme to layers."""
    layers = []
    width, height = _STICKER_REFERENCE_BODY
    for slot in (1, 2, 3):
        reference = str(raw_theme.get(f"sticker_{slot}") or "")
        if not _USER_PATTERN.fullmatch(reference):
            continue
        size = _bounded(raw_theme.get(f"sticker_{slot}_size"), 32.0, 16.0, 96.0)
        percent_x = _bounded(raw_theme.get(f"sticker_{slot}_x"), 50.0, 0.0, 100.0)
        percent_y = _bounded(raw_theme.get(f"sticker_{slot}_y"), 50.0, 0.0, 100.0)
        horizontal = (
            "left" if percent_x < 34 else "right" if percent_x > 66 else "center"
        )
        vertical = "top" if percent_y < 50 else "bottom"
        if horizontal != "center" and 34 <= percent_y <= 66:
            vertical = "center"
        anchor_x = {"left": 0.0, "center": width / 2, "right": width}[horizontal]
        anchor_y = {"top": 0.0, "center": height / 2, "bottom": height}[vertical]
        layers.append(
            DecorLayer(
                id=f"sticker-{slot}",
                name="",
                image=reference,
                anchor=f"{vertical}-{horizontal}",
                x=round(width * percent_x / 100 - anchor_x - size / 2, 1),
                y=round(height * percent_y / 100 - anchor_y - size / 2, 1),
                width=size,
                height=size,
            )
        )
    return tuple(layers)


def decor_overflow(layers, body_width, body_height, radius):
    """(left, top, right, bottom) a layer set reaches outside a body, at 100%."""
    left = top = right = bottom = 0.0
    for layer in layers:
        if layer.hidden:
            continue
        box = _layer_box(layer, body_width, body_height, radius)
        if box is None:
            continue
        x0, y0, x1, y1 = box
        left, top = max(left, -x0), max(top, -y0)
        right, bottom = max(right, x1 - body_width), max(bottom, y1 - body_height)
    return tuple(min(120.0, max(0.0, value)) for value in (left, top, right, bottom))


def _layer_box(layer, width, height, radius):
    if layer.anchor == "arc-top-left":
        corner = min(radius, height / 2, width / 2) * (1 - 2**-0.5)
        anchor_x = anchor_y = corner
    else:
        vertical, _, horizontal = layer.anchor.partition("-")
        anchor_x = {"left": 0.0, "center": width / 2, "right": width}[horizontal]
        anchor_y = {"top": 0.0, "center": height / 2, "bottom": height}[vertical]
    x0, y0 = anchor_x + layer.x, anchor_y + layer.y
    angle = math.radians(layer.rotation)
    cos, sin = abs(math.cos(angle)), abs(math.sin(angle))
    half_w = (layer.width * cos + layer.height * sin) / 2
    half_h = (layer.width * sin + layer.height * cos) / 2
    cx, cy = x0 + layer.width / 2, y0 + layer.height / 2
    box = [cx - half_w, cy - half_h, cx + half_w, cy + half_h]
    # Repeats stay inside the body along their axis.
    if layer.repeat == "y" and layer.anchor in REPEAT_Y_ANCHORS:
        box[1], box[3] = max(box[1], 0.0), min(box[3], height)
    elif layer.repeat == "x" and layer.anchor in REPEAT_X_ANCHORS:
        box[0], box[2] = max(box[0], 0.0), min(box[2], width)
    return box


def _layer(raw, index):
    image = str(raw.get("image") or "").strip()
    anchor = str(raw.get("anchor") or "top-left")
    if not is_image_reference(image) or anchor not in FRAME_ANCHORS:
        return None
    identifier = str(raw.get("id") or "")
    if not _ID_PATTERN.fullmatch(identifier):
        identifier = f"layer-{index + 1}"
    values = {
        key: _bounded(raw.get(key), getattr(DecorLayer, key), *DECOR_LIMITS[key])
        for key in DECOR_LIMITS
    }
    values["alpha"] = round(values["alpha"])
    return DecorLayer(
        id=identifier,
        name=" ".join(str(raw.get("name") or "").split())[:60],
        image=image,
        placement=_choice(raw.get("placement"), DECOR_PLACEMENTS, "front"),
        anchor=anchor,
        mirror=raw.get("mirror") is True,
        flip_y=raw.get("flip_y") is True,
        tint=_tint(raw.get("tint")),
        repeat=_choice(raw.get("repeat"), DECOR_REPEATS, "none"),
        hidden=raw.get("hidden") is True,
        **values,
    )


def _with_id(layer, identifier, seen):
    candidate, suffix = identifier, 2
    while candidate in seen:
        candidate, suffix = f"{identifier}-{suffix}", suffix + 1
    return replace(layer, id=candidate)


def _tint(value):
    value = str(value or "").strip()
    if value in THEME_COLOR_NAMES:
        return value
    color = QColor(value)
    return color.name(QColor.NameFormat.HexRgb) if value and color.isValid() else ""


def _choice(value, choices, fallback):
    value = str(value or "").strip().lower()
    return value if value in choices else fallback


def _bounded(value, fallback, minimum, maximum):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        value = fallback
    return type(minimum)(min(max(value, minimum), maximum))
