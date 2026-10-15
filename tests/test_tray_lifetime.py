"""Bounded menu ownership, stable navigation, and external process verdicts."""

import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace as N
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import QApplication, QMenu

from watched_kettle.runtime_smoke import _resources, _write_report
from watched_kettle.ui.assistant_tray import AssistantSystemTray
from scripts.runtime_check import assess, supervise, read_observation

# The smoke run checks the tray every 2 seconds and quits at the duration, so a
# 2-second run had one chance, at the moment it quit; slow CI runners missed it.
SOURCE_SMOKE_SECONDS = 6


class TrayLifetimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.projects = N(generation=0, cards=(), recent=())
        self.opened = []
        self.router = N(
            label=lambda _kind, _identifier="": "open",
            register=lambda kind, value: (kind, value),
            open=self.opened.append,
        )
        self.notifications = N(
            projects=self.projects,
            router=self.router,
            snapshot=N(recent=(), last_message=""),
        )
        self.pet = N(
            refresh=lambda: N(visual_state="idle", active_count=1, visible=True),
            snooze_bubbles=lambda _: None,
            resume_bubbles=lambda: None,
            toggle_visibility=lambda: None,
        )
        self.usage = N(
            enabled=True, snapshot=N(account_hash="one"), tray_summary=lambda: "80%"
        )
        self.replace_data(0)
        self.tray = AssistantSystemTray(
            self.pet, self.usage, self.notifications, lambda _: None, QPixmap(16, 16)
        )
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.tray.close()
        self.flush()

    def flush(self):
        self.app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def replace_data(self, index):
        self.projects.cards = (
            N(
                key=str(index),
                label="project",
                source="codex",
                summary="running",
                rows=(N(thread_id=str(index), title="title", state="running"),),
            ),
        )
        self.projects.recent = tuple(
            N(thread_id=str(index), state="done", occurred_at=n) for n in range(20)
        )

    def test_quit_menu_requests_app_quit_but_hide_does_not(self):
        with patch("watched_kettle.ui.assistant_tray.QApplication.quit") as quit_app:
            tray = AssistantSystemTray(
                self.pet,
                self.usage,
                self.notifications,
                lambda _: None,
                QPixmap(16, 16),
            )
            try:
                tray.visibility_action.trigger()
                quit_app.assert_not_called()
                quit_action = next(
                    action for action in tray.menu.actions() if action.text() == "종료"
                )
                quit_action.trigger()
                quit_app.assert_called_once_with()
            finally:
                tray.close()

    def counts(self):
        return (
            len(self.tray.menu.findChildren(QMenu)),
            len(self.tray.menu.findChildren(QAction)),
            len(self.tray._bindings),
            sum(len(rows) for rows in self.tray._rows.values()),
        )

    def repeat(self, changing):
        expected = self.counts()
        warm = None
        for i in range(10000):
            if changing:
                self.replace_data(i)
            self.tray.refresh()
            if i % 1000 == 999:
                self.flush()
                self.assertEqual(self.counts(), expected)
            if i == 4999:
                warm = _resources().get("private_bytes")
        final = _resources().get("private_bytes")
        if warm is not None and final is not None:
            self.assertLessEqual(final - warm, (32 if changing else 16) * 1024**2)
        self.assertEqual(len(self.tray._project_menus), 1)
        self.assertEqual(len(self.tray._rows), 5)

    def test_10000_identical_refreshes_keep_objects_and_memory_bounded(self):
        original = next(iter(self.tray._project_menus.values()))
        self.repeat(False)
        self.assertIs(next(iter(self.tray._project_menus.values())), original)

    def test_10000_replacements_reuse_slots_and_discard_old_keys(self):
        self.repeat(True)
        self.assertEqual(set(self.tray._project_menus), {"9999"})

    def test_10000_empty_and_populated_cycles_release_retired_objects(self):
        warm = None
        for i in range(10000):
            if i % 2:
                self.projects.cards = ()
                self.projects.recent = ()
            else:
                self.replace_data(i)
            self.tray.refresh()
            self.flush()
            if i % 1000 == 999:
                # 25 fixed actions include the hidden Claude Code usage line
                # and the separators around the home and usage entries.
                self.assertEqual(self.counts(), (7, 25, 0, 0))
            if i == 4999:
                warm = _resources().get("private_bytes")
        final = _resources().get("private_bytes")
        if warm is not None and final is not None:
            self.assertLessEqual(final - warm, 32 * 1024**2)

    def test_requests_coalesce_and_close_cancels_pending_work(self):
        with patch.object(
            self.tray, "_sync_structure", wraps=self.tray._sync_structure
        ) as sync:
            for _ in range(100):
                self.tray.request_refresh()
            self.flush()
            self.assertEqual(sync.call_count, 1)
            self.tray.request_refresh()
            self.tray.close()
            self.flush()
            self.assertEqual(sync.call_count, 1)
        self.tray.close()
        self.tray.refresh()

    def test_open_menu_defers_replacement_and_rejects_stale_click(self):
        menu = next(iter(self.tray._project_menus.values()))
        action = menu.actions()[0]
        self.tray.menu.aboutToShow.emit()
        self.replace_data(1)
        self.tray.refresh()
        self.assertEqual(set(self.tray._project_menus), {"0"})
        self.assertFalse(action.isEnabled())
        action.trigger()
        self.assertEqual(self.opened, [])
        self.tray.menu.aboutToHide.emit()
        self.flush()
        self.assertIs(menu, next(iter(self.tray._project_menus.values())))
        self.assertIs(action, menu.actions()[0])
        action.trigger()
        self.assertEqual(self.opened, [("thread", "1")])

    def test_generation_change_is_checked_at_click_without_refresh(self):
        action = next(iter(self.tray._project_menus.values())).actions()[0]
        self.projects.generation += 1
        action.trigger()
        self.assertEqual(self.opened, [])
        self.tray.refresh()
        action.trigger()
        self.assertEqual(self.opened, [("thread", "0")])

    def test_removed_projects_are_released_after_deferred_delete(self):
        self.projects.cards = ()
        self.projects.recent = ()
        self.tray.refresh()
        self.flush()
        self.assertEqual(self.tray._project_menus, {})
        self.assertEqual(len(self.tray.menu.findChildren(QMenu)), 7)
        self.assertEqual(self.tray._bindings, {})


