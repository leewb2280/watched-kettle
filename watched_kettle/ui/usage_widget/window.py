"""Qt Quick usage widget window that follows the desktop pet.

The window keeps the small interface the companion controller already uses
(show, hide, move, size, apply_snapshot and the click and drag signals), so
placement and preferences stay in UsageCompanionController.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import (
    Property,
    QObject,
    QPoint,
    QRect,
    QSize,
    Qt,
    QUrl,
    Signal,
)
from PySide6.QtGui import QColor, QGuiApplication, QPixmap
from PySide6.QtQuick import QQuickView, QQuickWindow, QSGRendererInterface
from PySide6.QtWidgets import QApplication

from watched_kettle.application.logging import log_event
from watched_kettle.ui import design_tokens
from watched_kettle.localization import t
from watched_kettle.ui.usage_companion import clamp_widget_position
from watched_kettle.ui.usage_widget.backdrop import ACRYLIC, OPAQUE
from watched_kettle.usage.widget_state import widget_state

QML_ROOT = Path(__file__).resolve().parent / "qml"
LAYOUTS = ("bars", "rings", "chips")
DEFAULT_LAYOUT = "rings"
# Below this background opacity every text gets an outline in the card color.
# The software renderer draws outlines jagged, so keep them for very
# see-through cards only (85% looked worse on a real desktop, 2026-10-04).
HALO_BELOW_OPACITY = 60
# Acrylic's tone over a dark editor in the stage 14 prototype, used where
# the settings preview cannot draw acrylic.
GLASS_PREVIEW_LIGHT = "#DFE0E0"
GLASS_PREVIEW_DARK = "#222324"
_THEME_KEYS = (
    "float-surface",
    "float-ink",
    "float-muted",
    "float-line",
    "float-shadow",
    "accent",
    "status-running",
    "status-attention",
    "status-done",
    "status-failed",
    "source-codex",
    "source-claude-code",
)


def use_software_renderer():
    """Pick the software scene graph before the first Qt Quick window.

    Measured on 2026-10-03: the default Direct3D 11 renderer added about
    69 MiB private memory for one small window, the software one about 20 MiB.
    """
    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.Software)


def qml_color(value):
    """Tokens use #RRGGBBAA; QML reads eight digits as #AARRGGBB."""
    if len(value) == 9:
        return "#" + value[7:9] + value[1:7]
    return value


def _is_dark(color):
    color = QColor(color)
    luminance = 0.299 * color.redF() + 0.587 * color.greenF() + 0.114 * color.blueF()
    return luminance < 0.5


def widget_theme(name, background=None, opacity=100, glass=None):
    """Colors for QML; a custom background picks readable text for itself.

    ``glass`` is "live" when DWM draws acrylic behind the window: the card
    keeps only a click-catching alpha step and drops its border and shadow.
    "preview" stands in for acrylic offscreen with the measured tone. Acrylic
    follows the app theme, so it ignores a custom color and the opacity.
    """
    if glass:
        background = None
    elif background:
        name = "dark" if _is_dark(background) else "light"
    tokens = design_tokens.theme_tokens(name)
    theme = {key.replace("-", "_"): qml_color(tokens[key]) for key in _THEME_KEYS}
    theme["glass"] = bool(glass)
    surface = QColor(background or tokens["float-surface"])
    if glass == "preview":
        surface = QColor(GLASS_PREVIEW_DARK if name == "dark" else GLASS_PREVIEW_LIGHT)
    elif glass:
        surface.setAlpha(1)
    else:
        # Keep at least one alpha step so the transparent card still takes clicks.
        surface.setAlpha(max(1, round(255 * max(0, min(100, int(opacity))) / 100)))
    theme["float_surface"] = surface.name(QColor.NameFormat.HexArgb)
    opacity = 100 if glass else int(opacity)
    if opacity < 100:
        # A see-through card takes on the unknown desktop color: a light card
        # at 70% over a black wallpaper is mid gray, where muted text falls to
        # about 3:1. Secondary text uses the body ink instead (2026-10-04).
        theme["float_muted"] = theme["float_ink"]
    # Design rule: below 60% the desktop shows through enough to need an
    # outline in the card's own color around every text.
    halo = QColor(background or tokens["float-surface"])
    halo.setAlpha(220)
    theme["halo"] = opacity < HALO_BELOW_OPACITY
    theme["halo_color"] = halo.name(QColor.NameFormat.HexArgb)
    theme["float_card"] = (
        qml_color(tokens["float-surface"])
        if not background
        else (QColor(background).name())
    )
    return theme


def system_theme_name():
    hints = QGuiApplication.styleHints()
    scheme = getattr(hints, "colorScheme", None)
    if scheme is not None and scheme() == Qt.ColorScheme.Dark:
        return "dark"
    return "light"


