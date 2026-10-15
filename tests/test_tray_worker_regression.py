"""Production usage facade/tray contract and packaged smoke failure reporting."""

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from watched_kettle.app_preferences import ApplicationPreferences
from watched_kettle.application.paths import AppPaths
from watched_kettle.features.notifications.service import NotificationService
from watched_kettle.features.usage.viewmodel import UsageViewModel
from watched_kettle.integrations.claude_code_status_line import normalize_status_line
from watched_kettle.ui.assistant_tray import AssistantSystemTray
from watched_kettle.usage.models import RateLimitBucket, UsageSnapshot, UsageWindow
from watched_kettle.usage.presentation import format_tray_summary
from watched_kettle.usage.worker import UsageWorkerService, UsageWorkerResult
from tests.test_usage_service import FakeClient


class UsageProviderClient(FakeClient):
    """Answer a fresh account probe and usage connection on the worker thread."""

    def __init__(self, parent=None):
        super().__init__()
        self.setParent(parent)

    def start(self):
        self.become_ready()

    def request(self, method, params=None):
        rid = super().request(method, params)
        responses = {
            "account/read": {"account": {"type": "chatgpt", "planType": "plus"}},
            "account/rateLimits/read": {
                "accountId": "provider-test",
                "rateLimits": {"limitId": "codex", "primary": {"usedPercent": 20}},
            },
            "account/usage/read": {"summary": {"lifetimeTokens": 100}},
        }
        if rid is not None:
            QTimer.singleShot(0, lambda: self.respond(rid, responses.get(method, {})))
        return rid


class TrayWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_provider_switches_stop_only_their_own_usage_and_survive_reload(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings = QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat)
            preferences = ApplicationPreferences(settings)
            worker = UsageWorkerService(
                AppPaths(root),
                preferences,
                client_factory=UsageProviderClient,
                claude_config_dir=root / "claude",
            )
            view = UsageViewModel(worker, preferences)

            def wait_for(predicate):
                for _ in range(300):
                    self.app.processEvents()
                    if predicate():
                        return
                    # Release the GIL so the Python-owned Qt worker can run.
                    time.sleep(0.01)
                self.fail("provider state did not arrive")

            try:
                wait_for(lambda: worker.availability.available)
                worker.start()
                wait_for(lambda: bool(worker.snapshot.buckets))
                view.set_enabled(False)
                wait_for(lambda: worker.snapshot.availability.state == "disabled")
                self.assertTrue(worker.claude_code_enabled)
                worker.observe_agent_payload(
                    normalize_status_line(
                        dict(
                            session_id="qa",
                            rate_limits=dict(
                                five_hour=dict(used_percentage=30, resets_at=1800000000)
                            ),
                        )
                    )
                )
                wait_for(lambda: bool(worker.claude_code_snapshot.buckets))
                self.assertEqual(
                    [b.limit_id for b in view.snapshot.buckets], ["claude_code"]
                )
                self.assertTrue(view.any_enabled)
                view.set_claude_code_enabled(False)
                wait_for(
                    lambda: worker.claude_code_snapshot.availability.state == "disabled"
                )
                self.assertEqual(view.snapshot.buckets, ())
                self.assertFalse(view.any_enabled)
                view.set_enabled(True)
                wait_for(lambda: bool(worker.snapshot.buckets))
                self.assertFalse(worker.claude_code_enabled)
                self.assertTrue(
                    all(b.limit_id != "claude_code" for b in view.snapshot.buckets)
                )
                reopened = ApplicationPreferences(
                    QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat)
                )
                self.assertTrue(reopened.load_usage_enabled())
                self.assertFalse(reopened.load_claude_code_usage_enabled())
            finally:
                worker.close()

    def test_old_shared_off_setting_is_migrated_once_before_codex_changes(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            preferences = ApplicationPreferences(
                QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat)
            )
            preferences.save_usage_enabled(False)
            worker = UsageWorkerService(
                AppPaths(root),
                preferences,
                client_factory=lambda parent: FakeClient(),
                claude_config_dir=root / "claude",
            )
            try:
                self.assertFalse(worker.claude_code_enabled)
                worker.set_enabled(True)
                self.assertFalse(preferences.load_claude_code_usage_enabled())
            finally:
                worker.close()

    def test_recovery_delivery_coalesces_and_account_change_discards_pending(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings = QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat)
            worker = UsageWorkerService(
                AppPaths(root),
                ApplicationPreferences(settings),
                client_factory=lambda parent: FakeClient(),
            )
            try:
                for _ in range(300):
                    time.sleep(0.01)
                    self.app.processEvents()
                    if worker.availability.available:
                        break
                updates = []
                worker.snapshot_changed.connect(updates.append)
                for i in range(100):
                    worker._receive(
                        UsageWorkerResult(
                            i,
                            100,
                            UsageSnapshot(account_hash="one", history_message=str(i)),
                            True,
                        )
                    )
                self.assertEqual(updates, [])
                self.app.processEvents()
                self.assertEqual(len(updates), 1)
                self.assertEqual(worker.snapshot.history_message, "99")
                worker._receive(
                    UsageWorkerResult(101, 100, UsageSnapshot(account_hash="one"), True)
                )
                worker._receive(
                    UsageWorkerResult(102, 101, UsageSnapshot(account_hash="two"))
                )
                self.app.processEvents()
                self.assertEqual(worker.snapshot.account_hash, "two")
                self.assertEqual(len(updates), 2)
            finally:
                worker.close()

    def test_summary_handles_missing_extremes_and_both_windows(self):
        cases = [
            ([], "확인 불가"),
            ([None], "확인 불가"),
            ([0], "잔여 0%"),
            ([100], "잔여 100%"),
            ([None, 80, 25], "잔여 25%"),
        ]
        for remaining, expected in cases:
            with self.subTest(remaining=remaining):
                buckets = tuple(
                    RateLimitBucket(str(i), primary=UsageWindow(remaining_percent=n))
                    for i, n in enumerate(remaining)
                )
                self.assertEqual(
                    format_tray_summary(UsageSnapshot(buckets=buckets)), expected
                )
        secondary_only = RateLimitBucket(
            "secondary", secondary=UsageWindow(remaining_percent=50)
        )
        self.assertEqual(
            format_tray_summary(UsageSnapshot(buckets=(secondary_only,))), "잔여 50%"
        )

    def test_summary_uses_tighter_codex_window_instead_of_reserve_bucket(self):
        codex = RateLimitBucket(
            "codex",
            primary=UsageWindow(remaining_percent=90),
            secondary=UsageWindow(remaining_percent=70),
        )
        for reserve_remaining in (76, 10):
            with self.subTest(reserve_remaining=reserve_remaining):
                reserve = RateLimitBucket(
                    "base_model_inference",
                    primary=UsageWindow(remaining_percent=reserve_remaining),
                )
                self.assertEqual(
                    format_tray_summary(UsageSnapshot(buckets=(reserve, codex))),
                    "잔여 70%",
                )
        missing = RateLimitBucket("codex", primary=UsageWindow())
        self.assertEqual(
            format_tray_summary(UsageSnapshot(buckets=(reserve, missing))), "확인 불가"
        )

    def test_real_worker_tray_initial_update_toggle_and_locked_storage(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings = QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat)
            preferences = ApplicationPreferences(settings)
            preferences.save_usage_enabled(True)
            worker = UsageWorkerService(
                AppPaths(root), preferences, client_factory=lambda parent: FakeClient()
            )
            tray = None
            try:
                with patch.object(
                    worker, "_send", side_effect=AssertionError("summary performed I/O")
                ):
                    self.assertEqual(worker.tray_summary(), "확인 불가")
                pet = SimpleNamespace(
                    refresh=lambda: SimpleNamespace(
                        visual_state="idle", active_count=0, visible=True
                    ),
                    snooze_bubbles=lambda _: None,
                    resume_bubbles=lambda: None,
                    toggle_visibility=lambda: None,
                )
                vm = UsageViewModel(worker, preferences)
                tray = AssistantSystemTray(
                    pet, vm, NotificationService(), lambda _: None, QPixmap(16, 16)
                )
                vm.snapshot_changed.connect(lambda _: tray.refresh())
                self.assertEqual(
                    tray.usage_status_action.text(), "Codex 사용량: 확인 불가"
                )
                for _ in range(300):
                    time.sleep(0.01)
                    self.app.processEvents()
                    if worker.availability.available:
                        break
                self.assertTrue(worker.availability.available)
                worker._send(
                    "_handle_limits",
                    {
                        "accountId": "tray-test",
                        "rateLimits": {"primary": {"usedPercent": 20}},
                    },
                )
                for _ in range(100):
                    time.sleep(0.01)
                    self.app.processEvents()
                    if worker.snapshot.buckets:
                        break
                tray.menu.aboutToShow.emit()
                self.assertEqual(
                    tray.usage_status_action.text(), "Codex 사용량: 잔여 80%"
                )
                connection = sqlite3.connect(AppPaths(root).database)
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    with patch.object(
                        worker,
                        "_send",
                        side_effect=AssertionError("summary performed I/O"),
                    ):
                        for _ in range(50):
                            self.assertEqual(vm.tray_summary(), "잔여 80%")
                finally:
                    connection.rollback()
                    connection.close()
                vm.set_enabled(False)
                self.assertEqual(
                    tray.usage_status_action.text(), "Codex 사용량: 비활성"
                )
                vm.set_enabled(True)
                self.assertNotEqual(
                    tray.usage_status_action.text(), "Codex 사용량: 비활성"
                )
            finally:
                if tray is not None:
                    tray.close()
                worker.close()
            self.assertFalse(worker._thread.isRunning())