class SupervisorTests(unittest.TestCase):
    def observation(self):
        return dict(
            status="observation_complete",
            elapsed_seconds=1,
            ticks=10,
            max_event_loop_gap_seconds=0,
            app_version="test",
            lifecycle_errors={},
            **{
                key: True
                for key in (
                    "tray_required",
                    "tray_created",
                    "tray_initial_checked",
                    "tray_checked",
                    "tray_closed",
                    "storage_available",
                )
            },
        )

    def run_child(self, suffix="", *, publish=True, **options):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "observation.json"
            code = "import json,time; from pathlib import Path; "
            if publish:
                # Publish atomically like runtime_smoke._write_report so a slow poll
                # never sees the empty file that write_text creates first.
                temporary = path.with_suffix(".json.tmp")
                code += (
                    f"Path({str(temporary)!r}).write_text("
                    f"{json.dumps(self.observation())!r}); "
                    f"Path({str(temporary)!r}).replace({str(path)!r}); "
                )
            code += suffix
            options.setdefault(
                "supervisor_resource_reader", lambda: {"private_bytes": 16 * 1024**2}
            )
            # A slow CI runner can take over 0.5 s just to start Python, so only
            # the startup-timeout case uses a short startup limit. The short exit
            # limit keeps the hung-cleanup case fast.
            options.setdefault("startup_timeout", 15)
            options.setdefault("exit_timeout", 0.2)
            result = supervise([sys.executable, "-c", code], path, 0.1, **options)
            self.assertTrue(result["process_exited"])
            self.assertTrue(path.with_suffix(".verdict.json").exists())
            return result

    def test_completed_observation_requires_successful_process_exit(self):
        # A healthy child also gets a real exit limit; Python can take over
        # 0.2 s to shut down on a slow CI runner.
        result = self.run_child(exit_timeout=10)
        self.assertEqual(result["status"], "passed", result["issues"])
        self.assertIn(
            "process_exit_failed", self.run_child("raise SystemExit(3)")["issues"]
        )

    def test_report_reader_uses_append_only_samples_during_publication(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            timeline = path.with_suffix(".samples.jsonl")
            _write_report(path, {"sequence": 1})
            if os.name == "nt":
                with path.open("r", encoding="utf-8"):
                    with self.assertRaises(PermissionError):
                        _write_report(path, {"sequence": 2})
            timeline.write_bytes(b'{"sequence": 1}\n{"sequence":')
            with timeline.open("rb"):
                _write_report(path, {"sequence": 3})
                with patch(
                    "scripts.runtime_check.read_report", side_effect=AssertionError
                ):
                    self.assertEqual(read_observation(path), {"sequence": 1})
            with timeline.open("ab") as stream:
                stream.write(b" 3}\n")
            self.assertEqual(read_observation(path), {"sequence": 3})

    def test_hung_cleanup_and_missing_startup_are_killed_and_failed(self):
        self.assertIn("exit_timeout", self.run_child("time.sleep(10)")["issues"])
        self.assertIn(
            "startup_timeout",
            self.run_child("time.sleep(10)", publish=False, startup_timeout=0.5)[
                "issues"
            ],
        )

    def test_memory_limit_stops_only_the_owned_child(self):
        result = self.run_child(
            "time.sleep(10)", resource_reader=lambda _: {"private_bytes": 2**31}
        )
        self.assertIn("memory_limit", result["issues"])

    def test_tick_and_gap_thresholds_are_part_of_external_verdict(self):
        observation = self.observation()
        observation.update(ticks=8, max_event_loop_gap_seconds=5)
        self.assertIn("tick_coverage_low", assess(observation, 0, 1))
        self.assertIn("event_loop_gap", assess(observation, 0, 1))

    def test_supervisor_memory_limit_is_independent_of_child(self):
        result = self.run_child(
            "time.sleep(10)",
            supervisor_resource_reader=lambda: {"private_bytes": 300 * 1024**2},
        )
        self.assertIn("supervisor_memory_limit", result["issues"])

    def test_supervisor_rejects_memory_from_a_redirector_process(self):
        observation = self.observation()
        observation["latest_resources"] = {"process_id": -1234}
        with patch.object(self, "observation", return_value=observation):
            result = self.run_child("time.sleep(0.3)")
        self.assertIn("process_identity_mismatch", result["issues"])

    def test_source_command_owns_the_actual_runtime_process(self):
        from scripts.runtime_check import source_command

        with TemporaryDirectory() as directory:
            report = Path(directory) / "source.json"
            command = source_command(
                Path(__file__).resolve().parent.parent,
                [
                    "--runtime-smoke-test",
                    "--require-tray",
                    "--duration-seconds",
                    str(SOURCE_SMOKE_SECONDS),
                    "--report",
                    str(report),
                ],
            )
            result = supervise(
                command,
                report,
                SOURCE_SMOKE_SECONDS,
                # The coverage suite's heap is not the standalone supervisor.
                # This test checks the real child PID, not the test runner's RAM.
                supervisor_resource_reader=lambda: {"private_bytes": 16 * 1024**2},
            )
        self.assertEqual(result["status"], "passed", result["issues"])
        self.assertEqual(
            result["pid"], result["observation"]["latest_resources"]["process_id"]
        )

    def test_unchanged_report_is_not_reparsed_on_each_poll(self):
        import scripts.runtime_check as module

        with patch.object(
            module, "read_observation", wraps=module.read_observation
        ) as read:
            self.run_child("time.sleep(0.3)")
        self.assertLessEqual(read.call_count, 1)
