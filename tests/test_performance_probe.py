import json
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QObject, QProcess, QTimer, Signal
from PySide6.QtWidgets import QApplication

from watched_kettle.performance_probe import (
    PerformanceProbe,
    Timeline,
    parse_probe_arguments,
)


class FakeApplication(QObject):
    aboutToQuit = Signal()

    def __init__(self):
        super().__init__()
        self.loop = QEventLoop()
        self.quit_count = 0

    def quit(self):
        self.quit_count += 1
        self.aboutToQuit.emit()
        self.loop.quit()


class FakeProcess:
    def __init__(self):
        self.running = True

    def state(self):
        if self.running:
            return QProcess.ProcessState.Running
        return QProcess.ProcessState.NotRunning

    def kill(self):
        self.running = False


class FakeHost:
    """Settings host that becomes ready immediately when opened."""

    def __init__(self):
        self.authenticated = False
        self.visible = False
        self.subscriptions = set()
        self.process = FakeProcess()
        self.calls = []

    def open_route(self, route):
        self.calls.append(("open", route))
        self.process.running = True
        self.authenticated = self.visible = True
        self.subscriptions = {"settings"}

    def hide(self):
        self.calls.append(("hide",))
        self.visible = False
        self.subscriptions = set()


class FakeRuntime:
    def __init__(self, host):
        self.center = host


class PerformanceProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def run_probe(self, *arguments):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        report = Path(directory.name) / "timeline.jsonl"
        options = parse_probe_arguments(
            ["--performance-probe", "--report", str(report), *arguments]
        )
        app, host = FakeApplication(), FakeHost()
        PerformanceProbe(options)(app, None, FakeRuntime(host))
        QTimer.singleShot(10_000, app.loop.quit)
        app.loop.exec()
        events = [
            json.loads(line)["event"]
            for line in report.read_text(encoding="utf-8").splitlines()
        ]
        return app, host, events

    def test_defaults_match_the_measurement_plan(self):
        options = parse_probe_arguments(["--performance-probe", "--report", "r"])

        self.assertEqual(options.scenario, "idle")
        self.assertEqual(options.warmup_seconds, 120.0)
        self.assertEqual(options.idle_seconds, 300.0)
        self.assertEqual(options.hidden_seconds, 330.0)

    def test_idle_quits_after_duration(self):
        app, host, events = self.run_probe("--duration-seconds", "0.05")

        self.assertEqual(events, ["probe_started", "probe_quit"])
        self.assertEqual(app.quit_count, 1)
        self.assertEqual(host.calls, [])

    def test_settings_cycle_records_each_phase_in_order(self):
        app, host, events = self.run_probe(
            "--scenario", "settings-cycle",
            "--warmup-seconds", "0.01",
            "--idle-seconds", "0.01",
            "--open-seconds", "0.01",
            "--hidden-seconds", "0.01",
            "--tail-seconds", "0.01",
        )  # fmt: skip

        self.assertEqual(
            [event for event in events if event != "probe_quit"],
            [
                "probe_started",
                "idle_window_start",
                "idle_window_end",
                "settings_open_requested",
                "settings_open_ready",
                "settings_hidden",
                "settings_reopen_requested",
                "settings_reopen_ready",
            ],
        )
        self.assertEqual([call[0] for call in host.calls], ["open", "hide", "open"])

    def test_settings_recovery_restarts_the_killed_child(self):
        app, host, events = self.run_probe(
            "--scenario",
            "settings-recovery",
            "--warmup-seconds",
            "0.01",
            "--tail-seconds",
            "0.01",
        )

        self.assertIn("settings_child_killed", events)
        self.assertIn("settings_child_stopped", events)
        self.assertIn("settings_recovered_ready", events)

    def test_long_mixed_never_opens_after_the_last_full_cycle(self):
        # Cycles start at 1, 2 and 3 s; a fourth would end after the 3.5 s quit.
        # The last hide has ~0.3 s of slack, enough for a loaded CI timer.
        app, host, events = self.run_probe(
            "--scenario", "long-mixed",
            "--duration-seconds", "3.5",
            "--cycle-seconds", "1.0",
            "--cycle-open-seconds", "0.2",
        )  # fmt: skip

        self.assertEqual(events.count("settings_open_ready"), 3)
        self.assertEqual(events.count("settings_hidden"), 3)
        self.assertEqual(events[-1], "probe_quit")

    def test_timeline_never_overwrites_a_report(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "timeline.jsonl"
            path.write_text("previous\n", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                Timeline(path)

            self.assertEqual(path.read_text(encoding="utf-8"), "previous\n")


if __name__ == "__main__":
    unittest.main()
