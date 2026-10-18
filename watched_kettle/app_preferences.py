"""Compatibility facade for feature-owned application preferences."""

import json
from watched_kettle.application.settings_store import open_settings


from watched_kettle.preferences.models import (
    BUBBLE_SCALE_MIN as BUBBLE_SCALE_MIN,
    BUBBLE_SCALE_MAX as BUBBLE_SCALE_MAX,
    BUBBLE_SCALE_STEP as BUBBLE_SCALE_STEP,
    DEFAULT_BUBBLE_SCALE as DEFAULT_BUBBLE_SCALE,
    BUBBLE_DURATION_MIN_SECONDS as BUBBLE_DURATION_MIN_SECONDS,
    BUBBLE_DURATION_MAX_SECONDS as BUBBLE_DURATION_MAX_SECONDS,
    BUBBLE_DURATION_STEP_SECONDS as BUBBLE_DURATION_STEP_SECONDS,
    DEFAULT_BUBBLE_DURATION_SECONDS as DEFAULT_BUBBLE_DURATION_SECONDS,
    PET_CATALOG_SORT_NAME as PET_CATALOG_SORT_NAME,
    PET_CATALOG_SORT_CUSTOM as PET_CATALOG_SORT_CUSTOM,
    PET_CATALOG_SORT_MODES as PET_CATALOG_SORT_MODES,
    DEFAULT_USAGE_WIDGET_COLOR as DEFAULT_USAGE_WIDGET_COLOR,
    DEFAULT_USAGE_WIDGET_OPACITY as DEFAULT_USAGE_WIDGET_OPACITY,
    USAGE_WIDGET_OPACITY_MIN as USAGE_WIDGET_OPACITY_MIN,
    USAGE_WIDGET_OPACITY_MAX as USAGE_WIDGET_OPACITY_MAX,
    USAGE_WIDGET_SCALE_MIN as USAGE_WIDGET_SCALE_MIN,
    USAGE_WIDGET_SCALE_MAX as USAGE_WIDGET_SCALE_MAX,
    USAGE_WIDGET_SCALE_STEP as USAGE_WIDGET_SCALE_STEP,
    DEFAULT_USAGE_WIDGET_SCALE as DEFAULT_USAGE_WIDGET_SCALE,
    USAGE_WIDGET_SCALE_BASIS_VERSION as USAGE_WIDGET_SCALE_BASIS_VERSION,
    LEGACY_USAGE_WIDGET_SCALE_MIN as LEGACY_USAGE_WIDGET_SCALE_MIN,
    LEGACY_USAGE_WIDGET_SCALE_MAX as LEGACY_USAGE_WIDGET_SCALE_MAX,
    LEGACY_USAGE_WIDGET_SCALE_BASE as LEGACY_USAGE_WIDGET_SCALE_BASE,
    DEFAULT_USAGE_WIDGET_HOUR_RANGE as DEFAULT_USAGE_WIDGET_HOUR_RANGE,
    USAGE_WIDGET_CONFIG_VERSION as USAGE_WIDGET_CONFIG_VERSION,
    USAGE_WIDGET_SHAPES as USAGE_WIDGET_SHAPES,
    DEFAULT_USAGE_WIDGET_SHAPE as DEFAULT_USAGE_WIDGET_SHAPE,
    USAGE_WIDGET_EMPHASES as USAGE_WIDGET_EMPHASES,
    USAGE_WIDGET_THEME_MODES as USAGE_WIDGET_THEME_MODES,
    normalize_usage_widget_choice as normalize_usage_widget_choice,
    normalize_usage_widget_color as normalize_usage_widget_color,
    normalize_usage_widget_opacity as normalize_usage_widget_opacity,
    normalize_usage_widget_scale as normalize_usage_widget_scale,
    migrate_legacy_usage_widget_scale as migrate_legacy_usage_widget_scale,
    normalize_usage_widget_hour_range as normalize_usage_widget_hour_range,
    normalize_pet_id_list as normalize_pet_id_list,
    normalize_bubble_scale as normalize_bubble_scale,
    normalize_bubble_duration_seconds as normalize_bubble_duration_seconds,
)
from watched_kettle.preferences.widget import WidgetPreferences
from watched_kettle.preferences.bubbles import BubblesPreferences
from watched_kettle.preferences.placement import PlacementPreferences
from watched_kettle.preferences.catalog import CatalogPreferences


