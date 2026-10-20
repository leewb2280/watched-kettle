"""Confirmed quota failures use structured times and cannot revive via children."""

import json
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tests import test_bubble_state_regressions as helpers
from watched_kettle.integrations.codex_hooks import sanitize_pet_event
from watched_kettle.integrations.codex_log import (
    CodexLogMonitor,
    normalize_codex_log_record,
)
from watched_kettle.features.project_activity.service import resume_time_text
from watched_kettle.state.codex_activity import CodexTurnOutcome
from watched_kettle.state.event_names import limit_resume_at
from watched_kettle.localization import get_translator, set_translator
from watched_kettle.localization.catalog import RESOURCE_ROOT
from watched_kettle.localization.packs import load_pack


class UsageLimitInputTests(unittest.TestCase):
    def test_resume_time_is_bounded_numeric_metadata_not_error_prose(self):
        stamp = datetime(2026, 10, 20, 6, 20, tzinfo=timezone.utc).timestamp()
        event = normalize_codex_log_record(
            dict(
                type="event_msg",
                payload=dict(
                    type="turn_aborted",
                    turn_id="t",
                    error=dict(
                        codex_error_info="usage_limit_exceeded",
                        resets_at=stamp,
                        message="PRIVATE 15:20",
                    ),
                ),
            ),
            "a",
        )
        self.assertEqual(event["event"], "failed")
        self.assertEqual(event["usage_resumes_at"], stamp)
        self.assertNotIn("PRIVATE", json.dumps(event))
        for invalid in (
            None,
            True,
            -1,
            0,
            "15:20",
            float("nan"),
            float("inf"),
            10**400,
        ):
            with self.subTest(value=invalid):
                self.assertEqual(limit_resume_at(invalid), 0)
                self.assertNotIn(
                    "usage_resumes_at",
                    sanitize_pet_event({**event, "usage_resumes_at": invalid}),
                )
        for overrides in (
            {"source": "claude_code"},
            {"event": "tool_start"},
            {"outcome_reason": "rate_limit"},
        ):
            self.assertNotIn(
                "usage_resumes_at", sanitize_pet_event({**event, **overrides})
            )


