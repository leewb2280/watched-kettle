"""Pet catalog access and safe live package switching for DesktopPet."""

import json
from pathlib import Path

from PIL import UnidentifiedImageError
from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices

from watched_kettle.config import (
    DEFAULT_LOOK_RANGE,
    DEFAULT_PET_WIDTH,
    FRAME_HEIGHT,
    FRAME_WIDTH,
)
from watched_kettle.pet.activity_controller import load_idle_activities
from watched_kettle.pet.catalog import (
    discover_pets_in_roots,
    personalize_pet_catalog,
)
from watched_kettle.pet.loader import load_pet
from watched_kettle.pet.preferences import PetPreferences
from watched_kettle.pet.bubble_theme import resolve_bubble_theme


class PetPackageMixin:
    @property
    def pet_id(self):
        return str(self.manifest.get("id", self.pet_directory.name))

    @property
    def pet_display_name(self):
        return str(
            self.manifest.get("displayName")
            or self.manifest.get("name")
            or self.pet_directory.name
        )

    def all_pets(self):
        return discover_pets_in_roots(self.pets_roots)

    def available_pets(self):
        return personalize_pet_catalog(
            self.all_pets(),
            self.app_preferences.load_pet_catalog_sort_mode(),
            self.app_preferences.load_pet_custom_order(),
            self.app_preferences.load_hidden_pet_ids(),
            required_visible_id=self.pet_id,
        )

    def open_user_pets_folder(self):
        """Create and open the durable folder for user-installed pets."""
        try:
            self.user_pets_root.mkdir(parents=True, exist_ok=True)
        except OSError:
            return False
        return QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self.user_pets_root.resolve()))
        )

    def user_pet_folder_counts(self, available_pets=None):
        """Return valid and incomplete immediate child counts for status UI."""
        available_pets = available_pets or self.all_pets()
        root = Path(self.user_pets_root)
        try:
            candidate_directories = [path for path in root.iterdir() if path.is_dir()]
        except OSError:
            candidate_directories = []
        valid_count = sum(
            1
            for entry in available_pets
            if entry.directory.parent.resolve() == root.resolve()
        )
        return valid_count, max(0, len(candidate_directories) - valid_count)

    def change_pet(self, pet_id):
        next_pet = next(
            (entry for entry in self.available_pets() if entry.id == str(pet_id)),
            None,
        )
        if next_pet is None:
            return False
        if next_pet.directory.resolve() == self.pet_directory.resolve():
            self.app_preferences.save_selected_pet_id(self.pet_id)
            return True

        try:
            manifest, frames, look_frames, sprite_version = load_pet(next_pet.directory)
            next_pet_id = str(manifest.get("id", next_pet.directory.name))
            look_direction_offset = int(manifest.get("lookDirectionOffset", 0)) % 16
            look_direction_mirrored = bool(manifest.get("lookDirectionMirrored", False))
            preferences = PetPreferences(
                next_pet_id,
                self.shared_settings,
            )
            default_theme_mode = self.app_preferences.load_bubble_theme_mode()
            if default_theme_mode == "custom":
                default_theme_mode = "character"
            bubble_theme_mode = preferences.load_bubble_theme_mode(default_theme_mode)
            custom_bubble_theme = preferences.load_custom_bubble_theme()
            pet_width = preferences.load_width(
                manifest.get("defaultWidth", DEFAULT_PET_WIDTH)
            )
            always_on_top = preferences.load_always_on_top()
            look_range = preferences.load_look_range(
                manifest.get("defaultLookRange", DEFAULT_LOOK_RANGE)
            )
            idle_activities = load_idle_activities(manifest, frames)
            idle_activities_enabled = preferences.load_idle_activities_enabled()
            auto_movement_enabled = preferences.load_auto_movement_enabled()
        except (
            FileNotFoundError,
            json.JSONDecodeError,
            OSError,
            TypeError,
            UnidentifiedImageError,
            ValueError,
        ):
            return False

        old_center = self.frameGeometry().center()
        was_visible = self.isVisible()
        self.timer.stop()
        self.activity_controller.cancel()
        self.activity_controller.deleteLater()
        self.movement_controller.cancel()
        self.movement_controller.deleteLater()

        self.pet_directory = next_pet.directory
        self.manifest = manifest
        self.frames = frames
        self.look_frames = look_frames
        self.sprite_version = sprite_version
        self.look_direction_index = None
        self.pointer_near = False
        self.current_state = None
        self.current_frame = 0
        self.double_click_waving = False
        self.renderer.clear()

        self.look_direction_offset = look_direction_offset
        self.look_direction_mirrored = look_direction_mirrored

        self.preferences = preferences
        self.bubble_theme_mode = bubble_theme_mode
        self.custom_bubble_theme = custom_bubble_theme
        self.pet_width = pet_width
        self.scale_factor = self.pet_width / FRAME_WIDTH
        self.always_on_top = always_on_top
        self.look_range = look_range
        self.setWindowFlag(
            Qt.WindowType.WindowStaysOnTopHint,
            self.always_on_top,
        )
        self.bubble_controller.sync_always_on_top(self.always_on_top)
        self.bubble_controller.set_theme(
            resolve_bubble_theme(
                self.manifest,
                self.bubble_theme_mode,
                self.custom_bubble_theme,
            )
        )
        self.activity_caption_controller.sync_always_on_top(self.always_on_top)
        self.setFixedSize(
            self.pet_width,
            round(self.pet_width * FRAME_HEIGHT / FRAME_WIDTH),
        )
        self.move(
            old_center.x() - self.width() // 2,
            old_center.y() - self.height() // 2,
        )
        self.keep_on_screen()

        self.setup_idle_activities(
            idle_activities,
            idle_activities_enabled,
        )
        self.setup_auto_movement(auto_movement_enabled)
        desired_state = self.agent_controller.desired_state
        self.set_state(
            desired_state if desired_state in self.frames else "idle",
            source="agent",
        )
        self.app_preferences.save_selected_pet_id(self.pet_id)

        if was_visible:
            self.show()
        self.refresh_controls()
        self.update()
        return True
