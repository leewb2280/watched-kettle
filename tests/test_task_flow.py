import unittest

from PySide6.QtWidgets import QApplication

from watched_kettle.features.tasks.notifications import TaskNotificationBridge
from watched_kettle.features.notifications.actions import NotificationActionRouter
from watched_kettle.features.notifications.service import NotificationService
from tests.task_support import PreviewTaskService


class TaskFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_resolved_request_notice_expires_without_losing_history(self):
        service = PreviewTaskService()
        notices = NotificationService()
        router = NotificationActionRouter()
        bridge = TaskNotificationBridge(service, notices, router)
        request = {"id": 20, "epoch": 3, "task_id": "sample-task"}
        service.state["requests"] = [request]
        service.approval.emit(request)
        record = notices.snapshot.recent[0]
        self.assertEqual(router.targets[record.action_token].kind, "task")
        service.state["requests"] = []
        service.changed.emit()
        self.assertTrue(notices.snapshot.recent[0].confirmed)
        self.assertEqual(notices.snapshot.recent[0].delivery, "expired")
        self.assertEqual(bridge.active, {})
