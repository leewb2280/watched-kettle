import io
import os
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from watched_kettle.integrations.assistant_notification import (
    build_notification_payload,
    run_assistant_notification,
)
from watched_kettle.integrations.codex_hooks import sanitize_pet_event
from watched_kettle.integrations.codex_spool import (
    MAX_EVENT_AGE_SECONDS,
    drain_spooled_events,
    spool_pet_event,
)


class AssistantNotificationTests(unittest.TestCase):
    def test_builds_provider_neutral_schedule_payload(self):
        payload = build_notification_payload(
            [
                "--assistant-notification",
                "--message",
                "10분 뒤 회의가 시작돼요",
                "--urgency",
                "high",
                "--notification-id",
                "meeting-123",
            ]
        )

        self.assertEqual(
            payload,
            {
                "source": "schedule",
                "event": "notification",
                "session_id": "meeting-123",
                "event_id": "meeting-123",
                "message": "10분 뒤 회의가 시작돼요",
                "urgency": "high",
            },
        )

    def test_sanitizer_accepts_only_bounded_schedule_notifications(self):
        sanitized = sanitize_pet_event(
            {
                "source": "calendar",
                "event": "ReminderDue",
                "session_id": "meeting 123",
                "message": "일정 제목 " * 30,
                "priority": "urgent",
            }
        )

        self.assertEqual(sanitized["source"], "schedule")
        self.assertEqual(sanitized["event"], "notification")
        self.assertEqual(sanitized["session_id"], "meeting_123")
        self.assertEqual(sanitized["urgency"], "high")
        self.assertEqual(len(sanitized["message"]), 120)
        self.assertIsNone(
            sanitize_pet_event(
                {
                    "source": "schedule",
                    "event": "tool_start",
                }
            )
        )
        self.assertIsNone(
            sanitize_pet_event(
                {
                    "source": "unknown-service",
                    "event": "notification",
                }
            )
        )

    def test_delivery_reports_success_and_uses_local_server(self):
        calls = []

        def sender(payload, server_name):
            calls.append((payload, server_name))
            return True

        output = io.StringIO()
        with redirect_stdout(output):
            result = run_assistant_notification(
                [
                    "--assistant-notification",
                    "--message",
                    "집중 시간이 끝났어요",
                ],
                sender=sender,
            )

        self.assertEqual(result, 0)
        self.assertEqual(len(calls), 1)
        self.assertIn('"accepted":true', output.getvalue())
        self.assertIn('"delivered":true', output.getvalue())

    def test_pipe_failure_queues_to_the_selected_user_runtime(self):
        queued = []

        def fallback(payload, spool_directory):
            queued.append((payload, spool_directory))
            return True

        output = io.StringIO()
        with redirect_stdout(output):
            result = run_assistant_notification(
                ["--assistant-notification", "--message", "알림"],
                sender=lambda payload, server_name: False,
                fallback=fallback,
            )

        self.assertEqual(result, 0)
        self.assertEqual(len(queued), 1)
        self.assertIn('"outcome":"queued"', output.getvalue())

    def test_delivery_failure_returns_nonzero(self):
        output = io.StringIO()
        with redirect_stdout(output):
            result = run_assistant_notification(
                ["--assistant-notification", "--message", "알림"],
                sender=lambda payload, server_name: False,
                fallback=lambda payload, spool_directory: False,
            )

        self.assertEqual(result, 1)
        self.assertIn('"accepted":false', output.getvalue())
        self.assertIn('"delivered":false', output.getvalue())

    def test_windowed_executable_can_deliver_without_stdout(self):
        with patch(
            "watched_kettle.integrations.assistant_notification.sys.stdout",
            None,
        ):
            result = run_assistant_notification(
                ["--assistant-notification", "--message", "알림"],
                sender=lambda payload, server_name: True,
            )

        self.assertEqual(result, 0)

    def test_schedule_queue_is_consumed_or_expires_within_one_minute(self):
        payload = {
            "source": "schedule",
            "event": "notification",
            "session_id": "private-meeting",
            "message": "민감한 일정 제목",
            "urgency": "normal",
        }
        with TemporaryDirectory() as directory:
            queue = Path(directory)
            self.assertTrue(spool_pet_event(payload, queue))
            queued_path = next(queue.glob("*.json"))
            self.assertIn("민감한 일정 제목", queued_path.read_text("utf-8"))

            events = list(drain_spooled_events(queue))

            self.assertEqual(events[0]["message"], "민감한 일정 제목")
            self.assertEqual(list(queue.glob("*.json")), [])

            self.assertTrue(spool_pet_event(payload, queue))
            stale_path = next(queue.glob("*.json"))
            stale_time = time.time() - MAX_EVENT_AGE_SECONDS - 1
            os.utime(stale_path, (stale_time, stale_time))

            self.assertEqual(list(drain_spooled_events(queue)), [])
            self.assertEqual(list(queue.glob("*.json")), [])


if __name__ == "__main__":
    unittest.main()
