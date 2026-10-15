import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QProcess, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from watched_kettle.application.logging import close_logging, configure_logging
from watched_kettle.integrations.codex_app_server import CodexAppServerClient


class FakeProcess(QObject):
    started = Signal()
    readyReadStandardOutput = Signal()
    readyReadStandardError = Signal()
    finished = Signal(int, object)
    errorOccurred = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.writes = []
        self.program = ""
        self.arguments = []
        self.running = False

    def setProgram(self, value):
        self.program = value

    def setArguments(self, value):
        self.arguments = value

    def start(self):
        self.running = True
        self.started.emit()

    def waitForStarted(self, _timeout):
        return self.running

    def state(self):
        return (
            QProcess.ProcessState.Running
            if self.running
            else QProcess.ProcessState.NotRunning
        )

    def write(self, value):
        self.writes.append(bytes(value))
        return len(value)

    def readAllStandardOutput(self):
        return b""

    def readAllStandardError(self):
        return b""

    def terminate(self):
        self.running = False

    def waitForFinished(self, _timeout):
        return True

    def kill(self):
        self.running = False


class CodexAppServerClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.clients = []

    def tearDown(self):
        for client in self.clients:
            client.close()
        self.app.processEvents()

    def make_client(self):
        client = CodexAppServerClient(program="codex", process_factory=FakeProcess)
        self.clients.append(client)
        return client

    def test_handshake_and_split_jsonl_response(self):
        client = self.make_client()
        ready = []
        client.ready_changed.connect(ready.append)
        client.start()
        initialize = json.loads(client.process.writes[0])
        client.feed_bytes(
            (
                json.dumps({"jsonrpc": "2.0", "id": initialize["id"], "result": {}})
                + "\n"
            ).encode()[:12]
        )
        self.assertFalse(client.ready)
        remaining = (
            json.dumps({"jsonrpc": "2.0", "id": initialize["id"], "result": {}}) + "\n"
        ).encode()[12:]
        client.feed_bytes(remaining)
        self.assertTrue(client.ready)
        self.assertEqual(json.loads(client.process.writes[-1])["method"], "initialized")
        self.assertEqual(ready, [True])
        client.close()

    def test_malformed_line_does_not_break_following_notification(self):
        client = self.make_client()
        errors, notices = [], []
        client.error_changed.connect(errors.append)
        client.notification_received.connect(
            lambda method, params: notices.append((method, params))
        )
        client.feed_bytes(b'bad-json\n{"jsonrpc":"2.0","method":"ping","params":{}}\n')
        self.assertTrue(errors)
        self.assertEqual(notices[0][0], "ping")

    def test_request_timeout_matches_original_method(self):
        client = self.make_client()
        responses = []
        client.response_received.connect(
            lambda request_id, method, params, result, error: responses.append(
                (request_id, method, error)
            )
        )
        client.start()
        request_id = client.request("account/read", timeout_ms=5)
        for _ in range(25):
            QTest.qWait(10)
            if any(item[0] == request_id for item in responses):
                break
        timed_out = next(item for item in responses if item[0] == request_id)
        self.assertEqual(timed_out[1], "account/read")
        self.assertEqual(timed_out[2]["code"], "timeout")
        client.close()

    def test_unexpected_process_exit_schedules_bounded_restart(self):
        client = self.make_client()
        client.start()
        client.process.running = False
        client.process.finished.emit(1, None)
        self.assertTrue(client._restart_timer.isActive())
        self.assertEqual(client._restart_timer.interval(), 5000)
        client.close()

    def test_connection_failures_emit_safe_structured_events(self):
        with TemporaryDirectory() as directory:
            log_path = configure_logging(Path(directory))
            try:
                client = self.make_client()
                client.start()
                request_id = client.request("account/read", timeout_ms=5)
                for _ in range(25):
                    QTest.qWait(10)
                    if client.error:
                        break
                self.assertIsNotNone(request_id)
                client.process.running = False
                client.process.finished.emit(1, None)
                rows = [
                    json.loads(line)
                    for line in log_path.read_text(encoding="utf-8").splitlines()
                ]
                events = {row["event"] for row in rows}
                self.assertIn("process_start", events)
                self.assertIn("initialize_sent", events)
                self.assertIn("request_timeout", events)
                self.assertIn("restart_scheduled", events)
                self.assertTrue(all("message" not in row for row in rows))
            finally:
                close_logging()


if __name__ == "__main__":
    unittest.main()
