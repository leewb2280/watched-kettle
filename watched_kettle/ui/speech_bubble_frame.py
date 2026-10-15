"""Paint package-declared outer bubble decorations (``pet/bubble_frame.py``)."""

from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap

from watched_kettle.pet.bubble_frame import registered_frame


def frame_insets(theme, scale=1.0):
    """Extra canvas the frame needs around the bubble body."""
    frame = registered_frame(theme.frame_style)
    if frame is None:
        return (0.0, 0.0, 0.0, 0.0)
    return tuple(value * float(scale) for value in frame.insets)


def content_padding(theme, top, bottom):
    """Return (top, bottom, extra left) content padding in unscaled pixels."""
    frame = registered_frame(theme.frame_style)
    if frame is None or frame.content_padding is None:
        return (top, bottom, 0)
    return frame.content_padding


def inner_border(theme):
    """Color of the inner line drawn by the double border style."""
    frame = registered_frame(theme.frame_style)
    if frame is not None and frame.inner_border is not None:
        color_ref, alpha = frame.inner_border
        color = _resolve_color(color_ref, theme)
        color.setAlpha(alpha)
        return color
    color = QColor(theme.border)
    color.setAlpha(115)
    return color


def paint_frame_backdrop(painter, rect, theme, scale=1.0):
    """Paint the halo and layers that sit behind the bubble surface."""
    frame = registered_frame(theme.frame_style)
    if frame is None:
        return
    if frame.halo is not None:
        _paint_halo(painter, rect, theme, frame.halo, scale)
    _paint_layers(painter, rect, theme, frame.backdrop, scale)


def paint_frame_overlay(painter, rect, theme, scale=1.0):
    """Paint the layers drawn over the finished bubble surface."""
    frame = registered_frame(theme.frame_style)
    if frame is not None:
        _paint_layers(painter, rect, theme, frame.overlay, scale)


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
        anchor = _anchor_point(rect, theme, layer.anchor, scale)
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
        _paint_image(painter, origin, theme, layer, scale)


def _paint_image(painter, origin, theme, layer, scale):
    if layer.color:
        color = _resolve_color(layer.color, theme)
        pixmap = _tinted_pixmap(layer.image, color.name(), layer.alpha)
        opacity = 1.0
    else:
        pixmap = _pixmap(layer.image)
        opacity = layer.alpha / 255
    if pixmap.isNull():
        return
    target = QRectF(origin.x(), origin.y(), layer.width * scale, layer.height * scale)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.setOpacity(painter.opacity() * opacity)
    if layer.mirror:
        painter.translate(target.left() + target.right(), 0)
        painter.scale(-1, 1)
    painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))
    painter.restore()


def _anchor_point(rect, theme, anchor, scale):
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
