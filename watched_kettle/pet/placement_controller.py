"""Screen placement controller for the DesktopPet UI shell."""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from watched_kettle.pet.placement import (
    clamp_window_position,
    create_saved_placement,
    restore_window_position,
)

POSITION_SAVE_DELAY_MS = 750


class PetPlacementController:
    def __init__(self, window):
        self.window = window

    def setup_position_persistence(self):
        self.window.position_save_timer = QTimer(self.window)
        self.window.position_save_timer.setSingleShot(True)
        self.window.position_save_timer.timeout.connect(
            self.window.save_window_placement
        )
        self.window._position_persistence_ready = True

    def move_to_initial_position(self):
        if self.window.restore_window_placement():
            return
        primary_screen = QApplication.primaryScreen()
        if primary_screen is None:
            return
        screen = primary_screen.availableGeometry()

        x = screen.right() - self.window.width() - 30

        bottom_margin = max(
            30,
            self.window.activity_caption_controller.reserved_height,
        )
        y = screen.bottom() - self.window.height() - bottom_margin

        self.window.move(x, y)

    def available_position_screens(self):
        return list(QApplication.screens())

    def restore_window_placement(self):
        placement = self.window.app_preferences.load_window_placement()
        position = restore_window_position(
            placement,
            self.window.available_position_screens(),
            QApplication.primaryScreen(),
            self.window.size(),
            self.window.activity_caption_controller.reserved_height,
        )
        if position is None:
            return False
        self.window.move(position)
        return True

    def schedule_position_save(self):
        if not self.window._position_persistence_ready:
            return
        self.window.position_save_timer.start(POSITION_SAVE_DELAY_MS)

    def save_window_placement(self):
        if not self.window._position_persistence_ready:
            return
        self.window.position_save_timer.stop()
        screen = (
            QApplication.screenAt(self.window.frameGeometry().center())
            or QApplication.primaryScreen()
        )
        if screen is None:
            return
        placement = create_saved_placement(
            screen.name(),
            self.window.pos(),
            self.window.size(),
            screen.availableGeometry(),
            self.window.activity_caption_controller.reserved_height,
        )
        self.window.app_preferences.save_window_placement(placement)

    def move_to_screen_center(self):
        self.window.note_user_activity()
        screen = (
            QApplication.screenAt(self.window.frameGeometry().center())
            or QApplication.primaryScreen()
        )
        if screen is None:
            return

        center = screen.availableGeometry().center()
        self.window.move(
            center.x() - self.window.width() // 2,
            center.y() - self.window.height() // 2,
        )
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()
        self.window.refresh_controls()

    def available_auto_movement_screens(self):
        return list(QApplication.screens())

    @staticmethod
    def screen_identity(screen):
        if screen is None:
            return None
        geometry = screen.geometry()
        return (
            screen.name(),
            geometry.x(),
            geometry.y(),
            geometry.width(),
            geometry.height(),
        )

    def resolve_auto_movement_screen(self):
        screens = self.window.available_auto_movement_screens()
        current_screen = QApplication.screenAt(self.window.frameGeometry().center())

        if self.window.auto_movement_screen_mode == "specific":
            selected = next(
                (
                    screen
                    for screen in screens
                    if screen.name() == self.window.auto_movement_screen_name
                ),
                None,
            )
            if selected is not None:
                return selected

        if self.window.auto_movement_screen_mode == "primary":
            primary = QApplication.primaryScreen()
            if primary is not None:
                return primary

        return current_screen or QApplication.primaryScreen()

    def auto_movement_bounds(self):
        target_screen = self.window.resolve_auto_movement_screen()
        if target_screen is None:
            return None

        current_screen = QApplication.screenAt(self.window.frameGeometry().center())
        if self.window.screen_identity(current_screen) != self.window.screen_identity(
            target_screen
        ):
            return None
        return target_screen.availableGeometry()

    def set_auto_movement_screen(self, mode, name=""):
        self.window.movement_controller.cancel(return_to_idle=True)
        self.window.app_preferences.save_auto_movement_screen(mode, name)
        (
            self.window.auto_movement_screen_mode,
            self.window.auto_movement_screen_name,
        ) = self.window.app_preferences.load_auto_movement_screen()
        self.window.schedule_auto_movement()
        self.window.refresh_controls()

    def move_to_auto_movement_screen(self):
        screen = self.window.resolve_auto_movement_screen()
        if screen is None:
            return

        self.window.note_user_activity()
        center = screen.availableGeometry().center()
        self.window.move(
            center.x() - self.window.width() // 2,
            center.y() - self.window.height() // 2,
        )
        self.window.keep_on_screen()
        self.window.show()
        self.window.raise_()
        self.window.schedule_auto_movement()
        self.window.refresh_controls()

    def keep_on_screen(self):
        center = self.window.frameGeometry().center()
        screen = QApplication.screenAt(center) or QApplication.primaryScreen()

        if screen is None:
            return

        self.window.move(
            clamp_window_position(
                self.window.pos(),
                self.window.size(),
                screen.availableGeometry(),
                self.window.activity_caption_controller.reserved_height,
            )
        )
