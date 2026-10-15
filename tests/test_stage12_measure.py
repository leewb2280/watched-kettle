import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication

from watched_kettle.integrations.codex_client import (
    WATCHED_KETTLE_SERVER_NAME,
    configured_pet_server_name,
)
from watched_kettle.integrations.codex_ipc import CodexHookServer
from watched_kettle.integrations.single_instance import (
    DEFAULT_INSTANCE_SERVER_NAME,
    configured_instance_server_name,
)
from scripts.stage12_measure import (
    CycleTiming,
    cycle_metrics,
    descendants,
    distribution,
    isolated_environment,
    nearest_rank,
    read_timeline,
    window_median,
)


class StatisticsTests(unittest.TestCase):
    def test_nearest_rank_uses_upper_sample_for_small_sets(self):
        self.assertEqual(nearest_rank([5, 1, 3, 2, 4], 95), 5)
        self.assertEqual(nearest_rank([5, 1, 3, 2, 4], 50), 3)
        self.assertIsNone(nearest_rank([], 95))

    def test_distribution_ignores_missing_values(self):
        result = distribution([1.0, None, 3.0])

        self.assertEqual(result["count"], 2)
        self.assertEqual(result["median"], 2.0)
        self.assertEqual(distribution([None]), {"count": 0})

    def test_window_median_is_inclusive(self):
        samples = [{"t": t, "total_private_bytes": t * 10} for t in range(10)]

        self.assertEqual(window_median(samples, 2, 4), 30)
        self.assertIsNone(window_median(samples, 20, 30))


class ProcessTreeTests(unittest.TestCase):
    def test_descendants_follow_parent_links_only(self):
        table = {
            10: (1, "app.exe"),
            11: (10, "WatchedKettleSettings.exe"),
            12: (11, "WatchedKettleSettings.exe"),
            20: (1, "other.exe"),
        }

        self.assertEqual(sorted(descendants(10, table)), [10, 11, 12])

    def test_descendants_tolerate_reused_self_parent(self):
        table = {4: (4, "System")}

        self.assertEqual(descendants(4, table), [4])
        self.assertEqual(descendants(99, table), [])


class IsolationTests(unittest.TestCase):
    def test_environment_moves_every_user_scoped_location(self):
        root = Path("C:/measure/run")

        environment = isolated_environment(root)

        self.assertEqual(environment["LOCALAPPDATA"], str(root / "LocalAppData"))
        self.assertEqual(
            environment["WATCHED_KETTLE_SPOOL_DIRECTORY"], str(root / "spool")
        )
        self.assertNotEqual(
            environment["WATCHED_KETTLE_INSTANCE_SERVER_NAME"],
            DEFAULT_INSTANCE_SERVER_NAME,
        )
        self.assertNotEqual(
            environment["WATCHED_KETTLE_SERVER_NAME"], WATCHED_KETTLE_SERVER_NAME
        )

    def test_names_are_unique_per_run(self):
        first = isolated_environment("a")
        second = isolated_environment("a")

        self.assertNotEqual(
            first["WATCHED_KETTLE_INSTANCE_SERVER_NAME"],
            second["WATCHED_KETTLE_INSTANCE_SERVER_NAME"],
        )

    def test_application_honors_isolation_overrides(self):
        with patch.dict(
            os.environ,
            {
                "WATCHED_KETTLE_INSTANCE_SERVER_NAME": "instance-x",
                "WATCHED_KETTLE_SERVER_NAME": "agent-x",
            },
        ):
            self.assertEqual(configured_instance_server_name(), "instance-x")
            self.assertEqual(configured_pet_server_name(), "agent-x")
            QCoreApplication.instance() or QCoreApplication([])
            self.assertEqual(CodexHookServer().server_name, "agent-x")

    def test_defaults_without_overrides(self):
        with patch.dict(os.environ):
            os.environ.pop("WATCHED_KETTLE_INSTANCE_SERVER_NAME", None)
            os.environ.pop("WATCHED_KETTLE_SERVER_NAME", None)
            self.assertEqual(
                configured_instance_server_name(), DEFAULT_INSTANCE_SERVER_NAME
            )
            self.assertEqual(configured_pet_server_name(), WATCHED_KETTLE_SERVER_NAME)


class CycleMetricsTests(unittest.TestCase):
    def events(self):
        return [
            {"event": "idle_window_start", "t": 100.0},
            {"event": "idle_window_end", "t": 400.0},
            {"event": "settings_open_ready", "t": 401.0, "duration_ms": 900},
            {"event": "settings_hidden", "t": 520.0},
            {"event": "settings_reopen_requested", "t": 850.0},
            {"event": "settings_reopen_ready", "t": 851.0, "duration_ms": 1200},
        ]

    def test_windows_split_idle_open_and_hidden_phases(self):
        mib = 1024 * 1024
        samples = []
        for t in range(0, 900, 5):
            value = 60 if t < 401 else 360 if t < 520 else 70
            samples.append(
                {
                    "t": float(t),
                    "total_private_bytes": value * mib,
                    "processes": [{"name": "app.exe"}],
                }
            )

        result = cycle_metrics(self.events(), samples, CycleTiming())

        self.assertEqual(result["issues"], [])
        self.assertEqual(result["idle_private_mib"], 60.0)
        self.assertEqual(result["open_private_mib"], 360.0)
        self.assertEqual(result["hidden_private_mib"], 70.0)
        self.assertEqual(result["first_open_ms"], 900)
        self.assertEqual(result["reopen_ms"], 1200)
        self.assertEqual(result["processes_while_hidden"], ["app.exe"])

    def test_missing_phases_are_reported_not_guessed(self):
        result = cycle_metrics(self.events()[:2], [], CycleTiming())

        self.assertIn("settings_open_ready", result["issues"])
        self.assertIsNone(result["hidden_private_mib"])
        self.assertIsNone(result["reopen_ms"])


class TimelineTests(unittest.TestCase):
    def test_timeline_entries_gain_epoch_seconds(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "timeline.jsonl"
            path.write_text(
                json.dumps(
                    {"event": "probe_started", "at_utc": "2026-10-02T00:00:00+00:00"}
                )
                + "\n",
                encoding="utf-8",
            )

            events = read_timeline(path)

        self.assertEqual(events[0]["event"], "probe_started")
        self.assertEqual(events[0]["t"], 1790899200.0)
        self.assertEqual(read_timeline(Path(directory) / "missing.jsonl"), [])


if __name__ == "__main__":
    unittest.main()
