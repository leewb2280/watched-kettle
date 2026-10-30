"""Paint outer bubble decorations: the pet frame (``pet/bubble_frame.py``)
and the user's decoration layers (``pet/bubble_decor.py``)."""

from functools import lru_cache
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap

from watched_kettle.pet.bubble_decor import (
    decor_overflow,
    frame_layers,
    ornament_kind,
)
from watched_kettle.ui.speech_bubble_decorations import ornament_pixmap
from watched_kettle.pet.bubble_frame import (
    MAX_FRAME_REPEATS,
    FrameHalo,
    registered_frame,
)


# Smallest body height a bubble gets; decoration overflow is measured on the
# smallest body so a growing bubble never needs more canvas.
MIN_BODY_HEIGHT = 40.0


def frame_insets(theme, scale=1.0):
    """Extra canvas the frame and decoration layers need around the body."""
    frame = registered_frame(theme.frame_style)
    insets = frame.insets if frame is not None else (0.0, 0.0, 0.0, 0.0)
    if theme.decor:
        width = max(48.0, theme.minimum_width - insets[0] - insets[2])
        overflow = decor_overflow(theme.decor, width, MIN_BODY_HEIGHT, theme.radius)
        insets = tuple(max(a, b) for a, b in zip(insets, overflow))
    halo = theme_halo(theme)
    if theme.halo_custom and halo is not None:
        # A pet frame's own insets already cover its halo.
        insets = tuple(max(a, b) for a, b in zip(insets, halo_reach(halo)))
    return tuple(value * float(scale) for value in insets)


def halo_reach(halo):
    """(left, top, right, bottom) a halo draws outside the body, in pixels.

    The stroke's outer half, its growth and offset, and a pixel of
    antialiasing.
    """
    reach = halo.grow + max(halo.min_width, halo.width) / 2 + 1
    return tuple(
        float(math.ceil(max(0.0, value)))
        for value in (reach, reach - halo.offset_y, reach, reach + halo.offset_y)
    )


def content_padding(theme, top, bottom):
    """Return (top, bottom, extra left) content padding in unscaled pixels."""
    if theme.content_custom:
        return (theme.content_top, theme.content_bottom, theme.content_left)
    frame = registered_frame(theme.frame_style)
    if frame is None or frame.content_padding is None:
        return (top, bottom, 0)
    return frame.content_padding


def theme_halo(theme):
    """The halo drawn around the body: the theme's own, or the pet frame's."""
    if theme.halo_custom:
        if theme.halo_width <= 0:
            return None
        return FrameHalo(
            color=theme.halo_color,
            alpha=theme.halo_alpha,
            width=theme.halo_width,
            min_width=1.0,
            offset_y=theme.halo_offset_y,
            grow=theme.halo_grow,
            # Corners round out as the line grows away from the body.
            radius_delta=theme.halo_grow,
        )
    frame = registered_frame(theme.frame_style)
    return frame.halo if frame is not None else None


def inner_border(theme):
    """Color of the inner line drawn by the double border style."""
    if theme.inner_border_custom:
        color = QColor(theme.inner_border_color)
        color.setAlpha(theme.inner_border_alpha)
        return color
    frame = registered_frame(theme.frame_style)
    if frame is not None and frame.inner_border is not None:
        color_ref, alpha = frame.inner_border
        color = _resolve_color(color_ref, theme)
        color.setAlpha(alpha)
        return color
    color = QColor(theme.border)
    color.setAlpha(115)
    return color


def paint_frame_backdrop(painter, rect, theme, scale=1.0, registry=None):
    """Paint the halo and layers that sit behind the bubble surface."""
    halo = theme_halo(theme)
    if halo is not None:
        _paint_halo(painter, rect, theme, halo, scale)
    frame = registered_frame(theme.frame_style)
    if frame is not None and theme.package_layers:
        _paint_layers(painter, rect, theme, frame.backdrop, scale)
    _paint_layers(
        painter, rect, theme, frame_layers(theme.decor, registry, "back"), scale
    )


def paint_frame_overlay(painter, rect, theme, scale=1.0, registry=None):
    """Paint the layers drawn over the finished bubble surface."""
    frame = registered_frame(theme.frame_style)
    if frame is not None and theme.package_layers:
        _paint_layers(painter, rect, theme, frame.overlay, scale)
    _paint_layers(
        painter, rect, theme, frame_layers(theme.decor, registry, "front"), scale
    )


