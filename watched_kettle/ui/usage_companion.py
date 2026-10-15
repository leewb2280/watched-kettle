"""Usage widget placement next to the desktop pet and its preferences."""

from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QObject, QPoint, QTimer
from PySide6.QtWidgets import QApplication

from watched_kettle.pet.placement import create_saved_placement, restore_window_position

USAGE_WIDGET_GAP = 8
# Reset countdowns and "n분 전" age the widget shows without a new snapshot.
USAGE_WIDGET_TICK_MS = 60_000
# The settings preview keeps its offscreen window this long after a request.
PREVIEW_RELEASE_MS = 30_000


def clamp_widget_position(position, widget_size, bounds):
    maximum_x = max(bounds.left(), bounds.right() - widget_size.width() + 1)
    maximum_y = max(bounds.top(), bounds.bottom() - widget_size.height() + 1)
    return QPoint(
        min(max(position.x(), bounds.left()), maximum_x),
        min(max(position.y(), bounds.top()), maximum_y),
    )


def usage_companion_position(pet_rect, widget_size, bounds, gap=USAGE_WIDGET_GAP):
    """Choose the roomier side of the pet and clamp inside the work area."""

    left_space = pet_rect.left() - bounds.left()
    right_space = bounds.right() - pet_rect.right()
    if right_space >= left_space:
        target_x = pet_rect.right() + 1 + gap
    else:
        target_x = pet_rect.left() - widget_size.width() - gap
    target_y = pet_rect.center().y() - widget_size.height() // 2
    return clamp_widget_position(
        QPoint(target_x, target_y),
        widget_size,
        bounds,
    )


