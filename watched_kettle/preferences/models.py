"""Application-wide preferences shared by every pet package."""

import json


BUBBLE_SCALE_MIN = 80
BUBBLE_SCALE_MAX = 140
BUBBLE_SCALE_STEP = 10
DEFAULT_BUBBLE_SCALE = 100
BUBBLE_DURATION_MIN_SECONDS = 5
BUBBLE_DURATION_MAX_SECONDS = 60
BUBBLE_DURATION_STEP_SECONDS = 1
DEFAULT_BUBBLE_DURATION_SECONDS = 8
PET_CATALOG_SORT_NAME = "name"
PET_CATALOG_SORT_CUSTOM = "custom"
PET_CATALOG_SORT_MODES = frozenset(
    {
        PET_CATALOG_SORT_NAME,
        PET_CATALOG_SORT_CUSTOM,
    }
)
DEFAULT_USAGE_WIDGET_COLOR = "#263246"
DEFAULT_USAGE_WIDGET_OPACITY = 93
USAGE_WIDGET_OPACITY_MIN = 0
USAGE_WIDGET_OPACITY_MAX = 100
USAGE_WIDGET_SCALE_MIN = 70
USAGE_WIDGET_SCALE_MAX = 130
USAGE_WIDGET_SCALE_STEP = 10
DEFAULT_USAGE_WIDGET_SCALE = 100
USAGE_WIDGET_SCALE_BASIS_VERSION = 2
LEGACY_USAGE_WIDGET_SCALE_MIN = 80
LEGACY_USAGE_WIDGET_SCALE_MAX = 160
LEGACY_USAGE_WIDGET_SCALE_BASE = 130
DEFAULT_USAGE_WIDGET_HOUR_RANGE = (0, 24)
USAGE_WIDGET_CONFIG_VERSION = 2
USAGE_WIDGET_SHAPES = ("rings", "bars", "chips")
DEFAULT_USAGE_WIDGET_SHAPE = "rings"
USAGE_WIDGET_EMPHASES = ("auto", "five_hour", "seven_day")
USAGE_WIDGET_THEME_MODES = ("app", "custom")
# Background material: an opaque card, or Windows 11 acrylic behind it.
USAGE_WIDGET_MATERIALS = ("opaque", "acrylic")
# The usage service still aggregates hourly quota changes for one Codex limit;
# the widget emphasis picks it.
USAGE_WIDGET_EMPHASIS_LIMIT_KEYS = {
    "auto": "",
    "five_hour": "codex|primary",
    "seven_day": "codex|secondary",
}


def normalize_usage_widget_choice(value, choices):
    """Return a known choice, falling back to the first (default) one."""
    value = str(value or "").strip().casefold()
    return value if value in choices else choices[0]


def normalize_usage_widget_color(value):
    value = str(value or "").strip().upper()
    if len(value) == 7 and value.startswith("#"):
        try:
            int(value[1:], 16)
        except ValueError:
            pass
        else:
            return value
    return DEFAULT_USAGE_WIDGET_COLOR


def normalize_usage_widget_opacity(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = DEFAULT_USAGE_WIDGET_OPACITY
    return min(USAGE_WIDGET_OPACITY_MAX, max(USAGE_WIDGET_OPACITY_MIN, value))


def normalize_usage_widget_scale(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = DEFAULT_USAGE_WIDGET_SCALE
    value = min(USAGE_WIDGET_SCALE_MAX, max(USAGE_WIDGET_SCALE_MIN, value))
    return round(value / USAGE_WIDGET_SCALE_STEP) * USAGE_WIDGET_SCALE_STEP


def migrate_legacy_usage_widget_scale(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return DEFAULT_USAGE_WIDGET_SCALE
    value = min(
        LEGACY_USAGE_WIDGET_SCALE_MAX, max(LEGACY_USAGE_WIDGET_SCALE_MIN, value)
    )
    converted = value * 100 / LEGACY_USAGE_WIDGET_SCALE_BASE
    return normalize_usage_widget_scale(converted)


def normalize_usage_widget_hour_range(start_hour, end_hour):
    try:
        start_hour = int(start_hour)
        end_hour = int(end_hour)
    except (TypeError, ValueError):
        return DEFAULT_USAGE_WIDGET_HOUR_RANGE
    if 0 <= start_hour <= 23 and 1 <= end_hour <= 24 and start_hour < end_hour:
        return start_hour, end_hour
    return DEFAULT_USAGE_WIDGET_HOUR_RANGE


def normalize_pet_id_list(value):
    """Return unique, non-empty pet IDs from one persisted JSON value."""
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return ()
    if not isinstance(value, (list, tuple)):
        return ()

    normalized = []
    seen = set()
    for pet_id in value:
        pet_id = str(pet_id or "").strip()
        if not pet_id or pet_id in seen:
            continue
        normalized.append(pet_id)
        seen.add(pet_id)
    return tuple(normalized)


def normalize_bubble_scale(value):
    try:
        scale = int(value)
    except (TypeError, ValueError):
        scale = DEFAULT_BUBBLE_SCALE
    scale = min(max(scale, BUBBLE_SCALE_MIN), BUBBLE_SCALE_MAX)
    steps = round((scale - BUBBLE_SCALE_MIN) / BUBBLE_SCALE_STEP)
    return BUBBLE_SCALE_MIN + steps * BUBBLE_SCALE_STEP


def normalize_bubble_duration_seconds(value):
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        seconds = DEFAULT_BUBBLE_DURATION_SECONDS
    return min(
        max(seconds, BUBBLE_DURATION_MIN_SECONDS),
        BUBBLE_DURATION_MAX_SECONDS,
    )
