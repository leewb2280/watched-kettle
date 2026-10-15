"""Speech-bubble geometry, text fitting, and native window rendering."""

from PySide6.QtCore import QPoint, QRectF, Qt
from watched_kettle.ui.speech_bubble_frame import content_padding
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QTextLayout,
)
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QVBoxLayout

from watched_kettle.app_preferences import (
    DEFAULT_BUBBLE_SCALE,
    normalize_bubble_scale,
)
from watched_kettle.ui.bubble_models import (
    SOURCE_MARK_TOKENS,
    source_display_label,
    source_mark_color,
    source_marked_text,
)
from watched_kettle.ui.speech_bubble_paint import (
    bubble_frame_insets,
    build_body_path,
    build_tail_path,
    paint_bubble_backdrop,
    paint_bubble_surface,
)
from watched_kettle.pet.bubble_theme import DEFAULT_BUBBLE_THEME


BUBBLE_GAP = 10
BUBBLE_STACK_GAP = 6
BUBBLE_MIN_WIDTH = 140
BUBBLE_MAX_WIDTH = 320
BUBBLE_HORIZONTAL_PADDING = 32
BUBBLE_BODY_TOP_MARGIN = 12
BUBBLE_BODY_BOTTOM_MARGIN = 14
BUBBLE_RADIUS = 11
BUBBLE_TAIL_SIZE = 18
BUBBLE_TAIL_HALF_BASE = 15
BUBBLE_SHADOW_OFFSET = 2
MAX_BUBBLE_LINES = 3
NOTICE_ACCESSIBLE_LABELS = {
    "error": "문제",
    "waiting": "확인 필요",
    "notification": "알림",
    "done": "완료",
    "cancelled": "중단",
    "start": "시작",
    "preview": "미리보기",
}
NOTICE_CATEGORY_LABELS = {
    "error": "작업 문제",
    "waiting": "확인 필요",
    "notification": "알림",
    "done": "작업 완료",
    "cancelled": "작업 중단",
    "start": "작업 시작",
    "preview": "미리보기",
}
CATEGORY_STYLES = {
    "error": ("#7f3434", "#ead0d0", "#fff3f2"),
    "waiting": ("#79551d", "#ead7b7", "#fff8e8"),
    "notification": ("#365c87", "#cedbed", "#f1f6fc"),
    "done": ("#3f684b", "#cce0d2", "#f1f8f3"),
    "cancelled": ("#58616d", "#d1d6dc", "#f4f5f7"),
    "start": ("#515966", "#d5dae2", "#f3f5f8"),
    "preview": ("#565c83", "#d8daeb", "#f5f5fb"),
}


def bubble_position(pet_rect, bubble_size, bounds, gap=BUBBLE_GAP):
    return bubble_stack_positions(pet_rect, (bubble_size,), bounds, gap=gap)[0]


def bubble_stack_positions(
    pet_rect,
    bubble_sizes,
    bounds,
    avoid_rects=(),
    gap=BUBBLE_GAP,
    stack_gap=BUBBLE_STACK_GAP,
    alignment="center",
):
    """Bottom-first cards above the pet, clamped independently on each axis.

    Layout reduction belongs to the controller. Obstacles never cause a side flip.
    Qt screen coordinates are logical pixels, including the eight pixel margin.
    """
    del avoid_rects
    sizes = tuple(bubble_sizes)
    if not sizes:
        return ()
    area = bounds.adjusted(8, 8, -8, -8)
    width = max(s.width() for s in sizes)
    height = sum(s.height() for s in sizes) + stack_gap * (len(sizes) - 1)
    x = min(
        max(pet_rect.center().x() - width // 2, area.left()),
        max(area.left(), area.right() - width + 1),
    )
    y = min(
        max(pet_rect.top() - gap - height, area.top()),
        max(area.top(), area.bottom() - height + 1),
    )
    cursor = y + height
    positions = []
    for size in sizes:
        cursor -= size.height()
        offset = 0 if alignment == "left" else (width - size.width()) // 2
        positions.append(QPoint(x + offset, cursor))
        cursor -= stack_gap
    return tuple(positions)


def elide_wrapped_text(text, font, width, max_lines=MAX_BUBBLE_LINES):
    """Elide text after a bounded number of visual lines."""
    value = str(text or "")
    if not value or width <= 0 or max_lines <= 0:
        return value

    layout = QTextLayout(value, font)
    layout.beginLayout()
    lines = []
    for _ in range(max_lines):
        line = layout.createLine()
        if not line.isValid():
            break
        line.setLineWidth(width)
        lines.append(line)
    overflow = layout.createLine().isValid()
    layout.endLayout()
    if not overflow or not lines:
        return value

    last = lines[-1]
    start = last.textStart()
    end = start + last.textLength()
    prefix = value[:start]
    last_text = value[start:end].rstrip()
    metrics = QFontMetrics(font)
    return prefix + metrics.elidedText(
        f"{last_text}…",
        Qt.TextElideMode.ElideRight,
        width,
    )


class SourceMarkLabel(QLabel):
    """The header chip; an agent source's dot sits in its widened left padding.

    The dot is painted rather than written as rich text so the heading stays
    plain text and keeps its width and eliding rules (BA-05).
    """

    def __init__(self):
        super().__init__()
        self.mark_color = ""
        self.mark_left = 0
        self.mark_size = 0

    def set_mark(self, color, left, size):
        if (color, left, size) != (self.mark_color, self.mark_left, self.mark_size):
            self.mark_color, self.mark_left, self.mark_size = color, left, size
            self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.mark_color:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self.mark_color))
        size = self.mark_size
        painter.drawEllipse(
            QRectF(self.mark_left, (self.height() - size) / 2, size, size)
        )
        painter.end()


