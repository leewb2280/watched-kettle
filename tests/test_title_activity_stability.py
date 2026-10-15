"""Title polling and continuous project placement regressions; no live accounts."""

import json
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PySide6.QtWidgets import QApplication

from watched_kettle.features.project_activity.metadata import (
    ConversationMetadataService,
    _MetadataWorker,
)
from watched_kettle.features.project_activity.service import (
    ProjectActivityService,
    ThreadMetadata,
)


class Client:
    ready = True

    def __init__(self):
        self.calls = []

    def request(self, method, params):
        self.calls.append((method, params))
        return len(self.calls)


class StabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.time = 100.0
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "state.json"
        self.activity = ProjectActivityService(now=lambda: self.time)
        self.worker = _MetadataWorker(Client, self.path)
        self.worker.client = Client()
        self.worker.clock = lambda: self.time
        self.worker.last_account_check = self.time
        self.worker.result.connect(self.activity.set_metadata)

    def tearDown(self):
        self.temp.cleanup()

    def event(self, thread="a", event="prompt", turn="1", scope="main"):
        return self.activity.observe(
            dict(
                source="codex",
                event=event,
                session_id=thread,
                turn_id=turn,
                agent_scope=scope,
                event_id="call" if event.startswith("tool_") else event,
            )
        )

    def reply(self, thread="a", name="New", error=None):
        rid = next(r for r, (t, _g) in self.worker.pending.items() if t == thread)
        self.worker.response(
            rid, "thread/read", {}, {"thread": {"id": thread, "name": name}}, error
        )

    def test_three_second_poll_does_not_wait_for_second_timer_window(self):
        self.event()
        self.worker.sync_targets({"a": 1}, 0)
        self.reply(name="Old")
        self.time = 102.9
        self.worker.request("a", 0)
        self.worker.pump()
        self.assertFalse(self.worker.pending)
        self.time = 103
        self.worker.pump()
        self.reply(name="New")
        self.assertEqual(self.activity.cards[0].rows[0].title, "New")
        self.assertEqual(len(self.worker.client.calls), 2)

    def test_routine_account_check_does_not_shorten_retry_deadline(self):
        self.worker.sync_targets({"a": 1}, 0)
        self.reply(error={"code": "timeout"})
        deadline = self.worker.due["a"]
        self.worker.control_request("account/read", {})
        rid = len(self.worker.client.calls)
        self.worker.response(rid, "account/read", {}, {"account": {"id": "same"}}, None)
        self.assertEqual(self.worker.due["a"], deadline)

    def test_four_inflight_fairness_and_no_duplicate(self):
        self.worker.sync_targets({str(i): i + 1 for i in range(520)}, 0)
        self.assertEqual(len(self.worker.pending), 4)
        self.assertLessEqual(len(self.worker.queue), 512)
        first = {t for t, _g in self.worker.pending.values()}
        self.time += 3
        self.worker.pump()
        self.assertEqual(len(self.worker.pending), 4)
        for thread in first:
            self.reply(thread)
        self.worker.pump()
        self.assertTrue(first.isdisjoint(t for t, _g in self.worker.pending.values()))

    def test_backoff_then_recovery_and_removed_registration(self):
        self.worker.sync_targets({"a": 1}, 0)
        for delay in (3, 6, 12, 30):
            self.reply(error={"code": "timeout"})
            self.assertEqual(self.worker.due["a"], self.time + delay)
            self.time += delay
            self.worker.pump()
        self.reply()
        self.assertNotIn("a", self.worker.failures)
        self.time += 3
        self.worker.pump()
        self.worker.sync_targets({}, 0)
        self.worker.sync_targets({"a": 2}, 0)
        self.reply(name="Obsolete")
        self.assertNotEqual(self.activity.metadata["a"].title, "Obsolete")
        self.worker.pump()
        self.reply(name="Current")
        self.assertEqual(self.activity.metadata["a"].title, "Current")

    def test_service_rejects_queued_old_registration_connection_and_account(self):
        service = ConversationMetadataService(self.activity)
        self.event()
        version = service._requested["a"]
        metadata = ThreadMetadata("a", title="Obsolete")
        service.connection_changed(1)
        service.receive(metadata, 0, version, 0)
        self.assertNotEqual(self.activity.metadata["a"].title, "Obsolete")
        self.event(event="done")
        self.activity.dismiss_completions(
            [self.activity.visible_completions[0].record_id]
        )
        self.event(turn="2")
        service.receive(metadata, 0, version, 1)
        self.assertNotEqual(self.activity.metadata["a"].title, "Obsolete")
        self.activity.reset()
        service.receive(metadata, 0, version, 1)
        self.assertFalse(self.activity.metadata)
        service.close()

    def test_disconnect_preserves_rows_and_same_account_resumes(self):
        self.event()
        self.worker.account = (None, "account-a", None)
        self.worker.reset.connect(self.activity.reset)
        self.worker.sync_targets({"a": 1}, 0)
        old = next(iter(self.worker.pending))
        self.worker.ready(False)
        self.assertEqual(len(self.activity.cards), 1)
        self.worker.response(
            old, "thread/read", {}, {"thread": {"id": "a", "name": "Stale"}}, None
        )
        self.worker.ready(True)
        account_id = next(
            r
            for r in self.worker.control_requests
            if self.worker.client.calls[r - 1][0] == "account/read"
        )
        self.worker.response(
            account_id, "account/read", {}, {"account": {"id": "account-a"}}, None
        )
        self.assertEqual(self.activity.generation, 0)
        self.worker.pump()
        self.assertTrue(self.worker.pending)

    def test_account_notification_and_malformed_reply_do_not_reset(self):
        self.event()
        self.worker.account = (None, "account-a", None)
        self.worker.reset.connect(self.activity.reset)
        for payload in ({}, {"account": {}}, {"account": "bad"}):
            self.worker.notification("account/updated", {})
            rid = len(self.worker.client.calls)
            self.worker.response(rid, "account/read", {}, payload, None)
            self.assertEqual(len(self.activity.cards), 1)
        self.worker.control_request("account/read", {})
        self.worker.response(
            len(self.worker.client.calls), "account/read", {}, {"account": None}, None
        )
        self.assertFalse(self.activity.cards)

    def test_stale_keeps_row_and_accepts_same_turn_heartbeat_and_completion(self):
        self.event()
        original = self.activity.cards[0].rows[0].sort_at
        self.time += 60
        self.activity.expire()
        self.assertTrue(self.activity.cards[0].rows[0].uncertain)
        self.assertEqual(self.activity.cards[0].summary, "상태 확인 중 1개")
        self.activity.set_metadata(ThreadMetadata("a", title="Updated"), 0)
        self.assertTrue(self.activity.cards[0].rows[0].uncertain)
        self.event(event="heartbeat")
        self.assertFalse(self.activity.cards[0].rows[0].uncertain)
        self.assertEqual(self.activity.cards[0].rows[0].sort_at, original)
        self.assertTrue(self.event(event="done"))
        self.assertEqual(len(self.activity.visible_completions), 1)
        self.assertFalse(self.event(event="tool_start"))

    def test_tool_threshold_and_waits(self):
        self.event()
        self.event(event="tool_start")
        self.event("wait")
        self.event("wait", "waiting")
        self.time += 179
        self.activity.expire()
        self.assertFalse(self.activity.activities["a"].uncertain)
        self.time += 1
        self.activity.expire()
        self.assertTrue(self.activity.activities["a"].uncertain)
        self.assertFalse(self.activity.activities["wait"].uncertain)
        self.assertTrue(self.event(event="tool_end"))
        self.assertFalse(self.activity.activities["a"].uncertain)

    def test_unknown_scope_cannot_hide_known_main_even_on_next_turn(self):
        self.event()
        self.event(event="tool_start", scope="unknown")
        self.assertEqual(len(self.activity.cards), 1)
        self.event(turn="2", scope="unknown")
        self.assertEqual(len(self.activity.cards), 1)
        self.event("child", scope="subagent")
        self.activity.set_metadata(ThreadMetadata("child", title="Child"), 0)
        self.assertEqual(self.activity.activities["child"].scope, "subagent")

    def test_local_relation_merges_before_api_response_without_title_regression(self):
        self.event()
        self.activity.set_metadata(ThreadMetadata("a", "p", "Project", title="A"), 0)
        self.path.write_text(
            json.dumps({"thread-project-assignments": {"b": {"projectId": "p"}}}),
            encoding="utf-8",
        )
        self.event("b")
        self.activity.set_metadata(ThreadMetadata("b", title="B"), 0)
        self.assertEqual(len(self.activity.bubble_cards), 2)
        self.worker.relation.connect(
            lambda t, p, label, g, v, e: self.activity.set_project_relation(
                t, p, label, g
            )
        )
        self.worker.sync_targets({"b": 1}, 0)
        self.assertEqual(len(self.activity.bubble_cards), 1)
        self.assertEqual(len(self.activity.bubble_cards[0].rows), 2)
        self.assertEqual(self.activity.metadata["b"].title, "B")
        self.assertTrue(self.worker.pending)

    def test_immediate_unknown_group_completion_and_projectless_are_distinct(self):
        self.event()
        self.event("b")
        self.event("none")
        self.activity.set_metadata(ThreadMetadata("none", ""), 0)
        self.event(event="done")
        expiry = self.activity.visible_completions[0].expires_at
        self.assertEqual(len(self.activity.bubble_cards), 2)
        self.time += 1
        self.assertEqual(len(self.activity.bubble_cards), 2)
        pending = next(c for c in self.activity.bubble_cards if c.kind == "unknown")
        self.assertEqual(len(pending.rows), 2)
        self.assertEqual(pending.label, "프로젝트 확인 중")
        self.activity.set_metadata(ThreadMetadata("a", "p", "Project"), 0)
        self.assertEqual(self.activity.visible_completions[0].expires_at, expiry)

    def test_missing_metadata_preserves_known_title_relation_and_no_repeat_signal(self):
        self.event()
        metadata = ThreadMetadata("a", "p", "Project", title="Known")
        self.activity.set_metadata(metadata, 0)
        changes = []
        self.activity.changed.connect(lambda: changes.append(True))
        self.activity.set_metadata(metadata, 0)
        self.activity.set_metadata(ThreadMetadata("a"), 0)
        self.assertFalse(changes)
        self.assertEqual(self.activity.metadata["a"], metadata)
        self.activity.set_metadata(
            replace(metadata, project_id="", project_label=""), 0
        )
        self.assertEqual(self.activity.cards[0].kind, "unassigned")

    def test_completion_remains_target_until_dismissal_or_expiry(self):
        service = ConversationMetadataService(self.activity)
        self.event()
        self.event(event="done")
        self.time += 20
        self.activity.expire()
        service.refresh_active()
        self.assertIn("a", service._requested)
        self.activity.dismiss_completions(
            [self.activity.visible_completions[0].record_id]
        )
        self.assertNotIn("a", service._requested)
        self.event(turn="2")
        self.event(event="done", turn="2")
        self.time += 300
        service.refresh_active()
        self.assertNotIn("a", service._requested)
        service.close()
