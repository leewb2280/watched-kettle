from dataclasses import replace
import unittest

from watched_kettle.features.tasks.completion import evaluate_completion, Verdict
from watched_kettle.features.tasks.models import (
    CheckKind,
    CompletionCheck,
    ReviewItem,
    TaskSpec,
    TaskState,
)
from watched_kettle.features.tasks.scheduling import allocate, ExecutionScope


class TaskCompletionTests(unittest.TestCase):
    def setUp(self):
        self.spec = TaskSpec(
            "Fix",
            "Fix",
            "p",
            "t",
            "C:/work",
            "v",
            checks=(CompletionCheck("tests", CheckKind.COMMAND, "python -m unittest"),),
        )

    def test_model_success_message_is_not_command_evidence(self):
        turn = {
            "id": "turn",
            "status": "completed",
            "items": [{"type": "agentMessage", "text": "All tests passed"}],
        }
        self.assertEqual(
            evaluate_completion(self.spec, turn, "turn").verdict, Verdict.UNKNOWN
        )

    def test_command_must_match_turn_path_and_exit_code(self):
        turn = {
            "id": "turn",
            "status": "completed",
            "items": [
                {
                    "type": "commandExecution",
                    "command": "python -m unittest",
                    "cwd": "C:/work",
                    "status": "completed",
                    "exitCode": 0,
                }
            ],
        }
        self.assertEqual(
            evaluate_completion(self.spec, turn, "turn").verdict, Verdict.PASSED
        )
        self.assertEqual(
            evaluate_completion(self.spec, turn, "other-turn").verdict, Verdict.UNKNOWN
        )
        turn["items"][0]["exitCode"] = 1
        self.assertEqual(
            evaluate_completion(self.spec, turn, "turn").verdict, Verdict.FAILED
        )
        turn["items"][0]["cwd"] = "C:/other"
        self.assertEqual(
            evaluate_completion(self.spec, turn, "turn").verdict, Verdict.UNKNOWN
        )

    def test_manual_confirmation_cannot_override_failure_or_running(self):
        spec = replace(self.spec, checks=(CompletionCheck("Inspect result"),))
        self.assertEqual(
            evaluate_completion(
                spec, {"id": "turn", "status": "completed"}, "turn"
            ).verdict,
            Verdict.UNKNOWN,
        )
        self.assertEqual(
            evaluate_completion(
                spec,
                {"id": "turn", "status": "completed"},
                "turn",
                manual_confirmed=True,
            ).verdict,
            Verdict.PASSED,
        )
        self.assertEqual(
            evaluate_completion(
                spec, {"id": "turn", "status": "failed"}, "turn", manual_confirmed=True
            ).verdict,
            Verdict.FAILED,
        )

    def test_scope_unverified_prevents_allocation(self):
        item = ReviewItem("one", TaskState.QUEUED, 1, self.spec, batch_id="b")
        selected, reasons = allocate((item,), {"b"}, set(), ExecutionScope(False, 0))
        self.assertEqual(selected, ())
        self.assertEqual(reasons["one"], "execution_scope_unverified")

    def test_batches_concurrency_shared_repository_and_fairness(self):
        items = tuple(
            ReviewItem(
                str(i),
                TaskState.QUEUED,
                1,
                replace(self.spec, project_id=str(i)),
                batch_id="b",
                position=i,
            )
            for i in range(3)
        )
        scope = ExecutionScope(True, 1)
        selected, _ = allocate(
            items,
            {"b"},
            set(),
            scope,
            last_served={"0": 50},
            lock_resolver=lambda _: ("shared",),
        )
        self.assertEqual([x.task_id for x in selected], ["1"])
        selected, _ = allocate(
            items, set(), set(), scope, lock_resolver=lambda _: ("shared",)
        )
        self.assertEqual(selected, ())

    def test_failed_predecessor_blocks_following_work(self):
        failed = ReviewItem("failed", TaskState.FAILED, 1, self.spec, batch_id="b")
        queued = ReviewItem(
            "next", TaskState.QUEUED, 1, self.spec, batch_id="b", position=1
        )
        selected, reasons = allocate(
            (failed, queued),
            {"b"},
            set(),
            ExecutionScope(True, 0),
            lock_resolver=lambda _: ("shared",),
        )
        self.assertEqual(selected, ())
        self.assertEqual(reasons["next"], "previous_task_needs_attention")


if __name__ == "__main__":
    unittest.main()
