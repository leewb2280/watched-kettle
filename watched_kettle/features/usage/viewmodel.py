"""UI-facing Work·Codex usage commands and immutable state."""

from watched_kettle.localization import t

from dataclasses import replace

from PySide6.QtCore import QObject, Signal

from watched_kettle.usage.claude_code_limits import tray_summary as claude_tray_summary
from watched_kettle.usage.models import UsageAvailability


class UsageViewModel(QObject):
    snapshot_changed = Signal(object)
    claude_code_changed = Signal(object)

    def __init__(self, service, preferences, parent=None):
        super().__init__(parent)
        self.service = service
        self.preferences = preferences
        service.snapshot_changed.connect(self._receive)
        self._claude_buckets = ()
        claude_code = getattr(service, "claude_code_snapshot_changed", None)
        if claude_code is not None:
            claude_code.connect(self._receive_claude_code)

    def _receive_claude_code(self, snapshot):
        self.claude_code_changed.emit(snapshot)
        buckets = tuple(getattr(snapshot, "buckets", ()) or ())
        if buckets != self._claude_buckets:
            # Limit cards, widget choices and the widget itself read buckets.
            self._claude_buckets = buckets
            self.snapshot_changed.emit(self.snapshot)

    def _with_claude_code(self, snapshot):
        """Show Claude Code limits next to Codex ones; worker state stays apart."""
        claude = self.claude_code_snapshot
        buckets = (
            tuple(getattr(claude, "buckets", ()) or ())
            if self.claude_code_enabled
            else ()
        )
        if not self.enabled:
            snapshot = replace(
                snapshot,
                buckets=(),
                availability=UsageAvailability("disabled", t("message.0478")),
            )
        return replace(snapshot, buckets=tuple(snapshot.buckets) + buckets)

    def claude_code_tray_summary(self):
        claude = self.claude_code_snapshot
        return claude_tray_summary(getattr(claude, "buckets", ()) or ())

    @property
    def claude_code_snapshot(self):
        """Claude Code task history; None when the service has no such source."""
        return getattr(self.service, "claude_code_snapshot", None)

    def claude_code(self, method, *args):
        command = getattr(self.service, "claude_code", None)
        return command(method, *args) if command is not None else False

    def _receive(self, snapshot):
        if (
            snapshot.project_mode
            and snapshot.account_hash
            and not snapshot.account_checking
        ):
            self.preferences.save_usage_project_order(
                snapshot.account_hash,
                snapshot.project_order,
                snapshot.project_custom_order,
            )
        self.snapshot_changed.emit(self._with_claude_code(snapshot))

    def set_project_query(self, search="", order=None, offset=0):
        custom = None
        if order is None:
            order, custom = self.preferences.load_usage_project_order(
                self.snapshot.account_hash
            )
        return self.service.set_project_query(search, order, offset, custom)

    def select_usage_project(self, key):
        return self.service.select_usage_project(key)

    def move_usage_project(self, key, direction=0, target="", before=True):
        return self.service.move_usage_project(key, direction, target, before)

    @property
    def snapshot(self):
        return self._with_claude_code(self.service.snapshot.for_display())

    @property
    def enabled(self):
        return self.service.enabled

    @property
    def claude_code_enabled(self):
        return getattr(self.service, "claude_code_enabled", True)

    @property
    def any_enabled(self):
        return self.enabled or self.claude_code_enabled

    @property
    def quiet_summary_enabled(self):
        return self.service.quiet_summary_enabled

    @property
    def widget_visible(self):
        return self.preferences.load_usage_widget_visible()

    @property
    def widget_legacy_offset(self):
        return self.preferences.load_usage_widget_legacy_offset()

    @property
    def widget_detached(self):
        return self.preferences.load_usage_widget_detached()

    @property
    def widget_click_through(self):
        return self.preferences.load_usage_widget_click_through()

    @property
    def widget_click_through_hotkey(self):
        return self.preferences.load_usage_widget_click_through_hotkey()

    @property
    def widget_placement(self):
        return self.preferences.load_usage_widget_placement()

    @property
    def widget_shape(self):
        return self.preferences.load_usage_widget_shape()

    @property
    def widget_emphasis(self):
        return self.preferences.load_usage_widget_emphasis()

    @property
    def widget_tasks_visible(self):
        return self.preferences.load_usage_widget_tasks_visible()

    @property
    def widget_today_visible(self):
        return self.preferences.load_usage_widget_today_visible()

    @property
    def widget_theme_mode(self):
        return self.preferences.load_usage_widget_theme_mode()

    @property
    def widget_background_color(self):
        return self.preferences.load_usage_widget_background_color()

    @property
    def widget_material(self):
        return self.preferences.load_usage_widget_material()

    @property
    def widget_background_opacity(self):
        return self.preferences.load_usage_widget_background_opacity()

    @property
    def widget_scale_percent(self):
        return self.preferences.load_usage_widget_scale()

    @property
    def widget_hour_range(self):
        return self.preferences.load_usage_widget_hour_range()

    @property
    def chart_days(self):
        return self.preferences.load_usage_chart_days()

    def refresh_requested(self):
        claude = self.claude_code("refresh") if self.claude_code_enabled else False
        codex = self.service.refresh(force=True) if self.enabled else False
        return bool(claude or codex)

    def clear_device_requested(self):
        return self.service.clear_device_history()

    def clear_requested(self):
        return self.service.clear_history()

    def set_task_query(self, search="", order="recent", limit=100, thread_hash=None):
        return self.service.set_task_query(
            search, order, limit, thread_hash=thread_hash
        )

    def set_conversation_query(self, search="", order="recent", offset=0):
        return self.service.set_conversation_query(
            search,
            order,
            offset,
            project_key=self.snapshot.selected_project_key
            if self.snapshot.project_mode
            else None,
        )

    def select_usage_conversation(self, thread_hash):
        return self.service.select_usage_conversation(thread_hash)

    def set_enabled(self, enabled):
        self.service.set_enabled(enabled)
        self.snapshot_changed.emit(self.snapshot)

    def set_claude_code_enabled(self, enabled):
        self.service.set_claude_code_enabled(enabled)
        self.snapshot_changed.emit(self.snapshot)

    def set_quiet_summary_enabled(self, enabled):
        self.service.set_quiet_summary_enabled(enabled)
        self.snapshot_changed.emit(self.snapshot)

    def set_widget_visible(self, visible):
        self.preferences.save_usage_widget_visible(bool(visible))
        self.snapshot_changed.emit(self.snapshot)

    def set_widget_click_through(self, enabled):
        self.preferences.save_usage_widget_click_through(bool(enabled))
        self.snapshot_changed.emit(self.snapshot)

    def toggle_widget_click_through(self):
        self.set_widget_click_through(not self.widget_click_through)

    def set_widget_click_through_hotkey(self, text):
        self.preferences.save_usage_widget_click_through_hotkey(text)
        self.snapshot_changed.emit(self.snapshot)

    def set_widget_shape(self, shape):
        shape = self.preferences.save_usage_widget_shape(shape)
        self.snapshot_changed.emit(self.snapshot)
        return shape

    def set_widget_emphasis(self, emphasis):
        emphasis = self.preferences.save_usage_widget_emphasis(emphasis)
        # The usage page charts hourly decreases of the emphasized Codex limit.
        self.service.set_selected_limit_key(
            self.preferences.load_usage_widget_limit_key()
        )
        self.snapshot_changed.emit(self.snapshot)
        return emphasis

    def set_widget_tasks_visible(self, visible):
        visible = self.preferences.save_usage_widget_tasks_visible(visible)
        self.snapshot_changed.emit(self.snapshot)
        return visible

    def set_widget_today_visible(self, visible):
        visible = self.preferences.save_usage_widget_today_visible(visible)
        self.snapshot_changed.emit(self.snapshot)
        return visible

    def set_widget_theme_mode(self, mode):
        mode = self.preferences.save_usage_widget_theme_mode(mode)
        self.snapshot_changed.emit(self.snapshot)
        return mode

    def reset_widget_settings(self):
        """Back to the default rings layout; style and placement stay."""
        self.preferences.save_usage_widget_shape("rings")
        self.preferences.save_usage_widget_tasks_visible(True)
        self.preferences.save_usage_widget_today_visible(False)
        self.set_widget_emphasis("auto")

    def set_widget_background_color(self, color):
        color = self.preferences.save_usage_widget_background_color(color)
        self.snapshot_changed.emit(self.snapshot)
        return color

    def set_widget_material(self, material):
        material = self.preferences.save_usage_widget_material(material)
        self.snapshot_changed.emit(self.snapshot)
        return material

    def set_widget_background_opacity(self, opacity):
        opacity = self.preferences.save_usage_widget_background_opacity(opacity)
        self.snapshot_changed.emit(self.snapshot)
        return opacity

    def reset_widget_style(self):
        self.preferences.reset_usage_widget_style()
        self.snapshot_changed.emit(self.snapshot)

    def set_widget_scale_percent(self, scale_percent):
        scale_percent = self.preferences.save_usage_widget_scale(scale_percent)
        self.snapshot_changed.emit(self.snapshot)
        return scale_percent

    def reset_widget_scale(self):
        self.preferences.reset_usage_widget_scale()
        self.snapshot_changed.emit(self.snapshot)

    def set_widget_hour_range(self, start_hour, end_hour):
        hour_range = self.preferences.save_usage_widget_hour_range(start_hour, end_hour)
        self.snapshot_changed.emit(self.snapshot)
        return hour_range

    def reset_widget_hour_range(self):
        self.preferences.reset_usage_widget_hour_range()
        self.snapshot_changed.emit(self.snapshot)

    def detach_widget(self, placement):
        self.preferences.save_usage_widget_placement(placement)
        self.preferences.save_usage_widget_detached(True)
        self.preferences.reset_usage_widget_offset()
        self.snapshot_changed.emit(self.snapshot)
        return placement

    def reset_widget_position(self):
        self.preferences.save_usage_widget_detached(False)
        self.preferences.reset_usage_widget_placement()
        self.preferences.reset_usage_widget_offset()
        self.snapshot_changed.emit(self.snapshot)

    def set_chart_days(self, days):
        self.preferences.save_usage_chart_days(days)
        self.snapshot_changed.emit(self.snapshot)

    def tray_summary(self):
        return self.service.tray_summary()
