"""Only correlated, bounded, persisted terminal evidence may resolve activity."""

import unittest
from unittest.mock import patch

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from watched_kettle.integrations.codex_turn_status import (
    CodexTurnStatusMonitor,
    _TurnStatusWorker,
)
from watched_kettle.state.codex_activity import CodexTurnTarget


class Client(QObject):
    ready_changed = Signal(bool)
    response_received = Signal(int, str, object, object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ready = True
        self.requests = []

    def start(self):
        pass

    def close(self):
        self.ready = False

    def request(self, method, params, timeout):
        self.requests.append((method, params, timeout))
        return len(self.requests)


class TurnStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.now = 100.0
        self.worker = _TurnStatusWorker(Client, clock=lambda: self.now)
        self.target = CodexTurnTarget("s", "t", 1, 0)
        self.results = []
        self.worker.outcome.connect(lambda epoch, outcome: self.results.append(outcome))

    def sync(self, *targets):
        self.worker.sync(targets or (self.target,), self.worker.epoch)

    def reply(self, data=(), cursor=None, error=None):
        rid = self.worker.pending[0]
        self.worker.response(
            rid,
            "thread/turns/list",
            {},
            dict(data=list(data), nextCursor=cursor),
            error,
        )

    def test_terminal_mapping_is_exact_and_content_free(self):
        for status, expected in (
            ("completed", "done"),
            ("failed", "failed"),
            ("interrupted", "cancelled"),
        ):
            with self.subTest(status=status):
                self.sync()
                self.reply(
                    [
                        dict(
                            id="t",
                            status=status,
                            error=None
                            if status == "completed"
                            else dict(
                                codexErrorInfo="usageLimitExceeded", message="SECRET"
                            ),
                        )
                    ]
                )
                self.assertEqual(self.results[-1].state, expected)
                self.assertNotIn("SECRET", repr(self.results))
                self.now += 30
        self.assertEqual(self.results[1].reason, "usage_limit")
        self.assertTrue(
            all(r[0] == "thread/turns/list" for r in self.worker.client.requests)
        )
        self.assertTrue(
            all(
                r[1]["itemsView"] == "notLoaded" and r[2] == 10000
                for r in self.worker.client.requests
            )
        )

    def test_active_missing_malformed_and_failed_reads_confirm_nothing(self):
        for data, error in (
            ([dict(id="t", status="inProgress")], None),
            ([dict(id="other", status="completed")], None),
            ([], dict(code="timeout")),
        ):
            self.sync()
            self.reply(data, error=error)
            self.assertFalse(self.results)
            self.now += 30
        self.sync()
        rid = self.worker.pending[0]
        self.worker.response(rid, "thread/turns/list", {}, dict(data="bad"), None)
        self.assertFalse(self.results)

    def test_read_budget_is_two_pages_and_retry_is_throttled(self):
        self.sync()
        self.reply([dict(id="older", status="completed")], cursor="page2")
        self.assertEqual(len(self.worker.client.requests), 2)
        self.reply([], cursor="page3")
        self.worker.pump()
        self.assertEqual(len(self.worker.client.requests), 2)
        self.now += 30
        self.worker.pump()
        self.assertEqual(len(self.worker.client.requests), 3)

    def test_changed_target_and_old_connection_replies_are_discarded(self):
        self.sync()
        replacement = CodexTurnTarget("s", "t", 2, 0)
        self.sync(replacement)
        self.reply([dict(id="t", status="completed")])
        self.assertFalse(self.results)
        self.now += 30
        self.worker.pump()
        old = self.worker.pending
        self.worker.ready(False)
        self.worker.response(
            old[0],
            "thread/turns/list",
            {},
            dict(data=[dict(id="t", status="failed")]),
            None,
        )
        self.assertFalse(self.results)

    def test_unsupported_is_quiet_until_reconnect_and_queue_is_bounded(self):
        self.sync(*(CodexTurnTarget(str(i), "t", 1, 0) for i in range(200)))
        self.assertEqual(len(self.worker.targets), 128)
        self.reply(error=dict(code=-32601))
        self.now += 100
        self.worker.pump()
        self.assertEqual(len(self.worker.client.requests), 1)
        self.worker.ready(True)
        self.assertEqual(len(self.worker.client.requests), 2)

    def test_ended_has_priority_and_previous_account_results_do_not_escape(self):
        ended = CodexTurnTarget("e", "t", 3, 0, True)
        self.sync(self.target, ended)
        self.assertEqual(self.worker.client.requests[0][1]["threadId"], "e")
        monitor = CodexTurnStatusMonitor(client_factory=Client)
        seen = []
        diagnostics = []
        monitor.outcome_detected.connect(seen.append)
        monitor.diagnostic_event.connect(lambda *args: diagnostics.append(args))
        monitor.account_changed(True)
        monitor.receive(0, object())
        monitor.receive_diagnostic(0, "old", {})
        self.assertFalse(seen)
        self.assertFalse(diagnostics)
        monitor.close()

    def test_diagnostic_preparation_failure_does_not_hide_real_outcome(self):
        self.sync()
        with patch(
            "watched_kettle.integrations.codex_turn_status.diagnostic_ref",
            side_effect=RuntimeError("diagnostic failure"),
        ):
            self.reply([dict(id="t", status="completed", error=None)])
        self.assertEqual(self.results[0].state, "done")
