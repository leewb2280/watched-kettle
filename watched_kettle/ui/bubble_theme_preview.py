"""Previews used by the speech-bubble customizer."""

from typing import Any
from watched_kettle.localization import t

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QRegion
from PySide6.QtWidgets import QWidget

from watched_kettle.ui.speech_bubble_decorations import background_image_rect
from watched_kettle.ui.speech_bubble_frame import anchor_point
from watched_kettle.ui.speech_bubble_paint import (
    bubble_frame_insets,
    build_body_path,
    build_tail_path,
    paint_bubble_backdrop,
    paint_bubble_surface,
)
from watched_kettle.ui.speech_bubble_window import SpeechBubbleWindow


PREVIEW_SAMPLES = ("notice", "long", "project")
# Rendered at twice the size so the editor stays sharp on high-DPI screens
# and when zoomed in.
PREVIEW_PIXEL_RATIO = 2
PROJECT_BODY_HEIGHT = 150


def render_bubble_preview(theme, registry, sample="notice"):
    """Draw a sample at the real 100% size; return (image, geometry).

    Notices use the real bubble window, so size, text and decorations match the
    desktop. The project sample is the card drawn by BubbleThemePreview at the
    theme's maximum width. Geometry is in 100% pixels of the image.
    """
    if sample == "project":
        widget: Any = BubbleThemePreview(registry, sample="project")
        left, top, right, bottom = bubble_frame_insets(theme)
        widget.setMinimumSize(0, 0)
        widget.resize(
            round(theme.maximum_width + left + right + 36),
            round(PROJECT_BODY_HEIGHT + top + bottom + 52),
        )
        widget.set_theme(theme)
        owner: QWidget = widget
    else:
        owner = _PreviewHost()
        widget = SpeechBubbleWindow(owner, theme=theme, element_registry=registry)
        widget.set_tail_side("bottom")
        text = t("bubble.editor.sample_long" if sample == "long" else "message.0253")
        widget.set_message(text, kind="done")
        widget.adjustSize()
    try:
        size = widget.size()
        image = QImage(
            size.width() * PREVIEW_PIXEL_RATIO,
            size.height() * PREVIEW_PIXEL_RATIO,
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.scale(PREVIEW_PIXEL_RATIO, PREVIEW_PIXEL_RATIO)
        widget.render(painter, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
        painter.end()
        return image, preview_geometry(theme, widget.body_rect(), size, registry)
    finally:
        owner.deleteLater()


def preview_geometry(theme, body, size, registry=None):
    """Body, photo and decoration boxes so the editor can draw handles."""
    layers = []
    for layer in theme.decor:
        anchor = anchor_point(body, theme, layer.anchor)
        layers.append(
            dict(
                id=layer.id,
                x=anchor.x() + layer.x,
                y=anchor.y() + layer.y,
                width=layer.width,
                height=layer.height,
                rotation=layer.rotation,
                anchorX=anchor.x(),
                anchorY=anchor.y(),
            )
        )
    return dict(
        width=size.width(),
        height=size.height(),
        body=dict(
            x=body.left(), y=body.top(), width=body.width(), height=body.height()
        ),
        background=_background_box(theme, body, registry),
        layers=layers,
    )


def _background_box(theme, body, registry):
    """The background photo's box, or None when there is none or it is tiled."""
    if registry is None or theme.background_image == "none":
        return None
    pixmap = registry.pixmap(theme.background_image)
    if pixmap.isNull():
        return None
    box = background_image_rect(pixmap.width(), pixmap.height(), body, theme)
    if box is None:
        return None
    return dict(x=box.left(), y=box.top(), width=box.width(), height=box.height())


class _PreviewHost(QWidget):
    """Stand-in pet for a bubble window that is laid out but never shown."""

    always_on_top = False


class BubbleThemePreview(QWidget):
    """Render an isolated sample without changing the active pet theme."""

    def __init__(self, registry, parent=None, sample="notice"):
        super().__init__(parent)
        self.registry = registry
        self.theme: Any = None
        # "notice": a short notification; "project": a project card with rows.
        self.sample = sample
        self.setMinimumSize(460, 205)

    def set_theme(self, theme):
        self.theme = theme
        self.update()

    def body_rect(self):
        body = QRectF(18, 16, self.width() - 36, self.height() - 52)
        left, top, right, bottom = bubble_frame_insets(self.theme)
        return body.adjusted(left, top, -right, -bottom)

    def paintEvent(self, event):
        del event
        if self.theme is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        outer = QRectF(18, 16, self.width() - 36, self.height() - 32)
        body = self.body_rect()
        path = build_body_path(body, self.theme)
        tail = build_tail_path(body, outer, "bottom", self.theme, half_base=15)
        if tail is not None:
            path = path.united(tail)
        paint_bubble_backdrop(painter, body, self.theme, registry=self.registry)
        shadow = QPainterPath(path)
        shadow.translate(0, 3)
        shadow_color = QColor(self.theme.shadow)
        shadow_color.setAlpha(self.theme.shadow_alpha)
        painter.fillPath(shadow, shadow_color)
        paint_bubble_surface(
            painter,
            path,
            body,
            self.theme,
            registry=self.registry,
            decorations=True,
        )
        self._paint_sample_text(painter, body)

    def _paint_sample_text(self, painter, body):
        if self.sample == "project":
            self._paint_project_sample(painter, body)
            return
        painter.save()
        if self.theme.header_style == "none":
            font = QFont(self.font())
            font.setPointSizeF(max(10.0, self.font().pointSizeF()))
            font.setBold(self.theme.text_bold)
            painter.setFont(font)
            painter.setPen(QColor(self.theme.text))
            message_rect = QRectF(body).adjusted(36, 22, -36, -18)
            painter.drawText(
                message_rect,
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                t("message.0253"),
            )
            painter.restore()
            return
        header_rect = QRectF(
            body.left() + 42,
            body.top() + 28,
            126,
            25,
        )
        if self.theme.header_style == "panel":
            header_rect.setWidth(150)
        radius = {
            "capsule": 11,
            "tab": 5,
            "ribbon": 2,
            "panel": 1,
        }.get(self.theme.header_style, 7)
        painter.setBrush(QColor("#f1f8f3"))
        painter.setPen(QPen(QColor("#3f684b"), 1))
        painter.drawRoundedRect(header_rect, radius, radius)
        font = QFont(self.font())
        font.setPointSizeF(max(8.0, font.pointSizeF() - 1))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#3f684b"))
        painter.drawText(
            header_rect,
            Qt.AlignmentFlag.AlignCenter,
            t("message.0252"),
        )
        font.setPointSizeF(max(10.0, self.font().pointSizeF()))
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(QColor(self.theme.text))
        message_rect = QRectF(body).adjusted(36, 64, -36, -20)
        painter.drawText(
            message_rect,
            Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
            t("message.0253"),
        )
        painter.restore()

    def _paint_project_sample(self, painter, body):
        """A project card: folder capsule, summary and two conversation rows."""
        painter.save()
        font = QFont(self.font())
        font.setPointSizeF(max(8.0, font.pointSizeF() - 1))
        font.setBold(True)
        painter.setFont(font)
        # Positions follow the body width so narrow real-size cards fit.
        inset = min(36.0, body.width() * 0.07)
        header = QRectF(
            body.left() + inset, body.top() + 26, min(120.0, body.width() * 0.4), 24
        )
        painter.setBrush(QColor("#eef1f4"))
        painter.setPen(QPen(QColor("#8a94a0"), 1))
        painter.drawRoundedRect(header, 11, 11)
        painter.setPen(QColor("#3c4650"))
        painter.drawText(header, Qt.AlignmentFlag.AlignCenter, "watched-kettle")
        font.setBold(self.theme.text_bold)
        font.setPointSizeF(max(10.0, self.font().pointSizeF()))
        painter.setFont(font)
        painter.setPen(QColor(self.theme.text))
        summary = QRectF(
            header.right() + 10,
            header.top(),
            max(0.0, body.right() - inset - header.right() - 10),
            header.height(),
        )
        painter.drawText(
            summary,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            painter.fontMetrics().elidedText(
                t("message.0254"), Qt.TextElideMode.ElideRight, round(summary.width())
            ),
        )
        rows = (
            (t("message.0255"), t("status.attention"), "#fcefc8", "#7a5410"),
            (t("message.0256"), t("message.0257"), "#e3edf7", "#2f5c86"),
        )
        top = header.bottom() + 14
        badge_width = min(96.0, body.width() * 0.3)
        for title, state, fill, ink in rows:
            painter.setPen(QColor(self.theme.text))
            title_rect = QRectF(
                body.left() + inset + 4,
                top,
                max(0.0, body.width() - 2 * inset - badge_width - 12),
                24,
            )
            painter.drawText(
                title_rect,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                painter.fontMetrics().elidedText(
                    title, Qt.TextElideMode.ElideRight, round(title_rect.width())
                ),
            )
            badge = QRectF(body.right() - inset - badge_width, top + 1, badge_width, 22)
            painter.setBrush(QColor(fill))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(badge, 6, 6)
            painter.setPen(QColor(ink))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, state)
            top += 30
        painter.restore()
