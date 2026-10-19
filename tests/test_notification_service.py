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

    def test_confirm_all_marks_every_pending_notice_and_ends_its_bubble(self):
        service = NotificationService()
        service.managed_delivery = True
        for message in ("첫째", "둘째", "셋째"):
            service.submit(NoticeRequest(source="system", message=message))
        first, second, third = service.snapshot.recent
        service.confirm(third.record_id)
        service.shown(service.candidates()[0].record_id)
        emitted = []
        service.snapshot_changed.connect(emitted.append)

        service.confirm_all()

        self.assertEqual(len(emitted), 1)
        self.assertTrue(all(r.confirmed for r in service.snapshot.recent))
        self.assertEqual({r.delivery for r in service.snapshot.recent}, {"expired"})
        self.assertEqual(service.candidates(), ())
        service.confirm_all()
        self.assertEqual(len(emitted), 1)


if __name__ == "__main__":
    unittest.main()
