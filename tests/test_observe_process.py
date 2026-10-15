"""Passive observation must preserve identity, data and target lifetime."""

import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from scripts.observe_process import WindowsProcess, observe


def resources():
    return {
        "memory_status": "available",
        "private_bytes": 1024**2,
        "working_set_bytes": 2 * 1024**2,
        "cpu_seconds": 0.2,
        "handle_count": 12,
        "gdi_objects": 0,
        "user_objects": 0,
    }


class Clock:
    def __init__(self):
        self.now = 0.0
        self.jump = 0

    def read(self):
        return self.now

    def sleep(self, duration):
        self.now += duration + self.jump
        self.jump = 0


class Target:
    identity = {"pid": 123, "created_filetime": 456, "sha256": "test"}

    def __init__(self):
        self.reads = 0
        self.exit_after = float("inf")
        self.value = resources()

    def alive(self):
        return self.reads < self.exit_after

    def sample(self):
        self.reads += 1
        return self.value


class ObservationTests(unittest.TestCase):
    def run_probe(self, folder, target=None, clock=None, duration=60):
        clock = clock or Clock()
        return observe(
            target or Target(),
            Path(folder) / "report.json",
            duration,
            clock=clock.read,
            wall=clock.read,
            sleep=clock.sleep,
            own_reader=resources,
        )

    def test_complete_is_not_a_manual_qa_pass(self):
        with TemporaryDirectory() as folder:
            target = Target()
            result = self.run_probe(folder, target)
            self.assertEqual(result["status"], "complete")
            self.assertEqual(result["manual_qa"], "not_assessed")
            self.assertTrue(target.alive())
            self.assertEqual(result["reads"], 61)
            lines = (Path(folder) / "report.samples.jsonl").read_text().splitlines()
            self.assertEqual(len(lines), 7)
            self.assertEqual(json.loads(lines[-1])["elapsed_seconds"], 60)

    def test_exit_is_incomplete_and_does_not_attach_to_another_pid(self):
        with TemporaryDirectory() as folder:
            target = Target()
            target.exit_after = 3
            result = self.run_probe(folder, target)
            self.assertIn("target_exited", result["issues"])
            self.assertIn("duration_short", result["issues"])
            self.assertEqual(target.reads, 3)

    def test_gap_invalidates_observation(self):
        with TemporaryDirectory() as folder:
            clock = Clock()
            clock.jump = 40
            result = self.run_probe(folder, clock=clock)
            self.assertIn("observation_gap", result["issues"])
            self.assertEqual(result["status"], "needs_review")

    def test_failed_memory_query_is_not_zero_usage(self):
        with TemporaryDirectory() as folder:
            target = Target()
            target.value = {**resources(), "memory_status": "unavailable"}
            result = self.run_probe(folder, target)
            self.assertIn("memory_unavailable", result["issues"])
            self.assertEqual(result["memory_trends"]["target"]["overall"]["samples"], 0)

    def test_identity_failure_is_reported_without_continuing(self):
        with TemporaryDirectory() as folder:
            target = Target()

            def replaced():
                raise ValueError("Process identity changed")

            target.sample = replaced
            result = self.run_probe(folder, target)
            self.assertIn("ValueError", result["issues"])
            self.assertEqual(result["reads"], 0)

    def test_interrupted_output_is_never_overwritten(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "report.samples.jsonl"
            path.write_text("preserve")
            with self.assertRaises(ValueError):
                self.run_probe(folder)
            self.assertEqual(path.read_text(), "preserve")

    def test_long_run_summary_has_fixed_size(self):
        with TemporaryDirectory() as folder:
            result = self.run_probe(folder, duration=100000)
            self.assertEqual(result["reads"], 100001)
            self.assertEqual(len(result["memory_trends"]["target"]["segments"]), 6)
            self.assertLess(len(json.dumps(result)), 12000)

    @unittest.skipUnless(os.name == "nt", "Windows handles required")
    def test_real_process_identity_and_counters(self):
        target = WindowsProcess(
            os.getpid(), getattr(sys, "_base_executable", sys.executable)
        )
        try:
            self.assertTrue(target.alive())
            self.assertEqual(target.identity["pid"], os.getpid())
            self.assertGreater(target.identity["created_filetime"], 0)
            sample = target.sample()
            self.assertEqual(sample["memory_status"], "available")
            self.assertGreater(sample["private_bytes"], 0)
            self.assertGreater(sample["handle_count"], 0)
        finally:
            target.close()
        self.assertIsNone(target.handle)

    @unittest.skipUnless(os.name == "nt", "Windows handles required")
    def test_wrong_executable_is_rejected(self):
        with self.assertRaises(ValueError):
            WindowsProcess(os.getpid(), Path(sys.executable).with_name("wrong.exe"))


if __name__ == "__main__":
    unittest.main()
