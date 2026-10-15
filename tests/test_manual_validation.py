import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.manual_validation import phase_at, summarize
from scripts.observe_process import observe
from tests.test_observe_process import Clock, Target, resources


class ManualValidationTests(unittest.TestCase):
    def test_phase_boundaries(self):
        self.assertEqual(phase_at(599)[2], "초기 로딩")
        self.assertEqual(phase_at(600)[2], "첫 조작")
        self.assertEqual(phase_at(1200)[2], "첫 대기")
        self.assertIsNone(phase_at(3600))

    def result(self, difference, *, complete=True, missing=False):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "observation.json"
            path.write_text(
                json.dumps({"status": "complete" if complete else "needs_review"})
            )
            with path.with_suffix(".samples.jsonl").open("w") as stream:
                for second in range(0, 3601, 10):
                    sample = {
                        **resources(),
                        "elapsed_seconds": second,
                        "private_bytes": 10 * 1024**2
                        + (difference if second >= 3000 else 0),
                    }
                    if missing and second == 1500:
                        sample["memory_status"] = "unavailable"
                    stream.write(json.dumps(sample) + "\n")
            return summarize(path)

    def test_memory_target_boundary_does_not_certify_manual_actions(self):
        result = self.result(2 * 1024**2)
        self.assertEqual(result["memory_target"], "passed")
        self.assertEqual(result["overall_manual_qa"], "not_automatically_assessed")
        self.assertEqual(self.result(2 * 1024**2 + 1)["memory_target"], "needs_review")

    def test_missing_or_cancelled_observation_cannot_pass(self):
        self.assertEqual(self.result(0, missing=True)["memory_target"], "not_assessed")
        self.assertEqual(
            self.result(0, complete=False)["memory_target"], "not_assessed"
        )

    def test_cancel_preserves_target_and_reports_incomplete(self):
        with TemporaryDirectory() as folder:
            clock, target = Clock(), Target()
            result = observe(
                target,
                Path(folder) / "report.json",
                60,
                clock=clock.read,
                wall=clock.read,
                sleep=clock.sleep,
                own_reader=resources,
                stop_requested=lambda: target.reads >= 3,
            )
            self.assertIn("cancelled", result["issues"])
            self.assertIn("duration_short", result["issues"])
            self.assertTrue(target.alive())


if __name__ == "__main__":
    unittest.main()
