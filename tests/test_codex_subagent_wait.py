"""Agent-wait classification, correlated lifetime and actual Qt parent rows."""

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tests import test_bubble_state_regressions as helpers
from watched_kettle.integrations.codex_hooks import (
    normalize_codex_hook,
    sanitize_pet_event,
)
from watched_kettle.integrations.codex_log import (
    CodexLogMonitor,
    normalize_codex_log_record,
)
from watched_kettle.localization import get_translator, set_translator
from watched_kettle.localization.catalog import RESOURCE_ROOT
from watched_kettle.localization.packs import load_pack


class SubagentWaitInputTests(unittest.TestCase):
    def call(self, name, arguments=None, **extra):
        return normalize_codex_log_record(
            dict(
                type="response_item",
                payload=dict(
                    type="function_call",
                    name=name,
                    arguments=arguments,
                    call_id="wait-call",
                    **extra,
                ),
            ),
            "parent",
        )

    def test_only_explicit_agent_wait_tools_are_classified_without_retaining_input(
        self,
    ):
        for name, arguments in (
            ("wait_agent", None),
            ("collaboration.wait_agent", "PRIVATE"),
            ("functions.wait_agent", None),
            ("wait", '{"ids":["PRIVATE"]}'),
            ("functions.wait", {"ids": ["PRIVATE"]}),
        ):
            with self.subTest(name=name):
                event = self.call(name, arguments)
                self.assertEqual(event["event"], "tool_start")
                self.assertEqual(event["tool_kind"], "subagent_wait")
                self.assertNotIn("PRIVATE", json.dumps(event))
                self.assertNotIn("arguments", event)
                self.assertNotIn("name", event)

    def test_cell_time_normal_and_malformed_waits_are_not_agent_waits(self):
        for name, arguments in (
            ("functions.wait", '{"cell_id":"exec-cell"}'),
            ("wait", '{"ids":[]}'),
            ("wait", '{"ids":[42]}'),
            ("wait", '{"ids":[""]}'),
            ("wait", "invalid"),
            ("wait", " " * 16_385),
            ("clock.sleep", None),
            ("exec_command", None),
            ("external.wait_agent", None),
            ({}, None),
        ):
            with self.subTest(name=name):
                # Stage 3 classifies dedicated time/cell waits separately.
                expected = (
                    "time_wait" if name in ("functions.wait", "clock.sleep") else None
                )
                self.assertEqual(self.call(name, arguments).get("tool_kind"), expected)

    def test_hook_classification_and_allowlist_preserve_only_identified_codex_starts(
        self,
    ):
        event = normalize_codex_hook(
            dict(
                hook_event_name="PreToolUse",
                session_id="parent",
                tool_use_id="wait-call",
                tool_name="wait",
                tool_input={"ids": ["PRIVATE"]},
            )
        )
        self.assertEqual(event["tool_kind"], "subagent_wait")
        self.assertNotIn("PRIVATE", json.dumps(event))
        for overrides in (
            {"event_id": ""},
            {"source": "claude_code"},
            {"event": "tool_end"},
            {"tool_kind": "PRIVATE"},
            {"tool_kind": ["subagent_wait"]},
        ):
            with self.subTest(overrides=overrides):
                self.assertNotIn(
                    "tool_kind", sanitize_pet_event({**event, **overrides})
                )


