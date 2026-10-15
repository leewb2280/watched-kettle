"""Opt-in measurement probe attached to the real application startup path.

``scripts.stage12_measure`` launches the packaged executable with
``--performance-probe``. The probe drives the settings window on a fixed
schedule and records only phase names and timings, never user content.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from time import monotonic

from PySide6.QtCore import QProcess, QTimer

PROBE_FLAG = "--performance-probe"
SCENARIOS = ("idle", "settings-cycle", "settings-recovery", "long-mixed")
READY_TIMEOUT_SECONDS = 20.0
POLL_INTERVAL_MS = 20
# PySide drops single-shot bound methods of collected objects; keep the running probe.
_ACTIVE_PROBES = []


def parse_probe_arguments(arguments):
    parser = argparse.ArgumentParser(prog=f"WatchedKettle {PROBE_FLAG}")
    parser.add_argument(PROBE_FLAG, action="store_true")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--scenario", choices=SCENARIOS, default="idle")
    parser.add_argument("--duration-seconds", type=float, default=60.0)
    parser.add_argument("--warmup-seconds", type=float, default=120.0)
    parser.add_argument("--idle-seconds", type=float, default=300.0)
    parser.add_argument("--open-seconds", type=float, default=120.0)
    parser.add_argument("--hidden-seconds", type=float, default=330.0)
    parser.add_argument("--cycle-seconds", type=float, default=600.0)
    parser.add_argument("--cycle-open-seconds", type=float, default=60.0)
    parser.add_argument("--tail-seconds", type=float, default=30.0)
    return parser.parse_args(arguments)


class Timeline:
    """Append-only phase log; an existing report is never overwritten."""

    def __init__(self, path, clock=monotonic):
        self.path = Path(path)
        self.clock = clock
        self.started = clock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open("x", encoding="utf-8")

    def record(self, event, **fields):
        if self.stream.closed:
            return
        entry = {
            "event": event,
            "elapsed_seconds": round(self.clock() - self.started, 4),
            "at_utc": datetime.now(timezone.utc).isoformat(),
            **fields,
        }
        self.stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self.stream.flush()

    def close(self):
        if not self.stream.closed:
            self.stream.close()


def settings_host(runtime):
    return getattr(runtime, "center", None) or getattr(runtime, "settings", None)


def host_ready(host):
    return bool(
        host.authenticated and host.visible and "settings" in host.subscriptions
    )


class PerformanceProbe:
    """Run one scenario as a chain of single-shot steps on the GUI thread."""

    def __init__(self, options, clock=monotonic):
        self.options = options
        self.clock = clock
        self.timeline = None
        self.app = None
        self.host = None

    def __call__(self, app, _pet, runtime):
        _ACTIVE_PROBES.append(self)
        self.app = app
        self.host = settings_host(runtime)
        self.timeline = Timeline(self.options.report, clock=self.clock)
        self.timeline.record(
            "probe_started", pid=os.getpid(), scenario=self.options.scenario
        )
        app.aboutToQuit.connect(self._finish)
        getattr(self, "_schedule_" + self.options.scenario.replace("-", "_"))()

    def _after(self, seconds, callback):
        # Single-shot calls keep no timer objects alive inside the measured process.
        QTimer.singleShot(max(0, round(seconds * 1000)), callback)

    def _quit(self):
        self.timeline.record("probe_quit")
        self.app.quit()

    def _finish(self):
        if self.timeline is not None:
            self.timeline.close()
        if self in _ACTIVE_PROBES:
            _ACTIVE_PROBES.remove(self)

    def _open(self, label, then):
        """Open the settings window and report when the renderer is subscribed."""
        requested = self.clock()
        self.timeline.record(label + "_requested")
        self.host.open_route("pet_settings")

        def poll():
            elapsed = self.clock() - requested
            if host_ready(self.host):
                self.timeline.record(
                    label + "_ready", duration_ms=round(elapsed * 1000)
                )
                then()
            elif elapsed > READY_TIMEOUT_SECONDS:
                self.timeline.record(label + "_timeout")
                self._quit()
            else:
                self._after(POLL_INTERVAL_MS / 1000, poll)

        poll()

    def _hide(self, label="settings_hidden"):
        self.host.hide()
        self.timeline.record(label)

    def _schedule_idle(self):
        self._after(self.options.duration_seconds, self._quit)

    def _schedule_settings_cycle(self):
        options = self.options

        def reopen():
            self._open(
                "settings_reopen", lambda: self._after(options.tail_seconds, self._quit)
            )

        def hide():
            self._hide()
            self._after(options.hidden_seconds, reopen)

        def first_open():
            self.timeline.record("idle_window_end")
            self._open("settings_open", lambda: self._after(options.open_seconds, hide))

        self._after(
            options.warmup_seconds,
            lambda: self.timeline.record("idle_window_start"),
        )
        self._after(options.warmup_seconds + options.idle_seconds, first_open)

    def _schedule_settings_recovery(self):
        def wait_stopped(started):
            if self.host.process.state() == QProcess.ProcessState.NotRunning:
                self.timeline.record(
                    "settings_child_stopped",
                    duration_ms=round((self.clock() - started) * 1000),
                )
                self._open(
                    "settings_recovered",
                    lambda: self._after(self.options.tail_seconds, self._quit),
                )
            elif self.clock() - started > READY_TIMEOUT_SECONDS:
                self.timeline.record("settings_child_stop_timeout")
                self._quit()
            else:
                self._after(POLL_INTERVAL_MS / 1000, lambda: wait_stopped(started))

        def kill():
            self.timeline.record("settings_child_killed")
            self.host.process.kill()
            wait_stopped(self.clock())

        self._after(
            self.options.warmup_seconds,
            lambda: self._open(
                "settings_open", lambda: self._after(self.options.tail_seconds, kill)
            ),
        )

    def _schedule_long_mixed(self):
        options = self.options
        start = options.cycle_seconds
        while start + options.cycle_open_seconds < options.duration_seconds:
            self._after(start, self._cycle)
            start += options.cycle_seconds
        self._after(options.duration_seconds, self._quit)

    def _cycle(self):
        self._open(
            "settings_open",
            lambda: self._after(self.options.cycle_open_seconds, self._hide),
        )


def probe_from_arguments(arguments):
    return PerformanceProbe(parse_probe_arguments(arguments))
