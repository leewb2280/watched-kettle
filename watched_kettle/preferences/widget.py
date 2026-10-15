"""widget preferences; existing QSettings keys are preserved."""

from .models import (
    DEFAULT_USAGE_WIDGET_COLOR,
    DEFAULT_USAGE_WIDGET_OPACITY,
    DEFAULT_USAGE_WIDGET_SCALE,
    USAGE_WIDGET_CONFIG_VERSION,
    USAGE_WIDGET_EMPHASES,
    USAGE_WIDGET_EMPHASIS_LIMIT_KEYS,
    USAGE_WIDGET_SCALE_BASIS_VERSION,
    USAGE_WIDGET_SHAPES,
    USAGE_WIDGET_MATERIALS,
    USAGE_WIDGET_THEME_MODES,
    migrate_legacy_usage_widget_scale,
    normalize_usage_widget_choice,
    normalize_usage_widget_color,
    normalize_usage_widget_hour_range,
    normalize_usage_widget_opacity,
    normalize_usage_widget_scale,
)


class WidgetPreferences:
    def __init__(self, settings, placement=None):
        self.settings = settings
        self.placement = placement

    def load_usage_widget_visible(self):
        return self.settings.value("usage/widgetVisible", True, type=bool)

    def save_usage_widget_visible(self, visible):
        self.settings.setValue("usage/widgetVisible", bool(visible))

    def load_usage_widget_offset(self):
        values = []
        for key in ("usage/widgetOffsetX", "usage/widgetOffsetY"):
            try:
                value = int(self.settings.value(key, 0))
            except (TypeError, ValueError):
                value = 0
            values.append(max(-4096, min(4096, value)))
        return tuple(values)

    def save_usage_widget_offset(self, x, y):
        offset = (
            max(-4096, min(4096, int(x))),
            max(-4096, min(4096, int(y))),
        )
        self.settings.setValue("usage/widgetOffsetX", offset[0])
        self.settings.setValue("usage/widgetOffsetY", offset[1])
        return offset

    def reset_usage_widget_offset(self):
        self.settings.remove("usage/widgetOffsetX")
        self.settings.remove("usage/widgetOffsetY")

    def load_usage_widget_legacy_offset(self):
        keys = ("usage/widgetOffsetX", "usage/widgetOffsetY")
        if all(self.settings.value(key, None) is None for key in keys):
            return None
        return self.load_usage_widget_offset()

    def load_usage_widget_detached(self):
        return self.settings.value("usage/widgetDetached", False, type=bool)

    def save_usage_widget_detached(self, detached):
        self.settings.setValue("usage/widgetDetached", bool(detached))

    def load_usage_widget_placement(self):
        return self.placement._load_saved_window_placement("usage/widgetPlacement")

    def save_usage_widget_placement(self, placement):
        self.placement._save_saved_window_placement("usage/widgetPlacement", placement)

    def reset_usage_widget_placement(self):
        for key in (
            "screenName",
            "x",
            "y",
            "workX",
            "workY",
            "workWidth",
            "workHeight",
            "relativeX",
            "relativeY",
        ):
            self.settings.remove(f"usage/widgetPlacement/{key}")

    def _ensure_usage_widget_settings(self):
        try:
            version = int(self.settings.value("usage/widgetConfigVersion", 0) or 0)
        except (TypeError, ValueError):
            version = 0
        if version >= USAGE_WIDGET_CONFIG_VERSION:
            return
        # One-time move from the version 1 presets (stage 14). The old keys stay
        # untouched so an older build still reads its own settings.
        layout = str(self.settings.value("usage/widgetLayoutPreset", "") or "")
        graph = str(self.settings.value("usage/widgetGraphMetric", "") or "")
        limit_key = str(self.settings.value("usage/widgetLimitKey", "") or "")
        color = self.settings.value("usage/widgetBackgroundColor", None)
        emphasis = (
            "seven_day"
            if limit_key.endswith("|secondary")
            else "five_hour"
            if limit_key.endswith("|primary")
            else "auto"
        )
        custom = (
            color is not None
            and normalize_usage_widget_color(color) != DEFAULT_USAGE_WIDGET_COLOR
        )
        self.settings.setValue("usage/widgetShape", USAGE_WIDGET_SHAPES[0])
        self.settings.setValue("usage/widgetEmphasis", emphasis)
        self.settings.setValue("usage/widgetTasksVisible", True)
        self.settings.setValue(
            "usage/widgetTodayVisible", layout == "detailed" or graph == "local_tokens"
        )
        self.settings.setValue("usage/widgetThemeMode", "custom" if custom else "app")
        self.settings.setValue("usage/widgetConfigVersion", USAGE_WIDGET_CONFIG_VERSION)

    def _load_choice(self, key, choices):
        self._ensure_usage_widget_settings()
        return normalize_usage_widget_choice(self.settings.value(key, ""), choices)

    def _save_choice(self, key, value, choices):
        self._ensure_usage_widget_settings()
        value = normalize_usage_widget_choice(value, choices)
        self.settings.setValue(key, value)
        return value

    def _load_flag(self, key, default):
        self._ensure_usage_widget_settings()
        return self.settings.value(key, default, type=bool)

    def _save_flag(self, key, value):
        self._ensure_usage_widget_settings()
        self.settings.setValue(key, bool(value))
        return bool(value)

    def load_usage_widget_shape(self):
        return self._load_choice("usage/widgetShape", USAGE_WIDGET_SHAPES)

    def save_usage_widget_shape(self, shape):
        return self._save_choice("usage/widgetShape", shape, USAGE_WIDGET_SHAPES)

    def load_usage_widget_emphasis(self):
        return self._load_choice("usage/widgetEmphasis", USAGE_WIDGET_EMPHASES)

    def save_usage_widget_emphasis(self, emphasis):
        return self._save_choice(
            "usage/widgetEmphasis", emphasis, USAGE_WIDGET_EMPHASES
        )

    def load_usage_widget_tasks_visible(self):
        return self._load_flag("usage/widgetTasksVisible", True)

    def save_usage_widget_tasks_visible(self, visible):
        return self._save_flag("usage/widgetTasksVisible", visible)

    def load_usage_widget_today_visible(self):
        return self._load_flag("usage/widgetTodayVisible", False)

    def save_usage_widget_today_visible(self, visible):
        return self._save_flag("usage/widgetTodayVisible", visible)

    def load_usage_widget_theme_mode(self):
        return self._load_choice("usage/widgetThemeMode", USAGE_WIDGET_THEME_MODES)

    def save_usage_widget_theme_mode(self, mode):
        return self._save_choice(
            "usage/widgetThemeMode", mode, USAGE_WIDGET_THEME_MODES
        )

    def load_usage_widget_material(self):
        return self._load_choice("usage/widgetMaterial", USAGE_WIDGET_MATERIALS)

    def save_usage_widget_material(self, material):
        return self._save_choice(
            "usage/widgetMaterial", material, USAGE_WIDGET_MATERIALS
        )

    def load_usage_widget_limit_key(self):
        """The Codex limit the usage service charts hourly, from the emphasis."""
        return USAGE_WIDGET_EMPHASIS_LIMIT_KEYS[self.load_usage_widget_emphasis()]

    def load_usage_widget_background_color(self):
        return normalize_usage_widget_color(
            self.settings.value(
                "usage/widgetBackgroundColor", DEFAULT_USAGE_WIDGET_COLOR
            )
        )

    def save_usage_widget_background_color(self, color):
        color = normalize_usage_widget_color(color)
        self.settings.setValue("usage/widgetBackgroundColor", color)
        return color

    def load_usage_widget_background_opacity(self):
        return normalize_usage_widget_opacity(
            self.settings.value(
                "usage/widgetBackgroundOpacity", DEFAULT_USAGE_WIDGET_OPACITY
            )
        )

    def save_usage_widget_background_opacity(self, opacity):
        opacity = normalize_usage_widget_opacity(opacity)
        self.settings.setValue("usage/widgetBackgroundOpacity", opacity)
        return opacity

    def reset_usage_widget_style(self):
        self.settings.remove("usage/widgetBackgroundColor")
        self.settings.remove("usage/widgetBackgroundOpacity")
        self.settings.remove("usage/widgetMaterial")

    def load_usage_widget_scale(self):
        key = "usage/widgetScalePercent"
        raw_value = self.settings.value(key, None)
        if raw_value is None:
            return DEFAULT_USAGE_WIDGET_SCALE
        try:
            basis_version = int(self.settings.value("usage/widgetScaleBasisVersion", 1))
        except (TypeError, ValueError):
            basis_version = 1
        if basis_version < USAGE_WIDGET_SCALE_BASIS_VERSION:
            scale_percent = migrate_legacy_usage_widget_scale(raw_value)
            self.settings.setValue(key, scale_percent)
            self.settings.setValue(
                "usage/widgetScaleBasisVersion", USAGE_WIDGET_SCALE_BASIS_VERSION
            )
            return scale_percent
        return normalize_usage_widget_scale(raw_value)

    def save_usage_widget_scale(self, scale_percent):
        scale_percent = normalize_usage_widget_scale(scale_percent)
        self.settings.setValue("usage/widgetScalePercent", scale_percent)
        self.settings.setValue(
            "usage/widgetScaleBasisVersion", USAGE_WIDGET_SCALE_BASIS_VERSION
        )
        return scale_percent

    def reset_usage_widget_scale(self):
        self.settings.remove("usage/widgetScalePercent")
        self.settings.setValue(
            "usage/widgetScaleBasisVersion", USAGE_WIDGET_SCALE_BASIS_VERSION
        )

    def load_usage_widget_hour_range(self):
        return normalize_usage_widget_hour_range(
            self.settings.value("usage/widgetHourlyStartHour", 0),
            self.settings.value("usage/widgetHourlyEndHour", 24),
        )

    def save_usage_widget_hour_range(self, start_hour, end_hour):
        start_hour, end_hour = normalize_usage_widget_hour_range(start_hour, end_hour)
        self.settings.setValue("usage/widgetHourlyStartHour", start_hour)
        self.settings.setValue("usage/widgetHourlyEndHour", end_hour)
        return start_hour, end_hour

    def reset_usage_widget_hour_range(self):
        self.settings.remove("usage/widgetHourlyStartHour")
        self.settings.remove("usage/widgetHourlyEndHour")
