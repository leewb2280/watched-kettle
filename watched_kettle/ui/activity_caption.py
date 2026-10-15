"""A compact text caption that follows underneath the desktop pet."""

from __future__ import annotations

from PySide6.QtCore import QObject, QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QVBoxLayout

from html import escape

from watched_kettle.ui import design_tokens
from watched_kettle.ui.bubble_models import source_display_label


CAPTION_GAP = 4
CAPTION_RADIUS = 12
CAPTION_RESERVED_HEIGHT = 32
ACTIVITY_MESSAGES = {
    "idle": "",
    "running-right": "오른쪽으로 걷는 중",
    "running-left": "왼쪽으로 걷는 중",
    "waving": "인사하는 중",
    "jumping": "점프하는 중",
    "failed": "풀이 죽어 있는 중",
    "waiting": "확인을 기다리는 중",
    "running": "작업을 돕는 중",
    "review": "내용을 살펴보는 중",
}


def activity_message(state, sources=()):
    """Name the working agents; a pet without them keeps a neutral caption."""
    message = ACTIVITY_MESSAGES.get(state, "")
    if state == "running" and sources:
        names = "·".join(source_display_label(source) for source in sources)
        return f"{names} {message}"
    return message


SOURCE_TOKENS = {"codex": "source-codex", "claude_code": "source-claude-code"}


def caption_theme(pet):
    """The app theme when the settings window chose one, else Windows'."""
    preferences = getattr(pet, "app_preferences", None)
    theme = preferences.load_app_theme() if preferences is not None else None
    if theme is None:
        hints = QApplication.styleHints() if QApplication.instance() else None
        scheme = getattr(hints, "colorScheme", None)
        theme = "dark" if scheme and scheme() == Qt.ColorScheme.Dark else "light"
    return design_tokens.theme_tokens(theme)


def caption_html(message, sources, tokens):
    """The caption text with a dot in each working source's color."""
    dots = "".join(
        f'<span style="color:{tokens[SOURCE_TOKENS[source]]}">●</span>&nbsp;'
        for source in sources
        if source in SOURCE_TOKENS
    )
    return dots + escape(message)


def caption_position(pet_rect, caption_size, bounds, gap=CAPTION_GAP):
    """Center the caption below the pet and keep it in the work area."""
    target_x = pet_rect.left() + (pet_rect.width() - caption_size.width()) // 2
    target_y = pet_rect.bottom() + 1 + gap
    maximum_x = max(bounds.left(), bounds.right() - caption_size.width() + 1)
    maximum_y = max(bounds.top(), bounds.bottom() - caption_size.height() + 1)
    return QPoint(
        min(max(target_x, bounds.left()), maximum_x),
        min(max(target_y, bounds.top()), maximum_y),
    )


class ActivityCaptionWindow(QFrame):
    """Independent rounded caption; intentionally has no stylesheet."""

    def __init__(self, pet):
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        if pet.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        super().__init__(pet, flags)
        self.pet = pet
        self.setObjectName("petActivityCaption")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAutoFillBackground(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.label)
        self._message = ""
        self._apply_theme(caption_theme(pet))

    def _apply_theme(self, tokens):
        """Floating-surface tokens, the same as the usage widget's card."""
        palette = self.label.palette()
        palette.setColor(QPalette.ColorRole.WindowText, QColor(tokens["float-ink"]))
        self.label.setPalette(palette)
        self._tokens = tokens
        self._surface_color = QColor(tokens["float-surface"])
        self._surface_color.setAlpha(235)
        line = tokens["float-line"]
        self._border_color = QColor(line[:7])
        self._border_color.setAlpha(int(line[7:9], 16) if len(line) == 9 else 255)

    @property
    def message(self):
        return self._message

    def set_message(self, message, sources=()):
        self._message = str(message or "")[:80]
        self._apply_theme(caption_theme(self.pet))
        self.label.setText(caption_html(self._message, sources, self._tokens))
        self.label.adjustSize()
        self.adjustSize()
        self.reposition()

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        surface = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = min(CAPTION_RADIUS, surface.height() / 2)
        path = QPainterPath()
        path.addRoundedRect(surface, radius, radius)
        painter.fillPath(path, self._surface_color)
        painter.setPen(QPen(self._border_color, 1.0))
        painter.drawPath(path)

    def reposition(self):
        screen = (
            QApplication.screenAt(self.pet.frameGeometry().center())
            or self.pet.screen()
            or QApplication.primaryScreen()
        )
        if screen is None:
            return
        self.move(
            caption_position(
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


class PetActivityCaptionController(QObject):
    def __init__(self, pet, enabled=False, parent=None):
        super().__init__(parent)
        self.pet = pet
        self.enabled = bool(enabled)
        self.state = "idle"
        self.working_sources = ()
        self.window = ActivityCaptionWindow(pet)

    @property
    def reserved_height(self):
        return CAPTION_RESERVED_HEIGHT if self.enabled else 0

    def set_working_sources(self, sources):
        sources = tuple(sources or ())
        if sources != self.working_sources:
            self.working_sources = sources
            self.set_state(self.state)

    def set_state(self, state):
        self.state = str(state or "idle")
        message = activity_message(self.state, self.working_sources)
        if not message:
            self.window.hide()
            return
        self.window.set_message(message, self.working_sources)
        if self.enabled and self.pet.isVisible():
            self.window.show()
            self.window.reposition()

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        self.set_state(self.state)

    def owner_shown(self):
        if self.enabled and ACTIVITY_MESSAGES.get(self.state, ""):
            self.window.show()
            self.window.reposition()

    def owner_hidden(self):
        self.window.hide()

    def reposition(self):
        if self.window.isVisible():
            self.window.reposition()

    def sync_always_on_top(self, enabled):
        self.window.sync_always_on_top(enabled)

    def close(self):
        self.window.close()
