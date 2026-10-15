from dataclasses import replace
import os
import unittest
from unittest.mock import patch

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from watched_kettle.features.tasks.execution import QueueExecutor
from watched_kettle.features.tasks.models import TaskState, source_version
from watched_kettle.features.tasks.scheduling import ExecutionScope
from tests import test_task_repository as storage_tests


class ExecutionClient(QObject):
    ready_changed = Signal(bool)
    response_received = Signal(int, str, object, object, object)
    notification_received = Signal(str, object)
    server_request_received = Signal(object, str, object)

    def __init__(self):
        super().__init__()
        self.ready = True
        self.calls = []

    def request(self, method, params):
        self.calls.append((method, params))
        return len(self.calls)

    def reply(self, rid, result=None, error=None):
        method, params = self.calls[rid - 1]
        self.response_received.emit(rid, method, params, result, error)


@unittest.skipUnless(os.name == "nt", "current-user DPAPI")
class TaskExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        storage_tests.TaskRepositoryTests.setUp(self)
        self.spec = replace(
            self.spec, cwd=self.temp.name, source_version=source_version([])
        )
        self.client = ExecutionClient()
        # Legacy full-read response tests. Paginated production flow has separate tests.
        self.executor = QueueExecutor(
            self.repo, self.client, clock=lambda: 10.0, history_reader=False
        )
        self.executor.observe_scope(ExecutionScope(True, 0))
        self.thread = {
            "id": self.spec.thread_id,
            "projectId": self.spec.project_id,
            "cwd": self.spec.cwd,
            "canAcceptDirectInput": True,
            "status": {"type": "idle"},
            "turns": [],
        }

    def tearDown(self):
        storage_tests.TaskRepositoryTests.tearDown(self)

    def start(self):
        identity = self.repo.save(self.spec, registered=True)
        self.executor.start_batch([identity])
        self.client.reply(1, {"thread": self.thread})
        self.client.reply(2, {"thread": self.thread})
        return identity

    def test_continuous_mode_excludes_existing_unselected_work_and_drafts(self):
        first = self.repo.save(self.spec, registered=True)
        existing = self.repo.save(
            replace(self.spec, instruction="existing"), registered=True
        )
        self.executor.start_batch([first], continuous=True)
        self.assertFalse(self.repo.require(existing).batch_id)
        later = self.repo.save(replace(self.spec, instruction="later"), registered=True)
        draft = self.repo.save(replace(self.spec, instruction="draft"))
        self.executor._dispatching.clear()
        self.executor.pump()
        self.assertTrue(self.repo.require(later).batch_id)
        self.assertFalse(self.repo.require(draft).batch_id)
        self.assertFalse(self.repo.require(existing).batch_id)
        self.executor.connection_changed(False)
        self.assertFalse(self.executor.continuous_projects)

    def test_batch_default_never_adopts_later_registration(self):
        first = self.repo.save(self.spec, registered=True)
        self.executor.start_batch([first])
        later = self.repo.save(replace(self.spec, instruction="later"), registered=True)
        self.executor._dispatching.clear()
        self.executor.pump()
        self.assertFalse(self.repo.require(later).batch_id)

    def test_two_independent_projects_can_finish_reserved_start_handshakes(self):
        from pathlib import Path

        identities, threads = [], []
        for index in range(2):
            path = Path(self.temp.name) / f"project-{index}"
            path.mkdir()
            spec = replace(
                self.spec,
                cwd=str(path),
                project_id=f"project-{index}",
                thread_id=f"thread-{index}",
                instruction=f"work-{index}",
            )
            identities.append(self.repo.save(spec, registered=True))
            threads.append(
                dict(
                    self.thread,
                    cwd=str(path),
                    projectId=spec.project_id,
                    id=spec.thread_id,
                )
            )
        self.executor.start_batch(identities)
        self.client.reply(1, {"thread": threads[0]})
        self.client.reply(2, {"thread": threads[1]})
        self.client.reply(3, {"thread": threads[0]})
        self.client.reply(5, {"turn": {"id": "turn-0"}})
        self.client.reply(4, {"thread": threads[1]})
        self.assertEqual(
            sum(method == "turn/start" for method, _ in self.client.calls), 2
        )

    def test_record_exists_before_turn_start_and_lost_response_never_retries(self):
        identity = self.start()
        self.assertEqual(self.client.calls[2][0], "turn/start")
        item = self.repo.require(identity)
        self.assertEqual(item.state, TaskState.STARTING)
        self.assertTrue(item.attempt_id)
        self.client.reply(3, error={"code": "timeout"})
        self.assertEqual(self.repo.require(identity).state, TaskState.RECONCILING)
        self.executor.pump()
        self.assertEqual(
            sum(method == "turn/start" for method, _ in self.client.calls), 1
        )

    def test_source_change_never_sends_resume_or_start(self):
        identity = self.repo.save(self.spec, registered=True)
        self.executor.start_batch([identity])
        changed = dict(self.thread, turns=[{"id": "new", "items": []}])
        self.client.reply(1, {"thread": changed})
        self.assertEqual(self.executor.reasons[identity], "source_changed")
        self.assertEqual(len(self.client.calls), 1)
        self.assertEqual(self.repo.require(identity).state, TaskState.QUEUED)

    def test_pause_during_preflight_never_reserves(self):
        identity = self.repo.save(self.spec, registered=True)
        self.executor.start_batch([identity])
        self.executor.paused = True
        self.client.reply(1, {"thread": self.thread})
        self.assertEqual(self.repo.require(identity).attempt_id, "")
        self.assertEqual(len(self.client.calls), 1)

    def test_completed_response_needs_manual_condition_then_erases_content(self):
        identity = self.start()
        self.client.reply(3, {"turn": {"id": "owned-turn"}})
        attempt = self.repo.require(identity).attempt_id
        self.executor._completed(
            attempt, {"id": "owned-turn", "status": "completed", "items": []}
        )
        self.assertEqual(self.repo.require(identity).state, TaskState.NEEDS_REVIEW)
        self.executor.confirm_result(attempt)
        self.assertEqual(self.repo.require(identity).state, TaskState.COMPLETE)
        self.assertIsNone(self.repo.require(identity).spec)

    def test_manual_confirmation_resumes_project_but_keeps_user_pause(self):
        identity = self.start()
        self.client.reply(3, {"turn": {"id": "owned-turn"}})
        attempt = self.repo.require(identity).attempt_id
        self.executor._completed(
            attempt, {"id": "owned-turn", "status": "completed", "items": []}
        )
        self.assertIn(self.spec.project_id, self.executor.paused_projects)
        self.executor.pause()
        self.executor.confirm_result(attempt)
        self.assertNotIn(self.spec.project_id, self.executor.paused_projects)
        self.assertTrue(self.executor.paused)

    def test_resolved_approval_cannot_be_answered_again(self):
        identity = self.start()
        self.client.reply(3, {"turn": {"id": "owned-turn"}})
        request = {"threadId": self.spec.thread_id, "turnId": "owned-turn"}
        self.executor.server_request(
            99, "item/commandExecution/requestApproval", request
        )
        self.assertEqual(self.executor.request_details[99]["task_id"], identity)
        self.executor.notification("serverRequest/resolved", {"requestId": 99})
        self.assertNotIn(99, self.executor.request_details)
        with self.assertRaisesRegex(ValueError, "request_expired"):
            self.executor.answer_request(99, {"decision": "accept"})

    def test_new_review_after_completed_turn_keeps_that_turn_in_its_version(self):
        identity = self.start()
        self.client.reply(3, {"turn": {"id": "owned-turn"}})
        attempt = self.repo.require(identity).attempt_id
        turn = {"id": "owned-turn", "status": "completed", "items": []}
        self.executor._completed(attempt, turn, manual_confirmed=True)
        next_spec = replace(
            self.spec,
            title="Next",
            instruction="new task",
            source_version=source_version([turn]),
        )
        successor = self.repo.save(next_spec, registered=True)
        self.executor.observe_scope(ExecutionScope(True, 0))
        self.executor.start_batch([successor])
        self.client.reply(
            len(self.client.calls), {"thread": {**self.thread, "turns": [turn]}}
        )
        self.assertEqual(self.repo.require(successor).state, TaskState.STARTING)
        self.assertEqual(self.client.calls[-1][0], "thread/resume")

    def test_original_batch_continues_after_confirming_first_result(self):
        first = self.repo.save(self.spec, registered=True)
        second = self.repo.save(
            replace(self.spec, instruction="next task"), registered=True
        )
        self.executor.start_batch([first, second])
        self.client.reply(1, {"thread": self.thread})
        self.client.reply(2, {"thread": self.thread})
        self.client.reply(3, {"turn": {"id": "owned-turn"}})
        attempt = self.repo.require(first).attempt_id
        turn = {"id": "owned-turn", "status": "completed", "items": []}
        self.executor._completed(attempt, turn)
        self.executor.confirm_result(attempt)
        self.executor.observe_scope(ExecutionScope(True, 0))
        self.client.reply(
            len(self.client.calls), {"thread": {**self.thread, "turns": [turn]}}
        )
        self.assertEqual(self.repo.require(second).state, TaskState.STARTING)

    def test_emergency_during_start_keeps_stop_intent_until_turn_identity_arrives(self):
        identity = self.start()
        self.executor.emergency_stop()
        self.assertFalse(any(m == "turn/interrupt" for m, _ in self.client.calls))
        self.client.reply(3, {"turn": {"id": "late-owned-turn"}})
        self.assertEqual(
            [p for m, p in self.client.calls if m == "turn/interrupt"],
            [{"threadId": self.spec.thread_id, "turnId": "late-owned-turn"}],
        )
        self.assertEqual(self.repo.require(identity).state, TaskState.RUNNING)

    def test_activation_race_retries_stop_once_and_never_after_connection_change(self):
        identity = self.start()
        self.client.reply(3, {"turn": {"id": "owned-turn"}})
        self.executor.emergency_stop()
        error = {"code": -32600, "message": "no active turn to interrupt"}
        with patch(
            "watched_kettle.features.tasks.execution.QTimer.singleShot"
        ) as timer:
            self.client.reply(len(self.client.calls), error=error)
            timer.assert_called_once()
            retry = timer.call_args.args[1]
            retry()
            self.client.reply(len(self.client.calls), error=error)
            timer.assert_called_once()
        self.assertEqual(sum(m == "turn/interrupt" for m, _ in self.client.calls), 2)
        self.assertEqual(self.repo.require(identity).state, TaskState.RECONCILING)
        self.executor.connection_changed(False)
        count = len(self.client.calls)
        retry()
        self.assertEqual(len(self.client.calls), count)
        self.assertEqual(sum(m == "turn/start" for m, _ in self.client.calls), 1)

    def test_emergency_interrupt_only_uses_ledger_owned_turn(self):
        identity = self.start()
        self.client.reply(3, {"turn": {"id": "owned-turn"}})
        self.executor.emergency_stop()
        calls = [p for method, p in self.client.calls if method == "turn/interrupt"]
        self.assertEqual(
            calls, [{"threadId": self.spec.thread_id, "turnId": "owned-turn"}]
        )
        self.assertEqual(self.repo.require(identity).state, TaskState.RUNNING)
        self.assertTrue(self.executor.paused)


if __name__ == "__main__":
    unittest.main()
