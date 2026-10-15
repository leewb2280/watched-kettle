"""Mouse dragging, gestures, and V2 pointer-look behavior for DesktopPet."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCursor

from watched_kettle.config import (
    DRAG_DIRECTION_THRESHOLD,
    FORCE_DRAG_ANIMATION,
    LOOK_DIRECTION_DEADZONE,
    LOOK_DIRECTION_INTERVAL,
    LOOK_RANGE_EXIT_MARGIN,
)
from watched_kettle.pet.look_direction import (
    direction_index_from_vector,
    is_pointer_near,
)


class PetPointerController:
    def __init__(self, window):
        self.window = window

    def setup_look_tracking(self):
        self.window.look_timer = QTimer(self.window)
        self.window.look_timer.timeout.connect(self.window.update_look_direction)
        self.window.look_timer.start(LOOK_DIRECTION_INTERVAL)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.window.dragging = True
            self.window.note_user_activity()
            self.window.double_click_waving = False
            self.window.look_direction_index = None

            global_pos = event.globalPosition().toPoint()
            self.window.drag_offset = global_pos - self.window.frameGeometry().topLeft()
            self.window.last_mouse_x = global_pos.x()
            self.window.direction_score = 0
            event.accept()

    def mouseMoveEvent(self, event):
        if not self.window.dragging:
            return
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return

        global_pos = event.globalPosition().toPoint()
        self.window.move(global_pos - self.window.drag_offset)

        if FORCE_DRAG_ANIMATION is not None:
            self.window.set_state(FORCE_DRAG_ANIMATION)
        else:
            self.window.update_drag_direction(global_pos.x())
        event.accept()

    def update_drag_direction(self, current_mouse_x):
        if self.window.last_mouse_x is None:
            self.window.last_mouse_x = current_mouse_x
            return

        delta_x = current_mouse_x - self.window.last_mouse_x
        self.window.last_mouse_x = current_mouse_x
        self.window.direction_score += delta_x
        self.window.direction_score = max(
            -DRAG_DIRECTION_THRESHOLD,
            min(DRAG_DIRECTION_THRESHOLD, self.window.direction_score),
        )

        if self.window.direction_score >= DRAG_DIRECTION_THRESHOLD:
            self.window.set_state("running-right")
        elif self.window.direction_score <= -DRAG_DIRECTION_THRESHOLD:
            self.window.set_state("running-left")

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.window.dragging = False
            self.window.last_mouse_x = None
            self.window.direction_score = 0

            if self.window.double_click_waving:
                event.accept()
                return

            self.window.restore_agent_display_state()
            if self.window.activity_labels_enabled:
                self.window.keep_on_screen()
            self.window.update_look_direction()
            event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.window.note_user_activity()
            self.window.dragging = False
            self.window.last_mouse_x = None
            self.window.direction_score = 0
            self.window.double_click_waving = True
            self.window.set_state("waving")
            if not hasattr(self.window, "wave_finish_timer"):
                self.window.wave_finish_timer = QTimer(self.window)
                self.window.wave_finish_timer.setSingleShot(True)
                self.window.wave_finish_timer.timeout.connect(self.window.finish_waving)
            self.window.wave_finish_timer.start(1000)
            opener = self.window.codex_opener
            if opener is not None and not opener():
                self.window.bubble_controller.preview(
                    "Codex 앱을 열 수 없어요. 설치 상태를 확인해 주세요."
                )
            event.accept()

    def finish_waving(self):
        was_double_click_waving = self.window.double_click_waving
        self.window.double_click_waving = False

        if (
            was_double_click_waving
            and self.window.current_state == "waving"
            and not self.window.dragging
        ):
            self.window.restore_agent_display_state()

    def update_look_direction(self):
        if (
            self.window.sprite_version < 2
            or not self.window.look_frames
            or self.window.dragging
        ):
            if self.window.look_direction_index is not None:
                self.window.look_direction_index = None
                self.window.update()
            return

        cursor_position = QCursor.pos()
        pet_center = self.window.frameGeometry().center()
        dx = cursor_position.x() - pet_center.x()
        dy = cursor_position.y() - pet_center.y()
        near_distance = self.window.look_range * self.window.scale_factor
        far_distance = (
            self.window.look_range + LOOK_RANGE_EXIT_MARGIN
        ) * self.window.scale_factor

        pointer_near = is_pointer_near(
            dx,
            dy,
            near_distance,
            far_distance,
            self.window.pointer_near,
        )

        if pointer_near != self.window.pointer_near:
            self.window.pointer_near = pointer_near

            if pointer_near:
                self.window.activity_controller.delay_timer.stop()
                if self.window.activity_controller.is_active:
                    self.window.activity_controller.cancel(return_to_idle=True)
                self.window.movement_controller.delay_timer.stop()
                if self.window.movement_controller.is_active:
                    self.window.movement_controller.cancel(return_to_idle=True)
            elif self.window.current_state == "idle":
                self.window.schedule_idle_activity()
                self.window.schedule_auto_movement()

        if self.window.current_state != "idle":
            if self.window.look_direction_index is not None:
                self.window.look_direction_index = None
                self.window.update()
            return

        direction_index = direction_index_from_vector(
            dx,
            dy,
            LOOK_DIRECTION_DEADZONE * self.window.scale_factor,
            self.window.look_direction_offset,
            self.window.look_direction_mirrored,
            max_distance=far_distance,
        )
        if not self.window.pointer_near:
            direction_index = None

        if direction_index != self.window.look_direction_index:
            self.window.look_direction_index = direction_index
            self.window.update()
