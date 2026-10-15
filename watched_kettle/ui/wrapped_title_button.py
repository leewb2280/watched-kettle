"""Clickable plain-text titles fitted to at most two measured visual lines."""

from math import ceil

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextLayout, QTextOption
from PySide6.QtWidgets import QPushButton


def _title_layout(text, font):
    layout = QTextLayout(text, font)
    option = QTextOption()
    option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    layout.setTextOption(option)
    return layout


def title_text_width(text, font):
    """Reserve whole pixels without rounding a shaped line below its width."""
    layout = _title_layout(text, font)
    layout.beginLayout()
    line = layout.createLine()
    width = 0.0
    if line.isValid():
        line.setLineWidth(1_000_000_000)
        width = line.naturalTextWidth()
    layout.endLayout()
    return ceil(width)


class WrappedTitleButton(QPushButton):
    def set_title(self, text, width, padding=8, max_lines=2):
        self.setFixedWidth(width)
        available = max(1, width - padding)
        layout = _title_layout(text, self.font())
        layout.beginLayout()
        lines = []
        for _ in range(max_lines):
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(available)
            lines.append((line.textStart(), line.textLength()))
        overflow = layout.createLine().isValid()
        layout.endLayout()
        displayed = [text[start : start + length].strip() for start, length in lines]
        if overflow and lines:
            displayed[-1] = self.fontMetrics().elidedText(
                text[lines[-1][0] :], Qt.TextElideMode.ElideRight, available
            )
        self.setText("\n".join(displayed).replace("&", "&&"))
        self.setFixedHeight(
            self.fontMetrics().height()
            + max(0, len(lines) - 1) * self.fontMetrics().lineSpacing()
            + padding
        )
        self.setToolTip(text)
        self.setAccessibleName(text)