class UsageCompanionController(QObject):
    """Connect preferences and usage snapshots to the companion window."""

    def __init__(
        self,
        pet,
        pet_viewmodel,
        usage_viewmodel,
        open_usage,
        parent=None,
        *,
        app_theme=lambda: None,
        activity=lambda: None,
        open_settings=None,
    ):
        super().__init__(parent)
        # Callables: the app theme name ("light"/"dark"/None for the system)
        # and per-provider running/attention counts.
        self.app_theme = app_theme
        self.activity = activity
        # Runs only while the widget is shown; hidden widgets do no work.
        self._tick = QTimer(self)
        self._tick.setInterval(USAGE_WIDGET_TICK_MS)
        self._tick.timeout.connect(self.refresh)
        self.pet = pet
        self.pet_viewmodel = pet_viewmodel
        self.usage_viewmodel = usage_viewmodel
        self.open_usage = open_usage
        # Imported here: the Qt Quick window reuses this module's placement helpers.
        from watched_kettle.ui.usage_widget.backdrop import Backdrop
        from watched_kettle.ui.usage_widget.window import (
            QuickUsageWindow,
            use_software_renderer,
        )

        use_software_renderer()
        self._window_class = QuickUsageWindow
        # The settings page's preview: a second, never shown window made on
        # demand and dropped after a quiet spell so it costs nothing at rest.
        self._preview_window = None
        self._preview_release = QTimer(self)
        self._preview_release.setSingleShot(True)
        self._preview_release.setInterval(PREVIEW_RELEASE_MS)
        self._preview_release.timeout.connect(self._release_preview)
        self.window = QuickUsageWindow(pet, backdrop=Backdrop())
        self.window.context = self._widget_context
        self.window.usage_route_requested.connect(self.open_usage)
        self.window.size_changed.connect(self.reposition)
        self.window.position_changed.connect(self._position_changed)
        usage_viewmodel.snapshot_changed.connect(self._usage_changed)
        pet_viewmodel.snapshot_changed.connect(self._pet_changed)
        self._connect_pet_signal(
            "usage_widget_visibility_requested", usage_viewmodel.set_widget_visible
        )
        self._connect_pet_signal(
            "usage_widget_shape_requested", usage_viewmodel.set_widget_shape
        )
        self._connect_pet_signal(
            "usage_widget_tasks_visibility_requested",
            usage_viewmodel.set_widget_tasks_visible,
        )
        self._connect_pet_signal(
            "usage_widget_today_visibility_requested",
            usage_viewmodel.set_widget_today_visible,
        )
        self._connect_pet_signal(
            "usage_widget_settings_requested", open_settings or open_usage
        )
        self._connect_pet_signal(
            "usage_widget_position_reset_requested", self._reset_widget_position
        )
        pet.installEventFilter(self)
        self._watched_screens = []
        app = QApplication.instance()
        if app is not None:
            app.screenAdded.connect(self._screen_added)
            app.screenRemoved.connect(self._screens_changed)
            for screen in app.screens():
                self._watch_screen(screen)
        hints = app.styleHints() if app is not None else None
        if hints is not None and hasattr(hints, "colorSchemeChanged"):
            # "Follow the app theme" also follows Windows when the app follows it.
            hints.colorSchemeChanged.connect(self.refresh)
        self._render(usage_viewmodel.snapshot)
        self._sync_menu_state()
        self._sync_visibility()

    def _widget_context(self):
        vm = self.usage_viewmodel
        claude = vm.claude_code_snapshot
        custom = vm.widget_theme_mode == "custom"
        return {
            "layout": vm.widget_shape,
            "emphasis": vm.widget_emphasis,
            "theme": self.app_theme(),
            "background": vm.widget_background_color if custom else None,
            "opacity": vm.widget_background_opacity,
            "material": getattr(vm, "widget_material", "opaque"),
            "claude_code_observed_at": getattr(claude, "limits_observed_at", None),
            "claude_code_enabled": None
            if getattr(vm, "claude_code_enabled", False)
            else False,
            "activity": self.activity() if vm.widget_tasks_visible else None,
            "today": vm.widget_today_visible,
            "hour_range": vm.widget_hour_range,
            "claude_code_hourly": getattr(claude, "today_hourly_tokens", ()),
        }

    def _connect_pet_signal(self, name, callback):
        signal = getattr(self.pet, name, None)
        if signal is not None:
            signal.connect(callback)

    def eventFilter(self, watched, event):
        if watched is self.pet:
            if event.type() in {QEvent.Type.Move, QEvent.Type.Resize}:
                if not self.usage_viewmodel.widget_detached:
                    self.reposition()
            elif event.type() == QEvent.Type.WindowStateChange:
                self._sync_visibility()
            elif event.type() == QEvent.Type.Show:
                self._sync_visibility()
            elif event.type() == QEvent.Type.Hide:
                self._tick.stop()
                self.window.hide()
            elif event.type() == QEvent.Type.Close:
                self.window.close()
        return super().eventFilter(watched, event)

    def _watch_screen(self, screen):
        if screen is None or screen in self._watched_screens:
            return
        screen.availableGeometryChanged.connect(self._screens_changed)
        self._watched_screens.append(screen)

    def _screen_added(self, screen):
        self._watch_screen(screen)
        self._screens_changed()

    def _screens_changed(self, *_args):
        if self.window.isVisible():
            self.reposition()

    def _render(self, snapshot):
        self.window.apply_snapshot(
            snapshot, scale_percent=self.usage_viewmodel.widget_scale_percent
        )

    def preview(self, *, sample=False, expanded=False):
        """Draw the widget with the current settings, offscreen.

        Returns the image and whether example values were used: when asked,
        or when no provider has anything to show yet.
        """
        from watched_kettle.usage.widget_sample import (
            SAMPLE_ACTIVITY,
            SAMPLE_CLAUDE_CODE_HOURLY,
            sample_snapshot,
        )

        if self._preview_window is None:
            self._preview_window = self._window_class()
        window = self._preview_window
        vm = self.usage_viewmodel
        # Offscreen there is nothing behind the card; acrylic shows as the
        # tone it has over a dark desktop.
        context = dict(self._widget_context(), expanded=bool(expanded), glass="preview")
        window.context = lambda: context
        window.apply_snapshot(vm.snapshot, scale_percent=vm.widget_scale_percent)
        if sample or not window.model._state.get("providers"):
            sample = True
            context.update(
                claude_code_enabled=None,
                claude_code_observed_at=None,
                claude_code_hourly=SAMPLE_CLAUDE_CODE_HOURLY,
                activity=SAMPLE_ACTIVITY if vm.widget_tasks_visible else None,
            )
            window.apply_snapshot(
                sample_snapshot(), scale_percent=vm.widget_scale_percent
            )
        # The view resizes to its root on a later event, and running the event
        # loop inside a settings request could let another request in. Size it
        # here instead; the first frame also lays out positioners (chips).
        root = window.rootObject()
        for _ in range(2):
            if root is not None:
                window.resize(math.ceil(root.width()), math.ceil(root.height()))
            image = window.grab()
        self._preview_release.start()
        return image, sample

    def _release_preview(self):
        if self._preview_window is not None:
            self._preview_window.close()
            self._preview_window.deleteLater()
            self._preview_window = None

    def refresh(self):
        """Redraw after a setting outside the usage snapshot changed."""
        self._render(self.usage_viewmodel.snapshot)

    def _usage_changed(self, snapshot):
        self._render(snapshot)
        self._sync_menu_state()
        self._sync_visibility()

    def _pet_changed(self, snapshot):
        self.window.sync_always_on_top(snapshot.always_on_top)
        self._sync_visibility()

    def _sync_menu_state(self):
        self.pet.usage_widget_available = getattr(
            self.usage_viewmodel, "any_enabled", self.usage_viewmodel.enabled
        )
        self.pet.usage_widget_visible = self.usage_viewmodel.widget_visible
        self.pet.usage_widget_shape = self.usage_viewmodel.widget_shape
        self.pet.usage_widget_tasks_visible = self.usage_viewmodel.widget_tasks_visible
        self.pet.usage_widget_today_visible = self.usage_viewmodel.widget_today_visible
        self.pet.usage_widget_position_customized = self.usage_viewmodel.widget_detached

    def _sync_visibility(self):
        visible = (
            getattr(self.usage_viewmodel, "any_enabled", self.usage_viewmodel.enabled)
            and self.usage_viewmodel.widget_visible
            and self.pet.isVisible()
        )
        if visible:
            was_visible = self.window.isVisible()
            self.window.show()
            if not was_visible:
                # Acrylic needs the native window, which exists once shown.
                self._render(self.usage_viewmodel.snapshot)
            self.reposition()
            if not self._tick.isActive():
                self._tick.start()
        else:
            self._tick.stop()
            self.window.hide()

    def _placement(self):
        screen = (
            QApplication.screenAt(self.pet.frameGeometry().center())
            or self.pet.screen()
            or QApplication.primaryScreen()
        )
        if screen is None:
            return None, None
        bounds = screen.availableGeometry()
        base = usage_companion_position(
            self.pet.frameGeometry(),
            self.window.size(),
            bounds,
        )
        return base, bounds

    def reposition(self):
        if not self.window.isVisible():
            return
        # Bubbles, usage and size updates arrive mid-drag; moving to the saved
        # spot then would pull the widget back. Release saves the new spot.
        if getattr(self.window, "dragging", False):
            return
        app = QApplication.instance()
        if self.usage_viewmodel.widget_detached and app is not None:
            target = restore_window_position(
                self.usage_viewmodel.widget_placement,
                app.screens(),
                app.primaryScreen(),
                self.window.size(),
            )
            if target is not None:
                self.window.move(target)
                return
            self.usage_viewmodel.reset_widget_position()
            return
        base, bounds = self._placement()
        if base is None:
            return
        legacy_offset = self.usage_viewmodel.widget_legacy_offset
        target = base
        if legacy_offset not in (None, (0, 0)):
            target = clamp_widget_position(
                base + QPoint(*legacy_offset),
                self.window.size(),
                bounds,
            )
        self.window.move(target)
        if legacy_offset not in (None, (0, 0)):
            self._detach_at(target)

    def _position_changed(self, position):
        self._detach_at(position)

    def _detach_at(self, position):
        screen = (
            QApplication.screenAt(position + self.window.rect().center())
            or self.window.screen()
            or QApplication.primaryScreen()
        )
        if screen is None:
            return
        placement = create_saved_placement(
            screen.name(),
            position,
            self.window.size(),
            screen.availableGeometry(),
        )
        self.usage_viewmodel.detach_widget(placement)

    def _reset_widget_position(self):
        self.usage_viewmodel.reset_widget_position()
        self.reposition()

    def close(self):
        self._tick.stop()
        self._preview_release.stop()
        self._release_preview()
        app = QApplication.instance()
        if app is not None:
            try:
                app.screenAdded.disconnect(self._screen_added)
                app.screenRemoved.disconnect(self._screens_changed)
            except (RuntimeError, TypeError):
                pass
        for screen in self._watched_screens:
            try:
                screen.availableGeometryChanged.disconnect(self._screens_changed)
            except (RuntimeError, TypeError):
                pass
        self._watched_screens.clear()
        self.pet.removeEventFilter(self)
        self.window.close()
