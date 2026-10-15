"""bubbles preferences; existing QSettings keys are preserved."""

from watched_kettle.bubble_timing import BubbleDurationPolicy, DURATION_KINDS
from watched_kettle.pet.bubble_theme import (
    DEFAULT_BUBBLE_THEME_MODE,
    normalize_bubble_theme_mode,
)

from .models import (
    DEFAULT_BUBBLE_SCALE,
    DEFAULT_BUBBLE_DURATION_SECONDS,
    normalize_bubble_scale,
    normalize_bubble_duration_seconds,
)


class BubblesPreferences:
    def __init__(self, settings, placement=None):
        self.settings = settings
        self.placement = placement

    def load_bubbles_enabled(self):
        return self.settings.value(
            "bubblesEnabled",
            True,
            type=bool,
        )

    def save_bubbles_enabled(self, enabled):
        self.settings.setValue("bubblesEnabled", bool(enabled))

    def load_bubble_scale(self):
        return normalize_bubble_scale(
            self.settings.value(
                "bubbleScalePercent",
                DEFAULT_BUBBLE_SCALE,
            )
        )

    def save_bubble_scale(self, scale):
        scale = normalize_bubble_scale(scale)
        self.settings.setValue("bubbleScalePercent", scale)
        return scale

    def load_bubble_duration_seconds(self):
        return normalize_bubble_duration_seconds(
            self.settings.value(
                "bubbleDurationSeconds",
                DEFAULT_BUBBLE_DURATION_SECONDS,
            )
        )

    def save_bubble_duration_seconds(self, seconds):
        seconds = normalize_bubble_duration_seconds(seconds)
        self.settings.setValue("bubbleDurationSeconds", seconds)
        return seconds

    def load_bubble_duration_policy(self):
        policy = BubbleDurationPolicy(common=self.load_bubble_duration_seconds())
        for kind in DURATION_KINDS:
            value = self.settings.value(f"bubbleDurationOverrides/{kind}", None)
            if value is not None:
                policy = policy.with_override(
                    kind, normalize_bubble_duration_seconds(value)
                )
        return policy

    def save_bubble_duration_policy(self, policy):
        self.save_bubble_duration_seconds(policy.common)
        for kind in DURATION_KINDS:
            key = f"bubbleDurationOverrides/{kind}"
            value = getattr(policy, kind)
            if value is None:
                self.settings.remove(key)
            else:
                self.settings.setValue(key, normalize_bubble_duration_seconds(value))

    def load_bubble_theme_mode(self):
        return normalize_bubble_theme_mode(
            self.settings.value(
                "bubbleThemeMode",
                DEFAULT_BUBBLE_THEME_MODE,
            )
        )

    def save_bubble_theme_mode(self, mode):
        mode = normalize_bubble_theme_mode(mode)
        self.settings.setValue("bubbleThemeMode", mode)
        return mode

    def load_activity_labels_enabled(self):
        return self.settings.value(
            "activityLabelsEnabled",
            False,
            type=bool,
        )

    def save_activity_labels_enabled(self, enabled):
        self.settings.setValue("activityLabelsEnabled", bool(enabled))
