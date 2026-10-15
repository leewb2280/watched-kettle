import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image

from scripts.capture_assistant_preview import capture_assistant_preview


class AssistantPreviewCaptureTests(unittest.TestCase):
    def test_capture_contains_pet_and_three_bubbles(self):
        with TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "assistant-preview.png"

            result = capture_assistant_preview(
                output,
                Path("pets/mori-bot"),
            )

            self.assertEqual(result.bubble_count, 3)
            self.assertGreater(max(result.bubble_widths), 300)
            self.assertLess(
                min(result.bubble_widths),
                max(result.bubble_widths),
            )
            self.assertEqual(result.primary_tail_side, "bottom")
            self.assertTrue(output.is_file())
            with Image.open(output) as image:
                self.assertEqual(image.size, (result.width, result.height))
            self.assertGreater(image.width, 300)
            self.assertGreater(image.height, 200)
            self.assertTrue(result.all_widgets_in_work_area)

    def test_top_edge_capture_moves_stack_below_pet_and_stays_in_bounds(self):
        with TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "assistant-top-preview.png"

            result = capture_assistant_preview(
                output,
                Path("pets/mori-bot"),
                placement="top",
            )

            self.assertEqual(result.bubble_count, 3)
            self.assertEqual(result.primary_tail_side, "top")
            self.assertTrue(result.all_widgets_in_work_area)
            self.assertTrue(output.is_file())


if __name__ == "__main__":
    unittest.main()
