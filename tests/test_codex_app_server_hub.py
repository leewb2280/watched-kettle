"""One App Server shared by several readers, each with its own view."""

from itertools import count
import time
import unittest

from PySide6.QtCore import QCoreApplication, QObject, Signal

from watched_kettle.integrations.codex_app_server_hub import AppServerHub


class FakeClient(QObject):
    ready_changed = Signal(bool)
    response_received = Signal(int, str, object, object, object)
    notification_received = Signal(str, object)
    error_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ready = False
        self.starts = 0
        self.closes = 0
        self.reject = False
        self.ready_on_start = True
        self.requests = {}
        self._ids = count(1)

    def start(self):
        self.starts += 1
        if self.ready_on_start and not self.ready:
            self.ready = True
            self.ready_changed.emit(True)

    def close(self):
        self.closes += 1
        if self.ready:
            self.ready = False
            self.ready_changed.emit(False)
        pending, self.requests = self.requests, {}
        for rid, (method, params) in pending.items():
            self.response_received.emit(rid, method, params, None, {"code": "closed"})

    def request(self, method, params=None, timeout_ms=10_000):
        if self.reject or not self.ready:
            return None
        rid = next(self._ids)
        self.requests[rid] = (method, params)
        return rid

    def respond(self, rid, result):
        method, params = self.requests.pop(rid)
        self.response_received.emit(rid, method, params, result, None)


def wait_until(condition, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if condition():
            return True
        time.sleep(0.005)
    return False


class Recorder:
    def __init__(self, handle):
        self.handle = handle
        self.ready = []
        self.responses = []
        self.notifications = []
        handle.ready_changed.connect(self.ready.append)
        handle.response_received.connect(
            lambda rid, method, params, result, error: self.responses.append(
                (rid, method, result, (error or {}).get("code"))
            )
        )
        handle.notification_received.connect(
            lambda method, params: self.notifications.append(method)
        )


class AppServerHubTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.clients = []

        def factory(parent=None):
            client = FakeClient(parent)
            self.clients.append(client)
            return client

        self.hub = AppServerHub(client_factory=factory)
        self.addCleanup(self.hub.close)

    def handle(self, **options):
        recorder = Recorder(self.hub.handle_factory(**options)())
        recorder.handle.start()
        self.assertTrue(wait_until(lambda: recorder.handle.ready))
        return recorder

    @property
    def client(self):
        return self.clients[0]

    def test_readers_share_one_process_and_get_only_their_replies(self):
        usage, metadata = self.handle(), self.handle()
        self.assertEqual(len(self.clients), 1)
        self.assertEqual(self.client.starts, 2)
        first = usage.handle.request("account/read", {})
        second = metadata.handle.request("account/read", {})
        self.assertEqual((first, second), (1, 1))
        self.assertTrue(wait_until(lambda: len(self.client.requests) == 2))
        for rid in sorted(self.client.requests):
            self.client.respond(rid, {"rid": rid})
        self.assertTrue(wait_until(lambda: usage.responses and metadata.responses))
        self.assertEqual(usage.responses, [(1, "account/read", {"rid": 1}, None)])
        self.assertEqual(metadata.responses, [(1, "account/read", {"rid": 2}, None)])

    def test_notifications_reach_every_open_reader(self):
        usage, metadata = self.handle(), self.handle()
        metadata.handle.close()
        self.client.notification_received.emit("account/updated", {})
        self.assertTrue(wait_until(lambda: usage.notifications))
        QCoreApplication.processEvents()
        self.assertEqual(usage.notifications, ["account/updated"])
        self.assertEqual(metadata.notifications, [])

    def test_one_reader_closing_leaves_the_others_connected(self):
        usage, metadata = self.handle(), self.handle()
        metadata.handle.request("thread/read", {})
        metadata.handle.close()
        self.assertFalse(metadata.handle.ready)
        self.assertEqual(metadata.ready, [True, False])
        self.assertEqual(metadata.responses, [(1, "thread/read", None, "closed")])
        self.assertIsNone(metadata.handle.request("thread/read", {}))
        self.assertTrue(wait_until(lambda: len(self.client.requests) == 1))
        # The server still answers; the closed reader does not hear it.
        self.client.respond(next(iter(self.client.requests)), {"late": True})
        time.sleep(0.05)
        QCoreApplication.processEvents()
        self.assertEqual(len(metadata.responses), 1)
        self.assertTrue(usage.handle.ready)
        self.assertEqual(self.client.closes, 0)
        usage.handle.close()
        self.assertTrue(wait_until(lambda: self.client.closes == 1))

    def test_last_reader_closing_ends_the_process_and_next_start_returns(self):
        reader = self.handle()
        reader.handle.close()
        self.assertTrue(wait_until(lambda: self.client.closes == 1))
        self.assertFalse(self.client.ready)
        reader.handle.start()
        self.assertTrue(wait_until(lambda: reader.handle.ready))
        self.assertEqual(self.client.starts, 2)

    def test_usage_reconnect_restarts_the_shared_process(self):
        usage = self.handle(restart_on_reopen=True)
        metadata = self.handle()
        usage.handle.close()
        usage.handle.start()
        self.assertTrue(wait_until(lambda: self.client.closes == 1))
        self.assertTrue(wait_until(lambda: usage.handle.ready))
        self.assertTrue(wait_until(lambda: metadata.ready == [True, False, True]))
        # Two first opens, then the restart.
        self.assertEqual(self.client.starts, 3)

    def test_a_close_before_the_first_open_still_restarts_the_process(self):
        # Signed out at start, the metadata reader keeps the process alive;
        # the sign-in check closes and starts the usage reader before it opened.
        self.handle()
        usage = Recorder(self.hub.handle_factory(restart_on_reopen=True)())
        usage.handle.close()
        usage.handle.start()
        self.assertTrue(wait_until(lambda: self.client.closes == 1))
        self.assertTrue(wait_until(lambda: usage.handle.ready))

    def test_a_restart_replaces_a_process_that_is_still_starting(self):
        usage = self.handle(restart_on_reopen=True)
        self.handle()  # the metadata reader keeps the process open
        self.client.ready_on_start = False
        self.client.close()  # the server exited; the client starts it again
        self.client.start()
        self.assertFalse(self.client.ready)
        closes = self.client.closes
        usage.handle.close()
        usage.handle.start()
        self.assertTrue(wait_until(lambda: self.client.closes == closes + 1))

    def test_a_refused_request_comes_back_as_an_error_reply(self):
        reader = self.handle()
        self.client.reject = True
        rid = reader.handle.request("thread/read", {})
        self.assertTrue(wait_until(lambda: reader.responses))
        self.assertEqual(
            reader.responses, [(rid, "thread/read", None, "app_server_request_limit")]
        )

    def test_closing_the_hub_ends_the_process(self):
        self.handle()
        self.hub.close()
        self.assertEqual(self.client.closes, 1)
        self.hub.close()


if __name__ == "__main__":
    unittest.main()
