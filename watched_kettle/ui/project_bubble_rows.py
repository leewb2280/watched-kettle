"""Reusable project rows with status badges and a two-row scroll viewport."""

from html import escape
from datetime import datetime
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from watched_kettle.features.project_activity.service import row_status_label
from watched_kettle.ui.wrapped_title_button import WrappedTitleButton, title_text_width


def _badge_presentation(row, theme):
    """Resolve presentation only; activity state remains owned by the service."""
    if row.uncertain:
        tooltip = "최근 활동을 받지 못했습니다. 작업 종료는 확인되지 않았습니다."
        if row.source == "codex" and row.last_confirmed_at:
            tooltip += "\n마지막 확인: " + datetime.fromtimestamp(
                row.last_confirmed_at
            ).astimezone().strftime("%Y-%m-%d %H:%M:%S")
        return (
            "상태 확인 중",
            tooltip,
            theme.text,
            "transparent",
        )
    if row.compacting:
        return "컨텍스트 압축 중", "", theme.text, "transparent"
    if row.state == "background":
        count = getattr(row, "background_count", 0)
        return (
            f"백그라운드 {count}개" if count else "백그라운드 대기",
            "백그라운드 작업이 끝나면 결과를 읽고 이어서 마무리합니다.",
            theme.text,
            "transparent",
        )
    colors = {
        "done": ("#17633a", "#d7f1df"),
        "waiting": ("#715000", "#fff0b5"),
        "failed": ("#922f35", "#f9dddd"),
    }
    foreground, background = colors.get(row.state, (theme.text, "transparent"))
    source = getattr(row, "source", "codex")
    tooltip = (
        "Claude Code가 도구 사용 권한을 물었습니다. "
        "승인한 뒤에도 그 도구가 끝날 때까지 이 표시가 남습니다."
        if source == "claude_code" and row.state == "waiting"
        else ""
    )
    return row_status_label(row), tooltip, foreground, background


class ProjectConversationRow(QFrame):
    def __init__(self, router, dismiss, parent=None):
        super().__init__(parent)
        self.setObjectName("projectConversationRow")
        self.router = router
        self.dismiss = dismiss
        self.row = None
        self.token = ""
        self.title = WrappedTitleButton(self)
        self.title.setFlat(True)
        self.title.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.title.setCursor(Qt.CursorShape.PointingHandCursor)
        self.title.clicked.connect(lambda: self.router.open(self.token))
        self.badge = QLabel(self)
        self.badge.setTextFormat(Qt.TextFormat.PlainText)
        self.badge.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.close_button = QToolButton(self)
        self.close_button.setText("×")
        self.close_button.setToolTip("완료 표시 닫기")
        self.close_button.setAccessibleName("완료 표시 닫기")
        self.close_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.clicked.connect(self._dismiss)
        self.line = QHBoxLayout(self)
        self.line.setContentsMargins(0, 0, 0, 0)
        self.line.addWidget(self.title)
        self.line.addWidget(self.badge)
        self.line.addWidget(self.close_button)

    def _dismiss(self):
        if self.row is not None:
            identifier = self.row.completion_id or self.row.dismiss_id
            if identifier:
                self.dismiss((identifier,))

    def configure(self, row, token, font, theme, scaled):
        self.row = row
        self.token = token
        self.title.setFont(font)
        self.badge.setFont(font)
        self.close_button.setFont(font)
        self.line.setSpacing(scaled(5))
        label, tooltip, foreground, background = _badge_presentation(row, theme)
        self.badge.setText(label)
        self.badge.setToolTip(tooltip)
        self.badge.setStyleSheet(
            f"color: {foreground}; background: {background}; border-radius: {scaled(4)}px; padding: {scaled(3)}px {scaled(5)}px;"
        )
        self.badge.ensurePolished()
        # QLabel's size hint includes its minimum size. Release the old fixed
        # size so a shorter status (or smaller font) can shrink again.
        self.badge.setMinimumSize(0, 0)
        self.badge.setMaximumSize(16_777_215, 16_777_215)
        self.badge.setFixedSize(self.badge.sizeHint())
        self.close_button.setFixedSize(scaled(20), scaled(22))
        self.close_button.setVisible(row.state == "done" or bool(row.dismiss_id))
        self.close_button.setToolTip(
            "완료 닫기" if row.completion_id else "미확인 작업 숨기기"
        )
        self.close_button.setStyleSheet(
            f"QToolButton {{ color: {theme.text}; border: none; background: transparent; }} QToolButton:hover {{ background: rgba(100,140,180,30); }}"
        )
        title_color = "#17633a" if row.highlighted else theme.text
        self.title.setStyleSheet(
            f"QPushButton {{ text-align: left; color: {title_color}; background: transparent; border: none; padding: {scaled(4)}px; }} QPushButton:hover {{ background: rgba(100,140,180,20); }}"
        )
        self.title.ensurePolished()
        self.setStyleSheet(
            f"QFrame#projectConversationRow {{ background: {'#e8f6ec' if row.highlighted else 'transparent'}; border-radius: {scaled(5)}px; }}"
        )
        self.setAccessibleName(f"{row.title} · {label}")

    def chrome_width(self):
        return (
            self.badge.width()
            + self.line.spacing()
            + (
                self.close_button.width() + self.line.spacing()
                if self.row.state == "done" or self.row.dismiss_id
                else 0
            )
        )

    def fit(self, width, scaled):
        self.setFixedWidth(width)
        self.title.set_title(
            self.row.title, max(1, width - self.chrome_width()), scaled(8)
        )
        self.setFixedHeight(
            max(
                self.title.height(),
                self.badge.height(),
                self.close_button.height()
                if self.row.state == "done" or self.row.dismiss_id
                else 0,
            )
        )


