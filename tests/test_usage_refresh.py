"""Additional quota reads stay bounded and do not expand retained history."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from watched_kettle.app_preferences import ApplicationPreferences
from watched_kettle.application.logging import _safe_event_fields
from watched_kettle.application.runtime import ApplicationRuntime
from watched_kettle.storage.usage_repository import VolatileUsageRepository
from watched_kettle.usage.models import UsageSnapshot
from watched_kettle.usage.service import CodexUsageService
from watched_kettle.usage.worker import UsageWorkerService
from tests.test_pet_preferences import FakeSettings
from tests.test_usage_service import FakeClient


def limits(used=10, account="acct"):
    return {
        "accountId": account,
        "rateLimits": {
            "limitId": "codex",
            "primary": {"usedPercent": used, "windowDurationMins": 300},
        },
    }


class UsageRefreshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.now = datetime(2026, 11, 6, tzinfo=timezone.utc)
        self.client = FakeClient()
        self.repository = VolatileUsageRepository(now=lambda: self.now)
        self.service = CodexUsageService(
            self.client,
            ApplicationPreferences(FakeSettings()),
            self.repository,
            now=lambda: self.now,
        )
        self.client.become_ready()
        self.respond(
            "account",
            {"account": {"type": "chatgpt", "email": "fixture@example.invalid"}},
        )
        self.respond("limits", limits())
        self.respond("usage", {"summary": {"lifetimeTokens": 100}})

    def tearDown(self):
        self.service.close()

    def respond(self, kind, result=None, error=None):
        rid = next(
            rid
            for rid, context in self.service.account.requests.items()
            if context.kind == kind
        )
        self.client.respond(rid, result, error)

    def quota_requests(self):
        return sum(
            method == "account/rateLimits/read" for _, method, _ in self.client.requests
        )

    def complete(self, thread="s", event="done", scope="main"):
        for name in ("prompt", event):
            self.service.observe_agent_payload(
                dict(
                    source="codex",
                    agent_scope=scope,
                    session_id=thread,
                    turn_id="t",
                    event=name,
                )
            )

    def follow_up(self):
        self.service.completion_rate_timer.stop()
        self.service.completion_rate_timer.timeout.emit()

    def test_active_timer_only_runs_for_enabled_connected_activity(self):
        service = self.service
        self.assertFalse(service.active_rate_timer.isActive())
        service.set_codex_active(True)
        self.assertTrue(service.active_rate_timer.isActive())
        self.assertEqual(service.active_rate_timer.interval(), 60_000)
        with patch.object(service.active_rate_timer, "start") as start:
            service.set_codex_active(True)
            start.assert_not_called()
        count = self.quota_requests()
        service.active_rate_timer.timeout.emit()
        self.assertEqual(self.quota_requests(), count + 1)
        service.set_codex_active(False)
        self.assertFalse(service.active_rate_timer.isActive())

    def test_activity_logs_start_and_stop_with_read_count_not_every_read(self):
        service = self.service
        events = []

        def record(_component, event, *_args, **fields):
            events.append((event, _safe_event_fields(fields)))

        with patch("watched_kettle.usage.service.log_event", side_effect=record):
            service.set_codex_active(True)
            service.set_codex_active(True)
            service.active_rate_timer.timeout.emit()
            self.respond("limits", limits(20))
            service.active_rate_timer.timeout.emit()
            self.respond("limits", limits(30))
            self.complete()
            self.respond("limits", limits(30))
            self.follow_up()
            self.respond("limits", limits(40))
            service.set_codex_active(False)
            service.set_codex_active(False)
        names = [event for event, _ in events]
        self.assertEqual(names.count("active_limits_started"), 1)
        self.assertEqual(names.count("completion_limits_requested"), 1)
        stopped = [
            fields for event, fields in events if event == "active_limits_stopped"
        ]
        self.assertEqual(len(stopped), 1)
        self.assertEqual(stopped[0]["reads"], 2)
        self.assertEqual(stopped[0]["reason"], "inactive")
        self.assertIn("duration_ms", stopped[0])
        requested = next(
            fields for event, fields in events if event == "completion_limits_requested"
        )
        self.assertIn("request_id", requested)

    def test_account_boundary_logs_the_cancelled_activity(self):
        service = self.service
        service.set_codex_active(True)
        with patch("watched_kettle.usage.service.log_event") as log:
            service._account_checking(True)
        stopped = [
            c for c in log.call_args_list if c.args[1] == "active_limits_stopped"
        ]
        self.assertEqual(len(stopped), 1)
        self.assertEqual(stopped[0].kwargs["reason"], "cancelled")

    def test_additional_response_updates_limits_and_alerts_without_history_work(self):
        service = self.service
        service.set_codex_active(True)
        samples = self.repository.load_quota_samples(service.snapshot.account_hash)
        previous = len(self.client.requests)
        notices = []
        service.notice_requested.connect(notices.append)
        with (
            patch.object(service, "_history_values") as history,
            patch.object(service, "_refresh_hourly_activity") as aggregate,
            patch.object(service.recovery_pages, "start") as recovery,
            patch.object(service.conversation_catalog, "start") as catalog,
        ):
            service.active_rate_timer.timeout.emit()
            self.now += timedelta(seconds=60)
            self.respond("limits", limits(95))
            history.assert_not_called()
            aggregate.assert_not_called()
            recovery.assert_not_called()
            catalog.assert_not_called()
        self.assertEqual(len(self.client.requests), previous + 1)
        self.assertEqual(service.snapshot.buckets[0].primary.remaining_percent, 5)
        self.assertEqual(service.snapshot.last_updated_at, self.now)
        self.assertEqual(
            self.repository.load_quota_samples(service.snapshot.account_hash), samples
        )
        self.assertTrue(notices)

    def test_regular_reads_and_notifications_still_record_history(self):
        service = self.service
        with (
            patch.object(service, "_record_rate_limit_samples") as record,
            patch.object(service, "_refresh_hourly_activity") as aggregate,
        ):
            service.rate_timer.timeout.emit()
            self.respond("limits", limits(20))
            self.assertEqual(record.call_count, 1)
            self.assertEqual(aggregate.call_count, 1)
            self.assertTrue(
                any(c.kind == "usage" for c in service.account.requests.values())
            )
            self.client.notification_received.emit(
                "account/rateLimits/updated", limits(30)
            )
            self.assertEqual(record.call_count, 2)

    def test_completion_burst_schedules_one_fixed_five_second_followup(self):
        service = self.service
        with patch.object(
            service.completion_rate_timer,
            "start",
            wraps=service.completion_rate_timer.start,
        ) as start:
            self.complete("first")
            self.assertTrue(service.completion_rate_timer.isActive())
            self.assertEqual(service.completion_rate_timer.interval(), 5000)
            self.complete("second", "failed")
            start.assert_called_once()
        self.respond("limits", limits(10))
        # The second completion's existing full read was coalesced behind the
        # first. Finish it before observing the five-second additional read.
        self.respond("limits", limits(10))
        count = self.quota_requests()
        self.follow_up()
        self.assertEqual(self.quota_requests(), count + 1)
        self.respond("limits", limits(20))
        self.assertEqual(service.snapshot.buckets[0].primary.remaining_percent, 80)

    def test_old_inflight_response_cannot_satisfy_completion_followup(self):
        service = self.service
        service.set_codex_active(True)
        service.active_rate_timer.timeout.emit()
        self.complete()
        self.follow_up()
        count = self.quota_requests()
        for _ in range(20):
            service.active_rate_timer.timeout.emit()
        self.assertEqual(self.quota_requests(), count)
        self.respond("limits", limits(10))
        self.assertEqual(self.quota_requests(), count + 1)
        self.respond("limits", limits(25))
        self.assertEqual(self.quota_requests(), count + 1)
        self.assertEqual(service.snapshot.buckets[0].primary.remaining_percent, 75)

    def test_manual_refresh_waits_for_old_transport_request(self):
        service = self.service
        service.set_codex_active(True)
        service.active_rate_timer.timeout.emit()
        old_id = next(
            rid for rid, c in service.account.requests.items() if c.kind == "limits"
        )
        count = self.quota_requests()
        service.refresh(force=True)
        self.respond(
            "account",
            {"account": {"type": "chatgpt", "email": "fixture@example.invalid"}},
        )
        self.assertEqual(self.quota_requests(), count)
        self.client.respond(old_id, limits(99))
        self.assertEqual(self.quota_requests(), count + 1)
        self.assertNotEqual(service.snapshot.buckets[0].primary.remaining_percent, 1)
        self.respond("limits", limits(30))
        self.respond("usage", {"summary": {"lifetimeTokens": 200}})
        self.assertEqual(service.snapshot.refresh.state, "success")
        self.assertTrue(service.active_rate_timer.isActive())

    def test_failure_releases_transport_and_does_not_retry_forever(self):
        service = self.service
        service.set_codex_active(True)
        service.active_rate_timer.timeout.emit()
        service.active_rate_timer.timeout.emit()
        count = self.quota_requests()
        self.respond("limits", error={"code": "timeout"})
        self.assertEqual(self.quota_requests(), count + 1)
        self.respond("limits", error={"code": "timeout"})
        self.assertEqual(self.quota_requests(), count + 1)
        self.assertFalse(service.account.requests)

    def test_account_boundaries_clear_activity_and_discard_old_commands(self):
        service = self.service
        generation = service.account.generation
        service.set_codex_active(True, generation)
        service.active_rate_timer.timeout.emit()
        self.complete()
        old_id = next(
            rid for rid, c in service.account.requests.items() if c.kind == "limits"
        )
        service._account_checking(True)
        self.assertFalse(service.active_rate_timer.isActive())
        self.assertFalse(service.completion_rate_timer.isActive())
        service.set_codex_active(True, generation)
        service._reset_account()
        self.client.respond(old_id, limits(99))
        self.assertFalse(service.snapshot.buckets)
        self.assertFalse(service.active_rate_timer.isActive())

    def assert_extra_work_cancelled(self, action):
        service = self.service
        service.set_codex_active(True)
        self.complete()
        self.assertTrue(service.active_rate_timer.isActive())
        self.assertTrue(service.completion_rate_timer.isActive())
        action(service)
        self.assertFalse(service.active_rate_timer.isActive())
        self.assertFalse(service.completion_rate_timer.isActive())

    def test_disconnect_cancels_extra_work(self):
        self.assert_extra_work_cancelled(lambda s: s._client_ready_changed(False))

    def test_disable_cancels_extra_work(self):
        self.assert_extra_work_cancelled(lambda s: s.set_enabled(False))

    def test_close_cancels_extra_work(self):
        self.assert_extra_work_cancelled(lambda s: s.close())

    def test_inactive_cancels_pending_active_read_but_keeps_completion_read(self):
        service = self.service
        service.set_codex_active(True)
        service.active_rate_timer.timeout.emit()
        service.active_rate_timer.timeout.emit()
        count = self.quota_requests()
        service.set_codex_active(False)
        self.respond("limits", limits())
        self.assertEqual(self.quota_requests(), count)
        self.complete()
        self.follow_up()
        count = self.quota_requests()
        service.set_codex_active(False)
        self.respond("limits", limits())
        self.assertEqual(self.quota_requests(), count + 1)

    def test_completion_during_manual_refresh_can_be_satisfied_by_a_later_full_read(
        self,
    ):
        service = self.service
        service.refresh(force=True)
        self.complete()
        self.follow_up()
        count = self.quota_requests()
        self.respond(
            "account",
            {"account": {"type": "chatgpt", "email": "fixture@example.invalid"}},
        )
        self.respond("limits", limits(30))
        self.respond("usage", {"summary": {"lifetimeTokens": 200}})
        self.assertEqual(self.quota_requests(), count + 1)
        self.assertEqual(service.snapshot.refresh.state, "success")

    def test_timed_out_manual_response_cannot_update_a_resumed_active_read(self):
        service = self.service
        service.set_codex_active(True)
        service.refresh(force=True)
        self.respond(
            "account",
            {"account": {"type": "chatgpt", "email": "fixture@example.invalid"}},
        )
        old_id = next(
            rid for rid, c in service.account.requests.items() if c.kind == "limits"
        )
        service.cancel_refresh(service.snapshot.refresh.request_id)
        service.active_rate_timer.timeout.emit()
        count = self.quota_requests()
        self.client.respond(old_id, limits(99))
        self.assertEqual(self.quota_requests(), count + 1)
        self.assertNotEqual(service.snapshot.buckets[0].primary.remaining_percent, 1)
        self.respond("limits", limits(30))
        self.assertEqual(service.snapshot.buckets[0].primary.remaining_percent, 70)

    def test_child_completion_does_not_schedule_an_extra_request(self):
        self.complete(scope="internal")
        self.assertFalse(self.service.completion_rate_timer.isActive())


class UsageActivityWiringTests(unittest.TestCase):
    def facade(self):
        facade = UsageWorkerService.__new__(UsageWorkerService)
        QObject.__init__(facade)
        facade._closed = False
        facade.enabled = True
        facade._account_generation = 7
        facade._codex_active = None
        facade._sending_activity = False
        facade.snapshot = UsageSnapshot()
        return facade

    def test_facade_sends_only_changes_with_the_received_account_generation(self):
        facade = self.facade()
        facade._send = Mock(return_value=True)
        facade.set_codex_active(True)
        facade.set_codex_active(True)
        facade.set_codex_active(False)
        self.assertEqual(facade._send.call_count, 2)
        facade._send.assert_called_with("set_codex_active", False, 7)

    def test_full_queue_does_not_reenter_through_the_snapshot_listener(self):
        # A rejected send publishes a storage error; the runtime listener
        # syncs activity again in the same call stack.
        facade = self.facade()
        facade._worker = Mock()
        facade._worker.enqueue.return_value = False
        facade._next_id = 0
        facade.snapshot_changed.connect(lambda _snapshot: facade.set_codex_active(True))
        self.assertFalse(facade.set_codex_active(True))
        self.assertEqual(facade._worker.enqueue.call_count, 1)
        self.assertIsNone(facade._codex_active)
        # Once the queue drains, the next sync sends the pending change.
        facade._worker.enqueue.return_value = True
        self.assertTrue(facade.set_codex_active(True))
        self.assertTrue(facade._codex_active)

    def test_runtime_uses_codex_working_cards_independent_of_widget_visibility(self):
        setter = Mock()
        runtime = SimpleNamespace(
            usage_service=SimpleNamespace(set_codex_active=setter),
            tool_enabled=lambda tool: True,
            projects=SimpleNamespace(
                cards=[
                    SimpleNamespace(source="claude_code", working=1),
                    SimpleNamespace(source="codex", working=0),
                ]
            ),
        )
        ApplicationRuntime._sync_usage_activity(runtime)
        setter.assert_called_with(False)
        runtime.projects.cards.append(SimpleNamespace(source="codex", working=2))
        ApplicationRuntime._sync_usage_activity(runtime)
        setter.assert_called_with(True)


if __name__ == "__main__":
    unittest.main()
