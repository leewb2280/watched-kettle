import json

from watched_kettle.application.settings_store import open_settings

from watched_kettle.config import (
    DEFAULT_LOOK_RANGE,
    DEFAULT_PET_WIDTH,
    FRAME_WIDTH,
    LOOK_RANGE_MAX,
    LOOK_RANGE_MIN,
    LOOK_RANGE_STEP,
    PET_WIDTH_OPTIONS,
)
from watched_kettle.pet.bubble_frame import frame_style_for, is_frame_style
from watched_kettle.pet.bubble_theme import (
    bubble_theme_from_dict,
    bubble_theme_to_dict,
    normalize_bubble_theme_mode,
)


class PetPreferences:
    """Persist per-pet display and behavior preferences."""

    def __init__(self, pet_id, settings=None):
        self.settings = settings if settings is not None else open_settings()
        self.pet_id = str(pet_id)
        self.prefix = f"pets/{pet_id}"

    def load_width(self, default_width=DEFAULT_PET_WIDTH):
        saved_width = self.settings.value(
            f"{self.prefix}/width",
        )
        migrated_legacy_scale = False

        if saved_width is None:
            legacy_scale = self.settings.value(
                f"{self.prefix}/scale",
            )

            if legacy_scale is not None:
                migrated_legacy_scale = True
                try:
                    saved_width = float(legacy_scale) * FRAME_WIDTH
                except (TypeError, ValueError):
                    saved_width = default_width
            else:
                saved_width = default_width

        try:
            saved_width = int(round(float(saved_width)))
        except (TypeError, ValueError):
            saved_width = DEFAULT_PET_WIDTH

        selected_width = min(
            PET_WIDTH_OPTIONS,
            key=lambda option: abs(option - saved_width),
        )

        if migrated_legacy_scale:
            self.save_width(selected_width)

        return selected_width

    def save_width(self, pet_width):
        self.settings.setValue(
            f"{self.prefix}/width",
            pet_width,
        )
        self.settings.remove(f"{self.prefix}/scale")

    def load_idle_activities_enabled(self):
        return self.settings.value(
            f"{self.prefix}/idleActivitiesEnabled",
            True,
            type=bool,
        )

    def save_idle_activities_enabled(self, enabled):
        self.settings.setValue(
            f"{self.prefix}/idleActivitiesEnabled",
            bool(enabled),
        )

    def load_auto_movement_enabled(self):
        return self.settings.value(
            f"{self.prefix}/autoMovementEnabled",
            False,
            type=bool,
        )

    def save_auto_movement_enabled(self, enabled):
        self.settings.setValue(
            f"{self.prefix}/autoMovementEnabled",
            bool(enabled),
        )

    def load_always_on_top(self):
        return self.settings.value(
            f"{self.prefix}/alwaysOnTop",
            True,
            type=bool,
        )

    def save_always_on_top(self, enabled):
        self.settings.setValue(
            f"{self.prefix}/alwaysOnTop",
            bool(enabled),
        )

    def load_bubble_theme_mode(self, default="character"):
        return normalize_bubble_theme_mode(
            self.settings.value(
                f"{self.prefix}/bubbleThemeMode",
                default,
            )
        )

    def save_bubble_theme_mode(self, mode):
        mode = normalize_bubble_theme_mode(mode)
        self.settings.setValue(
            f"{self.prefix}/bubbleThemeMode",
            mode,
        )
        return mode

    def load_custom_bubble_theme(self):
        value = self.settings.value(f"{self.prefix}/bubbleCustomTheme")
        if not value:
            return None
        try:
            data = json.loads(str(value))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        # Themes saved before frames moved into pet packages name the old
        # built-in frame; that frame now ships with this pet as "pet:<id>".
        saved_frame = str(data.get("frame_style") or "standard").strip()
        if not is_frame_style(saved_frame):
            data = {**data, "frame_style": frame_style_for(self.pet_id)}
        return bubble_theme_from_dict(data)

    def save_custom_bubble_theme(self, theme):
        self.settings.setValue(
            f"{self.prefix}/bubbleCustomTheme",
            json.dumps(
                bubble_theme_to_dict(theme),
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )

    def clear_custom_bubble_theme(self):
        self.settings.remove(f"{self.prefix}/bubbleCustomTheme")

    def load_look_range(self, default_range=DEFAULT_LOOK_RANGE):
        saved_range = self.settings.value(
            f"{self.prefix}/lookRange",
            default_range,
        )
        try:
            saved_range = int(round(float(saved_range)))
        except (TypeError, ValueError):
            saved_range = DEFAULT_LOOK_RANGE

        saved_range = min(
            max(saved_range, LOOK_RANGE_MIN),
            LOOK_RANGE_MAX,
        )
        return (
            LOOK_RANGE_MIN
            + round((saved_range - LOOK_RANGE_MIN) / LOOK_RANGE_STEP) * LOOK_RANGE_STEP
        )

    def save_look_range(self, look_range):
        self.settings.setValue(
            f"{self.prefix}/lookRange",
            int(look_range),
        )