SCROLLBAR_WIDTH = 5


class ProjectBubbleRows(QScrollArea):
    def __init__(self, router, dismiss, parent=None):
        super().__init__(parent)
        self.router = router
        self.dismiss = dismiss
        self.rows = {}
        self.ordered_ids = ()
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setWidgetResizable(False)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.viewport().setAutoFillBackground(False)
        self.body = QWidget()
        self.body.setAutoFillBackground(False)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.setWidget(self.body)
        self.body.setAutoFillBackground(False)

    def anchor(self):
        value = self.verticalScrollBar().value()
        if value == 0:
            return None, 0
        for key in self.ordered_ids:
            row = self.rows[key]
            if row.y() + row.height() > value:
                return key, value - row.y()
        return None, value

    def configure(self, rows, tokens, font, theme, scaled):
        self._anchor = self.anchor()
        identifiers = tuple(row.thread_id for row in rows)
        key, offset = self._anchor
        if key is not None and key not in identifiers:
            index = self.ordered_ids.index(key)
            neighbors = self.ordered_ids[index + 1 :] + self.ordered_ids[:index][::-1]
            self._anchor = (next((k for k in neighbors if k in identifiers), None), 0)
        for key in set(self.rows) - set(identifiers):
            widget = self.rows.pop(key)
            self.body_layout.removeWidget(widget)
            widget.hide()
            widget.deleteLater()
        for row, token in zip(rows, tokens):
            if row.thread_id not in self.rows:
                self.rows[row.thread_id] = ProjectConversationRow(
                    self.router, self.dismiss, self.body
                )
            self.rows[row.thread_id].configure(row, token, font, theme, scaled)
        if identifiers != self.ordered_ids:
            for index, key in enumerate(identifiers):
                self.body_layout.insertWidget(index, self.rows[key])
        self.ordered_ids = identifiers
        self.body_layout.setSpacing(scaled(5))
        self._style_scrollbar(theme, scaled)

    def _style_scrollbar(self, theme, scaled):
        """A thin bar in the bubble's text color instead of the native arrows.

        Only the look changes; range, value and anchoring stay Qt's (BA-06).
        """
        width = max(3, scaled(SCROLLBAR_WIDTH))
        color = QColor(theme.text)
        rgb = f"{color.red()},{color.green()},{color.blue()}"
        radius = width // 2
        self.verticalScrollBar().setStyleSheet(
            f"QScrollBar:vertical {{ width: {width}px; margin: 0; border: none;"
            f" border-radius: {radius}px; background: rgba({rgb},20); }}"
            " QScrollBar::handle:vertical {"
            f" background: rgba({rgb},90); border-radius: {radius}px;"
            f" min-height: {scaled(14)}px; }}"
            " QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical"
            " { height: 0; border: none; }"
            " QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical"
            " { background: none; }"
        )
        # The gap keeps row text off the bar.
        self._scroll_width = width + scaled(3)

    def scroll_width(self):
        if getattr(self, "_scroll_width", None):
            return self._scroll_width
        return self.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent)

    def natural_width(self, visible_count, scaled):
        scrollbar = self.scroll_width() if len(self.rows) > visible_count else 0
        return (
            max(
                (
                    title_text_width(row.row.title, row.title.font())
                    + row.chrome_width()
                    + scaled(8)
                    for row in self.rows.values()
                ),
                default=1,
            )
            + scrollbar
        )

    def fit(self, width, visible_count, scaled):
        keys = self.ordered_ids
        scrollbar = self.scroll_width() if len(keys) > visible_count else 0
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn
            if scrollbar
            else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        row_width = max(1, width - scrollbar)
        for row in self.rows.values():
            row.fit(row_width, scaled)
            row.show()
        gap = self.body_layout.spacing()
        height = sum(self.rows[key].height() for key in keys) + gap * max(
            0, len(keys) - 1
        )
        shown = keys[:visible_count]
        visible_height = sum(self.rows[key].height() for key in shown) + gap * max(
            0, len(shown) - 1
        )
        self.body.setFixedSize(row_width, max(1, height))
        self.setFixedSize(width, max(1, visible_height))
        self.body_layout.activate()
        # Update the range synchronously so a content shrink does not reset the
        # anchor before Qt processes its next layout event.
        bar = self.verticalScrollBar()
        bar.setRange(0, max(0, height - visible_height))
        bar.setPageStep(visible_height)
        key, offset = self._anchor
        bar.setValue(self.rows[key].y() + offset if key in self.rows else offset)


