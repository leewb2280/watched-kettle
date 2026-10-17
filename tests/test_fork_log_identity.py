"""Forked rollout headers and copied history must not complete the parent."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication, QWidget

from watched_kettle.features.agent_activity.service import AgentActivityService
from watched_kettle.features.notifications.actions import NotificationActionRouter
from watched_kettle.features.notifications.service import NotificationService
from watched_kettle.features.project_activity.service import (
    ProjectActivityService,
    ThreadMetadata,
)
from watched_kettle.integrations.codex_ipc import CodexHookServer, PIPE_TRANSPORT
from watched_kettle.integrations.codex_log import CodexLogMonitor
from watched_kettle.state.controller import PetAgentController
from watched_kettle.ui.actionable_bubbles import ActionableBubbleController


STAMP = "2026-01-15T09:30:00.620Z"


def record(kind, **payload):
    return {"timestamp": STAMP, "type": kind, "payload": payload}


def lifecycle(kind, turn):
    return record("event_msg", type=kind, turn_id=turn)


def metadata(owner, source="vscode", **extra):
    return record("session_meta", id=owner, source=source, **extra)


def fork_records(child="child", parent="parent"):
    # Sanitized structure observed in real paginated full-history forks. The
    # copied records have fresh timestamps, so a time cutoff cannot remove them.
    inherited = [
        metadata(parent),
        lifecycle("task_started", "copied-turn"),
        record("response_item", type="message"),
        record("response_item", type="function_call", name="tool", call_id="copied"),
        lifecycle("task_complete", "copied-turn"),
    ]
    return [
        metadata(
            child,
            {"subagent": {"thread_spawn": {"parent_thread_id": parent}}},
            session_id=parent,
            forked_from_id=parent,
            parent_thread_id=parent,
            subagent_history_start_ordinal=1 + len(inherited),
        ),
        *inherited,
        lifecycle("task_started", child + "-turn"),
        record("response_item", type="message"),
        lifecycle("task_complete", child + "-turn"),
    ]


def encode(records):
    return b"".join(json.dumps(r).encode() + b"\n" for r in records)


class ForkLogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / "rollout-child.jsonl"
        self.monitor = CodexLogMonitor(
            self.root, now=lambda: datetime(2026, 1, 15, 9, 30, 0, tzinfo=timezone.utc)
        )
        self.addCleanup(self.monitor.close)
        self.events = []
        self.monitor.payload_detected.connect(self.events.append)

    def feed(self, records, path=None):
        for r in records:
            self.monitor._process_line(path or self.path, json.dumps(r).encode())

    def read(self, records=200, byte_budget=1024 * 1024):
        self.monitor._positions.setdefault(self.path, 0)
        self.monitor._budget_bytes = byte_budget
        self.monitor._budget_records = records
        self.monitor._deadline = float("inf")
        self.monitor._read_new_records(self.path)

    def test_copied_parent_metadata_never_replaces_file_owner(self):
        self.feed(fork_records()[:2])
        self.assertEqual(self.monitor._session_ids[self.path], "child")
        self.assertEqual(self.monitor.session_scope("child"), "subagent")
        self.assertEqual(self.monitor.session_scope("parent"), "unknown")

    def test_fresh_copied_history_emits_no_lifecycle_or_heartbeat(self):
        records = fork_records()
        boundary = records[0]["payload"]["subagent_history_start_ordinal"]
        self.feed(records[:boundary])
        self.assertEqual(self.events, [])
        self.assertFalse(self.monitor._active_turns)
        self.assertFalse(self.monitor._recovery_confirmed)
        self.assertFalse(self.monitor._tool_turns)
        self.feed(records[boundary:])
        self.assertEqual([e["event"] for e in self.events], ["prompt", "ended"])
        self.assertTrue(all(e["session_id"] == "child" for e in self.events))
        self.assertTrue(all(e["agent_scope"] == "subagent" for e in self.events))

    def test_split_reads_and_partial_header_keep_the_history_boundary(self):
        data = encode(fork_records())
        self.path.write_bytes(data[:20])
        self.monitor.start()
        self.read()
        self.assertEqual(self.events, [])
        with self.path.open("ab") as stream:
            stream.write(data[20:])
        for _ in range(len(data)):
            self.read(records=1, byte_budget=37)
            if self.monitor._positions[self.path] == len(data):
                break
        self.assertEqual([e["event"] for e in self.events], ["prompt", "ended"])
        self.assertTrue(all(e["session_id"] == "child" for e in self.events))

    def test_existing_fork_does_not_replay_and_new_turn_keeps_owner(self):
        self.path.write_bytes(encode(fork_records()))
        self.monitor.start()
        self.read()
        self.assertEqual(self.events, [])
        with self.path.open("ab") as stream:
            stream.write(
                encode(
                    [
                        metadata("parent"),
                        lifecycle("task_started", "next"),
                        record("response_item", type="message"),
                        lifecycle("task_complete", "next"),
                    ]
                )
            )
        self.read()
        self.assertEqual([e["event"] for e in self.events], ["prompt", "ended"])
        self.assertTrue(all(e["session_id"] == "child" for e in self.events))
        self.assertEqual(self.monitor.session_scope("child"), "subagent")

    def test_startup_during_copied_prefix_does_not_treat_later_history_as_live(self):
        records = fork_records()
        prefix = encode(records[:3])
        suffix = encode(records[3:])
        self.path.write_bytes(prefix + suffix[:11])
        self.monitor.start()
        self.read()
        self.assertEqual(self.events, [])
        with self.path.open("ab") as stream:
            stream.write(suffix[11:])
        self.read()
        self.assertEqual([e["event"] for e in self.events], ["prompt", "ended"])
        self.assertTrue(all(e["turn_id"] == "child-turn" for e in self.events))

    def test_no_boundary_legacy_fork_still_keeps_child_identity(self):
        records = fork_records()
        records[0]["payload"].pop("subagent_history_start_ordinal")
        self.feed(records)
        self.assertTrue(self.events)
        self.assertTrue(all(e["session_id"] == "child" for e in self.events))
        self.assertTrue(all(e["agent_scope"] == "subagent" for e in self.events))

    def test_unknown_header_is_not_promoted_by_copied_main_metadata(self):
        for owner in (
            metadata("child", "future-source"),
            metadata("", "vscode"),
            {"type": "session_meta", "payload": None},
        ):
            with self.subTest(owner=owner):
                self.monitor.close()
                self.events.clear()
                self.feed([owner, metadata("parent"), lifecycle("task_complete", "t")])
                self.assertEqual(self.events[-1]["agent_scope"], "unknown")
                self.assertNotEqual(self.events[-1]["session_id"], "parent")

    def test_invalid_boundaries_do_not_crash_or_hide_new_work(self):
        for boundary in (None, True, -1, "6", {}, 0):
            with self.subTest(boundary=boundary):
                self.monitor.close()
                self.events.clear()
                self.feed(
                    [
                        metadata("child", subagent_history_start_ordinal=boundary),
                        lifecycle("task_started", "t"),
                        record("response_item", type="message"),
                        lifecycle("task_complete", "t"),
                    ]
                )
                self.assertEqual([e["event"] for e in self.events], ["prompt", "ended"])

    def test_discarded_large_line_and_invalid_json_do_not_shift_ordinals(self):
        records = fork_records()
        data = (
            encode(records[:2]) + b"x" * 1500 + b"\n{bad json}\n" + encode(records[4:])
        )
        self.path.write_bytes(data)
        with patch("watched_kettle.integrations.codex_log.MAX_LOG_LINE_BYTES", 1024):
            for _ in range(10):
                self.read(records=2)
        self.assertEqual([e["event"] for e in self.events], ["prompt", "ended"])
        self.assertTrue(all(e["turn_id"] == "child-turn" for e in self.events))

    def test_file_replacement_and_truncation_reset_owner_and_turn_correlations(self):
        for replace_file in (False, True):
            with self.subTest(replace_file=replace_file):
                self.monitor.close()
                self.events.clear()
                records = fork_records()[:-1] + [
                    record(
                        "response_item",
                        type="function_call",
                        name="request_user_input",
                        call_id="old",
                    ),
                    record("response_item", type="message", padding="x" * 2000),
                ]
                self.path.write_bytes(encode(records))
                self.read()
                self.assertTrue(self.monitor._pending_user_calls[self.path])
                self.assertTrue(self.monitor._tool_turns)
                self.assertTrue(self.monitor._active_turns)
                self.monitor._recovery_confirmed.add(self.path)
                self.events.clear()
                data = encode([metadata("replacement", "exec")])
                if replace_file:
                    replacement = self.root / "replacement.tmp"
                    replacement.write_bytes(data + b" " * 5000)
                    replacement.replace(self.path)
                else:
                    self.path.write_bytes(data)
                self.read()
                self.assertEqual(self.monitor.session_scope("replacement"), "main")
                self.assertEqual(self.monitor.session_scope("child"), "unknown")
                self.assertFalse(self.monitor._active_turns)
                self.assertFalse(self.monitor._recovery_confirmed)
                self.assertFalse(self.monitor._tool_turns)
                self.assertFalse(self.monitor._pending_user_calls)
                self.assertFalse(self.monitor._last_heartbeats)
                self.assertFalse(self.monitor._history_starts)
                self.assertEqual(self.events, [])

    def test_replacement_between_registration_and_first_poll_uses_new_header(self):
        self.path.write_bytes(encode(fork_records()))
        self.monitor.start()
        replacement = self.root / "replacement.tmp"
        replacement.write_bytes(
            encode(
                [
                    metadata("replacement"),
                    lifecycle("task_started", "new"),
                    record("response_item", type="message", padding="x" * 5000),
                ]
            )
        )
        replacement.replace(self.path)
        self.read()
        self.assertEqual(self.events[-1]["session_id"], "replacement")
        self.assertEqual(self.events[-1]["event"], "prompt")

    def test_forget_and_close_release_lifecycle_identity(self):
        for cleanup in (lambda: self.monitor._forget(self.path), self.monitor.close):
            self.feed(fork_records())
            cleanup()
            self.assertFalse(self.monitor._metadata_seen)
            self.assertFalse(self.monitor._history_starts)
            self.assertFalse(self.monitor._next_ordinals)
            self.assertFalse(self.monitor._startup_offsets)
            self.assertFalse(self.monitor._session_ids)
            self.assertFalse(self.monitor._agent_scopes)

    def test_child_completion_preserves_parent_bubble_and_actual_done_is_once(self):
        projects = ProjectActivityService(wall_now=lambda: 1)
        notices = []
        agent = PetAgentController(lambda _: None, on_presentation=notices.append)
        self.addCleanup(agent.deleteLater)
        surface = SimpleNamespace(
            apply_agent_payload=agent.apply_payload, agent_controller=agent
        )
        activity = AgentActivityService(surface, projects=projects)
        server = CodexHookServer(
            "fork-test-" + uuid4().hex,
            spool_directory=self.root / "queue",
            managed_spool_directory=None,
            managed_hook_health_path=None,
        )
        self.addCleanup(server.close)
        server.attach_log_monitor(self.monitor)
        server.payload_received.connect(activity.observe)
        pet = QWidget()
        pet.always_on_top = False
        pet.setGeometry(800, 900, 100, 110)
        router = NotificationActionRouter(opener=lambda _: True)
        bubbles = ActionableBubbleController(
            pet, projects, NotificationService(), router
        )
        self.addCleanup(pet.close)
        self.addCleanup(bubbles.close)
        screen = patch(
            "watched_kettle.ui.actionable_bubbles.QApplication.screenAt",
            return_value=SimpleNamespace(
                availableGeometry=lambda: QRect(0, 0, 1920, 1080)
            ),
        )
        screen.start()
        self.addCleanup(screen.stop)
        pet.show()

        def parent_event(event, turn="parent-turn"):
            return dict(
                source="codex",
                session_id="parent",
                event=event,
                turn_id=turn,
                agent_scope="main",
            )

        activity.observe(parent_event("prompt"))
        projects.set_metadata(ThreadMetadata("parent", "p", "Project"), 0)
        row = bubbles.visible_windows[0].project_rows.rows["parent"]
        for child in ("child", "other-child"):
            self.feed(fork_records(child)[:-1], self.root / (child + ".jsonl"))
        for child in ("other-child", "child"):
            self.feed(fork_records(child)[-1:], self.root / (child + ".jsonl"))
        self.assertEqual(row.badge.text(), "작업 중")
        self.assertTrue(row.close_button.isHidden())
        self.assertFalse(projects.completions)
        self.assertFalse(projects.visible_completions)
        self.assertFalse(any(p.notice and p.notice.event == "done" for p in notices))
        self.assertEqual(agent.aggregate_state.session_id, "codex:parent")
        self.assertEqual(agent.desired_state, "running")

        server._deliver_payload(parent_event("done"), PIPE_TRANSPORT)
        self.feed(
            [metadata("parent"), lifecycle("task_complete", "parent-turn")],
            self.root / "parent.jsonl",
        )
        self.assertEqual(len(projects.completions), 1)
        self.assertEqual(row.badge.text(), "완료")
        self.assertEqual(
            sum(bool(p.notice and p.notice.event == "done") for p in notices), 1
        )
        activity.observe(parent_event("prompt", "next-turn"))
        self.assertEqual(row.badge.text(), "작업 중")
        self.assertTrue(row.close_button.isHidden())


if __name__ == "__main__":
    unittest.main()