# (key, default, minimum, maximum) minutes; see docs/support-claude-code.md.
CLAUDE_CODE_TIMEOUT_FIELDS = (
    ("claude_code/work_timeout_minutes", 10, 1, 120),
    ("claude_code/waiting_timeout_minutes", 30, 1, 240),
)


def _bounded_int(value, default, low, high):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if low <= number <= high else default


# Daily chart ranges offered in the usage overview.
USAGE_CHART_DAYS = (7, 14, 30)

# Below this the pet is hard to find on a busy desktop.
PET_OPACITY_MIN = 50


class ApplicationPreferences:
    def __init__(self, settings=None):
        self.settings = settings if settings is not None else open_settings()

        self.placement = PlacementPreferences(self.settings)
        self.widget = WidgetPreferences(self.settings, self.placement)
        self.bubbles = BubblesPreferences(self.settings)
        self.catalog = CatalogPreferences(self.settings)

    def load_language_pack(self):
        return str(self.settings.value("app/languagePack", "") or "")

    def load_codex_not_detected_notice_shown(self):
        return self.settings.value(
            "codexNotDetectedNoticeShown",
            False,
            type=bool,
        )

    def save_codex_not_detected_notice_shown(self, shown):
        self.settings.setValue(
            "codexNotDetectedNoticeShown",
            bool(shown),
        )

    def load_update_auto_check(self):
        return self.settings.value("updates/autoCheck", True, type=bool)

    def save_update_auto_check(self, enabled):
        self.settings.setValue("updates/autoCheck", bool(enabled))

    def load_update_last_check(self):
        """When an automatic check last got an answer, in epoch seconds."""
        try:
            return max(0.0, float(self.settings.value("updates/lastCheck", 0)))
        except (TypeError, ValueError):
            return 0.0

    def save_update_last_check(self, timestamp):
        self.settings.setValue("updates/lastCheck", float(timestamp))

    def load_update_announced_version(self):
        return str(self.settings.value("updates/announcedVersion", "") or "")

    def save_update_announced_version(self, version):
        self.settings.setValue("updates/announcedVersion", str(version))

    def load_claude_code_timeouts(self):
        """Return (work, waiting) inactivity minutes for Claude Code sessions."""
        return tuple(
            _bounded_int(self.settings.value(key, default), default, low, high)
            for key, default, low, high in CLAUDE_CODE_TIMEOUT_FIELDS
        )

    def save_claude_code_timeouts(self, work_minutes, waiting_minutes):
        for (key, _default, low, high), value in zip(
            CLAUDE_CODE_TIMEOUT_FIELDS, (work_minutes, waiting_minutes)
        ):
            self.settings.setValue(key, max(low, min(high, int(value))))

    def load_usage_enabled(self):
        return self.settings.value("usage/enabled", True, type=bool)

    def load_claude_code_usage_enabled(self):
        # Off until chosen: Claude Code never inherits the Codex switch.
        return self.settings.value("usage/claude_code_enabled", False, type=bool)

    def save_claude_code_usage_enabled(self, enabled):
        self.settings.setValue("usage/claude_code_enabled", bool(enabled))

    def load_usage_project_order(self, account):
        value = self.settings.value(f"usage/projects/{account}", "") if account else ""
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            value = {}
        if not isinstance(value, dict):
            value = {}
        order = value.get("order", "recent")
        keys = value.get("keys", [])
        return (
            order if order in ("recent", "name", "custom") else "recent",
            tuple(k for k in keys if isinstance(k, str))
            if isinstance(keys, list)
            else (),
        )

    def save_usage_project_order(self, account, order, keys):
        if account:
            encoded = json.dumps(
                dict(order=order, keys=list(keys)), separators=(",", ":")
            )
            key = f"usage/projects/{account}"
            if self.settings.value(key, "") != encoded:
                self.settings.setValue(key, encoded)

    def save_usage_enabled(self, enabled):
        self.settings.setValue("usage/enabled", bool(enabled))

    def load_usage_quiet_summary_enabled(self):
        return self.settings.value(
            "usage/quietSummaryEnabled",
            True,
            type=bool,
        )

    def save_usage_quiet_summary_enabled(self, enabled):
        self.settings.setValue(
            "usage/quietSummaryEnabled",
            bool(enabled),
        )

    def load_usage_threshold_markers(self):
        value = self.settings.value("usage/thresholdMarkers", "[]")
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (TypeError, ValueError, json.JSONDecodeError):
                return frozenset()
        if not isinstance(value, (list, tuple)):
            return frozenset()
        return frozenset(str(item) for item in value if item)

    def save_usage_threshold_markers(self, markers):
        normalized = tuple(sorted({str(item) for item in markers if item}))
        self.settings.setValue(
            "usage/thresholdMarkers",
            json.dumps(normalized, ensure_ascii=False, separators=(",", ":")),
        )

    def load_usage_last_summary_date(self):
        return str(self.settings.value("usage/lastSummaryDate", "") or "")

    def save_usage_last_summary_date(self, date_text):
        self.settings.setValue("usage/lastSummaryDate", str(date_text or ""))

    def load_usage_chart_days(self):
        try:
            days = int(self.settings.value("usage/chartDays", 7))
        except (TypeError, ValueError):
            days = 7
        return days if days in USAGE_CHART_DAYS else 7

    def save_usage_chart_days(self, days):
        days = int(days) if int(days) in USAGE_CHART_DAYS else 7
        self.settings.setValue("usage/chartDays", days)
        return days

    def load_selected_pet_id(self):
        return self.catalog.load_selected_pet_id()

    def save_selected_pet_id(self, pet_id):
        return self.catalog.save_selected_pet_id(pet_id)

    def load_pet_catalog_sort_mode(self):
        return self.catalog.load_pet_catalog_sort_mode()

    def save_pet_catalog_sort_mode(self, mode):
        return self.catalog.save_pet_catalog_sort_mode(mode)

    def load_pet_custom_order(self):
        return self.catalog.load_pet_custom_order()

    def save_pet_custom_order(self, pet_ids):
        return self.catalog.save_pet_custom_order(pet_ids)

    def load_hidden_pet_ids(self):
        return self.catalog.load_hidden_pet_ids()

    def save_hidden_pet_ids(self, pet_ids):
        return self.catalog.save_hidden_pet_ids(pet_ids)

    def load_bubbles_enabled(self):
        return self.bubbles.load_bubbles_enabled()

    def save_bubbles_enabled(self, enabled):
        return self.bubbles.save_bubbles_enabled(enabled)

    def load_bubble_scale(self):
        return self.bubbles.load_bubble_scale()

    def save_bubble_scale(self, scale):
        return self.bubbles.save_bubble_scale(scale)

    def load_bubble_duration_seconds(self):
        return self.bubbles.load_bubble_duration_seconds()

    def save_bubble_duration_seconds(self, seconds):
        return self.bubbles.save_bubble_duration_seconds(seconds)

    def load_bubble_duration_policy(self):
        return self.bubbles.load_bubble_duration_policy()

    def save_bubble_duration_policy(self, policy):
        return self.bubbles.save_bubble_duration_policy(policy)

    def load_bubble_theme_mode(self):
        return self.bubbles.load_bubble_theme_mode()

    def save_bubble_theme_mode(self, mode):
        return self.bubbles.save_bubble_theme_mode(mode)

    def load_activity_labels_enabled(self):
        return self.bubbles.load_activity_labels_enabled()

    def load_pet_opacity(self):
        try:
            value = int(self.settings.value("pet/opacityPercent", 100))
        except (TypeError, ValueError):
            value = 100
        return min(100, max(PET_OPACITY_MIN, value))

    def save_pet_opacity(self, percent):
        value = min(100, max(PET_OPACITY_MIN, int(percent)))
        self.settings.setValue("pet/opacityPercent", value)
        return value

    def load_pet_shadow(self):
        return self.settings.value("pet/shadow", False, type=bool)

    def save_pet_shadow(self, enabled):
        self.settings.setValue("pet/shadow", bool(enabled))

    def load_pet_fade(self):
        return self.settings.value("pet/fade", True, type=bool)

    def save_pet_fade(self, enabled):
        self.settings.setValue("pet/fade", bool(enabled))

    def load_reduce_motion(self):
        """The settings window's "reduce motion" switch, shared by the pet."""
        try:
            saved = json.loads(str(self.settings.value("settingsUI/appearance", "")))
        except ValueError:
            return False
        return bool(saved.get("reduceMotion")) if isinstance(saved, dict) else False

    def save_activity_labels_enabled(self, enabled):
        return self.bubbles.save_activity_labels_enabled(enabled)

    def load_usage_widget_visible(self):
        return self.widget.load_usage_widget_visible()

    def save_usage_widget_visible(self, visible):
        return self.widget.save_usage_widget_visible(visible)

    def load_usage_widget_offset(self):
        return self.widget.load_usage_widget_offset()

    def save_usage_widget_offset(self, x, y):
        return self.widget.save_usage_widget_offset(x, y)

    def reset_usage_widget_offset(self):
        return self.widget.reset_usage_widget_offset()

    def load_usage_widget_legacy_offset(self):
        return self.widget.load_usage_widget_legacy_offset()

    def load_usage_widget_detached(self):
        return self.widget.load_usage_widget_detached()

    def save_usage_widget_detached(self, detached):
        return self.widget.save_usage_widget_detached(detached)

    def load_usage_widget_placement(self):
        return self.widget.load_usage_widget_placement()

    def save_usage_widget_placement(self, placement):
        return self.widget.save_usage_widget_placement(placement)

    def reset_usage_widget_placement(self):
        return self.widget.reset_usage_widget_placement()

    def load_usage_widget_shape(self):
        return self.widget.load_usage_widget_shape()

    def save_usage_widget_shape(self, value):
        return self.widget.save_usage_widget_shape(value)

    def load_usage_widget_emphasis(self):
        return self.widget.load_usage_widget_emphasis()

    def save_usage_widget_emphasis(self, value):
        return self.widget.save_usage_widget_emphasis(value)

    def load_usage_widget_tasks_visible(self):
        return self.widget.load_usage_widget_tasks_visible()

    def save_usage_widget_tasks_visible(self, value):
        return self.widget.save_usage_widget_tasks_visible(value)

    def load_usage_widget_today_visible(self):
        return self.widget.load_usage_widget_today_visible()

    def save_usage_widget_today_visible(self, value):
        return self.widget.save_usage_widget_today_visible(value)

    def load_usage_widget_theme_mode(self):
        return self.widget.load_usage_widget_theme_mode()

    def save_usage_widget_theme_mode(self, value):
        return self.widget.save_usage_widget_theme_mode(value)

    def load_usage_widget_limit_key(self):
        return self.widget.load_usage_widget_limit_key()

    def load_app_theme(self):
        """The settings-window theme: "light", "dark", or None for the system."""
        try:
            saved = json.loads(str(self.settings.value("settingsUI/appearance", "")))
        except ValueError:
            return None
        theme = saved.get("theme") if isinstance(saved, dict) else None
        return theme if theme in {"light", "dark"} else None

    def load_usage_widget_background_color(self):
        return self.widget.load_usage_widget_background_color()

    def save_usage_widget_background_color(self, color):
        return self.widget.save_usage_widget_background_color(color)

    def load_usage_widget_background_opacity(self):
        return self.widget.load_usage_widget_background_opacity()

    def save_usage_widget_background_opacity(self, opacity):
        return self.widget.save_usage_widget_background_opacity(opacity)

    def load_usage_widget_material(self):
        return self.widget.load_usage_widget_material()

    def save_usage_widget_material(self, value):
        return self.widget.save_usage_widget_material(value)

    def reset_usage_widget_style(self):
        return self.widget.reset_usage_widget_style()

    def load_usage_widget_scale(self):
        return self.widget.load_usage_widget_scale()

    def save_usage_widget_scale(self, scale_percent):
        return self.widget.save_usage_widget_scale(scale_percent)

    def reset_usage_widget_scale(self):
        return self.widget.reset_usage_widget_scale()

    def load_usage_widget_hour_range(self):
        return self.widget.load_usage_widget_hour_range()

    def save_usage_widget_hour_range(self, start_hour, end_hour):
        return self.widget.save_usage_widget_hour_range(start_hour, end_hour)

    def reset_usage_widget_hour_range(self):
        return self.widget.reset_usage_widget_hour_range()

    def load_auto_movement_screen(self):
        return self.placement.load_auto_movement_screen()

    def save_auto_movement_screen(self, mode, name=""):
        return self.placement.save_auto_movement_screen(mode, name)

    def load_window_placement(self):
        return self.placement.load_window_placement()

    def _load_saved_window_placement(self, prefix):
        return self.placement._load_saved_window_placement(prefix)

    def save_window_placement(self, placement):
        return self.placement.save_window_placement(placement)

    def _save_saved_window_placement(self, prefix, placement):
        return self.placement._save_saved_window_placement(prefix, placement)