class RuntimeTraySmokeTests(unittest.TestCase):
    def smoke(self, injection=""):
        with TemporaryDirectory() as directory:
            report = Path(directory) / "report.json"
            code = (
                "from watched_kettle.runtime_smoke import run_runtime_smoke\n"
                "from watched_kettle.application.runtime import ApplicationRuntime\n"
                + injection
                + "\n"
                + "raise SystemExit(run_runtime_smoke(['--runtime-smoke-test', '--require-tray', "
                "'--duration-seconds', '3', '--report', " + repr(str(report)) + "]))\n"
            )
            result = subprocess.run(
                [sys.executable, "-c", code], capture_output=True, timeout=30
            )
            self.assertTrue(report.exists(), result.stderr.decode(errors="replace"))
            return result.returncode, json.loads(report.read_text(encoding="utf-8"))

    def test_required_tray_is_exercised_without_system_tray(self):
        code, report = self.smoke()
        self.assertEqual(code, 0, report)
        for field in (
            "tray_required",
            "tray_created",
            "tray_initial_checked",
            "tray_checked",
            "tray_closed",
        ):
            self.assertTrue(report[field], field)
        self.assertEqual(report["lifecycle_errors"], {})

    def test_constructor_failure_writes_failed_report_and_stops_workers(self):
        code, report = self.smoke(
            "from watched_kettle.usage.worker import UsageWorkerService\n"
            "def broken(self): raise AttributeError('synthetic-private-text')\n"
            "UsageWorkerService.tray_summary = broken\n"
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["initialization_error"], "AttributeError")
        self.assertNotIn("synthetic-private-text", json.dumps(report))

    def test_close_failure_cannot_be_reported_as_success(self):
        code, report = self.smoke(
            "original_close = ApplicationRuntime.close\n"
            "def broken(self):\n"
            "    original_close(self)\n"
            "    raise RuntimeError('synthetic-private-text')\n"
            "ApplicationRuntime.close = broken\n"
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")
        self.assertTrue(report["lifecycle_errors"])
        self.assertNotIn("synthetic-private-text", json.dumps(report))
