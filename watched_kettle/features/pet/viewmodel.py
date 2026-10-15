"""A narrow UI boundary around the visible pet surface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from watched_kettle.pet.bubble_theme import bubble_theme_from_manifest
from watched_kettle.bubble_timing import BubbleDurationPolicy

if TYPE_CHECKING:
    from watched_kettle.pet.bubble_theme import SpeechBubbleTheme
    from watched_kettle.pet.window import DesktopPet
    from watched_kettle.features.pet.contracts import BubbleElementRegistry


@dataclass(frozen=True)
class PetSnapshot:
    pet_id: str
    display_name: str
    visual_state: str
    active_count: int
    visible: bool
    always_on_top: bool
    bubbles_enabled: bool
    activity_labels_enabled: bool
    idle_activities_enabled: bool
    auto_movement_enabled: bool
    pet_width: int
    look_range: int
    bubble_scale: int
    bubble_duration_seconds: int
    bubble_theme_mode: str
    bubbles_snoozed: bool
    bubble_snooze_remaining_minutes: int
    bubble_duration_policy: BubbleDurationPolicy = BubbleDurationPolicy()
    working_sources: tuple[str, ...] = ()
    opacity_percent: int = 100
    shadow: bool = False
    fade: bool = True


@dataclass(frozen=True)
class BubbleEditorState:
    """Read-only inputs required by the per-pet bubble editor."""

    display_name: str
    registry: BubbleElementRegistry
    theme: SpeechBubbleTheme
    package_theme: SpeechBubbleTheme


class PetViewModel(QObject):
    """Expose pet display state and commands without leaking UI ownership."""

    snapshot_changed = Signal(object)

    def __init__(self, pet: DesktopPet, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.pet = pet
        self.snapshot = self._snapshot()
        pet.controls_changed.connect(self.refresh)

    def refresh(self) -> PetSnapshot:
        updated = self._snapshot()
        if updated != self.snapshot:
            self.snapshot = updated
            self.snapshot_changed.emit(updated)
        return updated

    def available_pets(self):
        return self.pet.available_pets()

    def all_pets(self):
        """Return every valid package, including entries hidden from pickers."""
        return self.pet.all_pets()

    def catalog_preferences(self):
        """Return the persisted sort mode, order, and hidden package IDs."""
        preferences = self.pet.app_preferences
        return (
            preferences.load_pet_catalog_sort_mode(),
            preferences.load_pet_custom_order(),
            preferences.load_hidden_pet_ids(),
        )

    def save_catalog_preferences(self, sort_mode, custom_order, hidden_ids):
        """Persist a complete catalog edit and publish its visible result."""
        preferences = self.pet.app_preferences
        preferences.save_pet_catalog_sort_mode(sort_mode)
        preferences.save_pet_custom_order(custom_order)
        preferences.save_hidden_pet_ids(hidden_ids)
        self.refresh()

    @property
    def bubble_editor_state(self) -> BubbleEditorState:
        """Return immutable inputs needed to construct the bubble editor."""
        pet = self.pet
        return BubbleEditorState(
            display_name=pet.pet_display_name,
            registry=pet.bubble_element_registry,
            theme=(
                pet.custom_bubble_theme
                or bubble_theme_from_manifest(pet.manifest)
                or pet.bubble_controller.theme
            ),
            package_theme=(
                bubble_theme_from_manifest(pet.manifest) or pet.bubble_controller.theme
            ),
        )

    def refresh_bubble_elements(self):
        """Reload imported safe image elements used by visible bubbles."""
        self.pet.bubble_controller.refresh_element_assets()

    def save_custom_bubble_theme(self, theme):
        """Apply and persist one custom theme for the current package."""
        self.pet.set_custom_bubble_theme(theme)
        self.refresh()

    def reset_custom_bubble_theme(self):
        """Restore the current package theme and remove its custom override."""
        self.pet.clear_custom_bubble_theme()
        self.refresh()

    def change_pet(self, pet_id):
        changed = self.pet.change_pet(pet_id)
        self.refresh()
        return changed

    def set_width(self, value):
        self.pet.set_pet_width(value)
        self.refresh()

    def set_look_range(self, value):
        self.pet.set_look_range(value)
        self.refresh()

    def set_always_on_top(self, value):
        self.pet.set_always_on_top(value)
        self.refresh()

    def set_bubbles_enabled(self, value):
        self.pet.set_bubbles_enabled(value)
        self.refresh()

    def set_activity_labels_enabled(self, value):
        self.pet.set_activity_labels_enabled(value)
        self.refresh()

    def set_opacity(self, value):
        self.pet.set_opacity_percent(value)
        self.refresh()

    def set_shadow(self, value):
        self.pet.set_shadow_enabled(value)
        self.refresh()

    def set_fade(self, value):
        self.pet.set_fade_enabled(value)
        self.refresh()

    def set_idle_activities_enabled(self, value):
        self.pet.set_idle_activities_enabled(value)
        self.refresh()

    def set_auto_movement_enabled(self, value):
        self.pet.set_auto_movement_enabled(value)
        self.refresh()

    def set_bubble_scale(self, value):
        self.pet.set_bubble_scale(value)
        self.refresh()

    def set_bubble_duration(self, value):
        self.pet.set_bubble_duration_seconds(value)
        self.refresh()

    def set_bubble_duration_override(self, kind, value):
        self.pet.set_bubble_duration_override(kind, value)
        self.refresh()

    def reset_bubble_durations(self):
        self.pet.reset_bubble_durations()
        self.refresh()

    def clear_bubble_duration_overrides(self):
        self.pet.clear_bubble_duration_overrides()
        self.refresh()

    def set_bubble_theme(self, value):
        self.pet.set_bubble_theme_mode(value)
        self.refresh()

    def set_auto_movement_screen(self, mode, name=""):
        self.pet.set_auto_movement_screen(mode, name)
        self.refresh()

    def test_animation(self, state):
        self.pet.set_state(state)

    def test_movement(self):
        return self.pet.start_auto_movement_test()

    def move_to_auto_movement_screen(self):
        self.pet.move_to_auto_movement_screen()
        self.refresh()

    def recenter(self):
        self.pet.move_to_screen_center()
        self.refresh()

    def toggle_visibility(self):
        self.pet.toggle_visibility()
        self.refresh()

    def reset_agent_state(self):
        self.pet.reset_agent_state()
        self.refresh()

    def preview_bubble(self, message):
        self.pet.bubble_controller.preview(message)

    def snooze_bubbles(self, milliseconds):
        self.pet.bubble_controller.snooze(milliseconds)
        self.refresh()

    def resume_bubbles(self):
        self.pet.bubble_controller.resume()
        self.refresh()

    def restore_agent_display(self):
        self.pet.restore_agent_display_state()
        self.refresh()

    def available_screens(self):
        return self.pet.available_auto_movement_screens()

    def open_pet_folder(self):
        self.pet.user_pets_root.mkdir(parents=True, exist_ok=True)
        return QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self.pet.user_pets_root))
        )

    def _snapshot(self):
        presentation = getattr(self.pet.agent_controller, "current_presentation", None)
        bubble_controller = self.pet.bubble_controller
        return PetSnapshot(
            pet_id=self.pet.pet_id,
            display_name=self.pet.pet_display_name,
            visual_state=self.pet.current_state or "idle",
            active_count=presentation.active_count if presentation else 0,
            working_sources=tuple(getattr(presentation, "working_sources", ()) or ()),
            visible=self.pet.isVisible(),
            always_on_top=self.pet.always_on_top,
            bubbles_enabled=self.pet.bubbles_enabled,
            activity_labels_enabled=self.pet.activity_labels_enabled,
            opacity_percent=self.pet.opacity_percent,
            shadow=self.pet.shadow_enabled,
            fade=self.pet.fade_enabled,
            idle_activities_enabled=self.pet.activity_controller.enabled,
            auto_movement_enabled=self.pet.movement_controller.enabled,
            pet_width=self.pet.pet_width,
            look_range=self.pet.look_range,
            bubble_scale=self.pet.bubble_scale,
            bubble_duration_seconds=self.pet.bubble_duration_seconds,
            bubble_duration_policy=self.pet.bubble_duration_policy,
            bubble_theme_mode=self.pet.bubble_theme_mode,
            bubbles_snoozed=bool(getattr(bubble_controller, "is_snoozed", False)),
            bubble_snooze_remaining_minutes=int(
                getattr(bubble_controller, "snooze_remaining_minutes", 0) or 0
            ),
        )
