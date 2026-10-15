"""Constant-space runtime memory summaries."""

import gc
import unittest

from scripts.memory_metrics import MemoryTrend


class MemorySummaryTests(unittest.TestCase):
    def test_summaries_match_full_sample_arithmetic_without_retaining_samples(self):
        trend = MemoryTrend(1800)
        values = []
        for second in range(0, 1800, 10):
            value = 1000 + (second % 170)
            values.append((second, value))
            trend.add(second, {"private_bytes": value})
        for window, start in (
            (trend.after_warmup, 300),
            (trend.final_ten_minutes, 1200),
        ):
            expected = [value for second, value in values if second >= start]
            self.assertEqual(window.growth_bytes, max(expected) - expected[0])
            self.assertEqual(
                window.summary()["net_growth_bytes"], expected[-1] - expected[0]
            )
        self.assertEqual(sum(s.samples for s in trend.segments), len(values))
        gc.collect()
        owned = tuple(id(item) for item in trend.segments)
        for i in range(100000):
            trend.add(i + 1800, {"private_bytes": 1200})
        self.assertEqual(tuple(id(item) for item in trend.segments), owned)
        self.assertEqual(len(trend.segments), 6)
        self.assertFalse(hasattr(trend, "__dict__"))

    def test_missing_unavailable_and_invalid_samples_are_not_zero(self):
        trend = MemoryTrend(1800)
        for resources in (
            {},
            {"private_bytes": -1},
            {"private_bytes": True},
            {"private_bytes": 12, "memory_status": "unavailable"},
        ):
            trend.add(1200, resources)
        self.assertEqual(trend.after_warmup.missing, 4)
        self.assertIsNone(trend.after_warmup.growth_bytes)
        trend.add(1210, {"private_bytes": 100})
        self.assertIsNone(trend.after_warmup.growth_bytes)
        trend.add(1220, {"private_bytes": 90})
        self.assertEqual(trend.after_warmup.growth_bytes, 0)
        self.assertEqual(trend.after_warmup.summary()["net_growth_bytes"], -10)
