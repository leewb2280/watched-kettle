"""User-facing quota direction, precision and chart interaction regressions."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from watched_kettle.usage.widget_presentation import (
    _percent_text,
    compact_token_text,
    quota_decrease_text,
)


class UsageDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_token_precision_and_unit_carry(self):
        cases = (
            (None, "관찰 대기"),
            (0, "0"),
            (999, "999"),
            (1000, "1K"),
            (1250, "1.3K"),
            (25_400, "25.4K"),
            (999_949, "999.9K"),
            (999_950, "1M"),
            (4_143_920, "4.1M"),
            (999_950_000, "1B"),
            (1_200_000_000, "1.2B"),
            (999_950_000_000, "1T"),
            (1_200_000_000_000, "1.2T"),
            (1_234_500_000_000_000, "1,234.5T"),
        )
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(compact_token_text(value), expected)

    def test_quota_precision_keeps_missing_zero_and_small_decreases_distinct(self):
        for value, expected in (
            (None, "관찰 대기"),
            (0, "0%p"),
            (2, "−2%p"),
            (2.34, "−2.3%p"),
            (0.001, "−<0.1%p"),
        ):
            self.assertEqual(quota_decrease_text(value), expected)
        self.assertEqual(_percent_text(32.01), "32%")
        self.assertEqual(_percent_text(32.34), "32.3%")
