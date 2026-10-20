"""Explicit plan-mode metadata is scoped to the open Codex turn."""

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tests import test_bubble_state_regressions as helpers
from watched_kettle.integrations.codex_hooks import sanitize_pet_event
from watched_kettle.integrations.codex_log import (
    CodexLogMonitor,
    normalize_codex_log_record,
)
from watched_kettle.localization import get_translator, set_translator
from watched_kettle.localization.catalog import RESOURCE_ROOT
from watched_kettle.localization.packs import load_pack


class PlanModeInputTests(unittest.TestCase):
    def context(self, mode="plan", **extra):
        return normalize_codex_log_record(
            dict(
                type="turn_context",
                timestamp="2026-10-20T01:00:00Z",
                payload=dict(
                    turn_id="turn",
                    collaboration_mode=mode,
                    cwd="PRIVATE",
                    developer_instructions="PRIVATE",
                    **extra,
                ),
            ),
            "parent",
            agent_scope="main",
        )

    def test_only_explicit_mode_enum_crosses_the_privacy_boundary(self):
        for mode in ("plan", "default"):
            with self.subTest(mode=mode):
                event = self.context(
                    {"mode": mode, "settings": {"developer_instructions": "PRIVATE"}}
                )
                self.assertEqual(event["event"], "turn_mode")
                self.assertEqual(event["turn_id"], "turn")
                self.assertEqual(event["collaboration_mode"], mode)
                self.assertIn("collected_at", event)
                self.assertNotIn("PRIVATE", json.dumps(event))
                self.assertNotIn("settings", event)

    def test_missing_unknown_and_malformed_modes_are_not_guessed(self):
        for mode in (None, "plan", [], {"mode": "review"}, {"mode": ["plan"]}, {}):
            with self.subTest(mode=mode):
                self.assertIsNone(self.context(mode))
        event = normalize_codex_log_record(
            dict(
                type="response_item",
                payload=dict(
                    type="function_call", name="update_plan", call_id="plan-tool"
                ),
            ),
            "parent",
        )
        self.assertEqual(event["event"], "tool_start")
        self.assertNotIn("collaboration_mode", event)

    def test_mode_requires_codex_turn_identity_and_finite_record_time(self):
        event = self.context({"mode": "plan"})
        for overrides in (
            {"source": "claude_code"},
            {"turn_id": ""},
            {"turn_id": 42},
            {"collected_at": None},
            {"collected_at": True},
            {"collected_at": float("nan")},
            {"collected_at": float("inf")},
            {"collected_at": 10**400},
            {"collaboration_mode": {"mode": "plan"}},
        ):
            with self.subTest(overrides=overrides):
                self.assertIsNone(sanitize_pet_event({**event, **overrides}))