class UsageWidgetModel(QObject):
    """Everything QML reads; replaced as a whole when anything changes."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = {"providers": [], "empty": True, "tasksVisible": True}
        self._labels = {
            name: t("widget." + name)
            for name in (
                "empty",
                "today",
                "attention",
                "running",
            )
        }
        self._theme = widget_theme("light")
        self._layout = DEFAULT_LAYOUT
        self._scale = 1.0
        self._expanded = False

    def update(self, *, state=None, theme=None, layout=None, scale=None, expanded=None):
        values = {
            "_state": state if state is not None else self._state,
            "_theme": theme if theme is not None else self._theme,
            "_layout": layout if layout in LAYOUTS else self._layout,
            "_scale": float(scale) if scale is not None else self._scale,
            "_expanded": bool(expanded) if expanded is not None else self._expanded,
        }
        if all(getattr(self, name) == value for name, value in values.items()):
            return
        for name, value in values.items():
            setattr(self, name, value)
        self.changed.emit()

    labels = Property("QVariantMap", lambda self: self._labels, constant=True)
    state = Property("QVariantMap", lambda self: self._state, notify=changed)
    theme = Property("QVariantMap", lambda self: self._theme, notify=changed)
    layout = Property(str, lambda self: self._layout, notify=changed)
    scale = Property(float, lambda self: self._scale, notify=changed)
    # Unfolds layout C without hovering, for previews and captures.
    expanded = Property(bool, lambda self: self._expanded, notify=changed)


class QuickUsageWindow(QQuickView):
    usage_route_requested = Signal()
    size_changed = Signal()
    position_changed = Signal(QPoint)

    def __init__(self, pet=None, backdrop=None):
        super().__init__()
        self.pet = pet
        # Only the widget next to the pet draws acrylic; the settings preview
        # renders offscreen and stands in with the measured tone.
        self.backdrop = backdrop
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        if pet is not None and pet.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setFlags(flags)
        self.setColor(QColor(Qt.GlobalColor.transparent))
        self.setResizeMode(QQuickView.ResizeMode.SizeViewToRootObject)
        self.model = UsageWidgetModel(self)
        self.context = None
        self.rootContext().setContextProperty("widgetModel", self.model)
        self.setSource(QUrl.fromLocalFile(str(QML_ROOT / "UsageWidget.qml")))
        if not self.ready:
            # QML errors carry file paths; log only that loading failed.
            log_event(
                "usage.widget",
                "qml_load_failed",
                logging.WARNING,
                error_count=len(self.errors()),
            )
        self._press_global = None
        self._press_position = None
        self._dragging = False
        self._last_size = self.size()
        self.widthChanged.connect(self._size_changed)
        self.heightChanged.connect(self._size_changed)
        if pet is not None and pet.windowHandle() is not None:
            self.setTransientParent(pet.windowHandle())

    def _size_changed(self, *_args):
        if self.size() != self._last_size:
            self._last_size = self.size()
            self.size_changed.emit()

    @property
    def ready(self):
        return self.status() == QQuickView.Status.Ready

    @property
    def dragging(self):
        """True while the pointer moves the window; placement waits for release."""
        return self._dragging and self._press_global is not None

    def _clear_press(self):
        self._press_global = self._press_position = None
        self._dragging = False

    # The controller treats this window like the QWidget it replaces.
    def move(self, point):
        self.setPosition(point)

    def pos(self):
        return self.position()

    def rect(self):
        return QRect(QPoint(0, 0), self.size())

    def grab(self):
        return QPixmap.fromImage(self.grabWindow())

    def sync_always_on_top(self, enabled):
        self.setFlag(Qt.WindowType.WindowStaysOnTopHint, bool(enabled))

    def sync_click_through(self, enabled):
        flag = Qt.WindowType.WindowTransparentForInput
        if bool(self.flags() & flag) == bool(enabled):
            return
        was_visible = self.isVisible()
        self.setFlag(flag, bool(enabled))
        if was_visible:
            # The per-pixel layered window takes no clicks after the change
            # until it is shown again; repaints alone do not bring them back.
            self.hide()
            self.show()
        # The release of a press cut off by the change never arrives.
        self._clear_press()

    def apply_snapshot(self, snapshot, *, scale_percent=100, **_options):
        context = self.context() if self.context else {}
        state = widget_state(
            snapshot.for_display(),
            emphasis=context.get("emphasis", "auto"),
            claude_code_enabled=context.get("claude_code_enabled"),
            claude_code_observed_at=context.get("claude_code_observed_at"),
            activity=context.get("activity"),
            tasks_visible=context.get("tasks_visible", True),
            today=context.get("today", False),
            hour_range=context.get("hour_range", (0, 24)),
            claude_code_hourly=context.get("claude_code_hourly", ()),
        )
        theme_name = context.get("theme") or system_theme_name()
        material = context.get("material", OPAQUE)
        glass = None
        if material == ACRYLIC and context.get("glass") == "preview":
            glass = "preview"
        elif self.backdrop is not None and self.isVisible():
            # The native window exists once shown; hidden widgets keep the
            # material they had and are updated on the next show.
            if self.backdrop.apply(int(self.winId()), material, theme_name == "dark"):
                glass = "live"
        elif self.backdrop is not None and self.backdrop.active:
            glass = "live"
        self.model.update(
            state=state,
            theme=widget_theme(
                theme_name,
                context.get("background"),
                context.get("opacity", 100),
                glass,
            ),
            layout=context.get("layout", DEFAULT_LAYOUT),
            scale=max(0.7, min(1.3, scale_percent / 100)),
            expanded=context.get("expanded", False),
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._press_position = self.position()
            self._dragging = False
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press_global is None or not (
            event.buttons() & Qt.MouseButton.LeftButton
        ):
            # The release went elsewhere; a stale press would block placement.
            self._clear_press()
            return super().mouseMoveEvent(event)
        delta = event.globalPosition().toPoint() - self._press_global
        if not self._dragging:
            self._dragging = delta.manhattanLength() >= QApplication.startDragDistance()
        if self._dragging:
            target = self._press_position + delta
            screen = QGuiApplication.screenAt(target + self.rect().center()) or (
                self.screen()
            )
            if screen is not None:
                target = clamp_widget_position(
                    target,
                    QSize(self.width(), self.height()),
                    screen.availableGeometry(),
                )
            self.setPosition(target)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._press_global is not None
        ):
            dragging = self._dragging
            self._clear_press()
            if dragging:
                self.position_changed.emit(self.position())
            else:
                self.usage_route_requested.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def hideEvent(self, event):
        # Hidden mid-drag, no release arrives: drop the drag without saving.
        self._clear_press()
        super().hideEvent(event)