def layout_project_bubble(window, content, compact):
    """Fit fixed project header + independently scrolling conversation rows."""
    scaled = window._scaled
    font = window.label.font()
    window.category_label.setMinimumWidth(0)
    window.category_label.setMaximumWidth(16_777_215)
    window._update_category_label(content.heading)
    if not content.mark:
        window.category_label.setToolTip(content.heading)
    window.category_label.ensurePolished()
    window.summary_label.setFont(font)
    window.summary_label.setWordWrap(False)
    window.summary_label.setMinimumWidth(0)
    window.summary_label.setMaximumWidth(16_777_215)
    window.summary_label.setTextFormat(Qt.TextFormat.RichText)
    window.summary_label.setStyleSheet(f"color: {window.theme.text};")
    highlighted = any(row.highlighted for row in content.project_rows)
    parts = content.summary.split(" · ")
    window.summary_label.setText(
        " · ".join(
            f'<span style="background-color:#d7f1df;color:#17633a;font-weight:600">{escape(part).replace(" ", "&nbsp;")}</span>'
            if highlighted and part.startswith("완료 ")
            else escape(part).replace(" ", "&nbsp;")
            for part in parts
        )
    )
    window.summary_label.setToolTip(content.summary)
    window.summary_label.setAccessibleName(content.summary)
    window.summary_label.setVisible(bool(content.summary))
    window.summary_label.ensurePolished()
    window.project_rows.configure(
        content.project_rows,
        [token for _, token in content.rows],
        font,
        window.theme,
        scaled,
    )
    visible_count = 1 if compact else 2
    spacing = scaled(6) if content.summary else 0
    margins = window.content_layout.contentsMargins()
    screen_width = (
        max(1, content.available_width - margins.left() - margins.right())
        if content.available_width
        else 16_777_215
    )
    heading_width, summary_width = fit_header_to_screen(window, screen_width, spacing)
    header_width = heading_width + spacing + summary_width
    natural = max(
        header_width,
        window.project_rows.natural_width(visible_count, scaled),
    )
    if content.footer:
        natural = max(
            natural,
            title_text_width(content.footer, font) + scaled(8),
        )
    # The theme limit still bounds conversation titles, but cannot truncate a
    # project header. Only the actual screen bounds constrain the full header.
    maximum = min(
        screen_width,
        max(
            header_width,
            scaled(window.theme.maximum_width - window.theme.horizontal_padding),
        ),
    )
    minimum = min(
        maximum, scaled(window.theme.minimum_width - window.theme.horizontal_padding)
    )
    width = min(maximum, max(minimum, natural))
    window.header.setFixedWidth(width)
    window.header.layout().setSpacing(spacing)
    window.header.layout().setAlignment(Qt.AlignmentFlag.AlignLeft)
    window.category_label.setFixedWidth(heading_width)
    window.summary_label.setFixedWidth(summary_width)
    window.header.setFixedHeight(
        max(
            window.category_label.sizeHint().height(),
            window.summary_label.sizeHint().height() if content.summary else 0,
        )
    )
    window.header.show()
    window.project_rows.fit(width, visible_count, scaled)
    window.project_rows.show()
    window.label.hide()
    for button in window.buttons:
        button.hide()
    if content.footer:
        button = window.buttons[0]
        button.setFont(font)
        # Same text color as the other bubble buttons; the project path
        # returns before they are styled.
        button.setStyleSheet(
            "QPushButton { text-align: left; padding: 3px; "
            f"color: {window.theme.text}; }}"
            " QPushButton:hover { background: rgba(100,140,180,25); }"
        )
        button.set_title(content.footer, width, scaled(8), 1)
        if getattr(button, "action_token", None) != content.footer_token:
            if button.action_connected:
                button.clicked.disconnect()
            button.clicked.connect(lambda: window.activate(content.footer_token))
            button.action_connected = True
            button.action_token = content.footer_token
        button.show()
    window.setAccessibleName(
        " · ".join(filter(None, (content.heading, content.summary)))
    )
    window.setWindowTitle(f"말풍선 · {content.heading}")
    window.content_layout.activate()
    window.resize(window.sizeHint())


def fit_header_to_screen(window, available, spacing):
    """Measure styled, single-line labels; shrink type only beyond screen width."""
    category = window.category_label
    summary = window.summary_label
    category_style = category.styleSheet()
    summary_font = summary.font()
    base_category_pixels = window._scaled(10)
    base_summary_points = summary_font.pointSizeF()
    base_summary_pixels = summary_font.pixelSize()
    factor = 1.0
    while True:
        category.ensurePolished()
        summary.ensurePolished()
        heading_width = category.sizeHint().width()
        summary_width = summary.sizeHint().width() if window.content.summary else 0
        total = heading_width + spacing + summary_width
        if total <= available or factor <= 0.05:
            return heading_width, summary_width
        factor = max(0.05, min(factor - 0.05, factor * available / total))
        category.setStyleSheet(
            re.sub(
                r"font-size: \d+px;",
                f"font-size: {max(1, int(base_category_pixels * factor))}px;",
                category_style,
            )
        )
        if base_summary_points > 0:
            summary_font.setPointSizeF(max(1.0, base_summary_points * factor))
        else:
            summary_font.setPixelSize(max(1, int(base_summary_pixels * factor)))
        summary.setFont(summary_font)
