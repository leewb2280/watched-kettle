"""Claude Code rate limits from the status line bridge (stage 13)."""

import io
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from watched_kettle import hook_bridge_entrypoint
from watched_kettle.features.usage.viewmodel import UsageViewModel
from watched_kettle.integrations.claude_code_status_line import (
    normalize_status_line,
    run_original,
)
from watched_kettle.integrations.codex_hooks import sanitize_pet_event
from watched_kettle.storage.claude_code_repository import ClaudeCodeRepository
from watched_kettle.storage.database import DatabaseManager
from watched_kettle.usage.claude_code_limits import (
    QuotaSample,
    account_hash,
    bucket,
    threshold_notices,
    tray_summary,
)
from watched_kettle.usage.claude_code_service import ClaudeCodeUsageService
from watched_kettle.usage.models import UsageSnapshot, usage_limit_options


NOW = datetime.now(timezone.utc).replace(microsecond=0)
RESET = int((NOW + timedelta(hours=3)).timestamp())


def status_input(five=23.5, seven=41.2, reset=RESET):
    """Status line input shape from the official documentation."""
    return {
        "session_id": "s1",
        "model": {"display_name": "Opus"},
        "workspace": {"current_dir": "C:/Users/example/secret"},
        "rate_limits": {
            "five_hour": {"used_percentage": five, "resets_at": reset},
            "seven_day": {"used_percentage": seven, "resets_at": reset + 86400},
        },
    }


class StatusLineBridgeTests(unittest.TestCase):
    def test_only_limit_numbers_cross_the_pipe(self):
        event = normalize_status_line(status_input())

        self.assertEqual(event["event"], "rate_limits")
        self.assertEqual(event["five_hour_percent"], 23.5)
        self.assertEqual(event["seven_day_resets_at"], RESET + 86400)
        self.assertNotIn("secret", json.dumps(event))
        self.assertEqual(sanitize_pet_event(event), event)

    def test_missing_or_invalid_limits_send_nothing(self):
        self.assertIsNone(normalize_status_line({"session_id": "s1"}))
        self.assertIsNone(normalize_status_line(None))
        broken = status_input()
        broken["rate_limits"] = {"five_hour": {"used_percentage": "high"}}
        self.assertIsNone(normalize_status_line(broken))
        self.assertIsNone(
            sanitize_pet_event(
                {
                    "source": "claude_code",
                    "event": "rate_limits",
                    "session_id": "x",
                    "five_hour_percent": float("nan"),
                }
            )
        )

    def test_original_status_line_output_is_passed_through(self):
        output = run_original(
            "import sys; sys.stdout.write(sys.stdin.read().upper())",
            b"line",
            environment={**os.environ, "SHELL": sys.executable},
        )

        self.assertEqual(output, b"LINE")

    def test_bridge_mode_sends_limits_and_prints_the_original_line(self):
        with TemporaryDirectory() as directory:
            config = Path(directory) / "status-line.json"
            config.write_text(
                json.dumps(
                    {"original": {"command": "import sys; sys.stdout.write('mine')"}}
                ),
                encoding="utf-8",
            )
            stdout = io.BytesIO()
            sent = []
            with (
                patch.dict(
                    os.environ,
                    {
                        "WATCHED_KETTLE_STATUS_LINE_CONFIG": str(config),
                        "SHELL": sys.executable,
                    },
                ),
                patch(
                    "watched_kettle.integrations.codex_client.send_pet_event",
                    side_effect=lambda event, *args: sent.append(event) or True,
                ),
            ):
                code = hook_bridge_entrypoint.run_status_line(
                    io.BytesIO(json.dumps(status_input()).encode("utf-8")), stdout
                )

        self.assertEqual(code, 0)
        self.assertEqual(stdout.getvalue(), b"mine")
        self.assertEqual([event["event"] for event in sent], ["rate_limits"])

    def test_bridge_mode_without_original_or_app_prints_nothing(self):
        stdout = io.BytesIO()
        with (
            patch.dict(
                os.environ,
                {"WATCHED_KETTLE_STATUS_LINE_CONFIG": "missing-status-line.json"},
            ),
            patch(
                "watched_kettle.integrations.codex_client.send_pet_event",
                side_effect=OSError,
            ),
        ):
            code = hook_bridge_entrypoint.run_status_line(io.BytesIO(b"{bad"), stdout)

        self.assertEqual((code, stdout.getvalue()), (0, b""))


