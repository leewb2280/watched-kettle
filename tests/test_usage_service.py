import os
import sqlite3
import unittest
from datetime import date, datetime, timedelta, timezone
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from watched_kettle.app_preferences import ApplicationPreferences
from watched_kettle.storage.usage_repository import VolatileUsageRepository
from watched_kettle.usage.service import CodexUsageService
from watched_kettle.usage.turn_log import TurnUsageEvidence
from watched_kettle.usage.models import TaskUsageRecord
from watched_kettle.usage.identifiers import hash_identifier
from tests.test_pet_preferences import FakeSettings


class FakeClient(QObject):
    ready_changed = Signal(bool)
    response_received = Signal(int, str, object, object, object)
    notification_received = Signal(str, object)
    error_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.ready = False
        self.requests = []
        self.next_id = 1

    def start(self):
        pass

    def close(self):
        self.ready = False

    def request(self, method, params=None, timeout_ms=10000):
        request_id = self.next_id
        self.next_id += 1
        self.requests.append((request_id, method, params))
        return request_id

    def become_ready(self):
        self.ready = True
        self.ready_changed.emit(True)

    def respond(self, request_id, result=None, error=None):
        _, method, params = next(
            item for item in self.requests if item[0] == request_id
        )
        self.response_received.emit(request_id, method, params, result, error)


class UsageServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.preferences = ApplicationPreferences(FakeSettings())
        self.client = FakeClient()
        self.now = datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc)  # 19:00 at UTC+9
        self.local_timezone = timezone(timedelta(hours=9))
        repository = VolatileUsageRepository(now=lambda: self.now)
        self.service = CodexUsageService(
            self.client,
            self.preferences,
            repository,
            now=lambda: self.now,
            local_timezone=self.local_timezone,
        )

    def tearDown(self):
        self.service.turn_recovery.clear()
        self.service.rate_timer.stop()
        self.service.usage_timer.stop()
        self.service.day_timer.stop()
        self.temp.cleanup()

    def test_recovery_status_persists_reason_and_preserves_outcome(self):
        self._ready_and_account()
        service = self.service
        record = TaskUsageRecord(
            self.now,
            service.snapshot.account_hash,
            hash_identifier("thread"),
            "failed",
            turn_hash=hash_identifier("turn"),
            data_quality="unavailable",
            quality_reason="missing_start",
        )
        service.repository.append(record)
        service._recovery_started_for = (
            record.account_hash,
            service.account.generation,
        )
        key = (record.thread_hash, record.turn_hash)
        service._recovery_state(*key, "checking", "")
        service._flush_recovery()
        self.assertIn(key, service.snapshot.recovery_pending)
        service._recovery_state(*key, "unavailable", "counter_regressed")
        service._flush_recovery()
        self.assertNotIn(key, service.snapshot.recovery_pending)
        saved = service.repository.load(record.account_hash)[0]
        self.assertEqual(saved.outcome, "failed")
        self.assertEqual(
            saved.quality_reason, "recovery:counter_regressed|original:missing_start"
        )
        service._recovery_state(*key, "unavailable", "token_baseline_missing")
        service._flush_recovery()
        self.assertEqual(
            service.repository.load(record.account_hash)[0].quality_reason,
            "recovery:token_baseline_missing|original:missing_start",
        )

    def test_account_reset_and_history_clear_cancel_recovery(self):
        self._ready_and_account()
        service = self.service
        key = ("thread", "turn")
        service._recovery_state(*key, "checking", "")
        service._flush_recovery()
        service.turn_recovery.add_targets(("thread",))
        service.clear_history()
        self.assertFalse(service.snapshot.recovery_pending)
        self.assertFalse(service.turn_recovery.targets)
        service._reset_account("signed_out")
        service._recovery_state(*key, "checking", "")
        service._flush_recovery()
        self.assertFalse(service.snapshot.recovery_pending)
        self.assertFalse(service.turn_recovery.timer.isActive())

    def test_manual_refresh_schedules_existing_unavailable_records(self):
        self._ready_and_account()
        service = self.service
        service.refresh(force=True)
        self.assertIsNone(service._recovery_started_for)
        with patch.object(service.recovery_pages, "start") as recover:
            service._handle_limits(
                {"accountId": "acct", "rateLimits": {"primary": {"usedPercent": 10}}}
            )
        recover.assert_called_once()

    def test_account_verification_defers_recovery_updates(self):
        self._ready_and_account()
        self.service._publish(account_checking=True)
        self.service._recovery_state("thread", "turn", "checking", "")
        self.service._flush_recovery()
        self.assertFalse(self.service.snapshot.recovery_pending)

    def test_recovery_batches_pending_without_loading_history_and_noops_replays(self):
        self._ready_and_account()
        service = self.service
        emissions = []
        service.snapshot_changed.connect(emissions.append)
        with patch.object(
            service.repository, "load", wraps=service.repository.load
        ) as load:
            for i in range(100):
                service._recovery_state("thread", str(i), "checking", "")
            self.assertEqual(emissions, [])
            service._flush_recovery()
            self.assertEqual(len(emissions), 1)
            load.assert_not_called()
            for i in range(100):
                service._recovery_state("thread", str(i), "checking", "")
            service._flush_recovery()
            self.assertEqual(len(emissions), 1)
            load.assert_not_called()

    def test_deferred_recovery_flushes_once_and_old_generation_is_cancelled(self):
        self._ready_and_account()
        service = self.service
        service._publish(account_checking=True)
        service._recovery_state("thread", "turn", "checking", "")
        service._flush_recovery()
        self.assertFalse(service.snapshot.recovery_pending)
        self.assertTrue(service._recovery_changes)
        service._publish(account_checking=False)
        service._flush_recovery()
        self.assertIn(("thread", "turn"), service.snapshot.recovery_pending)
        service._recovery_state("thread", "new", "checking", "")
        service._reset_account("signed_out")
        service._flush_recovery()
        self.assertFalse(service._recovery_changes)
        self.assertFalse(service.snapshot.recovery_pending)
        self.assertFalse(service.recovery_timer.isActive())

    def test_storage_failure_retains_recovery_batch_for_retry(self):
        self._ready_and_account()
        service = self.service
        service._recovery_state("thread", "turn", "unavailable", "local_log_missing")
        with patch.object(
            service.repository,
            "apply_recovery_batch",
            side_effect=sqlite3.OperationalError("locked"),
        ):
            service._flush_recovery()
        self.assertTrue(service._recovery_changes)
        self.assertTrue(service.recovery_timer.isActive())
        service._flush_recovery()
        self.assertFalse(service._recovery_changes)
        self.assertFalse(service.recovery_timer.isActive())

    def test_fast_retry_with_same_verdict_does_not_leave_checking_queued(self):
        self._ready_and_account()
        service = self.service
        service._recovery_state("thread", "turn", "unavailable", "local_log_missing")
        service._flush_recovery()
        service._recovery_state("thread", "turn", "checking", "")
        service._recovery_state("thread", "turn", "unavailable", "local_log_missing")
        service._flush_recovery()
        self.assertFalse(service.snapshot.recovery_pending)
        self.assertFalse(service._recovery_changes)

    def _ready_and_account(self, limits=True):
        self.client.become_ready()
        account_id = next(
            item[0] for item in self.client.requests if item[1] == "account/read"
        )
        self.client.respond(
            account_id,
            {
                "account": {
                    "type": "chatgpt",
                    "email": "person@example.com",
                    "planType": "plus",
                },
                "requiresOpenaiAuth": True,
            },
        )

        if limits:
            limits_id = next(
                item[0]
                for item in reversed(self.client.requests)
                if item[1] == "account/rateLimits/read"
            )
            self.client.respond(
                limits_id,
                {"accountId": "acct", "rateLimits": {"primary": {"usedPercent": 10}}},
            )

    def test_api_key_auth_disables_only_usage_feature(self):
        self.client.become_ready()
        request_id = next(
            item[0] for item in self.client.requests if item[1] == "account/read"
        )
        self.client.respond(
            request_id, {"account": {"type": "apiKey"}, "requiresOpenaiAuth": True}
        )
        self.assertEqual(self.service.snapshot.availability.state, "unsupported_auth")

    def test_reset_credit_only_update_is_not_discarded(self):
        self.service._handle_limits(
            {"rateLimitResetCredits": {"availableCount": 0}}, sparse=True
        )

        self.assertEqual(self.service.snapshot.reset_credit_count, 0)

    def test_thresholds_are_silent_initially_and_deduplicated_per_reset(self):
        notices = []
        self.service.assistant_notice_ready.connect(notices.append)
        self._ready_and_account(limits=False)
        limits_id = next(
            item[0]
            for item in reversed(self.client.requests)
            if item[1] == "account/rateLimits/read"
        )
        self.client.respond(
            limits_id,
            {
                "accountId": "acct",
                "rateLimitsByLimitId": {
                    "five": {"primary": {"usedPercent": 75, "resetsAt": 1800000000}}
                },
            },
        )
        self.assertEqual(notices, [])
        self.client.notification_received.emit(
            "account/rateLimits/updated",
            {
                "rateLimitsByLimitId": {
                    "five": {"primary": {"usedPercent": 91, "resetsAt": 1800000000}}
                }
            },
        )
        self.assertEqual(len(notices), 1)
        self.assertIn("잔여 9%", notices[0]["message"])
        self.client.notification_received.emit(
            "account/rateLimits/updated",
            {
                "rateLimitsByLimitId": {
                    "five": {"primary": {"usedPercent": 95, "resetsAt": 1800000000}}
                }
            },
        )
        self.assertEqual(len(notices), 1)
        self.client.notification_received.emit(
            "account/rateLimits/updated",
            {
                "rateLimitsByLimitId": {
                    "five": {"primary": {"usedPercent": 100, "resetsAt": 1800000000}}
                }
            },
        )
        self.assertEqual(len(notices), 2)
        self.assertIn("잔여 0%", notices[-1]["message"])
        self.client.notification_received.emit(
            "account/rateLimits/updated",
            {
                "rateLimitsByLimitId": {
                    "five": {"primary": {"usedPercent": 5, "resetsAt": 1900000000}}
                }
            },
        )
        self.client.notification_received.emit(
            "account/rateLimits/updated",
            {
                "rateLimitsByLimitId": {
                    "five": {"primary": {"usedPercent": 71, "resetsAt": 1900000000}}
                }
            },
        )
        self.assertEqual(len(notices), 3)
        self.assertIn("잔여 29%", notices[-1]["message"])

    def test_prompt_and_done_are_enriched_from_matching_local_turn(self):
        self._ready_and_account()
        self.service.observe_agent_payload(
            {
                "source": "codex",
                "event": "prompt",
                "session_id": "thread-secret",
                "turn_id": "turn-1",
                "agent_scope": "main",
            }
        )
        self.service.observe_agent_payload(
            {
                "source": "codex",
                "event": "done",
                "session_id": "thread-secret",
                "turn_id": "turn-1",
                "agent_scope": "main",
            }
        )
        self.assertFalse(
            any(
                method == "account/usage/read" and params != {}
                for _, method, params in self.client.requests
            )
        )
        self.service.observe_local_turn_evidence(
            TurnUsageEvidence(
                "thread-secret",
                "turn-1",
                self.now,
                45,
                30,
                5,
                15,
                "gpt-6-sol",
                "medium",
                False,
            )
        )
        self.service._flush_recovery()
        records = self.service.repository.load(self.service.snapshot.account_hash)
        self.assertEqual(records[0].total_tokens, 45)
        self.assertEqual(records[0].input_tokens, 30)
        self.assertEqual(records[0].net_new_input_tokens, 25)
        self.assertIsNone(records[0].estimated_credits_micros)
        self.assertNotEqual(records[0].thread_hash, "thread-secret")

    def test_missing_baseline_is_measurement_unavailable(self):
        self._ready_and_account()
        self.service.observe_agent_payload(
            {
                "source": "codex",
                "event": "done",
                "session_id": "thread",
                "agent_scope": "main",
            }
        )
        self.service._flush_recovery()
        records = self.service.repository.load(self.service.snapshot.account_hash)
        self.assertEqual(records[0].data_quality, "unavailable")
        self.assertIsNone(records[0].total_tokens)

    def test_daily_summary_waits_for_refreshed_activity_and_runs_once(self):
        notices = []
        self.service.assistant_notice_ready.connect(notices.append)
        self._ready_and_account()
        self.service.observe_agent_payload(
            {
                "source": "codex",
                "event": "done",
                "session_id": "thread",
                "agent_scope": "main",
            }
        )
        usage_requests = [
            item
            for item in self.client.requests
            if item[1] == "account/usage/read" and item[2] == {}
        ]
        latest = usage_requests[-1]
        self.client.respond(
            latest[0],
            {
                "summary": {},
                "dailyUsageBuckets": [{"startDate": "2026-09-04", "tokens": 500}],
            },
        )
        self.assertEqual(len(notices), 1)
        self.assertIn("500", notices[0]["message"])
        self.service.observe_agent_payload(
            {
                "source": "codex",
                "event": "done",
                "session_id": "thread2",
                "agent_scope": "main",
            }
        )
        latest = [
            item
            for item in self.client.requests
            if item[1] == "account/usage/read" and item[2] == {}
        ][-1]
        self.client.respond(
            latest[0],
            {
                "summary": {},
                "dailyUsageBuckets": [{"startDate": "2026-09-04", "tokens": 600}],
            },
        )
        self.assertEqual(len(notices), 1)

    def test_daily_summary_uses_configured_local_evening_boundary(self):
        notices = []
        self.service.assistant_notice_ready.connect(notices.append)
        self._ready_and_account()
        self.now = datetime(2026, 9, 4, 8, 59, tzinfo=timezone.utc)
        self.service.observe_agent_payload(
            {
                "source": "codex",
                "event": "done",
                "session_id": "before-evening",
                "agent_scope": "main",
            }
        )
        latest = [
            item
            for item in self.client.requests
            if item[1] == "account/usage/read" and item[2] == {}
        ][-1]
        self.client.respond(
            latest[0],
            {
                "summary": {},
                "dailyUsageBuckets": [{"startDate": "2026-09-04", "tokens": 400}],
            },
        )
        self.assertEqual(notices, [])

        self.now = datetime(2026, 9, 4, 9, 0, tzinfo=timezone.utc)
        self.service.observe_agent_payload(
            {
                "source": "codex",
                "event": "done",
                "session_id": "evening",
                "agent_scope": "main",
            }
        )
        latest = [
            item
            for item in self.client.requests
            if item[1] == "account/usage/read" and item[2] == {}
        ][-1]
        self.client.respond(
            latest[0],
            {
                "summary": {},
                "dailyUsageBuckets": [{"startDate": "2026-09-04", "tokens": 500}],
            },
        )
        self.assertEqual(len(notices), 1)
        self.assertIn("500", notices[0]["message"])

    def test_account_lifetime_total_does_not_drive_hourly_activity(self):
        self._ready_and_account()
        initial = next(
            item
            for item in self.client.requests
            if item[1] == "account/usage/read" and item[2] == {}
        )
        self.client.respond(
            initial[0],
            {
                "summary": {"lifetimeTokens": 100},
                "dailyUsageBuckets": [{"startDate": "2026-09-04", "tokens": 160}],
            },
        )
        self.now = datetime(2026, 9, 4, 10, 10, tzinfo=timezone.utc)
        self.service._refresh_account_usage()
        latest = self.client.requests[-1]
        self.client.respond(
            latest[0],
            {
                "summary": {"lifetimeTokens": 160},
                "dailyUsageBuckets": [{"startDate": "2026-09-04", "tokens": 160}],
            },
        )

        self.assertTrue(
            all(
                bucket.tokens is None
                for bucket in self.service.snapshot.hourly_activity
            )
        )
        self.assertIsNone(self.service.snapshot.observed_today_tokens)
        self.assertIsNone(self.service.snapshot.last_sample_at)

    def test_local_log_batch_updates_tokens_and_selected_quota_independently(self):
        self._ready_and_account(limits=False)
        reset_at = datetime(2026, 9, 10, tzinfo=timezone.utc).isoformat()
        self.service._handle_limits(
            {
                "accountId": "acct",
                "rateLimitsByLimitId": {
                    "codex": {
                        "primary": {
                            "usedPercent": 42,
                            "windowDurationMins": 10080,
                            "resetsAt": 1788998400,
                        }
                    }
                },
            }
        )
        records = []
        for index, used in enumerate((42, 43, 42, 43, 51)):
            records.extend(
                (
                    {
                        "kind": "token",
                        "event_key": f"token-{index}",
                        "session_id": "secret-session",
                        "occurred_at": (
                            self.now + timedelta(minutes=index)
                        ).isoformat(),
                        "delta_tokens": 10,
                    },
                    {
                        "kind": "quota",
                        "event_key": f"quota-{index}",
                        "limit_id": "codex",
                        "slot": "primary",
                        "occurred_at": (
                            self.now + timedelta(minutes=index)
                        ).isoformat(),
                        "used_percent": used,
                        "window_duration_mins": 10080,
                        "resets_at": reset_at,
                    },
                )
            )
        self.service.observe_local_usage_batch(records)

        self.assertEqual(self.service.snapshot.observed_today_tokens, 50)
        self.assertEqual(self.service.snapshot.hourly_activity[19].tokens, 50)
        self.assertIsNone(self.service.snapshot.observed_today_percent_points)
        self.assertEqual(self.service.snapshot.selected_quota_observation_count, 1)
        self.assertEqual(len(self.service.repository.device.quotas()), 5)
        self.assertEqual(
            self.service.snapshot.quota_hourly_activity[19].percent_points, None
        )

    def test_today_values_move_to_the_new_day_without_new_samples(self):
        # 19:00 at UTC+9: 30 tokens observed today, then Codex stays idle.
        self.service.observe_local_usage_batch(
            [
                {
                    "kind": "token",
                    "event_key": f"token-{index}",
                    "session_id": "secret-session",
                    "occurred_at": (self.now + timedelta(minutes=index)).isoformat(),
                    "delta_tokens": 10,
                }
                for index in range(3)
            ]
        )
        self.assertEqual(self.service.snapshot.observed_today_tokens, 30)
        self.now += timedelta(hours=4)  # 23:00, same day: nothing to redo
        self.service._check_day()
        self.assertEqual(self.service.snapshot.observed_today_tokens, 30)

        self.now += timedelta(hours=1, minutes=1)  # 00:01 the next day
        self.service._check_day()
        snapshot = self.service.snapshot
        self.assertIsNone(snapshot.observed_today_tokens)
        self.assertEqual(snapshot.hourly_activity[19].tokens, None)
        self.assertEqual(snapshot.trend_hours["date"], date(2026, 9, 5))
        # Yesterday's hours now feed the usual-day average instead.
        self.assertIsNone(snapshot.trend_hours["average"])

    def test_periodic_account_usage_requests_are_deduplicated(self):
        self._ready_and_account()
        before = len(
            [
                item
                for item in self.client.requests
                if item[1] == "account/usage/read" and item[2] == {}
            ]
        )

        self.service._refresh_account_usage()
        self.service._refresh_account_usage()

        after = len(
            [
                item
                for item in self.client.requests
                if item[1] == "account/usage/read" and item[2] == {}
            ]
        )
        self.assertEqual(before, after)
        in_flight = next(
            item
            for item in reversed(self.client.requests)
            if item[1] == "account/usage/read" and item[2] == {}
        )
        self.client.respond(
            in_flight[0],
            {"summary": {"lifetimeTokens": 100}, "dailyUsageBuckets": []},
        )
        after_completion = [
            item
            for item in self.client.requests
            if item[1] == "account/usage/read" and item[2] == {}
        ]
        self.assertEqual(len(after_completion), after + 1)
        self.assertEqual(self.service.usage_timer.interval(), 10 * 60 * 1000)


if __name__ == "__main__":
    unittest.main()
