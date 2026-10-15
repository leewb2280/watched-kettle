import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from watched_kettle.features.tasks.catalog import ConversationCatalog


class CatalogClient(QObject):
    ready_changed = Signal(bool)
    response_received = Signal(int, str, object, object, object)
    notification_received = Signal(str, object)

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

    def close(self):
        self.ready = False


class TaskCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.client = CatalogClient()
        self.catalog = ConversationCatalog(self.client)
        self.catalog.enable(True)
        self.client.reply(1, {"account": {"id": "account"}})

    def test_pages_are_atomic_and_previews_not_retained(self):
        self.client.reply(2, {"data": [{"id": "p", "name": "Project"}]})
        self.client.reply(
            3,
            {
                "data": [{"id": "t", "preview": "SECRET", "turns": ["SECRET"]}],
                "nextCursor": "next",
            },
        )
        self.assertEqual(self.catalog.threads, {})
        self.client.reply(4, {"data": [{"id": "t2"}]})
        self.assertEqual(len(self.catalog.threads), 2)
        self.assertNotIn("preview", self.catalog.threads["t"])
        self.assertNotIn("turns", self.catalog.threads["t"])
        self.assertFalse(self.catalog.stale)

    def test_repeated_cursor_is_failure_not_empty_success(self):
        self.client.reply(2, {"data": []})
        self.client.reply(3, {"data": [], "nextCursor": "loop"})
        self.client.reply(4, {"data": [], "nextCursor": "loop"})
        self.assertTrue(self.catalog.stale)
        self.assertEqual(len(self.client.calls), 4)

    def test_account_change_clears_old_catalog_and_late_response(self):
        self.client.reply(2, {"data": [{"id": "p"}]})
        self.client.reply(3, {"data": [{"id": "t"}]})
        self.catalog.read_thread("t")
        read_id = len(self.client.calls)
        delivered = []
        self.catalog.thread_read.connect(delivered.append)
        self.catalog.notification("account/updated", {})
        self.client.reply(read_id, {"thread": {"id": "t", "turns": []}})
        self.assertEqual(self.catalog.threads, {})
        self.assertEqual(delivered, [])

    def test_refresh_same_account_preserves_review_session(self):
        changes = []
        self.catalog.account_changed.connect(changes.append)
        self.catalog.refresh()
        self.client.reply(len(self.client.calls), {"account": {"id": "account"}})
        self.assertEqual(changes, [])

    def test_excluded_project_cannot_read_body(self):
        self.client.reply(2, {"data": [{"id": "p"}]})
        self.client.reply(3, {"data": [{"id": "t", "projectId": "p"}]})
        self.catalog.excluded_projects.add("p")
        count = len(self.client.calls)
        self.catalog.read_thread("t")
        self.assertEqual(len(self.client.calls), count)


if __name__ == "__main__":
    unittest.main()
