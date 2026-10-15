# pet_window.py

from pathlib import Path
from dataclasses import replace
from watched_kettle.bubble_timing import BubbleDurationPolicy

from PySide6.QtCore import QPoint, QPropertyAnimation, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QRadialGradient
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
)

from watched_kettle.config import (
    FRAME_WIDTH,
    FRAME_HEIGHT,
    ANIMATIONS,
    DEFAULT_LOOK_RANGE,
    LOOK_RANGE_MAX,
    LOOK_RANGE_MIN,
    LOOK_RANGE_STEP,
    PET_WIDTH_OPTIONS,
    DEFAULT_PET_WIDTH,
)

from watched_kettle.app_preferences import (
    ApplicationPreferences,
    normalize_bubble_duration_seconds,
    normalize_bubble_scale,
)
from watched_kettle.pet.loader import load_pet
from watched_kettle.pet.activity_controller import (
    IdleActivityController,
    load_idle_activities,
)
from watched_kettle.pet.movement_controller import AutoMovementController
from watched_kettle.pet.preferences import PetPreferences
from watched_kettle.pet.renderer import PetFrameRenderer
from watched_kettle.pet.package_switching import PetPackageMixin
from watched_kettle.pet.pointer_interaction import PetPointerController
from watched_kettle.pet.placement_controller import PetPlacementController
from watched_kettle.pet.topmost_guard import TopmostGuard, app_topmost_windows
from watched_kettle.ui.activity_caption import PetActivityCaptionController
from watched_kettle.ui.bubble_elements import BubbleElementRegistry
from watched_kettle.ui.menu import show_pet_context_menu
from watched_kettle.ui.speech_bubble import PetBubbleController
from watched_kettle.pet.bubble_theme import (
    normalize_bubble_theme_mode,
    resolve_bubble_theme,
)


POSITION_SAVE_DELAY_MS = 750


