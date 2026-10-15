import math
import unittest

from watched_kettle.pet.look_direction import (
    direction_index_from_vector,
    is_pointer_near,
    mirrored_right_frame_source,
)


class DirectionIndexTests(unittest.TestCase):
    def test_cardinal_directions(self):
        self.assertEqual(direction_index_from_vector(0, -100), 0)
        self.assertEqual(direction_index_from_vector(100, 0), 4)
        self.assertEqual(direction_index_from_vector(0, 100), 8)
        self.assertEqual(direction_index_from_vector(-100, 0), 12)

    def test_diagonal_directions(self):
        self.assertEqual(direction_index_from_vector(100, -100), 2)
        self.assertEqual(direction_index_from_vector(100, 100), 6)
        self.assertEqual(direction_index_from_vector(-100, 100), 10)
        self.assertEqual(direction_index_from_vector(-100, -100), 14)

    def test_all_sixteen_direction_centers(self):
        for expected_index in range(16):
            angle = math.radians(expected_index * 22.5)
            dx = math.sin(angle) * 100
            dy = -math.cos(angle) * 100

            with self.subTest(index=expected_index):
                self.assertEqual(
                    direction_index_from_vector(dx, dy),
                    expected_index,
                )

    def test_neutral_deadzone(self):
        self.assertIsNone(direction_index_from_vector(30, 40, deadzone=50))
        self.assertEqual(
            direction_index_from_vector(0, -51, deadzone=50),
            0,
        )

    def test_pointer_outside_maximum_distance_returns_to_idle(self):
        self.assertEqual(
            direction_index_from_vector(
                0,
                -320,
                deadzone=48,
                max_distance=320,
            ),
            0,
        )
        self.assertIsNone(
            direction_index_from_vector(
                0,
                -321,
                deadzone=48,
                max_distance=320,
            )
        )

    def test_pointer_proximity_uses_enter_and_exit_hysteresis(self):
        self.assertTrue(
            is_pointer_near(
                320,
                0,
                enter_distance=320,
                exit_distance=380,
            )
        )
        self.assertFalse(
            is_pointer_near(
                321,
                0,
                enter_distance=320,
                exit_distance=380,
            )
        )
        self.assertTrue(
            is_pointer_near(
                379,
                0,
                enter_distance=320,
                exit_distance=380,
                was_near=True,
            )
        )
        self.assertFalse(
            is_pointer_near(
                381,
                0,
                enter_distance=320,
                exit_distance=380,
                was_near=True,
            )
        )

    def test_pet_specific_horizontal_mirror(self):
        self.assertEqual(
            direction_index_from_vector(
                100,
                0,
                mirror_horizontal=True,
            ),
            12,
        )
        self.assertEqual(
            direction_index_from_vector(
                -100,
                0,
                mirror_horizontal=True,
            ),
            4,
        )
        self.assertEqual(
            direction_index_from_vector(
                0,
                -100,
                mirror_horizontal=True,
            ),
            0,
        )
        self.assertEqual(
            direction_index_from_vector(
                0,
                100,
                mirror_horizontal=True,
            ),
            8,
        )

    def test_right_side_comes_from_mirrored_left_pose_family(self):
        self.assertEqual(mirrored_right_frame_source(0), (0, False))
        self.assertEqual(mirrored_right_frame_source(4), (4, True))
        self.assertEqual(mirrored_right_frame_source(8), (8, False))
        self.assertEqual(mirrored_right_frame_source(12), (4, False))

        self.assertEqual(mirrored_right_frame_source(2), (2, True))
        self.assertEqual(mirrored_right_frame_source(14), (2, False))

    def test_negative_deadzone_is_rejected(self):
        with self.assertRaises(ValueError):
            direction_index_from_vector(0, -1, deadzone=-1)

    def test_invalid_tracking_distances_are_rejected(self):
        with self.assertRaises(ValueError):
            direction_index_from_vector(
                0,
                -1,
                deadzone=50,
                max_distance=49,
            )

        with self.assertRaises(ValueError):
            is_pointer_near(
                0,
                0,
                enter_distance=400,
                exit_distance=300,
            )


if __name__ == "__main__":
    unittest.main()
