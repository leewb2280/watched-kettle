"""Explicit time waits keep correlated lifetimes and existing state priority."""

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tests import test_bubble_state_regressions as helpers
from tests import test_codex_subagent_wait as agent_waits
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


class TimeWaitInputTests(unittest.TestCase):
    call = agent_waits.SubagentWaitInputTests.call

    def test_explicit_sleep_and_wait_shapes_are_classified_without_retaining_inputs(
        self,
    ):
        for name, arguments in (
            ("sleep", '{"seconds":30,"note":"PRIVATE"}'),
            ("clock.sleep", '{"duration_ms":30000}'),
            ("functions.sleep", None),
            ("wait", '{"seconds":30}'),
            ("wait", {"duration_seconds": 30}),
            ("functions.wait", {"duration_ms": 30000}),
            ("functions.wait", '{"cell_id":"PRIVATE","yield_time_ms":30000}'),
        ):
            with self.subTest(name=name, arguments=arguments):
                event = self.call(name, arguments)
                self.assertEqual(event["tool_kind"], "time_wait")
                self.assertEqual(event["event"], "tool_start")
                self.assertNotIn("PRIVATE", json.dumps(event))
                self.assertNotIn("arguments", event)
                self.assertNotIn("duration_ms", event)

    def test_ordinary_shell_and_invalid_waits_do_not_become_time_waits(self):
        for name, arguments in (
            ("exec_command", '{"cmd":"sleep 30"}'),
            ("external.sleep", '{"seconds":30}'),
            ("wait", '{"ids":[],"seconds":30}'),
            ("wait", '{"cell_id":42,"seconds":30}'),
            ("wait", '{"cell_id":"","seconds":30}'),
            ("wait", '{"seconds":true}'),
            ("wait", '{"seconds":0}'),
            ("wait", '{"seconds":-30}'),
            ("wait", {"seconds": float("inf")}),
            ("wait", {"seconds": float("nan")}),
            ("wait", {"seconds": 10**400}),
            ("wait", "not-json"),
            ("wait", " " * 16_385),
            (None, None),
        ):
            with self.subTest(name=name, arguments=arguments):
                self.assertNotIn("tool_kind", self.call(name, arguments))
        self.assertEqual(
            self.call("wait", '{"ids":["child"],"seconds":30}')["tool_kind"],
            "subagent_wait",
        )

    def test_hooks_and_sanitizer_allow_only_identified_codex_wait_starts(self):
        event = normalize_codex_hook(
            dict(
                hook_event_name="PreToolUse",
                session_id="parent",
                tool_use_id="timer",
                tool_name="clock.sleep",
                tool_input={"duration_ms": 30000},
            )
        )
        self.assertEqual(event["tool_kind"], "time_wait")
        for overrides in (
            {"event_id": ""},
            {"source": "claude_code"},
            {"event": "tool_end"},
            {"tool_kind": {"PRIVATE": "time_wait"}},
        ):
            with self.subTest(overrides=overrides):
                self.assertNotIn(
                    "tool_kind", sanitize_pet_event({**event, **overrides})
                )


