import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtWidgets import QApplication

from watched_kettle.pet.movement_controller import (
    AutoMovementController,
    choose_horizontal_target,
    horizontal_limits,
)


class AutoMovementGeometryTests(unittest.TestCase):
    def test_horizontal_limits_keep_full_window_inside_negative_screen(self):
        bounds = QRect(-1920, 0, 1920, 1080)

        self.assertEqual(horizontal_limits(bounds, 112), (-1920, -112))

    def test_target_uses_only_available_direction_near_edge(self):
        bounds = QRect(0, 0, 500, 400)

        target = choose_horizontal_target(
            5,
            100,
            bounds,
            minimum_distance=60,
            maximum_distance=100,
            chooser=lambda choices: choices[0],
            randint=lambda minimum, maximum: maximum,
        )

        self.assertEqual(target, 105)

    def test_target_never_crosses_selected_display(self):
        bounds = QRect(1000, 50, 800, 600)
        target = choose_horizontal_target(
            1650,
            120,
            bounds,
            minimum_distance=60,
            maximum_distance=180,
            chooser=lambda choices: 1,
            randint=lambda minimum, maximum: maximum,
        )

        self.assertLessEqual(target + 120, bounds.right() + 1)


class AutoMovementControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.bounds = QRect(0, 0, 800, 600)
        self.position = QPoint(300, 200)
        self.started = []
        self.finished = []
        self.moves = []
        self.controller = AutoMovementController(
            enabled=True,
            can_start=lambda: True,
            bounds_provider=lambda: QRect(self.bounds),
            position_provider=lambda: QPoint(self.position),
            size_provider=lambda: QSize(100, 120),
            on_start=self.started.append,
            on_move=self.record_move,
            on_finish=self.finished.append,
        )

    def tearDown(self):
        self.controller.cancel()
        self.controller.deleteLater()

    def record_move(self, position):
        self.position = QPoint(position)
        self.moves.append(QPoint(position))

    def test_walk_advances_and_finishes_at_target(self):
        self.controller.start()
        target_x = self.controller.target_x
        state = self.controller.active_state

        self.assertIn(state, {"running-left", "running-right"})
        self.controller.advance(10_000)

        self.assertFalse(self.controller.is_active)
        self.assertEqual(self.position.x(), target_x)
        self.assertEqual(self.finished, [state])

    def test_display_geometry_change_cancels_active_walk(self):
        self.controller.start()
        state = self.controller.active_state
        self.bounds = QRect(800, 0, 800, 600)

        self.controller.advance(33)

        self.assertFalse(self.controller.is_active)
        self.assertEqual(self.finished, [state])

    def test_cancel_always_stops_movement_timer(self):
        self.controller.start()

        self.controller.cancel(return_to_idle=False)

        self.assertFalse(self.controller.is_active)
        self.assertFalse(self.controller.move_timer.isActive())
        self.assertEqual(self.finished, [])

    def test_forced_test_walk_ignores_disabled_schedule_setting(self):
        self.controller.enabled = False
        self.controller.can_start = lambda: False

        self.controller.start(force=True)

        self.assertTrue(self.controller.is_active)
        self.assertIn(
            self.controller.active_state,
            {"running-left", "running-right"},
        )


if __name__ == "__main__":
    unittest.main()
