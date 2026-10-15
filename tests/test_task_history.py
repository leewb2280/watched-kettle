import unittest

from PySide6.QtWidgets import QApplication

from watched_kettle.features.tasks.history import HistoryReader
from watched_kettle.features.tasks.models import source_version
from tests.test_task_catalog import CatalogClient


class TaskHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.client = CatalogClient()
        self.reader = HistoryReader(self.client)
        self.completed, self.failures = [], []
        self.reader.completed.connect(self.completed.append)
        self.reader.failed.connect(
            lambda identity, reason: self.failures.append((identity, reason))
        )
        self.metadata = {
            "id": "t",
            "projectId": "p",
            "cwd": "C:/work",
            "updatedAt": 12,
            "status": {"type": "idle"},
        }

    def tearDown(self):
        self.reader.cancel()
        self.reader.deleteLater()
        self.app.processEvents()

    def reply(self, result=None, error=None):
        self.client.reply(len(self.client.calls), result, error)
        for _ in range(4):
            self.app.processEvents()

    def start_items(self):
        self.reader.start("t")
        self.reply({"thread": self.metadata})
        self.assertEqual(self.client.calls[-1][0], "thread/turns/list")
        self.reply({"data": [{"id": "turn", "status": "completed"}]})
        self.assertEqual(self.client.calls[-1][0], "thread/items/list")

    def test_long_history_streams_and_late_cancel_is_applied_before_publication(self):
        self.start_items()
        original = {
            "id": "first",
            "type": "userMessage",
            "content": [{"type": "text", "text": "- [ ] 위젯 수정"}],
        }
        entries = [original]
        self.reply(
            {"data": [{"turnId": "turn", "item": original}], "nextCursor": "more"}
        )
        self.assertEqual(self.completed, [])
        for page in range(3):
            items = [
                {"id": f"{page}-{i}", "type": "agentMessage", "text": "설명 " * 500}
                for i in range(100)
            ]
            entries.extend(items)
            self.reply(
                {
                    "data": [{"turnId": "turn", "item": item} for item in items],
                    "nextCursor": f"page-{page}",
                }
            )
        cancel = {
            "id": "last",
            "type": "userMessage",
            "content": [{"type": "text", "text": "위젯 수정은 취소해"}],
        }
        entries.append(cancel)
        self.reply({"data": [{"turnId": "turn", "item": cancel}]})
        self.assertEqual(self.client.calls[-1][0], "thread/read")
        self.assertEqual(self.completed, [])
        self.reply({"thread": self.metadata})
        self.assertEqual(self.failures, [])
        result = self.completed[0]
        self.assertEqual(result["extraction"].candidates, ())
        self.assertGreater(result["extraction"].messages_read, 200)
        self.assertEqual(
            result["sourceVersion"],
            source_version([{"id": "turn", "status": "completed", "items": entries}]),
        )
        self.assertNotIn("turns", result)
        self.assertEqual(self.reader.items, [])

    def test_page_failure_is_not_empty_success_or_fallback(self):
        self.start_items()
        self.reply(error={"code": -32000, "message": "timeout"})
        self.assertEqual(self.completed, [])
        self.assertTrue(self.failures)
        self.assertFalse(any(p.get("includeTurns") for _, p in self.client.calls))

    def test_unsupported_pagination_falls_back_with_explicit_oversize_failure(self):
        self.reader.start("t")
        self.reply({"thread": self.metadata})
        self.reply(error={"code": -32601, "message": "method not found"})
        self.assertEqual(
            self.client.calls[-1],
            ("thread/read", {"threadId": "t", "includeTurns": True}),
        )
        self.reply(
            {
                "thread": {
                    **self.metadata,
                    "turns": [
                        {
                            "id": "turn",
                            "items": [{"type": "agentMessage", "text": "x" * 300000}],
                        }
                    ],
                }
            }
        )
        self.assertEqual(self.completed, [])
        self.assertIn("페이지 조회", self.failures[0][1])

    def test_item_from_other_turn_and_metadata_change_are_rejected(self):
        self.start_items()
        self.reply(
            {
                "data": [
                    {
                        "turnId": "other",
                        "item": {"type": "agentMessage", "text": "- [ ] 잘못된 작업"},
                    }
                ]
            }
        )
        self.assertTrue(self.failures)
        self.start_items()
        self.reply({"data": []})
        self.reply({"thread": {**self.metadata, "updatedAt": 13}})
        self.assertEqual(self.completed, [])
        self.assertIn("변경", self.failures[-1][1])

    def test_cancel_discards_queued_callbacks_and_late_responses(self):
        self.start_items()
        self.reader.cancel()
        count = len(self.client.calls)
        self.reply(
            {
                "data": [
                    {
                        "turnId": "turn",
                        "item": {"type": "agentMessage", "text": "- [ ] 오래된 작업"},
                    }
                ]
            }
        )
        self.assertEqual(len(self.client.calls), count)
        self.assertEqual(self.completed, [])