class UsageLimitProjectionTests(unittest.TestCase):
    setUpClass = classmethod(helpers.BubbleStateRegressions.setUpClass.__func__)
    tearDown = helpers.BubbleStateRegressions.tearDown
    send = helpers.BubbleStateRegressions.send
    start = helpers.BubbleStateRegressions.start
    advance = helpers.BubbleStateRegressions.advance
    row = helpers.BubbleStateRegressions.row
    window = helpers.BubbleStateRegressions.window

    def setUp(self):
        helpers.BubbleStateRegressions.setUp(self)
        self.wall = self.projects.wall_now()
        self.projects.wall_now = lambda: self.wall

    def failed(self, resumes=0, turn="1"):
        self.send(
            "failed", turn=turn, outcome_reason="usage_limit", usage_resumes_at=resumes
        )

    def expected(self, resets):
        return f"한도 · {resume_time_text(resets)} 재개"

    def test_unknown_and_past_resume_times_use_usage_limit_label(self):
        for turn, resets in (("unknown", 0), ("past", self.wall - 1)):
            self.start(turn=turn)
            self.failed(resets, turn)
            self.assertEqual(self.row().badge.text(), "사용량 한도")
            self.assertEqual(
                self.row().badge.toolTip(),
                "Codex 사용량 한도에 도달해 작업이 멈췄습니다.",
            )
            self.assertFalse(self.projects.completions)
            self.assertEqual(self.projects.cards[0].working, 0)
            self.assertEqual(self.projects.cards[0].waiting, 0)

    def test_known_resume_time_is_shown_but_row_keeps_result_time(self):
        self.start()
        self.failed(self.wall + 120)
        self.assertEqual(self.row().badge.text(), self.expected(self.wall + 120))
        self.assertEqual(
            self.row().badge.toolTip(),
            "Codex 사용량 한도에 도달해 작업이 멈췄습니다. "
            f"{resume_time_text(self.wall + 120)} 이후 다시 사용할 수 있습니다.",
        )
        self.assertEqual(self.window().content.summary, "사용량 한도 1개")
        self.advance(9)
        self.assertFalse(self.projects.cards)
        self.assertEqual(self.pet.agent_controller.current_presentation.active_count, 0)

    def test_old_children_cannot_revive_parent_before_or_after_resume(self):
        self.start()
        self.send(thread="child", agent_scope="subagent", parent_session_id="a")
        self.failed(self.wall + 120)
        for event in ("heartbeat", "tool_start", "waiting", "done"):
            self.send(event, thread="child", agent_scope="subagent", event_id="late")
            self.assertEqual(self.row().badge.text(), self.expected(self.wall + 120))
        self.advance(121)
        self.send("heartbeat", thread="child", agent_scope="subagent")
        self.assertFalse(self.projects.cards)
        self.send("prompt", turn="2")
        self.send(
            "waiting",
            thread="child",
            turn="1",
            agent_scope="subagent",
            event_id="old-question",
        )
        self.assertEqual(self.row().badge.text(), "작업 중")
        self.send(
            "prompt",
            thread="child",
            turn="2",
            agent_scope="subagent",
            parent_session_id="a",
        )
        self.send(
            "waiting",
            thread="child",
            turn="2",
            agent_scope="subagent",
            event_id="new-question",
        )
        self.assertEqual(self.row().badge.text(), "확인 필요")

    def test_neutral_end_keeps_known_time_until_correlated_failure_is_confirmed(self):
        self.start()
        self.send(
            "ended", outcome_reason="usage_limit", usage_resumes_at=self.wall + 120
        )
        self.assertEqual(self.row().badge.text(), "종료됨")
        target = self.projects.codex_turn_targets()[0]
        self.activity.observe_turn_outcome(
            CodexTurnOutcome(target, "failed", "usage_limit")
        )
        self.controller._render()
        self.assertEqual(self.row().badge.text(), self.expected(self.wall + 120))
        self.assertFalse(self.projects.completions)

    def test_other_root_and_non_usage_failures_keep_their_existing_behavior(self):
        self.start()
        self.start("other")
        self.failed()
        self.assertEqual(self.row("other").badge.text(), "작업 중")
        self.send(
            "failed",
            thread="other",
            outcome_reason="rate_limit",
            usage_resumes_at=self.wall + 120,
        )
        self.assertNotEqual(self.row("other").badge.text(), "사용량 한도")
        self.assertEqual(self.projects.activities["other"].usage_resumes_at, 0)

    def test_english_pack_and_account_reset(self):
        original = get_translator()
        self.addCleanup(set_translator, original)
        set_translator(load_pack(RESOURCE_ROOT / "en", official=True).translator())
        self.start()
        self.failed(self.wall + 120)
        self.controller._render()
        self.assertIn("Limit · resumes at", self.row().badge.text())
        self.projects.reset()
        self.assertFalse(self.projects._blocked_parents)
        self.assertFalse(self.projects._blocked_children)

    def test_real_log_uses_latest_exhausted_windows_only_in_the_same_turn(self):
        root = Path(self.directory.name) / "sessions"
        root.mkdir()
        path = root / "rollout-11111111-1111-4111-8111-111111111111.jsonl"
        monitor = CodexLogMonitor(
            root, now=lambda: datetime.fromtimestamp(self.wall, timezone.utc)
        )
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
                            timestamp=datetime.fromtimestamp(
                                self.wall, timezone.utc
                            ).isoformat(),
                            payload=payload,
                        )
                    )
                    + "\n"
                )
            deadline = time.perf_counter() + 2
            expected_offset = path.stat().st_size
            while (
                monitor._positions.get(path, 0) < expected_offset
                and time.perf_counter() < deadline
            ):
                monitor.poll_now()
                self.app.processEvents()
            self.assertEqual(monitor._positions.get(path), expected_offset)
            self.controller._render()
            self.app.processEvents()

        record("session_meta", id="a", source="cli")
        for index, limits, reset in (
            (
                1,
                {
                    "primary": {"used_percent": 100, "resets_at": self.wall + 60},
                    "secondary": {"used_percent": 100, "resets_at": self.wall + 120},
                },
                self.wall + 120,
            ),
            (2, None, 0),
            (
                3,
                {
                    "primary": {"used_percent": 100, "resets_at": self.wall + 60},
                    "secondary": {"used_percent": 100},
                },
                0,
            ),
            (
                4,
                {
                    "limit_id": "gpt-reserve",
                    "primary": {"used_percent": 100, "resets_at": self.wall + 60},
                },
                0,
            ),
            (5, {"primary": {"used_percent": 100, "resets_at": self.wall - 1}}, 0),
        ):
            with self.subTest(case=index):
                turn = str(index)
                record("event_msg", type="task_started", turn_id=turn)
                if limits:
                    record("event_msg", type="token_count", rate_limits=limits)
                self.assertEqual(self.row().badge.text(), "작업 중")
                record(
                    "event_msg",
                    type="turn_aborted",
                    turn_id=turn,
                    error={
                        "codex_error_info": "usage_limit_exceeded",
                        "message": "PRIVATE",
                    },
                )
                self.assertEqual(
                    self.row().badge.text(),
                    self.expected(reset) if reset else "사용량 한도",
                )
                self.assertFalse(monitor._quota_resets)
                self.assertFalse(monitor._pending_errors)

    def test_error_alone_and_successful_retry_do_not_create_quota_failure(self):
        self.start()
        monitor = CodexLogMonitor()
        self.addCleanup(monitor.close)
        path = Path("synthetic-quota-retry.jsonl")
        monitor._session_ids[path] = "a"
        monitor._agent_scopes[path] = "main"
        monitor.payload_detected.connect(self.server._receive_jsonl_payload)

        def record(**payload):
            monitor._process_line(
                path,
                json.dumps(
                    dict(
                        type="event_msg",
                        timestamp=datetime.fromtimestamp(
                            self.wall, timezone.utc
                        ).isoformat(),
                        payload=payload,
                    )
                ).encode(),
            )

        record(type="task_started", turn_id="1")
        record(
            type="error",
            turn_id="1",
            codex_error_info="usage_limit_exceeded",
            message="PRIVATE 15:20",
        )
        self.assertEqual(self.row().badge.text(), "작업 중")
        monitor._process_line(
            path,
            json.dumps(
                dict(type="response_item", payload={"type": "reasoning"})
            ).encode(),
        )
        record(type="task_complete", turn_id="1")
        self.assertEqual(self.projects.activities["a"].outcome_reason, "unknown")
        self.assertFalse(self.projects._blocked_parents)