class TimeWaitProjectionTests(unittest.TestCase):
    setUpClass = classmethod(helpers.BubbleStateRegressions.setUpClass.__func__)
    setUp = helpers.BubbleStateRegressions.setUp
    tearDown = helpers.BubbleStateRegressions.tearDown
    send = helpers.BubbleStateRegressions.send
    start = helpers.BubbleStateRegressions.start
    advance = helpers.BubbleStateRegressions.advance
    row = helpers.BubbleStateRegressions.row
    window = helpers.BubbleStateRegressions.window

    def time_wait(self, call="timer", turn="1"):
        payload = normalize_codex_log_record(
            dict(
                type="response_item",
                payload=dict(
                    type="function_call",
                    name="clock.sleep",
                    arguments='{"duration_ms":30000}',
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

    def test_thirty_second_wait_clears_on_return_and_not_elapsed_time(self):
        self.start()
        self.time_wait()
        self.advance(30)
        self.assertEqual(self.row().badge.text(), "잠시 대기")
        self.assertEqual(self.projects.cards[0].working, 1)
        self.assertEqual(self.projects.cards[0].waiting, 0)
        self.assertEqual(self.pet.agent_controller.aggregate_state.state, "running")
        self.assertIsNone(
            self.pet.agent_controller.current_presentation.persistent_notice
        )
        self.send("tool_end", event_id="timer")
        self.assertEqual(self.row().badge.text(), "작업 중")
        self.assertFalse(self.projects.activities["a"].time_waits)
        self.send("done")
        self.assertEqual(self.row().badge.text(), "완료")

    def test_early_return_clears_immediately_without_waiting_for_thirty_seconds(self):
        self.start()
        self.time_wait()
        self.advance(1)
        self.send("tool_end", event_id="timer")
        self.assertEqual(self.row().badge.text(), "작업 중")
        self.advance(29)
        self.assertEqual(self.row().badge.text(), "작업 중")

    def test_only_matching_returns_clear_each_wait_including_failed_tools(self):
        self.start()
        self.send("tool_start", event_id="timer")
        self.time_wait()
        self.time_wait("second")
        self.send("tool_start", event_id="file-read")
        self.send("tool_end", event_id="file-read")
        self.send("heartbeat")
        self.assertEqual(self.row().badge.text(), "잠시 대기")
        self.send("tool_end", event_id="timer")
        self.assertEqual(self.row().badge.text(), "잠시 대기")
        self.send("tool_failed", event_id="second")
        self.assertEqual(self.row().badge.text(), "작업 중")

    def test_terminal_events_clear_time_waits(self):
        for terminal in ("done", "ended", "cancelled", "failed"):
            with self.subTest(terminal=terminal):
                self.projects.reset()
                self.start(turn=terminal)
                self.time_wait(call=terminal, turn=terminal)
                self.send(terminal, turn=terminal)
                self.assertFalse(self.projects.activities["a"].time_waits)
                self.assertNotEqual(self.row().badge.text(), "잠시 대기")

    def test_old_turn_return_cannot_clear_new_wait(self):
        self.start()
        self.time_wait()
        self.send("prompt", turn="2")
        self.assertEqual(self.row().badge.text(), "작업 중")
        self.time_wait("new-timer", turn="2")
        self.send("tool_end", event_id="timer", turn="1")
        self.assertEqual(self.row().badge.text(), "잠시 대기")
        self.send("tool_end", event_id="new-timer", turn="2")
        self.assertEqual(self.row().badge.text(), "작업 중")

    def test_user_and_agent_waits_keep_priority_and_parent_wait_survives_child_selection(
        self,
    ):
        self.start()
        self.time_wait()
        self.advance(1)
        self.send(thread="child", agent_scope="subagent", parent_session_id="a")
        self.assertEqual(self.row().badge.text(), "잠시 대기")
        self.send("waiting", event_id="question")
        self.assertEqual(self.row().badge.text(), "확인 필요")
        self.send("tool_end", event_id="question")
        self.send("tool_start", event_id="agent", tool_kind="subagent_wait")
        self.assertEqual(self.row().badge.text(), "서브에이전트 대기")
        self.send("tool_end", event_id="agent")
        self.assertEqual(self.row().badge.text(), "잠시 대기")

    def test_uncertainty_policy_is_preserved_until_fresh_evidence(self):
        self.start()
        self.time_wait()
        self.advance(181)
        self.assertEqual(self.row().badge.text(), "응답 없음")
        self.send("heartbeat")
        self.assertEqual(self.row().badge.text(), "잠시 대기")
        self.send("tool_end", event_id="timer")
        self.assertEqual(self.row().badge.text(), "작업 중")

    def test_english_label_and_malformed_service_kind(self):
        self.start()
        self.projects.observe(
            dict(
                source="codex",
                event="tool_start",
                session_id="a",
                turn_id="1",
                event_id="bad",
                tool_kind=["time_wait"],
            )
        )
        self.assertEqual(self.row().badge.text(), "작업 중")
        self.time_wait()
        original = get_translator()
        self.addCleanup(set_translator, original)
        set_translator(load_pack(RESOURCE_ROOT / "en", official=True).translator())
        self.controller._render()
        self.assertEqual(self.row().badge.text(), "Waiting briefly")

    def test_real_rollout_collector_releases_sleep_and_cell_wait_outputs(self):
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
        record("event_msg", type="task_started", turn_id="1")
        for kind, name, arguments in (
            ("function_call", "clock.sleep", '{"duration_ms":30000}'),
            ("custom_tool_call", "functions.wait", '{"cell_id":"exec-cell"}'),
        ):
            with self.subTest(name=name):
                record(
                    "response_item",
                    type=kind,
                    name=name,
                    arguments=arguments,
                    call_id=kind,
                )
                self.assertEqual(self.row().badge.text(), "잠시 대기")
                record("response_item", type=kind + "_output", call_id=kind)
                self.assertEqual(self.row().badge.text(), "작업 중")
