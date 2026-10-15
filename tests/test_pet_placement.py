import unittest
from unittest.mock import Mock

from PySide6.QtCore import QPoint, QRect, QSize

from watched_kettle.pet.placement import (
    clamp_window_position,
    create_saved_placement,
    restore_window_position,
)


def fake_screen(name, work_area):
    screen = Mock()
    screen.name.return_value = name
    screen.availableGeometry.return_value = work_area
    return screen


class PetPlacementTests(unittest.TestCase):
    def test_same_work_area_restores_absolute_position(self):
        bounds = QRect(-1920, 0, 1920, 1080)
        size = QSize(192, 286)
        saved = create_saved_placement(
            "DISPLAY2",
            QPoint(-1500, 500),
            size,
            bounds,
        )
        screen = fake_screen("DISPLAY2", bounds)

        restored = restore_window_position(
            saved,
            [screen],
            screen,
            size,
        )

        self.assertEqual(restored, QPoint(-1500, 500))

    def test_changed_work_area_preserves_relative_position(self):
        old_bounds = QRect(0, 0, 1000, 800)
        new_bounds = QRect(1000, 40, 1600, 900)
        size = QSize(200, 300)
        saved = create_saved_placement(
            "DISPLAY2",
            QPoint(800, 500),
            size,
            old_bounds,
        )
        screen = fake_screen("DISPLAY2", new_bounds)

        restored = restore_window_position(
            saved,
            [screen],
            screen,
            size,
        )

        self.assertEqual(restored.x(), new_bounds.right() - size.width() + 1)
        self.assertEqual(restored.y(), new_bounds.bottom() - size.height() + 1)

    def test_removed_screen_falls_back_to_primary(self):
        saved = create_saved_placement(
            "REMOVED",
            QPoint(-800, 400),
            QSize(200, 300),
            QRect(-1000, 0, 1000, 800),
        )
        primary = fake_screen("PRIMARY", QRect(0, 0, 1200, 900))

        restored = restore_window_position(
            saved,
            [primary],
            primary,
            QSize(200, 300),
        )

        self.assertGreaterEqual(restored.x(), 0)
        self.assertGreaterEqual(restored.y(), 0)
        self.assertLessEqual(restored.x() + 200, 1200)
        self.assertLessEqual(restored.y() + 300, 900)

    def test_clamp_reserves_space_for_activity_caption(self):
        restored = clamp_window_position(
            QPoint(900, 750),
            QSize(200, 120),
            QRect(0, 0, 1000, 800),
            reserved_bottom=32,
        )

        self.assertEqual(restored, QPoint(800, 648))


if __name__ == "__main__":
    unittest.main()
