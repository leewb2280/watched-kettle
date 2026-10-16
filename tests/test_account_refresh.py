"""Account-switch and user-refresh regression tests without real credentials."""

import json
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from watched_kettle.integrations.account_monitor import AccountMonitor
from watched_kettle.application.logging import close_logging, configure_logging
from watched_kettle.usage.identifiers import hash_identifier
from watched_kettle.usage.models import UsageRefreshState, UsageSnapshot
from watched_kettle.usage.service import CodexUsageService
from watched_kettle.usage.worker import UsageWorkerService, UsageWorkerResult
from watched_kettle.application.paths import AppPaths
from tests.test_usage_service import FakeClient
from tests import test_usage_service as usage_fixture


class ReadyClient(FakeClient):
    def __init__(self, parent=None):
        super().__init__()
        self.setParent(parent)
        self.starts = 0
        self.closes = 0

    def start(self):
        self.starts += 1
        self.become_ready()

    def close(self):
        self.closes += 1
        was_ready = self.ready
        self.ready = False
        if was_ready:
            self.ready_changed.emit(False)


class AccountRefreshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.fixture = usage_fixture.UsageServiceTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.probes = []

        def factory(parent=None):
            client = ReadyClient(parent)
            self.probes.append(client)
            return client

        self.monitor = AccountMonitor(
            factory, auth_path=Path(self.temp.name) / "auth.json"
        )
        self.client = ReadyClient()
        self.service = CodexUsageService(
            self.client,
            self.fixture.preferences,
            self.fixture.service.repository,
            now=lambda: self.fixture.now,
            account_monitor=self.monitor,
        )
        self.addCleanup(self.service.close)
        self.boundaries = []
        self.service.account_changed.connect(self.boundaries.append)
        self.service.start()

    def respond(self, client, method, result=None, error=None):
        rid = next(r[0] for r in reversed(client.requests) if r[1] == method)
        client.respond(rid, result, error)
        return rid

    def probe(self, account_id="a", email="alice@example.invalid", plan="plus"):
        probe = self.probes[-1]
        account = (
            None
            if account_id is None
            else {"type": "chatgpt", "email": email, "planType": plan}
        )
        self.respond(probe, "account/read", {"account": account})
        if account is not None:
            self.respond(probe, "account/rateLimits/read", {"accountId": account_id})
        return probe

    def usage(
        self, account_id="a", email="alice@example.invalid", used=10, detail=True
    ):
        self.respond(
            self.client,
            "account/read",
            {"account": {"type": "chatgpt", "email": email, "planType": "plus"}},
        )
        self.respond(
            self.client,
            "account/rateLimits/read",
            {"accountId": account_id, "rateLimits": {"primary": {"usedPercent": used}}},
        )
        if detail:
            self.respond(
                self.client, "account/usage/read", {"summary": {"lifetimeTokens": 100}}
            )

    def ready(self):
        self.probe()
        self.usage()

    def test_external_switch_without_notification_restarts_and_rejects_old_response(
        self,
    ):
        self.ready()
        self.service._refresh_account_usage()
        old = self.client.requests[-1][0]
        self.monitor.periodic.timeout.emit()
        self.probe("b", "bob@example.invalid")
        self.assertEqual(self.boundaries, [False, True])
        self.assertEqual(self.service.snapshot.buckets, ())
        self.client.respond(old, {"summary": {"lifetimeTokens": 999}})
        self.assertIsNone(self.service.snapshot.summary.lifetime_tokens)
        self.usage("b", "bob@example.invalid", 42)
        self.assertEqual(self.service.snapshot.account_hash, hash_identifier("b"))
        self.assertEqual(self.service.snapshot.account_email, "b***@example.invalid")
        self.assertEqual(self.service.snapshot.account_plan, "plus")
        self.assertEqual(self.client.starts, 2)

    def test_signed_out_periodic_check_recovers_without_login_notification(self):
        self.ready()
        self.monitor.check()
        self.probe(None)
        self.assertEqual(self.service.snapshot.availability.state, "signed_out")
        self.assertEqual(self.service.snapshot.buckets, ())
        self.monitor.periodic.timeout.emit()
        self.probe("b", "bob@example.invalid")
        self.usage("b", "bob@example.invalid")
        self.assertEqual(self.service.snapshot.availability.state, "available")

    def test_same_email_different_account_id_is_a_transition(self):
        self.ready()
        self.monitor.check()
        self.probe("b")
        self.assertEqual(self.boundaries, [False, True])

    def test_file_rotation_masks_then_reconnects_without_account_transition(self):
        self.ready()
        self.monitor.auth_path.write_text("synthetic fixture", encoding="utf-8")
        self.monitor.poll_file()
        self.assertTrue(self.service.snapshot.account_checking)
        self.assertFalse(self.service.snapshot.for_display().buckets)
        self.assertFalse(self.service.clear_history())
        self.monitor.debounce.timeout.emit()
        self.probe()
        self.assertEqual(self.boundaries, [False, False])
        self.assertFalse(self.service.snapshot.account_checking)

    def test_update_before_account_response_keeps_connection_and_usage(self):
        self.probe()
        count = len(self.probes)
        for _ in range(5):
            self.client.notification_received.emit("account/updated", {})
        self.assertEqual(len(self.probes), count)
        self.assertFalse(self.service.snapshot.account_checking)
        self.usage()
        self.assertEqual(self.client.starts, 1)
        self.assertEqual(self.service.snapshot.availability.state, "available")
        self.assertTrue(self.service.snapshot.for_display().buckets)

    def test_same_account_notification_coalesces_and_resumes_limits(self):
        self.ready()
        before = len(self.probes)
        boundaries = list(self.boundaries)
        self.service._notification_received("account/updated", {})
        current = self.probes[-1]
        deadline = self.monitor.deadline.remainingTime()
        operation = self.monitor.operation_id
        for _ in range(10):
            self.service._notification_received("account/updated", {})
        self.assertEqual(len(self.probes), before + 1)
        self.assertIs(self.monitor.client, current)
        self.assertEqual(self.monitor.operation_id, operation)
        self.assertLessEqual(self.monitor.deadline.remainingTime(), deadline)
        account_reads = sum(r[1] == "account/read" for r in self.client.requests)
        self.probe()
        self.assertFalse(self.service.snapshot.account_checking)
        self.assertEqual(self.client.starts, 1)
        self.assertEqual(self.boundaries, boundaries)
        self.assertEqual(
            sum(r[1] == "account/read" for r in self.client.requests), account_reads
        )
        self.assertEqual(self.client.requests[-1][1], "account/rateLimits/read")
        self.respond(
            self.client,
            "account/rateLimits/read",
            {"accountId": "a", "rateLimits": {"primary": {"usedPercent": 23}}},
        )
        self.assertTrue(self.service.snapshot.for_display().buckets)

    def test_notification_does_not_replace_manual_probe(self):
        self.ready()
        self.service.refresh(force=True, refresh_id=17)
        current = self.monitor.client
        operation = self.monitor.operation_id
        self.service._notification_received("account/updated", {})
        self.assertIs(self.monitor.client, current)
        self.assertEqual(self.monitor.refresh_id, 17)
        self.assertEqual(self.monitor.operation_id, operation)
        self.probe()
        self.usage()
        self.assertEqual(self.service.snapshot.refresh.state, "success")

    def test_login_completed_supersedes_notification_probe(self):
        self.ready()
        self.client.notification_received.emit("account/updated", {})
        old_probe = self.probes[-1]
        old_operation = self.monitor.operation_id
        self.client.notification_received.emit("account/login/completed", {})
        self.assertIsNot(self.monitor.client, old_probe)
        self.assertNotEqual(self.monitor.operation_id, old_operation)
        self.assertEqual(self.monitor.reason, "login_completed")
        self.assertTrue(self.service.snapshot.account_checking)
        self.probe("b")
        self.usage("b")
        self.assertEqual(self.client.starts, 2)
        self.assertEqual(self.service.snapshot.account_hash, hash_identifier("b"))

    def test_file_rotation_supersedes_probe_and_coalesces_ordinary_updates(self):
        self.ready()
        self.client.notification_received.emit("account/updated", {})
        old_probe = self.probes[-1]
        self.monitor.auth_path.write_text("rotated", encoding="utf-8")
        self.monitor.poll_file()
        self.assertIsNone(self.monitor.client)
        for _ in range(5):
            self.client.notification_received.emit("account/updated", {})
        self.assertTrue(self.monitor.debounce.isActive())
        self.monitor.debounce.timeout.emit()
        self.assertIsNot(self.monitor.client, old_probe)
        self.assertEqual(self.monitor.reason, "auth_file_changed")
        self.probe()
        self.assertEqual(self.client.starts, 2)
        self.usage()
        self.assertFalse(self.service.snapshot.account_checking)

    def test_auth_generation_is_not_applied_before_initialize_succeeds(self):
        self.ready()
        applied = self.service._applied_auth_generation
        self.monitor.auth_path.write_text("rotated", encoding="utf-8")
        self.monitor.poll_file()
        self.monitor.debounce.timeout.emit()
        with patch.object(self.client, "start"):
            self.probe()
        self.assertEqual(self.service._applied_auth_generation, applied)
        self.client.error_changed.emit("synthetic connection failure")
        self.monitor.check()
        self.probe()
        self.assertEqual(
            self.service._applied_auth_generation, self.monitor.auth_generation
        )
        self.usage()
        self.assertEqual(self.service.snapshot.availability.state, "available")

    def test_file_change_failure_retains_generation_until_reconnected(self):
        self.ready()
        applied = self.service._applied_auth_generation
        self.monitor.auth_path.write_text("rotated", encoding="utf-8")
        self.monitor.poll_file()
        self.monitor.debounce.timeout.emit()
        self.respond(self.probes[-1], "account/read", error={"code": "timeout"})
        self.assertGreater(self.monitor.auth_generation, applied)
        self.assertEqual(self.service._applied_auth_generation, applied)
        self.monitor.check()
        self.probe()
        self.assertEqual(self.client.starts, 2)
        self.assertEqual(
            self.service._applied_auth_generation, self.monitor.auth_generation
        )
        self.usage()
        self.service._notification_received("account/updated", {})
        self.probe()
        self.assertEqual(self.client.starts, 2)

    def test_notification_detects_real_account_change_and_rejects_old_reply(self):
        self.ready()
        self.service._refresh_account_usage()
        old = self.client.requests[-1][0]
        self.service._notification_received("account/updated", {})
        self.probe("b")
        self.assertEqual(self.client.starts, 2)
        self.assertEqual(self.boundaries[-1], True)
        self.client.respond(old, {"summary": {"lifetimeTokens": 999}})
        self.assertIsNone(self.service.snapshot.summary.lifetime_tokens)
        self.usage("b", used=25)
        self.assertEqual(self.service.snapshot.availability.state, "available")

    def test_missing_account_id_does_not_repeat_reconnection(self):
        self.probe("")
        self.usage("")
        self.monitor.check()
        self.probe("")
        self.assertEqual(self.client.starts, 1)
        self.assertFalse(self.service.snapshot.account_hash)
        self.assertTrue(self.service.snapshot.for_display().buckets)

    def test_file_rotation_account_probe_failure_unmasks_cached_usage(self):
        self.ready()
        cached_buckets = self.service.snapshot.buckets
        self.monitor.auth_path.write_text("synthetic fixture", encoding="utf-8")
        self.monitor.poll_file()
        self.assertTrue(self.service.snapshot.account_checking)

        self.monitor.debounce.timeout.emit()
        self.assertTrue(self.service.refresh(force=True))
        self.respond(self.probes[-1], "account/read", error={"code": "timeout"})

        self.assertFalse(self.service.snapshot.account_checking)
        self.assertEqual(self.service.snapshot.availability.state, "offline")
        self.assertEqual(self.service.snapshot.refresh.state, "error")
        self.assertEqual(self.service.snapshot.buckets, cached_buckets)
        self.assertEqual(self.service.snapshot.for_display().buckets, cached_buckets)

    def test_file_rotation_rate_limit_failure_unmasks_and_recovers(self):
        self.ready()
        cached_buckets = self.service.snapshot.buckets
        self.monitor.auth_path.write_text("synthetic fixture", encoding="utf-8")
        self.monitor.poll_file()
        self.assertTrue(self.service.snapshot.account_checking)

        self.monitor.debounce.timeout.emit()
        self.respond(
            self.probes[-1],
            "account/read",
            {"account": {"type": "chatgpt", "email": "alice@example.invalid"}},
        )
        self.respond(
            self.probes[-1],
            "account/rateLimits/read",
            error={"code": "timeout"},
        )

        self.assertFalse(self.service.snapshot.account_checking)
        self.assertEqual(self.service.snapshot.availability.state, "offline")
        self.assertEqual(self.service.snapshot.buckets, cached_buckets)
        self.assertEqual(self.service.snapshot.for_display().buckets, cached_buckets)

        self.monitor.periodic.timeout.emit()
        self.probe()
        self.usage()
        self.assertFalse(self.service.snapshot.account_checking)
        self.assertEqual(self.service.snapshot.availability.state, "available")

    def test_account_probe_failure_logs_operation_and_recovery_state(self):
        log_path = configure_logging(Path(self.temp.name) / "logs")
        try:
            self.ready()
            self.service.refresh(force=True)
            self.respond(self.probes[-1], "account/read", error={"code": "timeout"})
            rows = [
                json.loads(line)
                for line in log_path.read_text(encoding="utf-8").splitlines()
            ]
            failed = next(row for row in rows if row["event"] == "probe_request_failed")
            self.assertEqual(failed["operation"], "account/read")
            self.assertEqual(failed["error_code"], "timeout")
            finished = next(
                row
                for row in rows
                if row["event"] == "probe_finished"
                and row.get("error_code") == "request_failed"
            )
            self.assertTrue(failed["operation_id"])
            self.assertEqual(failed["operation_id"], finished["operation_id"])
            self.assertTrue(
                any(row["event"] == "account_check_finished" for row in rows)
            )
            self.assertTrue(
                any(
                    row["event"] == "refresh_finished" and row["state"] == "error"
                    for row in rows
                )
            )
        finally:
            close_logging()

    def test_manual_refresh_does_not_complete_with_old_automatic_response(self):
        self.ready()
        self.service._refresh_account_usage()
        old = self.client.requests[-1][0]
        self.assertTrue(self.service.refresh(force=True, refresh_id=17))
        count = len(self.probes)
        self.assertTrue(self.service.refresh(force=True))
        self.assertEqual(len(self.probes), count)
        self.client.respond(old, {"summary": {"lifetimeTokens": 999}})
        self.assertTrue(self.service.snapshot.refresh.busy)
        self.assertEqual(self.service.snapshot.summary.lifetime_tokens, 100)
        self.probe()
        self.usage()
        refresh = self.service.snapshot.refresh
        self.assertEqual((refresh.request_id, refresh.state), (17, "success"))
        self.assertEqual(refresh.completed_at, self.fixture.now)
        self.assertEqual(self.client.starts, 1)

    def test_partial_failure_timeout_and_disabled_refresh_are_terminal(self):
        self.ready()
        self.service.refresh(force=True)
        self.probe()
        self.usage(detail=False)
        self.respond(self.client, "account/usage/read", error={"code": "timeout"})
        self.assertEqual(self.service.snapshot.refresh.state, "partial")
        self.service.refresh(force=True)
        self.service.refresh_timer.timeout.emit()
        self.assertEqual(self.service.snapshot.refresh.state, "error")
        self.assertIsNone(self.monitor.client)
        self.service.refresh(force=True)
        self.service.set_enabled(False)
        self.assertEqual(self.service.snapshot.refresh.state, "cancelled")
        self.assertFalse(self.service.refresh(force=True))
        # Codex switched off: no auth.json polling and no account probe.
        self.assertFalse(self.monitor.periodic.isActive())
        self.assertFalse(self.monitor.file_timer.isActive())
        self.assertIsNone(self.monitor.client)

    def test_same_account_recovers_from_offline_with_fresh_connection(self):
        self.ready()
        self.service.refresh(force=True)
        self.respond(self.probes[-1], "account/read", error={"code": "timeout"})
        self.service.refresh(force=True)
        self.probe()
        self.usage()
        self.assertEqual(self.client.starts, 2)
        self.assertEqual(self.boundaries, [False, False])
        self.assertEqual(self.service.snapshot.refresh.state, "success")

    def test_malformed_account_does_not_claim_logout(self):
        self.ready()
        self.service.refresh(force=True)
        self.probe()
        self.respond(self.client, "account/read", {"account": {}})
        self.assertEqual(self.service.snapshot.availability.state, "offline")
        self.assertTrue(self.service.snapshot.buckets)
        self.assertEqual(self.service.snapshot.refresh.state, "error")

    def test_request_after_timeout_cannot_update_or_save(self):
        self.ready()
        self.service.refresh(force=True)
        self.probe()
        self.usage(detail=False)
        old = self.client.requests[-1][0]
        self.service.refresh_timer.timeout.emit()
        snapshot = self.service.snapshot
        self.client.respond(old, {"summary": {"lifetimeTokens": 999}})
        self.assertEqual(self.service.snapshot, snapshot)

    def test_probe_failure_retains_cache_without_claiming_signed_out(self):
        self.ready()
        self.service.refresh(force=True)
        self.respond(self.probes[-1], "account/read", error={"code": "timeout"})
        self.assertEqual(self.service.snapshot.refresh.state, "error")
        self.assertEqual(self.service.snapshot.availability.state, "offline")
        self.assertTrue(self.service.snapshot.buckets)

    def test_empty_and_rejected_responses_finish(self):
        self.ready()
        self.service.refresh(force=True)
        self.probe()
        self.respond(
            self.client,
            "account/read",
            {"account": {"type": "chatgpt", "email": "alice@example.invalid"}},
        )
        self.respond(self.client, "account/rateLimits/read", {})
        self.assertEqual(self.service.snapshot.refresh.state, "error")
        self.service.refresh(force=True)
        self.client.request = lambda *args, **kwargs: None
        self.probe()
        self.assertEqual(self.service.snapshot.refresh.state, "error")

    def test_monitor_disposes_each_probe_and_stops_all_timers(self):
        self.ready()
        for _ in range(8):
            self.monitor.check()
            self.probe()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertFalse(self.monitor.findChildren(ReadyClient))
        self.assertIsNone(self.monitor.client)
        self.monitor.close()
        self.assertFalse(
            any(
                t.isActive()
                for t in (
                    self.monitor.periodic,
                    self.monitor.file_timer,
                    self.monitor.deadline,
                    self.monitor.debounce,
                )
            )
        )

    def test_missing_identity_never_uses_masked_email_as_storage_key(self):
        self.probe("", email=None)
        self.usage("", email=None)
        self.assertEqual(self.service.snapshot.account_hash, "")
        self.assertEqual(self.service.snapshot.account_email, "이메일 정보 없음")
        self.assertFalse(self.service.clear_history())
        self.monitor.check()
        self.probe("", email=None)
        # Missing identity still blocks storage, but is not a reconnect cause.
        self.assertEqual(self.client.starts, 1)
        self.assertFalse(self.service.clear_history())

    def test_display_masks_only_account_data(self):
        snapshot = replace(
            self.service.snapshot,
            observed_today_tokens=42,
            account_checking=True,
            refresh=UsageRefreshState(1, "refreshing"),
        )
        displayed = snapshot.for_display()
        self.assertEqual(displayed.observed_today_tokens, 42)
        self.assertTrue(displayed.refresh.busy)
        self.assertEqual(displayed.account_hash, "")
        self.assertEqual(UsageSnapshot().refresh.state, "idle")

    def test_history_and_device_totals_survive_account_switch(self):
        self.ready()
        repository = self.service.repository
        from watched_kettle.usage.models import TaskUsageRecord

        record = TaskUsageRecord(
            self.fixture.now,
            hash_identifier("a"),
            "thread",
            "completed",
            total_tokens=73,
        )
        repository.append(record)
        self.service.observe_local_usage_batch(
            (
                {
                    "kind": "token",
                    "event_key": "sample",
                    "session_id": "thread",
                    "occurred_at": self.fixture.now.isoformat(),
                    "delta_tokens": 42,
                },
            )
        )
        original_tokens = self.service.snapshot.observed_today_tokens
        self.monitor.check()
        self.probe("b", "bob@example.invalid")
        self.usage("b", "bob@example.invalid")
        self.assertEqual(repository.load(hash_identifier("a")), (record,))
        self.assertFalse(self.service.snapshot.recent_tasks)
        self.assertEqual(self.service.snapshot.observed_today_tokens, original_tokens)

    def test_late_notification_during_suspension_cannot_write_old_samples(self):
        self.ready()
        original = self.service.repository.load_quota_samples(hash_identifier("a"))
        self.service._account_checking(True)
        self.client.notification_received.emit(
            "account/rateLimits/updated",
            {"rateLimits": {"primary": {"usedPercent": 99}}},
        )
        self.assertEqual(
            self.service.repository.load_quota_samples(hash_identifier("a")), original
        )

    def test_quota_history_round_trip_and_late_response_are_account_scoped(self):
        self.ready()
        reset = int((self.fixture.now + timedelta(days=7)).timestamp())

        def observe(account, used):
            self.fixture.now += timedelta(minutes=5)
            self.client.notification_received.emit(
                "account/rateLimits/updated",
                {
                    "accountId": account,
                    "rateLimits": {
                        "primary": {
                            "usedPercent": used,
                            "windowDurationMins": 10080,
                            "resetsAt": reset,
                        }
                    },
                },
            )

        observe("a", 24)
        self.assertIsNone(self.service.snapshot.observed_today_percent_points)
        observe("a", 25)
        self.assertEqual(self.service.snapshot.observed_today_percent_points, 1)
        # The overview line uses the same samples: 1 %p spent, 75 % left.
        week = self.service.snapshot.trend_quota["seven_day"]
        self.assertEqual((week["spent"], week["now_remaining"]), (1.0, 75.0))
        original = self.service.repository.load_quota_samples(hash_identifier("a"))
        self.service._refresh_rate_limits()
        old_request = self.client.requests[-1][0]
        self.service._account_checking(True)
        masked = self.service.snapshot.for_display()
        self.assertIsNone(masked.observed_today_percent_points)
        self.assertIsNone(masked.quota_last_sample_at)
        self.assertIsNone(masked.trend_quota)
        self.monitor.check()
        self.probe("b", "bob@example.invalid")
        self.usage("b", "bob@example.invalid", 40)
        self.client.respond(
            old_request,
            {
                "accountId": "a",
                "rateLimits": {"primary": {"usedPercent": 99}},
            },
        )
        self.assertEqual(self.service.snapshot.account_hash, hash_identifier("b"))
        self.assertEqual(
            self.service.repository.load_quota_samples(hash_identifier("a")), original
        )
        observe("b", 40)
        self.assertIsNone(self.service.snapshot.observed_today_percent_points)
        observe("b", 42)
        self.assertEqual(self.service.snapshot.observed_today_percent_points, 2)
        self.monitor.check()
        self.probe("a")
        self.usage("a", used=25)
        self.assertEqual(self.service.snapshot.observed_today_percent_points, 1)
        observe("a", 26)
        self.assertEqual(self.service.snapshot.observed_today_percent_points, 2)
        self.monitor.check()
        self.probe(None)
        self.assertIsNone(self.service.snapshot.observed_today_percent_points)
        self.assertIsNone(self.service.snapshot.quota_last_sample_at)

    def test_selected_quota_timestamp_and_missing_limit_fallback(self):
        from watched_kettle.usage.models import QuotaUsageSample

        self.ready()
        now = self.fixture.now
        account = hash_identifier("a")
        self.service.repository.append_server_quota_samples(
            account,
            (
                QuotaUsageSample(
                    account,
                    "other",
                    "other",
                    "primary",
                    now + timedelta(minutes=1),
                    10,
                    300,
                    now + timedelta(hours=5),
                ),
            ),
        )
        self.service.set_selected_limit_key("default|primary")
        self.assertEqual(self.service.snapshot.quota_last_sample_at, now)
        self.service.set_selected_limit_key("missing|secondary")
        self.assertEqual(self.service.snapshot.selected_quota_key, "default|primary")
        self.assertEqual(self.service.snapshot.quota_last_sample_at, now)

    def test_change_mid_probe_discards_result_and_rechecks(self):
        first = self.probes[-1]
        self.monitor.auth_path.write_text("fixture-change", encoding="utf-8")
        self.probe()
        self.assertFalse(self.boundaries)
        self.assertIsNone(self.monitor.client)
        self.monitor.debounce.timeout.emit()
        self.assertIsNot(first, self.probes[-1])
        self.probe("b", "bob@example.invalid")
        self.assertEqual(
            self.service._verified_account.account_hash, hash_identifier("b")
        )

    def test_gui_acceptance_is_immediate_and_timeout_fences_queued_results(self):
        facade = UsageWorkerService(
            AppPaths(Path(self.temp.name) / "gui"),
            self.fixture.preferences,
            client_factory=ReadyClient,
        )
        self.addCleanup(facade.close)
        loop = QEventLoop()
        poll = QTimer()
        timeout = QTimer()
        timeout.setSingleShot(True)
        poll.timeout.connect(
            lambda: loop.quit() if facade.availability.available else None
        )
        timeout.timeout.connect(loop.quit)
        poll.start(10)
        # The loop exits as soon as the worker is ready; the cap only bounds a
        # slow CI start under coverage, where 3 s was not always enough.
        timeout.start(15000)
        loop.exec()
        poll.stop()
        timeout.stop()
        self.assertTrue(facade.availability.available)
        with patch.object(facade._worker, "enqueue", return_value=True) as enqueue:
            self.assertTrue(facade.refresh(force=True))
            pending = facade.snapshot
            self.assertTrue(pending.refresh.busy)
            self.assertTrue(facade.refresh(force=True))
            self.assertEqual(enqueue.call_count, 1)
            facade._refresh_timed_out()
            self.assertEqual(facade.snapshot.refresh.state, "error")
            facade._receive(
                UsageWorkerResult(
                    1,
                    0,
                    replace(pending, refresh=replace(pending.refresh, state="success")),
                )
            )
            self.assertEqual(facade.snapshot.refresh.state, "error")
            self.assertTrue(facade.refresh(force=True))
            facade.set_enabled(False)
            self.assertEqual(facade.snapshot.refresh.state, "cancelled")

    def test_queue_rejection_reenables_refresh(self):
        facade = UsageWorkerService(
            AppPaths(Path(self.temp.name) / "reject"),
            self.fixture.preferences,
            client_factory=ReadyClient,
        )
        self.addCleanup(facade.close)
        with patch.object(facade._worker, "enqueue", return_value=False):
            self.assertFalse(facade.refresh(force=True))
            self.assertEqual(facade.snapshot.refresh.state, "error")
            self.assertFalse(facade._refresh_timer.isActive())