class SubagentWaitProjectionTests(unittest.TestCase):
    setUpClass = classmethod(helpers.BubbleStateRegressions.setUpClass.__func__)
    setUp = helpers.BubbleStateRegressions.setUp
    tearDown = helpers.BubbleStateRegressions.tearDown
    send = helpers.BubbleStateRegressions.send
    start = helpers.BubbleStateRegressions.start
    advance = helpers.BubbleStateRegressions.advance
    row = helpers.BubbleStateRegressions.row
    window = helpers.BubbleStateRegressions.window

    def wait(self, call="wait-call", turn="1"):
        payload = normalize_codex_log_record(
            dict(
                type="response_item",
                payload=dict(
                    type="function_call",
                    name="collaboration.wait_agent",
                    call_id=call,
                    turn_id=turn,
                ),
            ),
            "a",
            agent_scope="main",
        )
        self.server._receive_jsonl_payload(payload)
        self.controller._render()
        self.app.processEvents()

    def child(self):
        self.send(thread="child", agent_scope="subagent", parent_session_id="a")

    def test_rollout_collector_delivers_wait_and_correlates_its_output(self):
        root = Path(self.directory.name) / "sessions"
        root.mkdir()
        path = root / "rollout-11111111-1111-4111-8111-111111111111.jsonl"
        monitor = CodexLogMonitor(root)
        self.addCleanup(monitor.close)
        self.server.log_monitor = None  # Replace the helper's scope-only stub.
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
        record("event_msg", type="task_started", turn_id="1")
        record(
            "response_item",
            type="function_call",
            name="wait",
            arguments='{"ids":["child"]}',
            call_id="wait-call",
        )
        self.assertEqual(self.row().badge.text(), "서브에이전트 대기")
        record("response_item", type="function_call_output", call_id="other")
        self.assertEqual(self.row().badge.text(), "서브에이전트 대기")
        record("response_item", type="function_call_output", call_id="wait-call")
        self.assertEqual(self.row().badge.text(), "작업 중")

    def test_child_existence_does_not_imply_parent_is_waiting(self):
        self.start()
        self.child()
        self.assertEqual(self.row().badge.text(), "작업 중")
        self.assertFalse(self.projects.cards[0].rows[0].subagent_waiting)

    def test_active_child_keeps_explicit_parent_wait_visible_beyond_parent_timeout(
        self,
    ):
        self.start()
        self.child()
        self.wait()
        for _ in range(5):
            self.advance(50)
            self.send("heartbeat", thread="child", agent_scope="subagent")
            self.assertEqual(self.row().badge.text(), "서브에이전트 대기")
            self.assertFalse(self.projects.cards[0].rows[0].uncertain)
            self.assertEqual(self.projects.cards[0].working, 1)
            self.assertEqual(self.projects.cards[0].waiting, 0)
        self.send("done", thread="child", agent_scope="subagent")
        self.assertEqual(self.projects.activities["a"].subagent_waits, {"wait-call"})
        self.send("tool_end", event_id="wait-call")
        self.assertEqual(self.row().badge.text(), "작업 중")

    def test_all_silent_members_become_uncertain_and_fresh_child_restores_wait_label(
        self,
    ):
        self.start()
        self.child()
        self.wait()
        self.advance(181)
        self.assertEqual(self.row().badge.text(), "응답 없음")
        self.send("heartbeat", thread="child", agent_scope="subagent")
        self.assertEqual(self.row().badge.text(), "서브에이전트 대기")

    def test_log_enriches_hook_and_only_matching_returns_clear_each_wait(self):
        self.start()
        self.send("tool_start", event_id="wait-call")
        self.wait()
        self.wait("other-wait")
        self.assertEqual(self.row().badge.text(), "서브에이전트 대기")
        self.send("tool_start", event_id="file-read")
        self.send("tool_end", event_id="file-read")
        self.send("tool_end", event_id="wait-call")
        self.assertEqual(self.row().badge.text(), "서브에이전트 대기")
        self.send("tool_failed", event_id="other-wait")
        self.assertEqual(self.row().badge.text(), "작업 중")
        self.assertFalse(self.projects.activities["a"].subagent_waits)

    def test_terminal_events_clear_waits(self):
        for terminal in ("done", "ended", "cancelled", "failed"):
            with self.subTest(terminal=terminal):
                self.projects.reset()
                self.start(turn=terminal)
                self.wait(call=terminal, turn=terminal)
                self.send(terminal, turn=terminal)
                self.assertFalse(self.projects.activities["a"].subagent_waits)
                self.assertNotEqual(self.row().badge.text(), "서브에이전트 대기")

    def test_old_turn_return_cannot_clear_new_turn_wait(self):
        self.start()
        self.wait()
        self.send("prompt", turn="2")
        self.assertEqual(self.row().badge.text(), "작업 중")
        self.wait("new-wait", turn="2")
        self.send("tool_end", event_id="wait-call", turn="1")
        self.assertEqual(self.row().badge.text(), "서브에이전트 대기")
        self.send("tool_end", event_id="new-wait", turn="2")
        self.assertEqual(self.row().badge.text(), "작업 중")

    def test_user_attention_precedes_agent_wait_and_english_pack_translates_it(self):
        self.start()
        self.wait()
        self.send("waiting", event_id="question")
        self.assertEqual(self.row().badge.text(), "확인 필요")
        self.send("tool_end", event_id="question")
        original = get_translator()
        self.addCleanup(set_translator, original)
        set_translator(load_pack(RESOURCE_ROOT / "en", official=True).translator())
        self.controller._render()
        self.assertEqual(self.row().badge.text(), "Waiting for subagents")
