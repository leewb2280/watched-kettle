"""Shared geometry and surface painting for speech bubbles."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QLinearGradient,
    QPainterPath,
    QPen,
    QPolygonF,
)

from watched_kettle.ui.speech_bubble_decorations import (
    paint_background_image,
    paint_frame_image,
    paint_ornaments,
    paint_pattern,
    paint_stickers,
)
from watched_kettle.ui import speech_bubble_frame as frames


def build_body_path(rect, theme, scale=1.0):
    rect = QRectF(rect)
    path = QPainterPath()
    radius = min(
        float(theme.radius) * scale,
        rect.height() / 2,
        rect.width() / 2,
    )
    if theme.shape == "tech":
        cut = min(14.0, rect.height() / 4)
        path.addPolygon(
            QPolygonF(
                [
                    QPointF(rect.left() + cut, rect.top()),
                    QPointF(rect.right() - cut, rect.top()),
                    QPointF(rect.right(), rect.top() + cut),
                    QPointF(rect.right(), rect.bottom() - cut),
                    QPointF(rect.right() - cut, rect.bottom()),
                    QPointF(rect.left() + cut, rect.bottom()),
                    QPointF(rect.left(), rect.bottom() - cut),
                    QPointF(rect.left(), rect.top() + cut),
                ]
            )
        )
        path.closeSubpath()
    elif theme.shape == "jelly":
        left, top, right, bottom = (
            rect.left(),
            rect.top(),
            rect.right(),
            rect.bottom(),
        )
        path.moveTo(left + radius * 1.3, top)
        path.cubicTo(
            right * 0.42 + left * 0.58,
            top - 2,
            right - radius,
            top,
            right,
            top + radius,
        )
        path.cubicTo(
            right + 2,
            bottom * 0.46 + top * 0.54,
            right,
            bottom - radius * 0.7,
            right - radius,
            bottom,
        )
        path.cubicTo(
            right * 0.64 + left * 0.36,
            bottom + 2,
            left + radius,
            bottom,
            left,
            bottom - radius,
        )
        path.cubicTo(
            left - 2,
            top * 0.48 + bottom * 0.52,
            left,
            top + radius,
            left + radius * 1.3,
            top,
        )
        path.closeSubpath()
    elif theme.shape == "comic":
        notch = min(9.0, rect.height() / 6)
        path.moveTo(rect.left() + radius, rect.top())
        path.lineTo(rect.right() - radius - notch, rect.top())
        path.quadTo(rect.right(), rect.top(), rect.right(), rect.top() + radius)
        path.lineTo(rect.right(), rect.bottom() - radius)
        path.quadTo(rect.right(), rect.bottom(), rect.right() - radius, rect.bottom())
        path.lineTo(rect.left() + radius + notch, rect.bottom())
        path.quadTo(rect.left(), rect.bottom(), rect.left(), rect.bottom() - radius)
        path.lineTo(rect.left(), rect.top() + radius)
        path.quadTo(rect.left(), rect.top(), rect.left() + radius, rect.top())
        path.closeSubpath()
    elif theme.shape == "cloud":
        body = QRectF(rect).adjusted(0, 5, 0, 0)
        path.addRoundedRect(body, radius, radius)
        lump_width = max(20.0, rect.width() / 4.8)
        centers = (0.20, 0.40, 0.61, 0.80)
        for index, ratio in enumerate(centers):
            size = lump_width * (1.12 if index in {1, 2} else 0.92)
            center_x = rect.left() + rect.width() * ratio
            ellipse = QRectF(
                center_x - size / 2,
                rect.top(),
                size,
                min(size * 0.72, rect.height() * 0.46),
            )
            lump = QPainterPath()
            lump.addEllipse(ellipse)
            path = path.united(lump)
    else:
        path.addRoundedRect(rect, radius, radius)
    return path


def build_tail_path(body_rect, outer_rect, side, theme, half_base=15):
    if theme.tail == "none":
        return None
    if side not in {"top", "bottom", "left", "right"}:
        return None
    body = QRectF(body_rect)
    outer = QRectF(outer_rect)
    half = float(half_base)
    tail = QPainterPath()

    if side in {"top", "bottom"}:
        center = body.center().x()
        edge = body.top() + 1 if side == "top" else body.bottom() - 1
        tip = outer.top() + 1 if side == "top" else outer.bottom() - 1
        sign = -1 if side == "top" else 1
        _vertical_tail(tail, center, edge, tip, sign, half, theme.tail)
    else:
        center = body.center().y()
        edge = body.left() + 1 if side == "left" else body.right() - 1
        tip = outer.left() + 1 if side == "left" else outer.right() - 1
        sign = -1 if side == "left" else 1
        _horizontal_tail(tail, center, edge, tip, sign, half, theme.tail)
    tail.closeSubpath()
    return tail


def bubble_frame_insets(theme, scale=1.0):
    return frames.frame_insets(theme, scale)


def paint_bubble_backdrop(painter, body_rect, theme, scale=1.0):
    frames.paint_frame_backdrop(painter, body_rect, theme, scale)


def paint_bubble_surface(
    painter,
    path,
    body_rect,
    theme,
    registry=None,
    decorations=True,
    scale=1.0,
):
    painter.save()
    if theme.glow:
        glow = QColor(theme.border)
        glow.setAlpha(52)
        painter.setPen(QPen(glow, max(4.0, theme.border_width * 5 * scale)))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

    painter.fillPath(path, theme_brush(body_rect, theme))
    paint_background_image(painter, path, body_rect, theme, registry)
    paint_pattern(painter, path, body_rect, theme, registry, scale)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(
        QPen(
            QColor(theme.border),
            max(1.0, theme.border_width * scale),
        )
    )
    # A user frame image replaces the drawn border.
    if not paint_frame_image(painter, body_rect, theme, registry, scale):
        painter.drawPath(path)

    if theme.border_style == "double":
        inner_rect = QRectF(body_rect).adjusted(
            4 * scale, 4 * scale, -4 * scale, -4 * scale
        )
        inner = build_body_path(inner_rect, theme, scale)
        color = frames.inner_border(theme)
        painter.setPen(QPen(color, max(1.0, scale)))
        painter.drawPath(inner)
    elif theme.border_style == "accent":
        accent = QColor(theme.border)
        accent.setAlpha(180)
        y = body_rect.top() + 5 * scale
        painter.setPen(
            QPen(
                accent,
                max(2.0, 2.4 * scale),
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
            )
        )
        painter.drawLine(
            QPointF(body_rect.left() + 18 * scale, y),
            QPointF(body_rect.right() - 18 * scale, y),
        )

    if decorations:
        paint_ornaments(painter, body_rect, theme, registry, scale)
        paint_stickers(painter, body_rect, theme, registry, scale)
    frames.paint_frame_overlay(painter, body_rect, theme, scale)
    painter.restore()


def theme_brush(rect, theme):
    start = QColor(theme.background)
    end = QColor(theme.fill_end)
    start.setAlpha(theme.fill_opacity)
    end.setAlpha(theme.fill_opacity)
    if theme.gradient == "vertical":
        gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    elif theme.gradient == "horizontal":
        gradient = QLinearGradient(rect.topLeft(), rect.topRight())
    else:
        return QBrush(start)
    gradient.setColorAt(0.0, start)
    gradient.setColorAt(1.0, end)
    return QBrush(gradient)


def _vertical_tail(path, center, edge, tip, sign, half, style):
    left = center - half
    right = center + half
    if style == "curved":
        path.moveTo(left, edge)
        path.cubicTo(
            center - half * 0.15,
            edge + sign * half * 0.25,
            center - half * 0.45,
            tip - sign * 2,
            center + half * 0.15,
            tip,
        )
        path.cubicTo(
            center + half * 0.55,
            tip - sign * 2,
            center + half * 0.35,
            edge + sign * half * 0.3,
            right,
            edge,
        )
    elif style == "stub":
        short_tip = edge + (tip - edge) * 0.62
        path.moveTo(center - half * 0.75, edge)
        path.quadTo(center, short_tip + sign * 2, center + half * 0.75, edge)
    elif style == "angular":
        path.moveTo(left, edge)
        path.lineTo(center - half * 0.15, edge + (tip - edge) * 0.46)
        path.lineTo(center + half * 0.18, edge + (tip - edge) * 0.32)
        path.lineTo(center, tip)
        path.lineTo(right, edge)
    elif style == "droplet":
        path.moveTo(center - half * 0.68, edge)
        path.cubicTo(
            center - half * 0.35,
            edge + (tip - edge) * 0.48,
            center - half * 0.18,
            tip,
            center,
            tip,
        )
        path.cubicTo(
            center + half * 0.18,
            tip,
            center + half * 0.35,
            edge + (tip - edge) * 0.48,
            center + half * 0.68,
            edge,
        )
    else:
        path.moveTo(left, edge)
        path.lineTo(center, tip)
        path.lineTo(right, edge)


def _horizontal_tail(path, center, edge, tip, sign, half, style):
    top = center - half
    bottom = center + half
    if style == "curved":
        path.moveTo(edge, top)
        path.cubicTo(
            edge + sign * half * 0.25,
            center - half * 0.15,
            tip - sign * 2,
            center - half * 0.45,
            tip,
            center + half * 0.15,
        )
        path.cubicTo(
            tip - sign * 2,
            center + half * 0.55,
            edge + sign * half * 0.3,
            center + half * 0.35,
            edge,
            bottom,
        )
    elif style == "stub":
        short_tip = edge + (tip - edge) * 0.62
        path.moveTo(edge, center - half * 0.75)
        path.quadTo(short_tip + sign * 2, center, edge, center + half * 0.75)
    elif style == "angular":
        path.moveTo(edge, top)
        path.lineTo(edge + (tip - edge) * 0.46, center - half * 0.15)
        path.lineTo(edge + (tip - edge) * 0.32, center + half * 0.18)
        path.lineTo(tip, center)
        path.lineTo(edge, bottom)
    elif style == "droplet":
        path.moveTo(edge, center - half * 0.68)
        path.cubicTo(
            edge + (tip - edge) * 0.48,
            center - half * 0.35,
            tip,
            center - half * 0.18,
            tip,
            center,
        )
        path.cubicTo(
            tip,
            center + half * 0.18,
            edge + (tip - edge) * 0.48,
            center + half * 0.35,
            edge,
            center + half * 0.68,
        )
    else:
        path.moveTo(edge, top)
        path.lineTo(tip, center)
        path.lineTo(edge, bottom)
