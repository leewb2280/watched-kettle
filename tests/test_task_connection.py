import unittest

from PySide6.QtWidgets import QApplication

from watched_kettle.features.tasks.connection import (
    DesktopExecutionAdapter,
    ExecutionCapabilities,
)
from tests.test_task_catalog import CatalogClient


class TaskConnectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.client = CatalogClient()
        self.now = 10.0
        self.adapter = DesktopExecutionAdapter(
            client=self.client,
            clock=lambda: self.now,
            lock_resolver=lambda cwd: ("path:" + cwd,),
        )
        self.adapter.account = "a"

    def tearDown(self):
        self.adapter.close()
        self.adapter.deleteLater()
        self.app.processEvents()

    def reply(self, result):
        self.client.reply(len(self.client.calls), result)

    def test_read_success_does_not_attest_desktop_ownership(self):
        self.adapter.poll()
        self.reply({"account": {"id": "a"}})
        self.reply({"data": []})
        self.assertTrue(self.adapter.capabilities.readable)
        self.assertFalse(self.adapter.capabilities.executable)
        self.assertFalse(self.adapter.snapshot.reliable)

    def test_verified_contract_counts_parent_once_and_all_busy_paths(self):
        self.adapter.verified = ExecutionCapabilities(True, True, True, True, True)
        self.adapter.poll()
        self.reply({"account": {"id": "a"}})
        self.reply({"data": ["main", "child"]})
        self.reply(
            {"thread": {"id": "main", "cwd": "root", "status": {"type": "active"}}}
        )
        self.reply(
            {
                "thread": {
                    "id": "child",
                    "parentThreadId": "main",
                    "cwd": "other",
                    "status": {"type": "active"},
                }
            }
        )
        self.assertTrue(self.adapter.snapshot.reliable)
        self.assertEqual(self.adapter.snapshot.active_main_tasks, 1)
        self.assertEqual(
            self.adapter.snapshot.busy_lock_keys, frozenset({"path:root", "path:other"})
        )
        self.adapter.notification("thread/status/changed", {})
        self.assertFalse(self.adapter.snapshot.reliable)

    def test_account_mismatch_and_not_loaded_fail_closed(self):
        self.adapter.verified = ExecutionCapabilities(True, True, True, True, True)
        self.adapter.poll()
        self.reply({"account": {"id": "other-account"}})
        self.assertFalse(self.adapter.snapshot.reliable)
        self.adapter.poll()
        self.reply({"account": {"id": "a"}})
        self.reply({"data": ["unknown"]})
        self.reply({"thread": {"id": "unknown", "status": {"type": "notLoaded"}}})
        self.assertFalse(self.adapter.snapshot.reliable)

    def test_late_observation_cannot_grant_a_slot(self):
        self.adapter.verified = ExecutionCapabilities(True, True, True, True, True)
        self.adapter.poll()
        self.reply({"account": {"id": "a"}})
        self.now += 4
        self.reply({"data": []})
        self.assertFalse(self.adapter.snapshot.reliable)
