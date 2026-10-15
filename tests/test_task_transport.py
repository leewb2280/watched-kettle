import json
import unittest

from PySide6.QtWidgets import QApplication

from watched_kettle.integrations.codex_task_client import CodexTaskClient
from tests.test_codex_app_server import FakeProcess


class TaskTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_server_request_is_only_answered_after_user_decision(self):
        client = CodexTaskClient(program="codex", process_factory=FakeProcess)
        try:
            requests = []
            client.server_request_received.connect(lambda *args: requests.append(args))
            client.start()
            client.feed_bytes(b'{"id":1,"result":{}}\n')
            count = len(client.process.writes)
            client.feed_bytes(
                b'{"id":"approval-1","method":"item/commandExecution/requestApproval","params":{"threadId":"t","turnId":"turn"}}\n'
            )
            self.assertEqual(len(client.process.writes), count)
            self.assertEqual(len(requests), 1)
            self.assertTrue(
                client.answer_server_request("approval-1", {"decision": "decline"})
            )
            self.assertEqual(
                json.loads(client.process.writes[-1])["result"], {"decision": "decline"}
            )
            self.assertFalse(
                client.answer_server_request("approval-1", {"decision": "accept"})
            )
        finally:
            client.close()

    def test_reconnect_invalidates_old_server_requests(self):
        client = CodexTaskClient(program="codex", process_factory=FakeProcess)
        try:
            client.start()
            client.feed_bytes(b'{"id":1,"result":{}}\n')
            client.feed_bytes(b'{"id":"old","method":"input","params":{}}\n')
            client.ready_changed.emit(False)
            self.assertFalse(client.answer_server_request("old", {}))
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()
