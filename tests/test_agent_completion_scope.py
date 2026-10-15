"""Regression coverage for completion notifications during multi-agent work."""

import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from watched_kettle.integrations.codex_bridge import run_hook_bridge
from watched_kettle.integrations.codex_hooks import (
    normalize_codex_hook,
    sanitize_pet_event,
)
from watched_kettle.integrations.codex_ipc import (
    CodexHookServer,
    JSONL_TRANSPORT,
    PIPE_TRANSPORT,
)
from watched_kettle.integrations.codex_log import CodexLogMonitor
from watched_kettle.integrations.codex_spool import (
    drain_spooled_events,
    spool_pet_event,
)
from watched_kettle.state.controller import PetAgentController
from watched_kettle.pet.window import DesktopPet
from tests.test_pet_preferences import FakeSettings


class AgentCompletionScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        clock_patch = patch(
            "watched_kettle.integrations.codex_log.monotonic", return_value=0.0
        )
        clock_patch.start()
        self.addCleanup(clock_patch.stop)
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.monitor = CodexLogMonitor(self.root / "sessions")
        self.monitor.sessions_root.mkdir()
        self.server = CodexHookServer(
            f"scope-test-{uuid4().hex}",
            spool_directory=self.root / "queue",
            managed_spool_directory=None,
            managed_hook_health_path=None,
        )
        self.server.attach_log_monitor(self.monitor)
        self.states = []
        self.presentations = []
        self.controller = PetAgentController(
            self.states.append,
            on_presentation=self.presentations.append,
        )
        self.server.payload_received.connect(self.controller.apply_payload)
        self.addCleanup(self.controller.deleteLater)
        self.addCleanup(self.server.close)
        self.addCleanup(self.monitor.close)

    def hook(self, name, session_id="main", **fields):
        payload = normalize_codex_hook(
            {
                "hook_event_name": name,
                "session_id": session_id,
                **fields,
            }
        )
        self.server._deliver_payload(payload, PIPE_TRANSPORT)

    def rollout(self, source, session_id="child", existing=False):
        path = self.monitor.sessions_root / f"rollout-{session_id}.jsonl"
        self.append(
            path,
            "session_meta",
            {
                "id": session_id,
                "source": source,
                "instructions": "PRIVATE INSTRUCTIONS MUST NEVER BE EMITTED",
            },
        )
        if existing:
            self.append(path, "event_msg", {"type": "task_complete"})
            self.monitor.start()
        return path

    @staticmethod
    def append(path, kind, payload):
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"type": kind, "payload": payload}) + "\n")

    def test_child_hook_completion_cleans_up_without_interrupting_parent(self):
        self.hook("UserPromptSubmit")
        self.hook("SubagentStart", agent_id="child")
        self.assertIsNone(self.presentations[-1].notice)
        self.hook("SubagentStop", agent_id="child")
        self.assertEqual(self.controller.aggregate_state.session_id, "codex:main")
        self.assertEqual(self.controller.desired_state, "running")
        self.assertIsNone(self.presentations[-1].notice)
        self.assertEqual(self.presentations[-1].active_count, 1)
        self.assertNotIn("jumping", self.states)

    def test_guardian_new_and_existing_logs_do_not_announce_completion(self):
        for existing in (False, True):
            with self.subTest(existing=existing):
                self.controller.clear()
                self.hook("UserPromptSubmit", session_id=f"parent-{existing}")
                path = self.rollout(
                    {"subagent": {"other": "guardian"}},
                    session_id=f"guardian-{existing}",
                    existing=existing,
                )
                before = len(self.presentations)
                if existing:
                    self.monitor.poll_now()
                    self.assertEqual(len(self.presentations), before)
                for number in range(3):
                    for kind in ("task_started", "task_complete"):
                        self.append(
                            path, "event_msg", {"type": kind, "turn_id": str(number)}
                        )
                    self.monitor.poll_now()
                    self.assertIsNone(self.presentations[-1].notice)
                    self.assertEqual(self.presentations[-1].active_count, 1)
                    self.assertEqual(self.controller.desired_state, "running")
                self.assertEqual(
                    self.monitor.session_scope(f"guardian-{existing}"), "internal"
                )
                self.assertNotIn("jumping", self.states)

    def test_hook_start_and_log_completion_use_same_child_identity(self):
        self.hook("UserPromptSubmit")
        self.hook("SubagentStart", agent_id="child")
        path = self.rollout(
            {"subagent": {"thread_spawn": {"parent_thread_id": "main"}}}
        )
        self.append(path, "event_msg", {"type": "task_complete"})
        self.monitor.poll_now()
        self.assertEqual(self.presentations[-1].active_count, 1)
        self.assertIsNone(self.presentations[-1].notice)
        self.assertEqual(self.controller.aggregate_state.session_id, "codex:main")

    def test_raw_subagent_aliases_have_the_same_quiet_cleanup(self):
        self.controller.apply_payload(
            {"source": "codex", "event": "prompt", "session_id": "main"}
        )
        for event in ("SubagentStart", "subagent_stop"):
            self.controller.apply_payload(
                {
                    "source": "codex",
                    "event": event,
                    "session_id": "main",
                    "agent_id": "child",
                }
            )
        self.assertEqual(self.presentations[-1].active_count, 1)
        self.assertIsNone(self.presentations[-1].notice)
        self.assertEqual(self.controller.desired_state, "running")

    def test_main_completion_announces_while_another_conversation_runs(self):
        self.hook("UserPromptSubmit", session_id="first")
        self.hook("UserPromptSubmit", session_id="second")
        self.hook("Stop", session_id="first")
        self.assertEqual(self.presentations[-1].notice.event, "done")
        self.assertEqual(self.controller.desired_state, "jumping")
        self.assertEqual(self.presentations[-1].active_count, 1)
        self.controller.finish_transient()
        self.assertEqual(self.controller.desired_state, "running")
        self.assertEqual(self.controller.aggregate_state.session_id, "codex:second")

    def test_main_log_completion_announces_after_restart_without_replay(self):
        for source in ("vscode", "cli", "exec"):
            with self.subTest(source=source):
                self.monitor.close()
                path = self.rollout(source, session_id=source, existing=True)
                before = len(self.presentations)
                self.monitor.poll_now()
                self.assertEqual(len(self.presentations), before)
                self.append(
                    path, "event_msg", {"type": "task_complete", "turn_id": "new"}
                )
                self.monitor.poll_now()
                self.assertEqual(self.presentations[-1].notice.event, "done")

    def test_unknown_completion_is_quiet_but_does_not_hide_known_main_completion(self):
        self.hook("UserPromptSubmit")
        self.server._deliver_payload(
            {
                "source": "codex",
                "event": "done",
                "session_id": "main",
                "turn_id": "turn-1",
                "agent_scope": "unknown",
            },
            JSONL_TRANSPORT,
        )
        self.assertIsNone(self.presentations[-1].notice)
        self.assertNotIn("jumping", self.states)
        self.hook("Stop", turn_id="turn-1")
        self.assertEqual(self.presentations[-1].notice.event, "done")

    def test_known_guardian_metadata_overrides_legacy_hook_completion(self):
        self.rollout({"subagent": {"other": "guardian"}}, existing=True)
        self.hook("UserPromptSubmit")
        self.hook("Stop", session_id="child")
        self.assertIsNone(self.presentations[-1].notice)
        self.assertEqual(self.controller.desired_state, "running")

    def test_waiting_notice_survives_other_child_completion_and_clears_on_own_end(self):
        self.hook("UserPromptSubmit")
        self.rollout(
            {"subagent": {"thread_spawn": {}}},
            session_id="waiting-child",
            existing=True,
        )
        self.hook(
            "PermissionRequest", approval_actor="user", session_id="waiting-child"
        )
        self.assertEqual(self.presentations[-1].notice.event, "waiting")
        self.hook("SubagentStop", agent_id="other-child")
        self.assertEqual(self.controller.desired_state, "waiting")
        self.assertEqual(
            self.presentations[-1].persistent_notice.session_id, "codex:waiting-child"
        )
        self.hook("SubagentStop", agent_id="waiting-child")
        self.assertIsNone(self.presentations[-1].persistent_notice)
        self.assertEqual(self.controller.desired_state, "running")

    def test_duplicate_main_completion_from_hook_and_log_announces_once(self):
        for first, second in (
            (PIPE_TRANSPORT, JSONL_TRANSPORT),
            (JSONL_TRANSPORT, PIPE_TRANSPORT),
        ):
            with self.subTest(first=first):
                session_id = uuid4().hex
                event = normalize_codex_hook(
                    {"hook_event_name": "Stop", "session_id": session_id}
                )
                before = len(self.presentations)
                self.assertTrue(self.server._deliver_payload(event, first))
                self.assertFalse(self.server._deliver_payload(event, second))
                self.assertEqual(len(self.presentations), before + 1)
                self.assertEqual(self.presentations[-1].notice.event, "done")

    def test_background_completion_does_not_cancel_other_completion_animation(self):
        self.hook("Stop")
        self.hook("SubagentStop", agent_id="child")
        self.assertEqual(self.controller.desired_state, "jumping")
        self.assertTrue(self.controller.transient_timer.isActive())
        self.assertIsNone(self.presentations[-1].notice)

    def test_partial_existing_metadata_is_classified_when_write_finishes(self):
        path = self.monitor.sessions_root / "rollout-child.jsonl"
        record = (
            json.dumps(
                {
                    "type": "session_meta",
                    "payload": {
                        "id": "child",
                        "source": {"subagent": {"other": "guardian"}},
                    },
                }
            )
            + "\n"
        )
        path.write_text(record[:20], encoding="utf-8")
        self.monitor.start()
        with path.open("a", encoding="utf-8") as stream:
            stream.write(record[20:])
        self.append(path, "event_msg", {"type": "task_complete"})
        self.monitor.poll_now()
        self.assertEqual(self.monitor.session_scope("child"), "internal")
        self.assertIsNone(self.presentations[-1].notice)

    def test_unknown_or_malformed_metadata_does_not_assert_main_completion(self):
        for source in (None, "future-source", {"future": "source"}):
            path = self.rollout(source, session_id=uuid4().hex)
            self.append(path, "event_msg", {"type": "task_complete"})
            before = len(self.presentations)
            for _ in range(20):
                self.monitor.poll_now()
                if len(self.presentations) > before:
                    break
            self.assertGreater(len(self.presentations), before)
            self.assertIsNone(self.presentations[-1].notice)
        self.assertNotIn("jumping", self.states)

    def test_scope_survives_bridge_queue_and_sanitization_without_private_content(self):
        raw = {
            "hook_event_name": "SubagentStop",
            "session_id": "main",
            "agent_id": "child",
            "last_assistant_message": "PRIVATE OUTPUT",
        }
        queue = self.root / "queue"
        run_hook_bridge(
            io.BytesIO(json.dumps(raw).encode()),
            sender=lambda _: False,
            fallback=lambda event: spool_pet_event(event, queue),
        )
        events = list(drain_spooled_events(queue))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["agent_scope"], "subagent")
        self.assertNotIn("PRIVATE", json.dumps(events))
        self.assertEqual(sanitize_pet_event(events[0]), events[0])
        self.assertEqual(
            sanitize_pet_event({**events[0], "agent_scope": {"bad": "value"}})[
                "agent_scope"
            ],
            "unknown",
        )

    def test_qt_bubble_is_hidden_for_child_end_and_visible_for_main_end(self):
        pet = DesktopPet(Path("pets/mori-bot"), settings=FakeSettings())
        self.addCleanup(pet.deleteLater)
        self.addCleanup(pet.close)
        self.server.payload_received.connect(pet.apply_agent_payload)
        pet.set_bubbles_enabled(True, persist=False)
        pet.show()
        self.app.processEvents()
        self.hook("UserPromptSubmit")
        pet.bubble_controller.clear_notices()
        self.hook("SubagentStart", agent_id="child")
        self.hook("SubagentStop", agent_id="child")
        self.assertEqual(pet.bubble_controller.visible_windows, ())
        self.assertEqual(pet.current_state, "running")
        self.hook("Stop")
        self.assertEqual(pet.bubble_controller.current_notice.event, "done")
        self.assertTrue(pet.bubble_controller.window.isVisible())
        self.assertEqual(pet.current_state, "jumping")


if __name__ == "__main__":
    unittest.main()