class SpeechBubbleWindow(QFrame):
    """Render one non-activating, scalable speech-bubble window."""

    def __init__(
        self,
        pet,
        scale_percent=DEFAULT_BUBBLE_SCALE,
        theme=DEFAULT_BUBBLE_THEME,
        element_registry=None,
        source_marks_shown=False,
    ):
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        if pet.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        super().__init__(pet, flags)
        self.pet = pet
        self.setObjectName("petSpeechBubble")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAutoFillBackground(False)
        self._tail_side = None
        self._notice_kind = ""
        self._notice_source = ""
        # The agent source whose dot the header shows; "" for none.
        self._mark_source = ""
        self.source_marks_shown = bool(source_marks_shown)
        self._raw_message = ""
        self._scale_percent = normalize_bubble_scale(scale_percent)
        self._theme = theme or DEFAULT_BUBBLE_THEME
        self._element_registry = element_registry
        self._decorations_enabled = True

        self.content_layout = QVBoxLayout(self)
        self.content_layout.setSpacing(5)
        self._update_content_margins()
        self.category_label = SourceMarkLabel()
        self.category_label.setObjectName("bubbleCategory")
        self.category_label.setTextFormat(Qt.TextFormat.PlainText)
        self.category_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.NoTextInteraction
        )
        self.category_label.hide()
        self.content_layout.addWidget(
            self.category_label,
            0,
            Qt.AlignmentFlag.AlignLeft,
        )
        self.label = QLabel()
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setWordWrap(True)
        self.label.setMinimumWidth(0)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.content_layout.addWidget(self.label)
        self._base_label_font = QFont(self.label.font())
        self._apply_scaled_font()

        self._apply_theme_palette()

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        outline_width = max(
            1.0,
            self._theme.border_width * self.scale_factor,
        )
        shadow_offset = self._scaled(BUBBLE_SHADOW_OFFSET)
        bubble_rect = QRectF(self.rect()).adjusted(
            outline_width / 2,
            outline_width / 2,
            -outline_width / 2,
            -outline_width / 2 - shadow_offset,
        )
        frame_left, frame_top, frame_right, frame_bottom = bubble_frame_insets(
            self._theme, self.scale_factor
        )
        bubble_rect.adjust(
            frame_left,
            frame_top,
            -frame_right,
            -frame_bottom,
        )
        if self._tail_side == "top":
            bubble_rect.adjust(0, self.tail_size, 0, 0)
        elif self._tail_side == "bottom":
            bubble_rect.adjust(0, 0, 0, -self.tail_size)
        elif self._tail_side == "left":
            bubble_rect.adjust(self.tail_size, 0, 0, 0)
        elif self._tail_side == "right":
            bubble_rect.adjust(0, 0, -self.tail_size, 0)
        path = build_body_path(bubble_rect, self._theme, self.scale_factor)
        tail = build_tail_path(
            bubble_rect,
            QRectF(self.rect()).adjusted(0, 0, 0, -shadow_offset),
            self._tail_side,
            self._theme,
            half_base=self._scaled(BUBBLE_TAIL_HALF_BASE),
        )
        if tail is not None:
            path = path.united(tail)
        self._input_path = path
        paint_bubble_backdrop(
            painter,
            bubble_rect,
            self._theme,
            self.scale_factor,
        )
        shadow_path = QPainterPath(path)
        shadow_path.translate(0, shadow_offset)
        shadow_color = QColor(self._theme.shadow)
        shadow_color.setAlpha(self._theme.shadow_alpha)
        painter.fillPath(shadow_path, shadow_color)
        paint_bubble_surface(
            painter,
            path,
            bubble_rect,
            self._theme,
            registry=self._element_registry,
            decorations=self._decorations_enabled,
            scale=self.scale_factor,
        )

    @property
    def message(self):
        return self.label.text()

    @property
    def notice_kind(self):
        return self._notice_kind

    @property
    def tail_side(self):
        return self._tail_side

    @property
    def scale_percent(self):
        return self._scale_percent

    @property
    def theme(self):
        return self._theme

    @property
    def scale_factor(self):
        return self._scale_percent / 100.0

    @property
    def tail_size(self):
        if self._theme.tail == "none":
            return 0
        return self._scaled(BUBBLE_TAIL_SIZE)

    def set_scale_percent(self, scale_percent):
        scale_percent = normalize_bubble_scale(scale_percent)
        if scale_percent == self._scale_percent:
            return
        self._scale_percent = scale_percent
        self._apply_scaled_font()
        self._update_content_margins()
        self.set_message(
            self._raw_message,
            self._notice_kind,
            self._notice_source,
        )

    def set_theme(self, theme):
        theme = theme or DEFAULT_BUBBLE_THEME
        if theme == self._theme:
            return
        self._theme = theme
        if self._theme.tail == "none":
            self._tail_side = None
        self._apply_scaled_font()
        self._apply_theme_palette()
        self._update_content_margins()
        self.set_message(
            self._raw_message,
            self._notice_kind,
            self._notice_source,
        )

    def set_source_marks_shown(self, shown):
        shown = bool(shown)
        if shown == self.source_marks_shown:
            return
        self.source_marks_shown = shown
        self.set_message(self._raw_message, self._notice_kind, self._notice_source)

    def set_decorations_enabled(self, enabled):
        enabled = bool(enabled)
        if enabled == self._decorations_enabled:
            return
        self._decorations_enabled = enabled
        self._update_content_margins()
        self.adjustSize()
        self.update()

    def set_message(self, message, kind=None, source=None):
        if kind is not None:
            self._notice_kind = str(kind or "")
        if source is not None:
            self._notice_source = str(source or "")
        text = str(message or "").strip()[:120]
        self._raw_message = text
        metrics = self.label.fontMetrics()
        longest_line = max(text.splitlines() or [""], key=len)
        category_text = self._category_text()
        self._mark_source = (
            self._notice_source
            if self.source_marks_shown
            and self._notice_source in SOURCE_MARK_TOKENS
            and NOTICE_CATEGORY_LABELS.get(self._notice_kind)
            else ""
        )
        self._update_category_label(category_text)
        category_width = self.category_label.sizeHint().width() if category_text else 0
        natural_width = max(
            metrics.horizontalAdvance(longest_line),
            category_width,
        )
        bubble_width = min(
            max(
                natural_width + self._scaled(self._theme.horizontal_padding),
                self._scaled(self._theme.minimum_width),
            ),
            self._scaled(self._theme.maximum_width),
        )
        label_width = bubble_width - self._scaled(self._theme.horizontal_padding)
        self.label.setFixedWidth(label_width)
        self.label.setMaximumHeight(metrics.lineSpacing() * MAX_BUBBLE_LINES)
        self.label.setText(elide_wrapped_text(text, self.label.font(), label_width))
        accessible_label = NOTICE_ACCESSIBLE_LABELS.get(self._notice_kind)
        source_label = self._source_label()
        if accessible_label and source_label:
            accessible_text = f"{accessible_label}: {source_label} · {text}"
        elif accessible_label:
            accessible_text = f"{accessible_label}: {text}"
        elif source_label:
            accessible_text = f"{source_label}: {text}"
        else:
            accessible_text = text
        self.setAccessibleName(accessible_text)
        self.label.adjustSize()
        self.adjustSize()
        self.update()

    def clear_message(self):
        """Remove raw text before this hidden window enters the reuse pool."""
        self._notice_kind = ""
        self._notice_source = ""
        self._raw_message = ""
        self.category_label.clear()
        self.category_label.hide()
        self.label.clear()
        self.setAccessibleName("")

    def set_tail_side(self, side):
        side = side if side in {"top", "bottom", "left", "right"} else None
        if self._theme.tail == "none":
            side = None
        if side == self._tail_side:
            return
        self._tail_side = side
        self._update_content_margins()
        self.adjustSize()
        self.update()

    def _update_content_margins(self):
        self.content_layout.setSpacing(self._scaled(5))
        horizontal_padding = self._scaled(self._theme.horizontal_padding)
        left = horizontal_padding // 2
        right = horizontal_padding - left
        padding_top, padding_bottom, extra_left = content_padding(
            self._theme, BUBBLE_BODY_TOP_MARGIN, BUBBLE_BODY_BOTTOM_MARGIN
        )
        top = self._scaled(padding_top)
        bottom = self._scaled(padding_bottom)
        if extra_left:
            left += self._scaled(extra_left)
        frame_left, frame_top, frame_right, frame_bottom = bubble_frame_insets(
            self._theme, self.scale_factor
        )
        left += round(frame_left)
        top += round(frame_top)
        right += round(frame_right)
        bottom += round(frame_bottom)
        if self._decorations_enabled and (
            self._theme.ornament_left != "none" or self._theme.ornament_right != "none"
        ):
            top += self._scaled(14)
        if self._tail_side == "left":
            left += self.tail_size
        elif self._tail_side == "top":
            top += self.tail_size
        elif self._tail_side == "right":
            right += self.tail_size
        elif self._tail_side == "bottom":
            bottom += self.tail_size
        self.content_layout.setContentsMargins(left, top, right, bottom)

    def _apply_scaled_font(self):
        font = QFont(self._base_label_font)
        font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
        if font.pointSizeF() > 0:
            font.setPointSizeF(font.pointSizeF() * self.scale_factor)
        elif font.pixelSize() > 0:
            font.setPixelSize(self._scaled(font.pixelSize()))
        font.setBold(self._theme.text_bold)
        self.label.setFont(font)
        self.category_label.setFont(font)
        horizontal = (
            Qt.AlignmentFlag.AlignLeft
            if self._theme.text_alignment == "left"
            else Qt.AlignmentFlag.AlignHCenter
        )
        self.label.setAlignment(horizontal | Qt.AlignmentFlag.AlignVCenter)

    def _apply_theme_palette(self):
        label_palette = self.label.palette()
        label_palette.setColor(
            self.label.foregroundRole(),
            QColor(self._theme.text),
        )
        self.label.setPalette(label_palette)
        self.update()

    def _scaled(self, value):
        return max(1, round(value * self.scale_factor))

    def _source_label(self):
        if self._notice_source == "preview":
            return "미리보기"
        value = source_display_label(self._notice_source)
        return value if self._notice_source else ""

    def _category_text(self):
        if self._theme.header_style == "none":
            return ""
        source_label = self._source_label()
        kind_label = NOTICE_CATEGORY_LABELS.get(self._notice_kind, "")
        if kind_label and self._notice_source in SOURCE_MARK_TOKENS:
            # Agent sources are a dot when both are in use, else left out.
            source_label = ""
        return " · ".join(value for value in (source_label, kind_label) if value)

    def _update_category_label(self, category_text):
        if not category_text:
            self.category_label.clear()
            self.category_label.hide()
            return
        text_color, border_color, background_color = CATEGORY_STYLES.get(
            self._notice_kind,
            ("#515966", "#d5dae2", "#f3f5f8"),
        )
        radius = 7
        vertical_padding = 1
        horizontal_padding = 7
        extra_style = ""
        if self._theme.header_style == "tab":
            radius = 4
            extra_style = (
                f"border-bottom: {self._scaled(2)}px solid {self._theme.border};"
            )
        elif self._theme.header_style == "ribbon":
            radius = 2
            horizontal_padding = 10
            extra_style = "font-style: italic;"
        elif self._theme.header_style == "panel":
            radius = 1
            vertical_padding = 2
            extra_style = (
                f"border-left: {self._scaled(3)}px solid {self._theme.border};"
            )
        mark = source_mark_color(self._mark_source)
        mark_size = self._scaled(6)
        left_padding = self._scaled(horizontal_padding)
        border_left = self._scaled(3) if self._theme.header_style == "panel" else 1
        self.category_label.set_mark(mark, border_left + left_padding, mark_size)
        if mark:
            left_padding += mark_size + self._scaled(4)
        marked = source_marked_text(category_text, self._mark_source)
        self.category_label.setToolTip(marked if mark else "")
        self.category_label.setAccessibleName(marked)
        self.category_label.setText(category_text)
        self.category_label.setStyleSheet(
            "QLabel#bubbleCategory {"
            f"color: {text_color};"
            f"border: 1px solid {border_color};"
            f"background: {background_color};"
            f"border-radius: {self._scaled(radius)}px;"
            f"padding: {self._scaled(vertical_padding)}px"
            f" {self._scaled(horizontal_padding)}px"
            f" {self._scaled(vertical_padding)}px {left_padding}px;"
            f"font-size: {self._scaled(10)}px;"
            "font-weight: 600;"
            f"{extra_style}"
            "}"
        )
        self.category_label.show()

    def reposition(self):
        screen = (
            QApplication.screenAt(self.pet.frameGeometry().center())
            or self.pet.screen()
            or QApplication.primaryScreen()
        )
        if screen is None:
            return
        self.move(
            bubble_position(
                self.pet.frameGeometry(),
                self.sizeHint(),
                screen.availableGeometry(),
            )
        )

    def sync_always_on_top(self, enabled):
        was_visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, bool(enabled))
        if was_visible:
            self.show()
            self.reposition()
