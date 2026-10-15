import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from watched_kettle.features.notifications.models import NoticeRequest
from watched_kettle.features.notifications.service import NotificationService


class NotificationServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_request_becomes_privacy_safe_agent_payload(self):
        service = NotificationService()
        payloads = []
        service.payload_ready.connect(payloads.append)
        self.assertTrue(
            service.submit(
                NoticeRequest(
                    source="system",
                    message="공유 한도 90% 사용",
                    urgency="high",
                    session_id="usage",
                )
            )
        )
        self.assertEqual(payloads[0]["event"], "notification")
        self.assertEqual(payloads[0]["urgency"], "high")
        self.assertLessEqual(len(payloads[0]["message"]), 120)

    def test_explicit_deduplication_key_is_delivered_once(self):
        service = NotificationService()
        notice = NoticeRequest(
            source="system",
            message="한 번만",
            deduplication_key="same-window",
        )
        self.assertTrue(service.submit(notice))
        self.assertFalse(service.submit(notice))
        self.assertEqual(len(service.snapshot.recent), 1)


if __name__ == "__main__":
    unittest.main()
