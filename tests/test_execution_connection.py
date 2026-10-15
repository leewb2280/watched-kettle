import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PySide6.QtWidgets import QApplication

from watched_kettle.integrations.codex_task_client import CodexTaskClient
from watched_kettle.integrations.execution_connection import (
    connection_target,
    transport_failure,
)
from tests.test_codex_app_server import FakeProcess


class ConnectionDiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_explicit_endpoint_and_missing_default_are_distinguished(self):
        with TemporaryDirectory() as root:
            default = connection_target("codex", home=root)
            self.assertFalse(default.exists)
            endpoint = Path(root) / "test.sock"
            endpoint.touch()
            explicit = connection_target("codex", endpoint=endpoint)
            self.assertTrue(explicit.exists)
            self.assertEqual(explicit.arguments[-2:], ("--sock", str(endpoint)))
        with self.assertRaises(ValueError):
            connection_target("codex", endpoint="relative.sock")

    def test_stderr_classification_never_returns_secret_or_path(self):
        data = b"Error: failed to connect to C:/PRIVATE/token.sock SECRET-TOKEN (os error 10050)"
        status = transport_failure(data, endpoint_exists=False)
        self.assertEqual(status.code, "endpoint_missing")
        self.assertEqual(status.os_error, 10050)
        self.assertNotIn("PRIVATE", repr(status))
        self.assertNotIn("TOKEN", repr(status))
        self.assertEqual(transport_failure(data).code, "socket_unavailable")
        self.assertIsNone(transport_failure(b"normal diagnostic log"))

    def test_split_error_and_process_exit_retain_specific_diagnostic(self):
        client = CodexTaskClient(program="codex", process_factory=FakeProcess)
        try:
            client.start()
            process = client.process
            process.readAllStandardError = lambda: b"Error: failed to con"
            client._read_stderr()
            process.readAllStandardError = lambda: b"nect (os error 10050)"
            client._read_stderr()
            process.readAllStandardError = lambda: b""
            process.running = False
            process.finished.emit(1, None)
            self.assertEqual(client.connection_status.code, "socket_unavailable")
            self.assertEqual(client.connection_status.exit_code, 1)
        finally:
            client.close()

    def test_initialize_error_is_not_reported_as_ready(self):
        client = CodexTaskClient(program="codex", process_factory=FakeProcess)
        try:
            client.start()
            client.feed_bytes(
                (
                    json.dumps({"id": 1, "error": {"code": -1, "message": "private"}})
                    + "\n"
                ).encode()
            )
            self.assertEqual(client.connection_status.code, "initialization_failed")
            self.assertFalse(client.ready)
        finally:
            client.close()
