from dataclasses import replace
import os
import unittest

from PySide6.QtWidgets import QApplication

from watched_kettle.features.tasks.execution import QueueExecutor
from watched_kettle.features.tasks.models import (
    source_version,
    CompletionCheck,
    CheckKind,
    TaskState,
)
from watched_kettle.features.tasks.scheduling import ExecutionScope, resolve_lock_keys
from tests.test_task_execution import ExecutionClient
from tests import test_task_repository as storage_tests


@unittest.skipUnless(os.name == "nt", "current user DPAPI")
class ExecutionHistoryFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        storage_tests.TaskRepositoryTests.setUp(self)
        self.thread = {
            "id": self.spec.thread_id,
            "projectId": self.spec.project_id,
            "cwd": self.temp.name,
            "updatedAt": 1,
            "canAcceptDirectInput": True,
            "status": {"type": "idle"},
            "turns": [
                {
                    "id": "old",
                    "status": "completed",
                    "items": [
                        {"type": "toolOutput", "text": "unrelated"} for _ in range(305)
                    ],
                }
            ],
        }
        self.spec = replace(
            self.spec,
            cwd=self.temp.name,
            source_version=source_version(self.thread["turns"]),
            checks=(
                CompletionCheck("selected command", CheckKind.COMMAND, "test-command"),
            ),
        )
        self.client = ExecutionClient()
        self.executor = QueueExecutor(self.repo, self.client, clock=lambda: 10.0)
        self.executor.observe_scope(ExecutionScope(True, 0))
        self.next_response = 0

    def tearDown(self):
        self.executor.history_reader.cancel()
        self.executor.deleteLater()
        self.app.processEvents()
        storage_tests.TaskRepositoryTests.tearDown(self)

    def step(self):
        for _ in range(4):
            self.app.processEvents()
        if self.next_response >= len(self.client.calls):
            return False
        self.next_response += 1
        method, params = self.client.calls[self.next_response - 1]
        if method in {"thread/read", "thread/resume"}:
            result = {
                "thread": {
                    k: v
                    for k, v in self.thread.items()
                    if k != "turns" or params.get("includeTurns")
                }
            }
        elif method == "thread/turns/list":
            result = {
                "data": [
                    {"id": t["id"], "status": t["status"]} for t in self.thread["turns"]
                ]
            }
        elif method == "thread/items/list":
            items = next(
                t["items"] for t in self.thread["turns"] if t["id"] == params["turnId"]
            )
            start = int(params.get("cursor") or 0)
            result = {
                "data": [
                    {"turnId": params["turnId"], "item": i}
                    for i in items[start : start + 100]
                ],
                "nextCursor": str(start + 100) if start + 100 < len(items) else None,
            }
        elif method == "turn/start":
            result = {"turn": {"id": "owned"}}
            self.thread["turns"].append(
                {"id": "owned", "status": "inProgress", "items": []}
            )
        else:
            self.fail(method)
        self.client.reply(self.next_response, result)
        return True

    def drive(self, predicate):
        for _ in range(120):
            if predicate():
                return
            self.step()
        self.fail("flow did not reach expected state")

    def test_long_history_start_and_exact_turn_command_completion(self):
        identity = self.repo.save(self.spec, registered=True)
        self.executor.start_batch([identity])
        self.drive(lambda: self.repo.require(identity).state == TaskState.RUNNING)
        receipt = self.repo.receipt(self.repo.require(identity).attempt_id)
        self.assertEqual(
            receipt["execution_context"]["dispatch_version"], self.spec.source_version
        )
        self.thread["turns"][-1].update(
            status="completed",
            items=[
                {
                    "type": "commandExecution",
                    "command": "test-command",
                    "cwd": self.temp.name,
                    "status": "completed",
                    "exitCode": 0,
                    "aggregatedOutput": "SECRET OUTPUT",
                }
            ],
        )
        self.drive(lambda: self.repo.require(identity).state == TaskState.COMPLETE)
        self.assertFalse(
            any(
                p.get("includeTurns")
                for m, p in self.client.calls
                if m == "thread/read"
            )
        )
        self.assertEqual(sum(m == "turn/start" for m, _ in self.client.calls), 1)

    def test_partial_history_failure_never_starts_a_turn(self):
        identity = self.repo.save(self.spec, registered=True)
        self.executor.start_batch([identity])
        self.step()
        self.next_response += 1
        self.client.reply(self.next_response, error={"code": "timeout"})
        self.assertTrue(self.executor.paused)
        self.assertEqual(self.repo.require(identity).state, TaskState.QUEUED)
        self.assertNotIn("turn/start", [m for m, _ in self.client.calls])

    def test_manual_work_after_allocation_blocks_reserved_path(self):
        identity = self.repo.save(self.spec, registered=True)
        self.executor.start_batch([identity])
        self.executor.observe_scope(
            ExecutionScope(True, 1, frozenset(resolve_lock_keys(self.temp.name)))
        )
        self.drive(lambda: identity in self.executor.reasons)
        self.assertEqual(self.executor.reasons[identity], "repository_busy")
        self.assertNotIn("turn/start", [m for m, _ in self.client.calls])

    def test_same_project_manual_work_blocks_different_path(self):
        identity = self.repo.save(self.spec, registered=True)
        self.executor.observe_scope(
            ExecutionScope(True, 1, active_projects=frozenset({self.spec.project_id}))
        )
        self.executor.start_batch([identity])
        self.assertEqual(self.executor.reasons[identity], "project_busy")
        self.assertEqual(self.client.calls, [])

    def test_reconnection_requires_reconciliation_then_explicit_resume(self):
        first = self.repo.save(self.spec, registered=True)
        second = self.repo.save(
            replace(self.spec, instruction="second"), registered=True
        )
        self.executor.start_batch([first, second])
        self.drive(lambda: self.repo.require(first).state == TaskState.RUNNING)
        self.executor.connection_changed(False)
        self.executor.observe_scope(ExecutionScope(True, 0))
        with self.assertRaisesRegex(ValueError, "reconciliation_required"):
            self.executor.resume()
        self.thread["turns"][-1].update(
            status="completed",
            items=[
                {
                    "type": "commandExecution",
                    "command": "test-command",
                    "cwd": self.temp.name,
                    "status": "completed",
                    "exitCode": 0,
                }
            ],
        )
        self.next_response = len(self.client.calls)
        self.executor.reconcile(self.repo.require(first).attempt_id)
        self.drive(lambda: self.repo.require(first).state == TaskState.COMPLETE)
        self.assertTrue(self.executor.paused)
        self.executor.observe_scope(ExecutionScope(True, 0))
        self.executor.resume()
        self.assertIn("owned", self.executor.expected_turns[second])
        self.drive(lambda: self.repo.require(second).state == TaskState.RUNNING)