class PlanModeProjectionTests(unittest.TestCase):
    setUpClass = classmethod(helpers.BubbleStateRegressions.setUpClass.__func__)
    setUp = helpers.BubbleStateRegressions.setUp
    tearDown = helpers.BubbleStateRegressions.tearDown
    send = helpers.BubbleStateRegressions.send
    start = helpers.BubbleStateRegressions.start
    advance = helpers.BubbleStateRegressions.advance
    row = helpers.BubbleStateRegressions.row
    window = helpers.BubbleStateRegressions.window

    def mode(self, mode="plan", turn="1", thread="a", stamp=None):
        stamp = self.projects.wall_now() if stamp is None else stamp
        payload = normalize_codex_log_record(
            dict(
                type="turn_context",
                timestamp=datetime.fromtimestamp(stamp, timezone.utc).isoformat(),
                payload=dict(turn_id=turn, collaboration_mode={"mode": mode}),
            ),
            thread,
            agent_scope="main",
        )
        self.server._receive_jsonl_payload(payload)
        self.controller._render()
        self.app.processEvents()

    def test_plan_mode_survives_normal_tools_and_explicit_default_clears_it(self):
        self.start()
        self.mode()
        self.assertEqual(self.row().badge.text(), "계획 세우는 중")
        self.send("tool_start", event_id="read")
        self.send("tool_end", event_id="read")
        self.send("heartbeat")
        self.assertEqual(self.row().badge.text(), "계획 세우는 중")
        self.assertEqual(self.projects.cards[0].working, 1)
        self.assertEqual(self.projects.cards[0].waiting, 0)
        self.assertEqual(self.pet.agent_controller.aggregate_state.state, "running")
        self.mode("default")
        self.assertEqual(self.row().badge.text(), "작업 중")

    def test_next_turn_defaults_to_working_and_rejects_old_turn_mode(self):
        self.start()
        self.mode()
        self.send("prompt", turn="2")
        self.assertEqual(self.row().badge.text(), "작업 중")
        self.assertFalse(self.projects.activities["a"].planning)
        self.mode(turn="1")
        self.assertEqual(self.row().badge.text(), "작업 중")
        self.mode("default", turn="2")
        self.assertEqual(self.row().badge.text(), "작업 중")

    def test_older_same_turn_mode_cannot_override_newer_identical_metadata(self):
        self.start()
        base = self.projects.wall_now()
        self.mode(stamp=base + 1)
        self.mode(stamp=base + 3)
        self.mode("default", stamp=base + 2)
        self.assertEqual(self.row().badge.text(), "계획 세우는 중")
        self.mode("default", stamp=base + 4)
        self.assertEqual(self.row().badge.text(), "작업 중")

    def test_same_turn_mode_can_precede_a_later_arriving_activity_hook(self):
        self.start()
        recorded = self.projects._collection_started_at + 0.000001
        self.projects.activities["a"].started_wall_at = recorded + 1
        self.mode(stamp=recorded)
        self.assertEqual(self.row().badge.text(), "계획 세우는 중")

    def test_mode_cannot_create_activity_or_confirm_liveness(self):
        self.mode()
        self.assertFalse(self.projects.activities)
        self.assertFalse(self.controller.visible_windows)
        self.start()
        self.advance(61)
        item = self.projects.activities["a"]
        before = (
            item.last_seen_at,
            item.last_confirmed_at,
            item.revision,
            item.uncertain,
        )
        self.mode()
        self.assertEqual(
            (item.last_seen_at, item.last_confirmed_at, item.revision, item.uncertain),
            before,
        )
        self.assertEqual(self.row().badge.text(), "응답 없음")
        self.assertEqual(self.pet.agent_controller.current_presentation.active_count, 0)

    def test_mode_cannot_restore_a_dismissed_uncertain_row(self):
        self.start()
        self.advance(61)
        self.row().close_button.click()
        self.mode()
        self.assertFalse(self.controller.visible_windows)
        self.assertTrue(self.projects.activities["a"].hidden_uncertain)

    def test_terminal_events_clear_mode_and_late_context_cannot_restore_it(self):
        for terminal in ("done", "ended", "cancelled", "failed"):
            with self.subTest(terminal=terminal):
                self.projects.reset()
                self.start(turn=terminal)
                self.mode(turn=terminal)
                self.send(terminal, turn=terminal)
                self.mode(turn=terminal)
                self.assertFalse(self.projects.activities["a"].planning)
                self.assertNotEqual(self.row().badge.text(), "계획 세우는 중")

    def test_child_plan_does_not_change_default_parent_mode(self):
        self.start()
        self.send(thread="child", agent_scope="subagent", parent_session_id="a")
        self.mode(thread="child")
        self.assertTrue(self.projects.activities["child"].planning)
        self.assertEqual(self.row().badge.text(), "작업 중")
        self.mode()
        self.assertEqual(self.row().badge.text(), "계획 세우는 중")

    def test_attention_permission_and_tool_waits_precede_plan_label(self):
        self.start()
        self.mode()
        self.send("waiting", event_id="question")
        self.assertEqual(self.row().badge.text(), "확인 필요")
        self.send("tool_end", event_id="question")
        self.send("permission", event_id="approval")
        self.assertEqual(self.row().badge.text(), "권한 처리 중")
        self.send("permission_resolved", event_id="approval")
        for kind, expected in (
            ("time_wait", "잠시 대기"),
            ("subagent_wait", "서브에이전트 대기"),
        ):
            self.send("tool_start", event_id=kind, tool_kind=kind)
            self.assertEqual(self.row().badge.text(), expected)
            self.send("tool_end", event_id=kind)
            self.assertEqual(self.row().badge.text(), "계획 세우는 중")

    def test_english_pack_translates_planning(self):
        self.start()
        self.mode()
        original = get_translator()
        self.addCleanup(set_translator, original)
        set_translator(load_pack(RESOURCE_ROOT / "en", official=True).translator())
        self.controller._render()
        self.assertEqual(self.row().badge.text(), "Planning")

    def test_real_collector_isolates_plan_context_from_the_next_normal_turn(self):
        root = Path(self.directory.name) / "sessions"
        root.mkdir()
        path = root / "rollout-11111111-1111-4111-8111-111111111111.jsonl"
        monitor = CodexLogMonitor(root)
        self.addCleanup(monitor.close)
        self.server.log_monitor = None
        self.server.attach_log_monitor(monitor)
        monitor.start()

        def record(kind, **payload):
            with path.open("a", encoding="utf-8") as stream:
                stream.write(
                    json.dumps(
                        dict(
                            type=kind,
                            timestamp=datetime.now(timezone.utc).isoformat(),
                            payload=payload,
                        )
                    )
                    + "\n"
                )
            monitor.poll_now()
            self.controller._render()
            self.app.processEvents()

        record("session_meta", id="a", source="cli")
        record("turn_context", turn_id="1", collaboration_mode={"mode": "plan"})
        self.assertFalse(self.projects.activities)
        record("event_msg", type="task_started", turn_id="1")
        self.assertEqual(self.row().badge.text(), "작업 중")
        record("turn_context", turn_id="1", collaboration_mode={"mode": "plan"})
        self.assertEqual(self.row().badge.text(), "계획 세우는 중")
        record("response_item", type="reasoning")
        self.assertEqual(self.row().badge.text(), "계획 세우는 중")
        record("event_msg", type="task_complete", turn_id="1")
        self.assertEqual(self.row().badge.text(), "종료됨")
        record("event_msg", type="task_started", turn_id="2")
        record("turn_context", turn_id="1", collaboration_mode={"mode": "plan"})
        self.assertEqual(self.row().badge.text(), "작업 중")
        record("turn_context", turn_id="2", collaboration_mode={"mode": "default"})
        record(
            "response_item",
            type="function_call",
            name="update_plan",
            call_id="plan-tool",
        )
        self.assertEqual(self.row().badge.text(), "작업 중")
