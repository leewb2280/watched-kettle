import os
from threading import Thread
import unittest
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtNetwork import QLocalSocket
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from watched_kettle.integrations.single_instance import (
    ACK_COMMAND,
    QUIT_COMMAND,
    SingleInstanceCoordinator,
)


class SingleInstanceCoordinatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.server_name = f"watched-kettle-test-{uuid4().hex}"
        self.coordinators = []

    def tearDown(self):
        for coordinator in reversed(self.coordinators):
            coordinator.close()
        self.app.processEvents()

    def create_coordinator(self):
        coordinator = SingleInstanceCoordinator(
            server_name=self.server_name,
            connect_timeout_ms=100,
        )
        self.coordinators.append(coordinator)
        return coordinator

    def test_first_process_becomes_primary(self):
        primary = self.create_coordinator()

        self.assertTrue(primary.start())
        self.assertTrue(primary.server.isListening())

    def test_second_process_requests_primary_activation(self):
        primary = self.create_coordinator()
        activations = []
        secondary_results = []
        primary.activation_requested.connect(lambda: activations.append(True))
        self.assertTrue(primary.start())

        def launch_secondary():
            secondary = SingleInstanceCoordinator(
                server_name=self.server_name,
                connect_timeout_ms=500,
            )
            secondary_results.append(secondary.start())
            secondary.close()

        thread = Thread(target=launch_secondary)
        thread.start()
        for _ in range(100):
            if not thread.is_alive():
                break
            QTest.qWait(10)
        thread.join(timeout=1)
        QTest.qWait(50)

        self.assertEqual(secondary_results, [False])
        self.assertEqual(activations, [True])

    def test_quit_command_requests_quit_only(self):
        primary = self.create_coordinator()
        activations = []
        quits = []
        replies = []
        primary.activation_requested.connect(lambda: activations.append(True))
        primary.quit_requested.connect(lambda: quits.append(True))
        self.assertTrue(primary.start())

        def send_quit():
            # Mirrors the installer's raw pipe client: write, then read the ack.
            socket = QLocalSocket()
            socket.connectToServer(self.server_name)
            if socket.waitForConnected(500):
                socket.write(QUIT_COMMAND)
                socket.flush()
                socket.waitForBytesWritten(500)
                for _ in range(10):
                    if socket.waitForReadyRead(200):
                        break
                replies.append(bytes(socket.readAll()))
            socket.abort()

        thread = Thread(target=send_quit)
        thread.start()
        for _ in range(300):
            if not thread.is_alive():
                break
            QTest.qWait(10)
        thread.join(timeout=1)
        QTest.qWait(50)

        self.assertEqual(replies, [ACK_COMMAND])
        self.assertEqual(quits, [True])
        self.assertEqual(activations, [])

    def test_endpoint_can_be_reused_after_primary_closes(self):
        primary = self.create_coordinator()
        replacement = self.create_coordinator()
        self.assertTrue(primary.start())

        primary.close()
        self.app.processEvents()

        self.assertTrue(replacement.start())


if __name__ == "__main__":
    unittest.main()
