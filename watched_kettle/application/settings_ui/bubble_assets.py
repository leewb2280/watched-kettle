"""Images and pet decoration data the bubble editor shows; never local paths."""

from __future__ import annotations

import base64
from dataclasses import asdict
from io import BytesIO

from PIL import Image
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QColor

from watched_kettle.pet.bubble_decor import ORNAMENT_KINDS, ORNAMENT_PREFIX, DecorLayer
from watched_kettle.pet.bubble_frame import (
    frame_style_for,
    package_image_reference,
    registered_frame,
)
from watched_kettle.pet.bubble_theme import BUBBLE_THEME_LIMITS
from watched_kettle.ui.speech_bubble_decorations import ornament_pixmap


THUMBNAIL_SIZE = 96
# Element and package images are stored as PNG or WebP only.
STORED_FORMATS = ("PNG", "WEBP")


def image_entry(reference, name, kind, path):
    """Wire entry for an image: thumbnail data and natural size."""
    thumbnail, width, height = "", 1, 1
    try:
        with Image.open(path, formats=STORED_FORMATS) as source:
            width, height = source.size
            image = source.convert("RGBA")
        image.thumbnail((THUMBNAIL_SIZE, THUMBNAIL_SIZE))
        output = BytesIO()
        image.save(output, format="PNG")
        thumbnail = "data:image/png;base64," + base64.b64encode(
            output.getvalue()
        ).decode("ascii")
    except OSError, ValueError, Image.DecompressionBombError:
        pass
    return dict(
        id=reference,
        name=name,
        kind=kind,
        thumbnail=thumbnail,
        width=width,
        height=height,
    )


def library_entries(registry):
    return [
        image_entry(element.reference, element.name, element.kind, element.image_path)
        for element in registry.elements
    ]


def ornament_entries(theme):
    """Built-in ornaments the decoration tab adds as layers, in theme colors."""
    entries = []
    for kind in sorted(ORNAMENT_KINDS):
        pixmap = ornament_pixmap(kind, theme)
        thumbnail = pixmap.scaled(
            THUMBNAIL_SIZE,
            THUMBNAIL_SIZE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        thumbnail.save(buffer, "PNG")
        buffer.close()
        entries.append(
            dict(
                id=ORNAMENT_PREFIX + kind,
                # The settings window shows its own translated name.
                name=kind,
                kind="ornament",
                thumbnail="data:image/png;base64,"
                + base64.b64encode(bytes(data.data())).decode("ascii"),
                width=max(1, pixmap.width()),
                height=max(1, pixmap.height()),
            )
        )
    return entries


def package_entries(pet_id):
    """The distinct images the pet's own frame uses, as "pkg:" entries."""
    style = frame_style_for(pet_id)
    frame = registered_frame(style)
    if frame is None:
        return []
    entries, seen = [], set()
    for layer in (*frame.backdrop, *frame.overlay):
        reference = layer.image and package_image_reference(style, layer.image)
        if not reference or reference in seen:
            continue
        seen.add(reference)
        name = reference.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        entries.append(image_entry(reference, name, "package", layer.image))
    return entries


def package_decor(pet_id):
    """The pet frame's layers as editable decor, or [] when one is a dot.

    Dot (circle) layers have no image, so a frame with them cannot be copied
    without losing part of it; packages draw dots as tinted image layers.
    """
    style = frame_style_for(pet_id)
    frame = registered_frame(style)
    if frame is None:
        return []
    layers: list[dict] = []
    for placement, group in (("back", frame.backdrop), ("front", frame.overlay)):
        for layer in group:
            reference = layer.image and package_image_reference(style, layer.image)
            if not reference:
                return []
            repeat, gap, inset = "none", 0.0, 0.0
            if layer.repeat_y is not None:
                repeat, gap, inset = (
                    "y",
                    layer.repeat_y.gap,
                    layer.repeat_y.bottom_inset,
                )
            elif layer.repeat_x is not None:
                repeat, gap, inset = "x", layer.repeat_x.gap, layer.repeat_x.right_inset
            layers.append(
                asdict(
                    DecorLayer(
                        id=f"pet-{len(layers) + 1}",
                        name=reference.rsplit("/", 1)[-1].rsplit(".", 1)[0],
                        image=reference,
                        placement=placement,
                        anchor=layer.anchor,
                        x=layer.x,
                        y=layer.y,
                        width=layer.width,
                        height=layer.height,
                        rotation=layer.rotation,
                        mirror=layer.mirror,
                        flip_y=layer.flip_y,
                        alpha=layer.alpha,
                        tint=layer.color,
                        repeat=repeat,
                        repeat_gap=gap,
                        repeat_inset=inset,
                    )
                )
            )
    return layers


def package_frame_values(pet_id, theme):
    """The pet frame's inner line, halo and text spacing as theme values.

    Color names such as "shadow" resolve against theme, the pet's own theme.
    """
    frame = registered_frame(frame_style_for(pet_id))
    if frame is None:
        return {}

    def color(reference):
        if reference in {"border", "shadow", "background", "text"}:
            reference = getattr(theme, reference)
        return QColor(reference).name(QColor.NameFormat.HexRgb)

    def bounded(key, value):
        low, high = BUBBLE_THEME_LIMITS[key]
        return min(max(value, low), high)

    values: dict[str, str | int | float | bool | None] = {}
    if frame.inner_border is not None:
        reference, alpha = frame.inner_border
        values.update(inner_border_color=color(reference), inner_border_alpha=alpha)
    if frame.halo is not None:
        halo = frame.halo
        values.update(
            halo_color=color(halo.color),
            halo_alpha=halo.alpha,
            halo_width=bounded("halo_width", halo.width),
            halo_offset_y=bounded("halo_offset_y", halo.offset_y),
            halo_grow=bounded("halo_grow", halo.grow),
        )
    if frame.content_padding is not None:
        top, bottom, left = frame.content_padding
        values.update(
            content_top=bounded("content_top", top),
            content_bottom=bounded("content_bottom", bottom),
            content_left=bounded("content_left", left),
        )
    return values