class LimitPolicyTests(unittest.TestCase):
    def sample(self, percent, window="five_hour", reset=RESET):
        return QuotaSample(
            window, NOW, percent, datetime.fromtimestamp(reset, timezone.utc)
        )

    def test_bucket_matches_the_codex_limit_model(self):
        latest = {
            "five_hour": self.sample(23.5),
            "seven_day": self.sample(41.2, "seven_day"),
        }

        options = usage_limit_options(bucket(latest, NOW))

        self.assertEqual(
            [o.key for o in options], ["claude_code|primary", "claude_code|secondary"]
        )
        self.assertEqual(options[0].window.remaining_percent, 76.5)
        self.assertIn("Claude Code", options[0].label)

    def test_windows_past_their_reset_are_estimated_full(self):
        past = int(NOW.timestamp()) - 1
        latest = {
            "five_hour": self.sample(50, reset=past),
            # Two weekly resets missed: the next one is the third.
            "seven_day": self.sample(80, "seven_day", past - 8 * 86400),
        }

        (item,) = bucket(latest, NOW)

        self.assertEqual(
            (item.primary.remaining_percent, item.primary.estimated), (100.0, True)
        )
        # The 5-hour window starts at the next use, so its reset is unknown.
        self.assertIsNone(item.primary.resets_at)
        self.assertTrue(item.secondary.estimated)
        self.assertEqual(
            item.secondary.resets_at,
            datetime.fromtimestamp(past - 8 * 86400, timezone.utc) + timedelta(days=14),
        )
        self.assertEqual(
            tray_summary((item,)), "5시간 잔여 100%(추정) · 7일 잔여 100%(추정)"
        )

    def test_a_new_sample_replaces_the_estimate(self):
        latest = {"five_hour": self.sample(50, reset=int(NOW.timestamp()) - 1)}
        self.assertTrue(bucket(latest, NOW)[0].primary.estimated)

        latest["five_hour"] = self.sample(12)
        (item,) = bucket(latest, NOW)

        self.assertEqual(
            (item.primary.remaining_percent, item.primary.estimated), (88.0, False)
        )

    def test_threshold_is_announced_once_when_crossed(self):
        crossed = threshold_notices(self.sample(65), self.sample(72), NOW)

        self.assertEqual(len(crossed), 1)
        self.assertIn("Claude Code 5시간 잔여 28%", crossed[0].message)
        self.assertEqual(threshold_notices(self.sample(72), self.sample(75), NOW), ())
        self.assertEqual(threshold_notices(None, self.sample(95), NOW), ())
        new_window = threshold_notices(
            self.sample(95), self.sample(71, reset=RESET + 18000), NOW
        )
        self.assertEqual(len(new_window), 1)

    def test_account_is_hashed(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory) / ".claude"
            folder.mkdir()
            (Path(directory) / ".claude.json").write_text(
                json.dumps(
                    {"oauthAccount": {"accountUuid": "uuid-1", "emailAddress": "a@b"}}
                ),
                encoding="utf-8",
            )
            value = account_hash(folder)

        self.assertTrue(value.startswith("claude_code:"))
        self.assertNotIn("uuid-1", value)
        self.assertEqual(account_hash(Path("missing")), "claude_code:local")


class LimitServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = TemporaryDirectory()
        root = Path(self.directory.name)
        self.database = DatabaseManager(root / "usage.sqlite3")
        self.assertTrue(self.database.start().available)
        self.notices = []

    def tearDown(self):
        self.database.close()
        self.directory.cleanup()

    def service(self):
        service = ClaudeCodeUsageService(
            ClaudeCodeRepository(self.database),
            config_dir=Path(self.directory.name) / "claude",
        )
        service.notice_requested.connect(self.notices.append)
        service.start()
        return service

    def observe(self, service, five, seven=10.0):
        service.observe_agent_payload(normalize_status_line(status_input(five, seven)))

    def test_unchanged_values_are_not_stored_on_every_response(self):
        service = self.service()
        for _ in range(4):
            self.observe(service, 41, 55)
        self.observe(service, 42, 55)

        rows = service.repository.quota_samples(
            service.snapshot.account_hash, NOW - timedelta(days=1)
        )
        self.assertEqual(
            sorted((window, percent) for window, _at, percent, _reset in rows),
            [("five_hour", 41.0), ("five_hour", 42.0), ("seven_day", 55.0)],
        )
        self.assertIsNotNone(service.snapshot.limits_observed_at)
        service.close()

    def test_limits_reach_the_snapshot_and_survive_a_restart(self):
        service = self.service()
        self.observe(service, 60)
        self.observe(service, 75)
        self.assertEqual(len(self.notices), 1)
        self.assertEqual(service.snapshot.buckets[0].primary.remaining_percent, 25.0)
        service.close()

        restarted = self.service()
        self.assertEqual(restarted.snapshot.buckets[0].primary.used_percent, 75.0)
        self.observe(restarted, 76)
        self.assertEqual(len(self.notices), 1)
        restarted.close()


class _Service(QObject):
    snapshot_changed = Signal(object)
    claude_code_snapshot_changed = Signal(object)

    def __init__(self):
        super().__init__()
        self.snapshot = UsageSnapshot()
        self.claude_code_snapshot = None
        self.enabled = True


class ViewModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_widget_snapshot_lists_claude_code_after_codex(self):
        service = _Service()
        view = UsageViewModel(service, preferences=None)
        emitted = []
        view.snapshot_changed.connect(emitted.append)
        claude = SimpleNamespace(
            buckets=bucket(
                {
                    "five_hour": QuotaSample(
                        "five_hour",
                        NOW,
                        30.0,
                        datetime.fromtimestamp(RESET, timezone.utc),
                    )
                },
                NOW,
            )
        )
        service.claude_code_snapshot = claude
        service.claude_code_snapshot_changed.emit(claude)

        self.assertEqual([b.limit_id for b in emitted[-1].buckets], ["claude_code"])
        self.assertEqual(view.claude_code_tray_summary(), "5시간 잔여 70%")


if __name__ == "__main__":
    unittest.main()