def _paint_halo(painter, rect, theme, halo, scale):
    expanded = (
        QRectF(rect)
        .translated(0, halo.offset_y * scale)
        .adjusted(
            -halo.grow * scale,
            -halo.grow * scale,
            halo.grow * scale,
            halo.grow * scale,
        )
    )
    radius = min(expanded.height() / 2, (theme.radius + halo.radius_delta) * scale)
    path = QPainterPath()
    path.addRoundedRect(expanded, radius, radius)
    color = _resolve_color(halo.color, theme)
    color.setAlpha(halo.alpha)
    painter.save()
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(
        QPen(
            color,
            max(halo.min_width, halo.width * scale),
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
    )
    painter.drawPath(path)
    painter.restore()


def _paint_layers(painter, rect, theme, layers, scale):
    for layer in layers:
        anchor = anchor_point(rect, theme, layer.anchor, scale)
        origin = QPointF(anchor.x() + layer.x * scale, anchor.y() + layer.y * scale)
        if layer.circle_radius:
            color = _resolve_color(layer.color, theme)
            color.setAlpha(layer.alpha)
            painter.save()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            radius = layer.circle_radius * scale
            painter.drawEllipse(origin, radius, radius)
            painter.restore()
            continue
        if layer.repeat_y is not None:
            _paint_repeated_image(painter, rect, origin, theme, layer, scale)
        elif layer.repeat_x is not None:
            _paint_repeated_row(painter, rect, origin, theme, layer, scale)
        else:
            _paint_image(painter, origin, theme, layer, scale)


def _repeat_range(start, origin, end, size, step, scale):
    """First index and count of whole tiles from origin that fit in start..end."""
    if (
        scale <= 0
        or size <= 0
        or step <= 0
        or not all(
            math.isfinite(value) for value in (scale, size, step, start, end, origin)
        )
    ):
        return 0, 0
    # Subpixel scaling must not lose a complete tile exactly on a boundary.
    tolerance = 1e-7 * scale
    first = max(0, math.ceil((start - origin - tolerance) / step))
    last = math.floor((end - origin - size + tolerance) / step)
    return first, min(MAX_FRAME_REPEATS, max(0, last - first + 1))


def _paint_repeated_image(painter, rect, origin, theme, layer, scale):
    height = layer.height * scale
    step = (layer.height + layer.repeat_y.gap) * scale
    bottom = rect.bottom() - layer.repeat_y.bottom_inset * scale
    first, count = _repeat_range(rect.top(), origin.y(), bottom, height, step, scale)
    if not count:
        return
    painter.save()
    painter.setClipRect(rect, Qt.ClipOperation.IntersectClip)
    for index in range(first, first + count):
        position = QPointF(origin.x(), origin.y() + index * step)
        _paint_image(painter, position, theme, layer, scale)
    painter.restore()


def _paint_repeated_row(painter, rect, origin, theme, layer, scale):
    width = layer.width * scale
    step = (layer.width + layer.repeat_x.gap) * scale
    right = rect.right() - layer.repeat_x.right_inset * scale
    first, count = _repeat_range(rect.left(), origin.x(), right, width, step, scale)
    if not count:
        return
    painter.save()
    # A row may sit above or below the body, so only the sides are clipped.
    band = QRectF(rect.left(), rect.top() - 100000, rect.width(), 200000)
    painter.setClipRect(band, Qt.ClipOperation.IntersectClip)
    for index in range(first, first + count):
        position = QPointF(origin.x() + index * step, origin.y())
        _paint_image(painter, position, theme, layer, scale)
    painter.restore()


def _paint_image(painter, origin, theme, layer, scale):
    kind = ornament_kind(layer.image)
    if layer.color:
        color = _resolve_color(layer.color, theme)
        if kind:
            pixmap = ornament_pixmap(kind, theme, color.name(), layer.alpha)
        else:
            pixmap = _tinted_pixmap(layer.image, color.name(), layer.alpha)
        opacity = 1.0
    else:
        pixmap = ornament_pixmap(kind, theme) if kind else _pixmap(layer.image)
        opacity = layer.alpha / 255
    if pixmap.isNull():
        return
    width, height = layer.width * scale, layer.height * scale
    if layer.keep_aspect:
        fit = min(width / pixmap.width(), height / pixmap.height())
        width, height = pixmap.width() * fit, pixmap.height() * fit
    center = QPointF(
        origin.x() + layer.width * scale / 2, origin.y() + layer.height * scale / 2
    )
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.setOpacity(painter.opacity() * opacity)
    painter.translate(center)
    if layer.rotation:
        painter.rotate(layer.rotation)
    if layer.mirror or layer.flip_y:
        painter.scale(-1 if layer.mirror else 1, -1 if layer.flip_y else 1)
    painter.drawPixmap(
        QRectF(-width / 2, -height / 2, width, height), pixmap, QRectF(pixmap.rect())
    )
    painter.restore()


def anchor_point(rect, theme, anchor, scale=1.0):
    if anchor == "arc-top-left":
        radius = min(theme.radius * scale, rect.height() / 2, rect.width() / 2)
        offset = radius * (1 - 2**-0.5)
        return QPointF(rect.left() + offset, rect.top() + offset)
    vertical, _, horizontal = anchor.partition("-")
    x = {
        "left": rect.left(),
        "center": rect.center().x(),
        "right": rect.right(),
    }[horizontal]
    y = {
        "top": rect.top(),
        "center": rect.center().y(),
        "bottom": rect.bottom(),
    }[vertical]
    return QPointF(x, y)


def _resolve_color(reference, theme):
    if reference in {"border", "shadow", "background", "text"}:
        return QColor(getattr(theme, reference))
    return QColor(reference)


@lru_cache(maxsize=64)
def _pixmap(path):
    return QPixmap(path)


@lru_cache(maxsize=64)
def _tinted_pixmap(path, color_name, alpha):
    image = QImage(path)
    if image.isNull():
        return QPixmap()
    image = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    color = QColor(color_name)
    color.setAlpha(alpha)
    painter = QPainter(image)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(image.rect(), color)
    painter.end()
    return QPixmap.fromImage(image)
