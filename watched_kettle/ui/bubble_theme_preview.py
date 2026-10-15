"""Live preview widget used by the speech-bubble customizer."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from watched_kettle.ui.speech_bubble_paint import (
    bubble_frame_insets,
    build_body_path,
    build_tail_path,
    paint_bubble_backdrop,
    paint_bubble_surface,
)


class BubbleThemePreview(QWidget):
    """Render an isolated sample without changing the active pet theme."""

    def __init__(self, registry, parent=None, sample="notice"):
        super().__init__(parent)
        self.registry = registry
        self.theme = None
        # "notice": a short notification; "project": a project card with rows.
        self.sample = sample
        self.setMinimumSize(460, 205)

    def set_theme(self, theme):
        self.theme = theme
        self.update()

    def paintEvent(self, event):
        del event
        if self.theme is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        outer = QRectF(18, 16, self.width() - 36, self.height() - 32)
        body = QRectF(outer).adjusted(0, 0, 0, -20)
        left, top, right, bottom = bubble_frame_insets(self.theme)
        body.adjust(left, top, -right, -bottom)
        path = build_body_path(body, self.theme)
        tail = build_tail_path(body, outer, "bottom", self.theme, half_base=15)
        if tail is not None:
            path = path.united(tail)
        paint_bubble_backdrop(painter, body, self.theme)
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
                "새로운 말풍선 디자인을 미리 확인해 보세요",
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
            "Codex · 작업 완료",
        )
        font.setPointSizeF(max(10.0, self.font().pointSizeF()))
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(QColor(self.theme.text))
        message_rect = QRectF(body).adjusted(36, 64, -36, -20)
        painter.drawText(
            message_rect,
            Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
            "새로운 말풍선 디자인을 미리 확인해 보세요",
        )
        painter.restore()

    def _paint_project_sample(self, painter, body):
        """A project card: folder capsule, summary and two conversation rows."""
        painter.save()
        font = QFont(self.font())
        font.setPointSizeF(max(8.0, font.pointSizeF() - 1))
        font.setBold(True)
        painter.setFont(font)
        header = QRectF(body.left() + 36, body.top() + 26, 120, 24)
        painter.setBrush(QColor("#eef1f4"))
        painter.setPen(QPen(QColor("#8a94a0"), 1))
        painter.drawRoundedRect(header, 11, 11)
        painter.setPen(QColor("#3c4650"))
        painter.drawText(header, Qt.AlignmentFlag.AlignCenter, "watched-kettle")
        font.setBold(self.theme.text_bold)
        font.setPointSizeF(max(10.0, self.font().pointSizeF()))
        painter.setFont(font)
        painter.setPen(QColor(self.theme.text))
        painter.drawText(
            QRectF(header.right() + 10, header.top(), 200, header.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            "확인 필요 1개 · 작업 중 1개",
        )
        rows = (
            ("화면 검수", "확인 필요", "#fcefc8", "#7a5410"),
            ("회귀 검사", "작업 중", "#e3edf7", "#2f5c86"),
        )
        top = header.bottom() + 14
        for title, state, fill, ink in rows:
            painter.setPen(QColor(self.theme.text))
            painter.drawText(
                QRectF(body.left() + 40, top, body.width() - 200, 24),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                title,
            )
            badge = QRectF(body.right() - 140, top + 1, 96, 22)
            painter.setBrush(QColor(fill))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(badge, 6, 6)
            painter.setPen(QColor(ink))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, state)
            top += 30
        painter.restore()
