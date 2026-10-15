"""Pattern and ornament painting for speech-bubble themes."""

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF


def paint_pattern(painter, path, rect, theme, registry=None, scale=1.0):
    """Paint a built-in or user-supplied pattern clipped to the bubble."""
    if theme.pattern == "none":
        return
    painter.save()
    painter.setClipPath(path)
    color = QColor(theme.border)
    color.setAlpha(24)
    painter.setPen(QPen(color, max(1.0, scale)))
    spacing = max(12, round(20 * scale))
    if theme.pattern.startswith("user:") and registry is not None:
        pixmap = registry.pixmap(theme.pattern)
        if not pixmap.isNull():
            tile = max(18, round(28 * scale))
            pixmap = pixmap.scaled(
                tile,
                tile,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            for y in range(round(rect.top()), round(rect.bottom()) + tile, tile):
                for x in range(round(rect.left()), round(rect.right()) + tile, tile):
                    painter.setOpacity(0.16)
                    painter.drawPixmap(x, y, pixmap)
            painter.setOpacity(1.0)
        painter.restore()
        return
    for y in range(round(rect.top()) + spacing, round(rect.bottom()), spacing):
        for x in range(round(rect.left()) + spacing, round(rect.right()), spacing):
            if theme.pattern == "dots":
                painter.setBrush(color)
                painter.drawEllipse(QPointF(x, y), 1.5 * scale, 1.5 * scale)
            elif theme.pattern == "stars":
                _draw_star(painter, QPointF(x, y), 3.0 * scale, color)
    if theme.pattern == "grid":
        for x in range(round(rect.left()) + spacing, round(rect.right()), spacing):
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
        for y in range(round(rect.top()) + spacing, round(rect.bottom()), spacing):
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
    painter.restore()


def _user_pixmap(registry, reference):
    if registry is None or not str(reference).startswith("user:"):
        return None
    pixmap = registry.pixmap(reference)
    return None if pixmap.isNull() else pixmap


def paint_background_image(painter, path, rect, theme, registry=None):
    """Cover the bubble with the user's photo, cropped around its focus point.

    It is drawn over the bubble color at the theme's opacity, so the color
    shows through and keeps text readable on busy photos.
    """
    pixmap = _user_pixmap(registry, theme.background_image)
    if pixmap is None:
        return
    cover = max(rect.width() / pixmap.width(), rect.height() / pixmap.height())
    zoom = cover * theme.background_zoom / 100
    width, height = pixmap.width() * zoom, pixmap.height() * zoom
    x = rect.left() - (width - rect.width()) * theme.background_focus_x / 100
    y = rect.top() - (height - rect.height()) * theme.background_focus_y / 100
    painter.save()
    painter.setClipPath(path)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.setOpacity(theme.background_opacity / 100)
    painter.drawPixmap(QRectF(x, y, width, height), pixmap, QRectF(pixmap.rect()))
    painter.restore()


def paint_frame_image(painter, rect, theme, registry=None, scale=1.0):
    """Stretch a 9-slice frame image over the bubble; False when there is none.

    The corners keep their size, the edges stretch along one axis and the
    middle stretches both ways.
    """
    pixmap = _user_pixmap(registry, theme.frame_image)
    if pixmap is None:
        return False
    source = max(1, min(theme.frame_slice, pixmap.width() // 2, pixmap.height() // 2))
    target = max(
        1.0, min(theme.frame_slice * scale, rect.width() / 2, rect.height() / 2)
    )
    sx = (0, source, pixmap.width() - source, pixmap.width())
    sy = (0, source, pixmap.height() - source, pixmap.height())
    tx = (rect.left(), rect.left() + target, rect.right() - target, rect.right())
    ty = (rect.top(), rect.top() + target, rect.bottom() - target, rect.bottom())
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    for row in range(3):
        for column in range(3):
            painter.drawPixmap(
                QRectF(
                    tx[column],
                    ty[row],
                    tx[column + 1] - tx[column],
                    ty[row + 1] - ty[row],
                ),
                pixmap,
                QRectF(
                    sx[column],
                    sy[row],
                    sx[column + 1] - sx[column],
                    sy[row + 1] - sy[row],
                ),
            )
    painter.restore()
    return True


def paint_stickers(painter, rect, theme, registry=None, scale=1.0):
    """Up to three user stickers placed by percent of the bubble body."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    for slot in (1, 2, 3):
        pixmap = _user_pixmap(registry, getattr(theme, f"sticker_{slot}"))
        if pixmap is None:
            continue
        box = getattr(theme, f"sticker_{slot}_size") * scale
        fit = min(box / pixmap.width(), box / pixmap.height())
        width, height = pixmap.width() * fit, pixmap.height() * fit
        center_x = (
            rect.left() + rect.width() * getattr(theme, f"sticker_{slot}_x") / 100
        )
        center_y = (
            rect.top() + rect.height() * getattr(theme, f"sticker_{slot}_y") / 100
        )
        painter.drawPixmap(
            QRectF(center_x - width / 2, center_y - height / 2, width, height),
            pixmap,
            QRectF(pixmap.rect()),
        )
    painter.restore()


def paint_ornaments(painter, rect, theme, registry=None, scale=1.0):
    """Paint the theme's built-in or user-supplied corner ornaments."""
    size = 24 * scale * theme.ornament_scale / 100
    left = QPointF(rect.left() + 18 * scale, rect.top() + 13 * scale)
    right = QPointF(rect.right() - 18 * scale, rect.top() + 13 * scale)
    seen_center = False
    for reference, center, mirror in (
        (theme.ornament_left, left, False),
        (theme.ornament_right, right, True),
    ):
        if reference == "none":
            continue
        if reference.startswith("user:") and registry is not None:
            pixmap = registry.pixmap(reference)
            if not pixmap.isNull():
                target = QRectF(
                    center.x() - size / 2,
                    center.y() - size / 2,
                    size,
                    size,
                )
                painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))
            continue
        if reference == "goggles":
            if not seen_center:
                _draw_builtin_ornament(
                    painter,
                    QPointF(rect.center().x(), rect.top() + 12 * scale),
                    reference,
                    theme,
                    size,
                    False,
                )
                seen_center = True
            continue
        _draw_builtin_ornament(painter, center, reference, theme, size, mirror)


def _draw_builtin_ornament(painter, center, kind, theme, size, mirror):
    painter.save()
    painter.translate(center)
    if mirror:
        painter.scale(-1, 1)
    unit = size / 24.0
    border = QColor(theme.border)
    fill = QColor(theme.fill_end if theme.gradient != "solid" else theme.background)
    accent = QColor(theme.border).lighter(135)
    painter.setPen(
        QPen(
            border,
            max(1.2, 1.5 * unit),
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
    )
    painter.setBrush(fill)
    if kind == "cat-ear":
        path = QPainterPath()
        path.moveTo(-9 * unit, 5 * unit)
        path.lineTo(-6 * unit, -11 * unit)
        path.lineTo(5 * unit, 2 * unit)
        path.closeSubpath()
        painter.drawPath(path)
        painter.setBrush(accent)
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(-6 * unit, -6 * unit),
                    QPointF(-5 * unit, 0),
                    QPointF(0, 1 * unit),
                ]
            )
        )
    elif kind == "small-wing":
        path = QPainterPath()
        path.moveTo(-8 * unit, 5 * unit)
        path.cubicTo(-13 * unit, 0, -10 * unit, -8 * unit, -2 * unit, -4 * unit)
        path.cubicTo(-8 * unit, -2 * unit, -5 * unit, 5 * unit, 2 * unit, 2 * unit)
        path.cubicTo(-3 * unit, 8 * unit, 2 * unit, 9 * unit, 7 * unit, 3 * unit)
        painter.drawPath(path)
    elif kind == "horn":
        path = QPainterPath()
        path.moveTo(-7 * unit, 5 * unit)
        path.cubicTo(-12 * unit, -6 * unit, -5 * unit, -12 * unit, 2 * unit, -9 * unit)
        path.cubicTo(-4 * unit, -5 * unit, -1 * unit, 1 * unit, 6 * unit, 3 * unit)
        path.closeSubpath()
        painter.setBrush(accent)
        painter.drawPath(path)
    elif kind == "bat-wing":
        path = QPainterPath()
        path.moveTo(7 * unit, 5 * unit)
        path.lineTo(-1 * unit, -8 * unit)
        path.lineTo(-4 * unit, -1 * unit)
        path.lineTo(-10 * unit, -5 * unit)
        path.lineTo(-8 * unit, 4 * unit)
        path.lineTo(-2 * unit, 2 * unit)
        path.closeSubpath()
        painter.setBrush(accent)
        painter.drawPath(path)
    elif kind == "star":
        _draw_star(painter, QPointF(), 9 * unit, accent)
    elif kind == "sparkle":
        painter.setBrush(accent)
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(0, -10 * unit),
                    QPointF(2 * unit, -2 * unit),
                    QPointF(9 * unit, 0),
                    QPointF(2 * unit, 2 * unit),
                    QPointF(0, 10 * unit),
                    QPointF(-2 * unit, 2 * unit),
                    QPointF(-9 * unit, 0),
                    QPointF(-2 * unit, -2 * unit),
                ]
            )
        )
    elif kind == "ribbon":
        painter.drawEllipse(QRectF(-8 * unit, -5 * unit, 8 * unit, 8 * unit))
        painter.drawEllipse(QRectF(0, -5 * unit, 8 * unit, 8 * unit))
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(-2 * unit, 1 * unit),
                    QPointF(-6 * unit, 10 * unit),
                    QPointF(0, 7 * unit),
                    QPointF(2 * unit, 1 * unit),
                ]
            )
        )
    elif kind == "goggles":
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QRectF(-13 * unit, -5 * unit, 11 * unit, 8 * unit))
        painter.drawEllipse(QRectF(2 * unit, -5 * unit, 11 * unit, 8 * unit))
        painter.drawLine(QPointF(-2 * unit, -1 * unit), QPointF(2 * unit, -1 * unit))
    elif kind == "magnet":
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(
            QPen(
                accent,
                max(3.0, 5 * unit),
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
            )
        )
        arc = QRectF(-8 * unit, -8 * unit, 16 * unit, 17 * unit)
        painter.drawArc(arc, 0, -180 * 16)
    painter.restore()


def _draw_star(painter, center, radius, color):
    points = []
    for index in range(10):
        angle = -math.pi / 2 + index * math.pi / 5
        length = radius if index % 2 == 0 else radius * 0.42
        points.append(
            QPointF(
                center.x() + math.cos(angle) * length,
                center.y() + math.sin(angle) * length,
            )
        )
    painter.save()
    painter.setPen(QPen(color, 1.0))
    painter.setBrush(color)
    painter.drawPolygon(QPolygonF(points))
    painter.restore()
