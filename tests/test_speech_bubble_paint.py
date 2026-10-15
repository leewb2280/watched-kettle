import unittest

from PySide6.QtCore import QRectF

from watched_kettle.ui.speech_bubble_paint import (
    build_body_path,
    build_tail_path,
)
from watched_kettle.pet.bubble_theme import SpeechBubbleTheme


class SpeechBubblePaintTests(unittest.TestCase):
    @staticmethod
    def theme(shape="rounded", tail="triangle"):
        return SpeechBubbleTheme(
            background="#ffffff",
            border="#333333",
            text="#111111",
            shadow="#000000",
            shape=shape,
            tail=tail,
        )

    def test_all_body_shapes_produce_bounded_paths(self):
        rect = QRectF(20, 20, 260, 100)
        for shape in ("rounded", "cloud", "jelly", "comic", "tech"):
            with self.subTest(shape=shape):
                path = build_body_path(rect, self.theme(shape=shape))
                self.assertFalse(path.isEmpty())
                self.assertTrue(
                    rect.adjusted(-3, -3, 3, 3).contains(path.boundingRect())
                )

    def test_all_tail_styles_support_four_directions(self):
        outer = QRectF(0, 0, 300, 150)
        body_by_side = {
            "top": QRectF(0, 20, 300, 130),
            "bottom": QRectF(0, 0, 300, 130),
            "left": QRectF(20, 0, 280, 150),
            "right": QRectF(0, 0, 280, 150),
        }
        for tail_style in ("triangle", "curved", "stub", "angular", "droplet"):
            for side, body in body_by_side.items():
                with self.subTest(tail=tail_style, side=side):
                    path = build_tail_path(
                        body,
                        outer,
                        side,
                        self.theme(tail=tail_style),
                    )
                    self.assertIsNotNone(path)
                    self.assertFalse(path.isEmpty())
                    self.assertTrue(
                        outer.adjusted(-2, -2, 2, 2).contains(path.boundingRect())
                    )

    def test_tail_none_does_not_build_a_pointer(self):
        path = build_tail_path(
            QRectF(0, 0, 200, 80),
            QRectF(0, 0, 200, 100),
            "bottom",
            self.theme(tail="none"),
        )

        self.assertIsNone(path)


if __name__ == "__main__":
    unittest.main()