class DesktopPet(
    PetPackageMixin,
    QWidget,
):
    """Render and interact with one pet while runtime services stay external."""

    center_requested = Signal(str)
    controls_changed = Signal()
    usage_widget_visibility_requested = Signal(bool)
    usage_widget_shape_requested = Signal(str)
    usage_widget_tasks_visibility_requested = Signal(bool)
    usage_widget_today_visibility_requested = Signal(bool)
    usage_widget_settings_requested = Signal()
    usage_widget_position_reset_requested = Signal()

    def __init__(
        self,
        pet_directory: Path,
        settings=None,
        pets_roots=None,
        user_pets_root=None,
        bubble_elements_root=None,
        agent_controller_factory=None,
        codex_opener=None,
    ) -> None:
        super().__init__()
        self.placement_controller = PetPlacementController(self)
        self.pointer_controller = PetPointerController(self)

        self.pet_directory = Path(pet_directory)
        self.pets_root = self.pet_directory.parent
        configured_roots = tuple(
            Path(root) for root in (pets_roots or (self.pets_root,))
        )
        if self.pets_root not in configured_roots:
            configured_roots = (*configured_roots, self.pets_root)
        self.pets_roots = configured_roots
        self.user_pets_root = Path(user_pets_root or self.pets_root)
        self.shared_settings = settings
        self.agent_controller_factory = agent_controller_factory
        if codex_opener is None and agent_controller_factory is None:
            # Keep source-mode DesktopPet behavior; pet-only passes an idle factory.
            from importlib import import_module

            codex_opener = import_module(
                "watched_kettle.integrations.codex_launcher"
            ).open_codex_new_conversation
        self.codex_opener = codex_opener
        self.app_preferences = ApplicationPreferences(settings)
        (
            self.auto_movement_screen_mode,
            self.auto_movement_screen_name,
        ) = self.app_preferences.load_auto_movement_screen()
        self.bubbles_enabled = self.app_preferences.load_bubbles_enabled()
        self.bubble_scale = self.app_preferences.load_bubble_scale()
        self.bubble_duration_seconds = (
            self.app_preferences.load_bubble_duration_seconds()
        )
        self.bubble_duration_policy = self.app_preferences.load_bubble_duration_policy()
        self.bubble_theme_mode = self.app_preferences.load_bubble_theme_mode()
        self.opacity_percent = self.app_preferences.load_pet_opacity()
        self.shadow_enabled = self.app_preferences.load_pet_shadow()
        self.fade_enabled = self.app_preferences.load_pet_fade()
        self._fade_animation = None
        self.activity_labels_enabled = (
            self.app_preferences.load_activity_labels_enabled()
        )
        self.dragging = False
        self.drag_offset = QPoint()
        self.last_mouse_x = None
        self.direction_score = 0
        self.double_click_waving = False
        self.pointer_near = False
        self.movement_test_active = False
        self._position_persistence_ready = False
        self.usage_widget_available = False
        self.usage_widget_visible = True
        self.usage_widget_shape = "rings"
        self.usage_widget_tasks_visible = True
        self.usage_widget_today_visible = False
        self.usage_widget_position_customized = False

        # None으로 시작하는 이유:
        # 최초 set_state("idle") 호출이 무시되지 않게 하기 위함
        self.current_state = None
        self.current_frame = 0
        self.look_direction_index = None

        (
            self.manifest,
            self.frames,
            self.look_frames,
            self.sprite_version,
        ) = load_pet(self.pet_directory)
        self.renderer = PetFrameRenderer()

        self.look_direction_offset = (
            int(
                self.manifest.get(
                    "lookDirectionOffset",
                    0,
                )
            )
            % 16
        )
        self.look_direction_mirrored = bool(
            self.manifest.get(
                "lookDirectionMirrored",
                False,
            )
        )

        self.preferences = PetPreferences(
            self.manifest.get("id", self.pet_directory.name),
            settings,
        )
        default_theme_mode = (
            "character"
            if self.bubble_theme_mode == "custom"
            else self.bubble_theme_mode
        )
        self.bubble_theme_mode = self.preferences.load_bubble_theme_mode(
            default_theme_mode
        )
        self.custom_bubble_theme = self.preferences.load_custom_bubble_theme()
        self.bubble_element_registry = BubbleElementRegistry(bubble_elements_root)
        self.pet_width = self.preferences.load_width(
            self.manifest.get("defaultWidth", DEFAULT_PET_WIDTH)
        )
        self.always_on_top = self.preferences.load_always_on_top()
        self.look_range = self.preferences.load_look_range(
            self.manifest.get("defaultLookRange", DEFAULT_LOOK_RANGE)
        )
        self.scale_factor = self.pet_width / FRAME_WIDTH
        idle_activities = load_idle_activities(
            self.manifest,
            self.frames,
        )
        idle_activities_enabled = self.preferences.load_idle_activities_enabled()
        auto_movement_enabled = self.preferences.load_auto_movement_enabled()

        self.setup_window()
        self.setup_animation()
        self.setup_idle_activities(
            idle_activities,
            idle_activities_enabled,
        )
        self.setup_auto_movement(auto_movement_enabled)
        self.setup_bubble()
        self.setup_activity_caption()
        self.setup_agent_state()
        self.setup_look_tracking()
        self.setup_position_persistence()
        # Puts the pet, bubbles and widget back on top when Windows drops them.
        self.topmost_guard = TopmostGuard(
            lambda: self.always_on_top and self.isVisible(),
            lambda: app_topmost_windows(first=self),
            parent=self,
        )

        self.move_to_initial_position()

        self.set_state("idle")

    def setup_window(self):
        window_flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self.always_on_top:
            window_flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(window_flags)

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.setFixedSize(
            self.pet_width,
            round(self.pet_width * FRAME_HEIGHT / FRAME_WIDTH),
        )

    def setup_animation(self):
        self.timer = QTimer(self)

        self.timer.timeout.connect(self.next_frame)

    def setup_idle_activities(self, activities, enabled):
        self.activity_controller = IdleActivityController(
            activities=activities,
            enabled=enabled,
            can_start=self.can_start_idle_activity,
            on_start=self.start_ambient_activity,
            on_finish=self.finish_ambient_activity,
            parent=self,
        )

    def setup_auto_movement(self, enabled):
        self.movement_controller = AutoMovementController(
            enabled=enabled,
            can_start=self.can_start_auto_movement,
            bounds_provider=self.auto_movement_bounds,
            position_provider=self.pos,
            size_provider=self.size,
            on_start=self.start_auto_movement,
            on_move=self.move,
            on_finish=self.finish_auto_movement,
            parent=self,
        )

    def setup_agent_state(self):
        factory = self.agent_controller_factory
        if factory is None:
            # Source compatibility: packaged pet-only entry points inject IdlePetController.
            from importlib import import_module

            factory = import_module(
                "watched_kettle.state.controller"
            ).PetAgentController
        self.agent_controller = factory(
            on_display_state=self.apply_agent_display_state,
            on_presentation=self.apply_agent_presentation,
            parent=self,
        )

    def setup_bubble(self):
        self.bubble_controller = PetBubbleController(
            pet=self,
            enabled=self.bubbles_enabled,
            scale_percent=self.bubble_scale,
            duration_seconds=self.bubble_duration_seconds,
            theme=resolve_bubble_theme(
                self.manifest,
                self.bubble_theme_mode,
                self.custom_bubble_theme,
            ),
            element_registry=self.bubble_element_registry,
            parent=self,
        )

    def setup_activity_caption(self):
        self.activity_caption_controller = PetActivityCaptionController(
            pet=self,
            enabled=self.activity_labels_enabled,
            parent=self,
        )

    def apply_agent_payload(self, payload: object):
        """Apply one normalized or raw agent event to the visible pet."""
        return self.agent_controller.apply_payload(payload)

    def apply_agent_display_state(self, state):
        if self.dragging or self.double_click_waving:
            return

        self.set_state(state, source="agent")

    def apply_agent_presentation(self, presentation):
        caption = getattr(self, "activity_caption_controller", None)
        if caption is not None:
            caption.set_working_sources(getattr(presentation, "working_sources", ()))
        self.bubble_controller.apply(presentation)
        self.refresh_controls()

    def restore_agent_display_state(self):
        self.agent_controller.restore_display()

    def reset_agent_state(self):
        """Return the assistant to idle while preserving privacy-safe history."""
        self.note_user_activity()
        self.agent_controller.clear()
        self.bubble_controller.clear_notices()
        self.refresh_controls()

    def setup_position_persistence(self):
        return self.placement_controller.setup_position_persistence()

    def move_to_initial_position(self):
        return self.placement_controller.move_to_initial_position()

    def available_position_screens(self):
        return self.placement_controller.available_position_screens()

    def restore_window_placement(self):
        return self.placement_controller.restore_window_placement()

    def schedule_position_save(self):
        return self.placement_controller.schedule_position_save()

    def save_window_placement(self):
        return self.placement_controller.save_window_placement()

    def move_to_screen_center(self):
        return self.placement_controller.move_to_screen_center()

    def available_auto_movement_screens(self):
        return self.placement_controller.available_auto_movement_screens()

    @staticmethod
    def screen_identity(screen):
        return PetPlacementController.screen_identity(screen)

    def resolve_auto_movement_screen(self):
        return self.placement_controller.resolve_auto_movement_screen()

    def auto_movement_bounds(self):
        return self.placement_controller.auto_movement_bounds()

    def set_auto_movement_screen(self, mode, name=""):
        return self.placement_controller.set_auto_movement_screen(mode, name)

    def move_to_auto_movement_screen(self):
        return self.placement_controller.move_to_auto_movement_screen()

    def toggle_visibility(self):
        if self.isVisible():
            self.movement_controller.cancel(return_to_idle=True)
            self._fade(0.0, self.hide)
        else:
            self.setWindowOpacity(0.0 if self._fades() else 1.0)
            self.show()
            self.raise_()
            self.activateWindow()
            self.schedule_auto_movement()
            self._fade(1.0)
        self.refresh_controls()

    def _fades(self):
        return self.fade_enabled and not self.app_preferences.load_reduce_motion()

    def _fade(self, target, finished=None):
        """Fade the window, or jump straight there when motion is reduced."""
        if self._fade_animation is not None:
            self._fade_animation.stop()
        if not self._fades():
            self.setWindowOpacity(1.0)
            if finished is not None:
                finished()
            return
        animation = QPropertyAnimation(self, b"windowOpacity", self)
        animation.setDuration(140)
        animation.setEndValue(target)
        if finished is not None:
            # Restore full opacity once hidden, so the next show starts clean.
            animation.finished.connect(finished)
            animation.finished.connect(lambda: self.setWindowOpacity(1.0))
        self._fade_animation = animation
        animation.start()

    def set_opacity_percent(self, percent):
        self.opacity_percent = self.app_preferences.save_pet_opacity(percent)
        self.update()

    def set_shadow_enabled(self, enabled):
        self.shadow_enabled = bool(enabled)
        self.app_preferences.save_pet_shadow(self.shadow_enabled)
        self.update()

    def set_fade_enabled(self, enabled):
        self.fade_enabled = bool(enabled)
        self.app_preferences.save_pet_fade(self.fade_enabled)

    def showEvent(self, event):
        super().showEvent(event)
        bubble_controller = getattr(self, "bubble_controller", None)
        if bubble_controller is not None:
            bubble_controller.owner_shown()
        caption_controller = getattr(
            self,
            "activity_caption_controller",
            None,
        )
        if caption_controller is not None:
            caption_controller.owner_shown()
        if self.current_state == "idle":
            if not hasattr(self, "show_schedule_timer"):
                self.show_schedule_timer = QTimer(self)
                self.show_schedule_timer.setSingleShot(True)
                self.show_schedule_timer.timeout.connect(self.schedule_auto_movement)
            self.show_schedule_timer.start(0)

    def hideEvent(self, event):
        bubble_controller = getattr(self, "bubble_controller", None)
        if bubble_controller is not None:
            bubble_controller.owner_hidden()
        caption_controller = getattr(
            self,
            "activity_caption_controller",
            None,
        )
        if caption_controller is not None:
            caption_controller.owner_hidden()
        super().hideEvent(event)

    def moveEvent(self, event):
        super().moveEvent(event)
        bubble_controller = getattr(self, "bubble_controller", None)
        if bubble_controller is not None:
            bubble_controller.reposition()
        caption_controller = getattr(
            self,
            "activity_caption_controller",
            None,
        )
        if caption_controller is not None:
            caption_controller.reposition()
        self.schedule_position_save()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        bubble_controller = getattr(self, "bubble_controller", None)
        if bubble_controller is not None:
            bubble_controller.reposition()
        caption_controller = getattr(
            self,
            "activity_caption_controller",
            None,
        )
        if caption_controller is not None:
            caption_controller.reposition()

    def closeEvent(self, event):
        for timer in self.findChildren(QTimer):
            timer.stop()
        if getattr(self, "_position_persistence_ready", False):
            self.save_window_placement()
        bubble_controller = getattr(self, "bubble_controller", None)
        if bubble_controller is not None:
            bubble_controller.close()
        caption_controller = getattr(
            self,
            "activity_caption_controller",
            None,
        )
        if caption_controller is not None:
            caption_controller.close()
        super().closeEvent(event)

    def set_always_on_top(self, enabled, persist=True):
        enabled = bool(enabled)
        if enabled == self.always_on_top:
            return

        was_visible = self.isVisible()
        self.always_on_top = enabled
        self.setWindowFlag(
            Qt.WindowType.WindowStaysOnTopHint,
            enabled,
        )
        if was_visible:
            self.show()

        self.bubble_controller.sync_always_on_top(enabled)
        self.activity_caption_controller.sync_always_on_top(enabled)

        if persist:
            self.preferences.save_always_on_top(enabled)
        self.refresh_controls()

    def reveal(self):
        """Show and foreground the existing assistant without moving it."""
        self.show()
        self.raise_()
        self.activateWindow()
        self.schedule_auto_movement()
        self.refresh_controls()

    def set_bubbles_enabled(self, enabled, persist=True):
        self.bubbles_enabled = bool(enabled)
        self.bubble_controller.set_enabled(self.bubbles_enabled)
        if persist:
            self.app_preferences.save_bubbles_enabled(self.bubbles_enabled)
        self.refresh_controls()

    def set_bubble_scale(self, scale, persist=True):
        scale = normalize_bubble_scale(scale)
        self.bubble_scale = scale
        self.bubble_controller.set_scale_percent(scale)
        if persist:
            self.app_preferences.save_bubble_scale(scale)
        self.refresh_controls()
        return scale

    def set_bubble_duration_seconds(self, seconds, persist=True):
        seconds = normalize_bubble_duration_seconds(seconds)
        self.bubble_duration_seconds = seconds
        self.bubble_duration_policy = replace(
            self.bubble_duration_policy, common=seconds
        )
        self.bubble_controller.set_duration_policy(self.bubble_duration_policy)
        if persist:
            self.app_preferences.save_bubble_duration_seconds(seconds)
        self.refresh_controls()
        return seconds

    def set_bubble_duration_override(self, kind, seconds):
        self.bubble_duration_policy = self.bubble_duration_policy.with_override(
            kind, seconds
        )
        self.bubble_controller.set_duration_policy(self.bubble_duration_policy)
        self.app_preferences.save_bubble_duration_policy(self.bubble_duration_policy)
        self.refresh_controls()

    def reset_bubble_durations(self):
        self.bubble_duration_policy = BubbleDurationPolicy()
        self.bubble_duration_seconds = self.bubble_duration_policy.common
        self.bubble_controller.set_duration_policy(self.bubble_duration_policy)
        self.app_preferences.save_bubble_duration_policy(self.bubble_duration_policy)
        self.refresh_controls()

    def clear_bubble_duration_overrides(self):
        self.bubble_duration_policy = replace(
            self.bubble_duration_policy,
            result=None,
            general=None,
            schedule=None,
            completion=None,
        )
        self.bubble_controller.set_duration_policy(self.bubble_duration_policy)
        self.app_preferences.save_bubble_duration_policy(self.bubble_duration_policy)
        self.refresh_controls()

    def set_bubble_theme_mode(self, mode, persist=True):
        mode = normalize_bubble_theme_mode(mode)
        self.bubble_theme_mode = mode
        self.bubble_controller.set_theme(
            resolve_bubble_theme(
                self.manifest,
                mode,
                self.custom_bubble_theme,
            )
        )
        if persist:
            self.app_preferences.save_bubble_theme_mode(mode)
            self.preferences.save_bubble_theme_mode(mode)
        self.refresh_controls()
        return mode

    def set_custom_bubble_theme(self, theme, persist=True):
        self.custom_bubble_theme = theme
        if persist:
            self.preferences.save_custom_bubble_theme(theme)
        self.set_bubble_theme_mode("custom", persist=persist)
        return self.custom_bubble_theme

    def clear_custom_bubble_theme(self, persist=True):
        self.custom_bubble_theme = None
        if persist:
            self.preferences.clear_custom_bubble_theme()
        self.set_bubble_theme_mode("character", persist=persist)

    def set_activity_labels_enabled(self, enabled, persist=True):
        self.activity_labels_enabled = bool(enabled)
        self.activity_caption_controller.set_enabled(self.activity_labels_enabled)
        self.keep_on_screen()
        self.activity_caption_controller.reposition()
        if persist:
            self.app_preferences.save_activity_labels_enabled(
                self.activity_labels_enabled
            )
        self.refresh_controls()

    def show_settings(self) -> None:
        """Request the application-owned Assistant Center pet-settings route."""
        self.note_user_activity()
        self.center_requested.emit("pet_settings")

    def show_usage(self) -> None:
        """Request the application-owned Assistant Center usage route."""
        self.center_requested.emit("usage")

    def refresh_controls(self) -> None:
        """Notify application-owned view models that visible state changed."""
        self.controls_changed.emit()

    def set_pet_width(self, pet_width, persist=True):
        if pet_width not in PET_WIDTH_OPTIONS:
            return

        old_center = self.frameGeometry().center()
        self.pet_width = pet_width
        self.scale_factor = pet_width / FRAME_WIDTH
        self.renderer.clear()

        self.setFixedSize(
            pet_width,
            round(pet_width * FRAME_HEIGHT / FRAME_WIDTH),
        )
        self.move(
            old_center.x() - self.width() // 2,
            old_center.y() - self.height() // 2,
        )
        self.keep_on_screen()

        if persist:
            self.preferences.save_width(pet_width)

        self.note_user_activity()
        self.refresh_controls()
        self.update()

    def set_look_range(self, look_range, persist=True):
        try:
            look_range = int(look_range)
        except (TypeError, ValueError):
            return
        if not LOOK_RANGE_MIN <= look_range <= LOOK_RANGE_MAX:
            return
        if (look_range - LOOK_RANGE_MIN) % LOOK_RANGE_STEP != 0:
            return

        self.look_range = look_range
        if persist:
            self.preferences.save_look_range(look_range)
        self.update_look_direction()
        self.refresh_controls()

    def keep_on_screen(self):
        return self.placement_controller.keep_on_screen()

    def set_state(self, state, source="manual"):
        if state not in self.frames:
            return

        if source != "ambient":
            self.activity_controller.cancel()
        if source != "movement":
            self.movement_test_active = False
            self.movement_controller.cancel()

        if self.current_state == state:
            if state == "idle":
                self.schedule_idle_activity()
                self.schedule_auto_movement()
            return

        if state != "waving":
            self.double_click_waving = False

        self.current_state = state
        self.current_frame = 0
        self.activity_caption_controller.set_state(state)

        if state != "idle":
            self.look_direction_index = None
            self.activity_controller.delay_timer.stop()

        interval = ANIMATIONS[state]["interval"]

        self.timer.start(interval)

        if state == "idle":
            self.schedule_idle_activity()
            self.schedule_auto_movement()

        self.refresh_controls()
        self.update()

    def can_start_idle_activity(self):
        return (
            self.current_state == "idle"
            and not self.dragging
            and not self.pointer_near
            and not self.movement_controller.is_active
            and self.agent_controller.desired_state == "idle"
        )

    def can_start_auto_movement(self):
        return (
            self.current_state == "idle"
            and self.isVisible()
            and not self.dragging
            and not self.pointer_near
            and not self.activity_controller.is_active
            and self.agent_controller.desired_state == "idle"
            and self.auto_movement_bounds() is not None
        )

    def start_ambient_activity(self, state):
        self.set_state(state, source="ambient")

    def finish_ambient_activity(self, state):
        if self.current_state == state:
            self.set_state("idle", source="ambient")

    def start_auto_movement(self, state):
        self.set_state(state, source="movement")

    def finish_auto_movement(self, state):
        if self.movement_test_active:
            self.movement_test_active = False
            self.restore_agent_display_state()
            return
        if self.current_state == state:
            self.set_state("idle", source="movement")

    def schedule_idle_activity(self):
        self.activity_controller.schedule()

    def start_idle_activity(self):
        self.activity_controller.start()

    def finish_idle_activity(self):
        self.activity_controller.finish()

    def schedule_auto_movement(self):
        self.movement_controller.schedule()

    def start_scheduled_auto_movement(self):
        self.movement_controller.start()

    def start_auto_movement_test(self):
        self.note_user_activity()
        if not self.isVisible():
            self.show()
            self.raise_()
        if self.auto_movement_bounds() is None:
            self.move_to_auto_movement_screen()

        self.movement_test_active = True
        self.movement_controller.start(force=True)
        if not self.movement_controller.is_active:
            self.movement_test_active = False
        self.refresh_controls()

    def finish_scheduled_auto_movement(self):
        self.movement_controller.finish()

    def note_user_activity(self):
        self.activity_controller.note_user_activity()
        self.movement_controller.note_user_activity()

    def set_idle_activities_enabled(self, enabled):
        self.preferences.save_idle_activities_enabled(enabled)
        self.activity_controller.set_enabled(enabled)
        self.refresh_controls()

    def set_auto_movement_enabled(self, enabled):
        self.preferences.save_auto_movement_enabled(enabled)
        self.movement_controller.set_enabled(enabled)
        self.refresh_controls()

    def next_frame(self):
        if self.current_state is None:
            return

        frames = self.frames[self.current_state]

        self.current_frame += 1

        if self.current_frame >= len(frames):
            self.current_frame = 0

        self.update()

    def paintEvent(self, event):
        if self.current_state is None:
            return

        painter = QPainter(self)

        painter.setRenderHint(
            QPainter.RenderHint.SmoothPixmapTransform,
            False,
        )

        if (
            self.current_state == "idle"
            and self.look_direction_index is not None
            and self.look_frames
        ):
            pixmap = self.look_frames[self.look_direction_index]

        else:
            pixmap = self.frames[self.current_state][self.current_frame]

        scaled_pixmap = self.renderer.scale(
            pixmap,
            self.size(),
        )
        painter.setOpacity(self.opacity_percent / 100)
        if self.shadow_enabled:
            self._paint_ground_shadow(painter)

        painter.drawPixmap(
            0,
            0,
            scaled_pixmap,
        )

    def _paint_ground_shadow(self, painter):
        """A soft oval under the feet; sprites stand on the window's bottom."""
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        width, height = self.width() * 0.56, max(4.0, self.height() * 0.06)
        rect = QRectF(
            (self.width() - width) / 2, self.height() - height - 1, width, height
        )
        gradient = QRadialGradient(rect.center(), width / 2)
        gradient.setColorAt(0.0, QColor(0, 0, 0, 70))
        gradient.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(rect)
        painter.restore()

    def contextMenuEvent(self, event):
        self.note_user_activity()
        command = show_pet_context_menu(
            parent=self,
            global_position=event.globalPos(),
            current_state=self.current_state,
            idle_activities_enabled=(self.activity_controller.enabled),
            auto_movement_enabled=(self.movement_controller.enabled),
            always_on_top=self.always_on_top,
            usage_widget_available=self.usage_widget_available,
            usage_widget_visible=self.usage_widget_visible,
            usage_widget_shape=self.usage_widget_shape,
            usage_widget_tasks_visible=self.usage_widget_tasks_visible,
            usage_widget_today_visible=self.usage_widget_today_visible,
            usage_widget_position_customized=(self.usage_widget_position_customized),
        )

        if command is None:
            return

        if command.name == "set_idle_activities_enabled":
            self.set_idle_activities_enabled(command.value)

        elif command.name == "set_auto_movement_enabled":
            self.set_auto_movement_enabled(command.value)

        elif command.name == "set_always_on_top":
            self.set_always_on_top(command.value)

        elif command.name == "set_usage_widget_visible":
            self.usage_widget_visibility_requested.emit(bool(command.value))

        elif command.name == "set_usage_widget_shape":
            self.usage_widget_shape_requested.emit(str(command.value))
        elif command.name == "set_usage_widget_tasks_visible":
            self.usage_widget_tasks_visibility_requested.emit(bool(command.value))
        elif command.name == "set_usage_widget_today_visible":
            self.usage_widget_today_visibility_requested.emit(bool(command.value))
        elif command.name == "show_usage_settings":
            self.usage_widget_settings_requested.emit()

        elif command.name == "reset_usage_widget_position":
            self.usage_widget_position_reset_requested.emit()

        elif command.name == "show_settings":
            self.show_settings()

        elif command.name == "recenter":
            self.move_to_screen_center()

        elif command.name == "quit":
            QApplication.quit()

    def setup_look_tracking(self):
        return self.pointer_controller.setup_look_tracking()

    def mousePressEvent(self, event):
        return self.pointer_controller.mousePressEvent(event)

    def mouseMoveEvent(self, event):
        return self.pointer_controller.mouseMoveEvent(event)

    def update_drag_direction(self, current_mouse_x):
        return self.pointer_controller.update_drag_direction(current_mouse_x)

    def mouseReleaseEvent(self, event):
        return self.pointer_controller.mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        return self.pointer_controller.mouseDoubleClickEvent(event)

    def finish_waving(self):
        return self.pointer_controller.finish_waving()

    def update_look_direction(self):
        return self.pointer_controller.update_look_direction()
