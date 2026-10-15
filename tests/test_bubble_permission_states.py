"""Approval ownership must not be confused with a request for human input."""

import unittest
from PySide6.QtGui import QFont

from watched_kettle.integrations.codex_hooks import (
    normalize_codex_hook,
    encode_pet_event,
)
from watched_kettle.state.events import build_decision
from watched_kettle.state.session_manager import AgentSessionManager
from tests import test_actionable_bubbles as helpers


class PermissionProjectTests(unittest.TestCase):
    setUpClass = classmethod(helpers.ProjectTests.setUpClass.__func__)
    setUp = helpers.ProjectTests.setUp
    event = helpers.ProjectTests.event
    meta = helpers.ProjectTests.meta

    def test_permission_lifecycle_and_header_agree(self):
        self.event()
        self.meta("a")
        for actor, state, summary in (
            ("unknown", "permission", "권한 처리 중 1개"),
            ("auto", "running", "작업 중 1개"),
            ("user", "waiting", "확인 필요 1개"),
        ):
            self.event(event="permission", event_id="p", approval_actor=actor)
            card = self.projects.cards[0]
            self.assertEqual(card.rows[0].state, state)
            self.assertEqual(card.summary, summary)
        self.event(event="permission_resolved", event_id="p")
        self.assertEqual(self.projects.cards[0].summary, "작업 중 1개")

    def test_other_request_and_old_turn_cannot_clear_human_wait(self):
        self.event()
        self.meta("a")
        self.event(event="permission", event_id="a", approval_actor="user")
        self.event(event="permission", event_id="b", approval_actor="unknown")
        self.event(event="permission_resolved", event_id="b")
        self.assertEqual(self.projects.cards[0].waiting, 1)
        self.assertFalse(
            self.event(event="permission_resolved", event_id="a", turn="old")
        )
        self.assertEqual(self.projects.cards[0].waiting, 1)
        self.event(event="tool_end", event_id="a")
        self.assertEqual(self.projects.cards[0].waiting, 0)

    def test_unknown_duplicate_cannot_erase_explicit_user_wait(self):
        self.event()
        self.meta("a")
        self.event(event="permission", event_id="p", approval_actor="user")
        self.event(event="permission", event_id="p")
        self.assertEqual(self.projects.cards[0].waiting, 1)


class PermissionHookTests(unittest.TestCase):
    def test_neutral_permission_does_not_announce_or_erase_other_wait(self):
        manager = AgentSessionManager()
        for actor in ("unknown", "auto"):
            result = manager.apply(
                build_decision(
                    dict(
                        source="codex",
                        event="permission",
                        session_id="p",
                        event_id="a",
                        approval_actor=actor,
                    )
                )
            )
            self.assertFalse(result.display.announce)
            self.assertEqual(result.aggregate.state, "running")
        manager.apply(
            build_decision(
                dict(
                    source="codex",
                    event="waiting",
                    session_id="p",
                    event_id="user-input",
                )
            )
        )
        result = manager.apply(
            build_decision(
                dict(
                    source="codex",
                    event="permission_resolved",
                    session_id="p",
                    event_id="a",
                )
            )
        )
        self.assertEqual(result.aggregate.state, "waiting")

    def test_normalization_keeps_actor_and_neutral_default(self):
        for reviewer, actor in (
            (None, "unknown"),
            ("auto_review", "auto"),
            ("user", "user"),
        ):
            payload = normalize_codex_hook(
                {
                    "hook_event_name": "PermissionRequest",
                    "session_id": "p",
                    "tool_use_id": "a",
                    "approvalsReviewer": reviewer,
                }
            )
            self.assertEqual(payload["event"], "permission")
            self.assertEqual(payload["approval_actor"], actor)
            self.assertIsNotNone(encode_pet_event(payload))
            decision = build_decision(payload)
            self.assertEqual(
                decision.persistent_state, "waiting" if actor == "user" else "running"
            )


class BubbleFontTests(unittest.TestCase):
    setUpClass = classmethod(helpers.CardTests.setUpClass.__func__)
    setUp = helpers.CardTests.setUp
    tearDown = helpers.CardTests.tearDown

    def test_all_bubble_text_keeps_no_hinting_after_scaling(self):
        self.projects.observe(
            dict(source="codex", event="prompt", session_id="font", turn_id="1")
        )
        self.projects.set_metadata(
            helpers.ThreadMetadata(
                "font", "p", "긴 프로젝트 이름 확인", title="프로그램 점검"
            ),
            self.projects.generation,
        )
        application_font = QFont(self.app.font())
        for scale in (100, 125, 150, 200):
            self.controller.set_scale_percent(scale)
            self.controller._render()
            self.app.processEvents()
            window = self.controller.visible_windows[0]
            row = window.project_rows.rows["font"]
            for widget in (
                window.category_label,
                window.summary_label,
                row.title,
                row.badge,
            ):
                self.assertEqual(
                    widget.font().hintingPreference(),
                    QFont.HintingPreference.PreferNoHinting,
                )
            self.assertGreaterEqual(
                row.title.height(), row.title.fontMetrics().height() + window._scaled(8)
            )
            self.assertLess(row.title.geometry().right(), row.badge.geometry().left())
        self.assertEqual(self.app.font(), application_font)


if __name__ == "__main__":
    unittest.main()
