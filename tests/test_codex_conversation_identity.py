"""Verified Codex identity across hooks, metadata, completion rows and pets."""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from tests.test_project_metadata import Client
from watched_kettle.activity_diagnostics import diagnostic_ref
from watched_kettle.features.agent_activity.service import AgentActivityService
from watched_kettle.features.project_activity.metadata import (
    ConversationMetadataService,
    _MetadataWorker,
)
from watched_kettle.features.project_activity.service import (
    ProjectActivityService,
    ThreadMetadata,
)
from watched_kettle.integrations.activity_recovery import RecoverySnapshot
from watched_kettle.integrations.codex_hooks import normalize_codex_hook
from watched_kettle.integrations.codex_ipc import (
    CodexHookServer,
    PIPE_TRANSPORT,
    JSONL_TRANSPORT,
)
from watched_kettle.state.agent_scope import (
    scope_from_session_source,
    scope_from_thread_metadata,
)
from watched_kettle.state.controller import PetAgentController


class ConversationIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 100.0
        self.projects = ProjectActivityService(
            now=lambda: self.now, wall_now=lambda: 0.0
        )
        self.states = []
        self.pet = SimpleNamespace(
            agent_controller=PetAgentController(self.states.append)
        )
        self.pet.apply_agent_payload = self.pet.agent_controller.apply_payload
        self.activity = AgentActivityService(self.pet, projects=self.projects)
        self.server = CodexHookServer(
            f"identity-{uuid4().hex}",
            spool_directory=Path(self.temp.name) / "queue",
            managed_spool_directory=None,
            managed_hook_health_path=None,
        )
        self.server.payload_received.connect(self.activity.observe)
        self.catalog = ConversationMetadataService(self.projects)
        # Run the real worker synchronously with an inert, read-only RPC client.
        self.worker = _MetadataWorker(Client, Path(self.temp.name) / "desktop.json")
        self.worker.client = Client()
        self.worker.clock = lambda: self.now
        self.worker.last_account_check = self.now
        self.catalog.targets_changed.connect(self.worker.sync_targets)
        self.catalog.invalidated.connect(self.worker.invalidate)
        self.worker.delivered.connect(self.catalog.receive)
        self.worker.relation.connect(self.catalog.receive_relation)
        self.diagnostics = []
        self.projects.activity_diagnostics.callback = (
            lambda e, **f: self.diagnostics.append((e, f))
        )
        self.addCleanup(self.server.close)
        self.addCleanup(self.pet.agent_controller.clear)
        self.addCleanup(self.pet.agent_controller.deleteLater)
        self.addCleanup(self.catalog.deleteLater)
        self.addCleanup(self.worker.deleteLater)
        self.addCleanup(self.projects.deleteLater)
        self.addCleanup(self.activity.deleteLater)

    def reset_state(self):
        self.server._recent_events.clear()
        self.projects.reset()
        # The inert client has no account transport; model its successful check.
        self.worker.account_verified = True
        self.worker.last_account_check = self.now

    def hook(self, name="UserPromptSubmit", thread="normal", turn="1", **extra):
        payload = normalize_codex_hook(
            {
                "hook_event_name": name,
                "session_id": thread,
                "turn_id": turn,
                **extra,
            }
        )
        self.assertEqual(payload["agent_scope"], "unknown")
        self.server._deliver_payload(payload, PIPE_TRANSPORT)
        return payload

    def reply(self, thread="normal", error=None, **fields):
        rid = next(rid for rid, (t, _) in self.worker.pending.items() if t == thread)
        result = {
            "thread": {
                "id": thread,
                "ephemeral": False,
                "source": "appServer",
                "parentThreadId": None,
                "projectId": "",
                "name": "실제 대화",
                **fields,
            }
        }
        self.worker.response(
            rid, "thread/read", {}, result if not error else None, error
        )

    def advance(self, seconds):
        self.now += seconds
        self.projects.expire()
        self.catalog.refresh_active()
        self.worker.pump()

    def assert_quiet(self):
        self.assertFalse(self.projects.cards)
        self.assertFalse(self.projects.completions)
        self.assertFalse(self.projects.recent)
        self.assertEqual(self.pet.agent_controller.desired_state, "idle")
        presentation = self.pet.agent_controller.current_presentation
        self.assertEqual(presentation.active_count, 0)
        self.assertFalse(presentation.working_sources)
        self.assertIsNone(presentation.notice)
        self.assertIsNone(presentation.persistent_notice)
        self.assertFalse(self.pet.agent_controller.transient_timer.isActive())

    def test_reported_ambient_sessions_never_become_visible(self):
        for thread in ("ambient_suggestions", "ambient_suggestion_safety"):
            self.hook(thread=thread)
            self.reply(thread, error={"code": -32600, "message": "PRIVATE"})
            self.hook("Stop", thread=thread)
            self.assert_quiet()
        self.advance(31)
        for thread in ("ambient_suggestions", "ambient_suggestion_safety"):
            self.assertIn(thread, self.worker.targets)
            self.reply(thread, error={"code": -32600})
        self.assert_quiet()
        self.advance(300)
        self.assertFalse(self.projects.unconfirmed_completion_threads)
        self.assertFalse(self.worker.targets)

    def test_projectless_normal_completion_is_exactly_one(self):
        self.hook()
        self.assert_quiet()
        self.reply()
        self.assertEqual(self.projects.cards[0].kind, "unassigned")
        self.assertEqual(self.activity.snapshot.active_count, 1)
        self.assertIsNone(self.pet.agent_controller.current_presentation.notice)
        self.hook("Stop")
        self.assertEqual(len(self.projects.completions), 1)
        self.assertEqual(self.projects.cards[0].done, 1)
        self.assertEqual(
            self.pet.agent_controller.current_presentation.notice.event, "done"
        )
        self.catalog.refresh_active()
        self.advance(15)
        self.reply()
        self.assertEqual(len(self.projects.completions), 1)

    def test_transient_failure_recovers_while_running_without_start_replay(self):
        self.hook()
        self.reply(error={"code": -32600})
        self.assert_quiet()
        self.advance(3)
        self.reply(name=None, projectId=None)
        self.assertEqual(self.activity.snapshot.active_count, 1)
        self.assertEqual(self.projects.cards[0].kind, "unknown")
        self.assertEqual(self.projects.cards[0].rows[0].title, "Codex 대화")
        self.assertIsNone(self.pet.agent_controller.current_presentation.notice)
        self.hook("Stop")
        self.assertEqual(len(self.projects.completions), 1)

    def test_completed_before_metadata_recovers_after_activity_expiry(self):
        self.hook(turn="")
        self.reply(error={"code": -32600})
        self.hook("Stop", turn="")
        self.assert_quiet()
        self.advance(20)
        self.assertNotIn("normal", self.projects.activities)
        self.reply()
        record = self.projects.completions[0]
        self.assertEqual(record.completed_at, 100)
        self.assertEqual(record.highlight_until, 115)
        self.assertEqual(record.expires_at, 400)
        self.assertFalse(self.projects.cards[0].rows[0].highlighted)
        self.assertEqual(self.pet.agent_controller.desired_state, "idle")
        self.assertFalse(self.pet.agent_controller.transient_timer.isActive())
        self.assertIsNone(self.pet.agent_controller.current_presentation.notice)

    def test_metadata_before_result_expiry_releases_idless_candidate_once(self):
        self.hook(turn="")
        self.hook("Stop", turn="")
        self.reply()
        self.assertEqual(len(self.projects.completions), 1)
        self.projects.set_metadata(ThreadMetadata("normal", agent_scope="main"), 0)
        self.assertEqual(len(self.projects.completions), 1)
        self.assertEqual(self.pet.agent_controller.desired_state, "idle")

    def test_explicit_ephemeral_or_internal_evidence_discards_candidate(self):
        for fields in (
            {"ephemeral": True},
            {"source": {"subAgent": {"other": "guardian"}}},
            {"parentThreadId": "parent", "source": {"subAgent": {"threadSpawn": {}}}},
        ):
            with self.subTest(fields=fields):
                self.reset_state()
                self.hook()
                self.hook("Stop")
                self.reply(**fields)
                self.assert_quiet()
                self.assertFalse(self.projects.unconfirmed_completion_threads)

    def test_unknown_waits_failures_and_compaction_have_no_pet_effect(self):
        self.hook()
        self.hook("PermissionRequest", tool_use_id="tool", approval_actor="user")
        self.assert_quiet()
        self.hook("PreCompact")
        self.assert_quiet()
        self.hook("PostToolUse", tool_use_id="tool", tool_response={"success": False})
        self.assert_quiet()
        self.server._deliver_payload(
            {
                "source": "codex",
                "session_id": "normal",
                "event": "failed",
                "turn_id": "1",
                "agent_scope": "unknown",
            },
            PIPE_TRANSPORT,
        )
        self.assert_quiet()

    def test_wait_is_projected_only_after_confirmation(self):
        self.hook()
        self.hook("PermissionRequest", tool_use_id="tool", approval_actor="user")
        self.assert_quiet()
        self.reply()
        self.assertEqual(self.projects.cards[0].waiting, 1)
        self.assertEqual(self.pet.agent_controller.desired_state, "waiting")
        self.assertIsNotNone(
            self.pet.agent_controller.current_presentation.persistent_notice
        )
        self.assertIsNone(self.pet.agent_controller.current_presentation.notice)

    def test_names_and_project_assignment_are_not_identity_evidence(self):
        self.hook()
        self.projects.set_project_relation("normal", "p", "프로젝트", 0)
        self.reply(source="unknown", name="제목 있음")
        self.assert_quiet()

    def test_legacy_main_hook_cannot_confirm_identity(self):
        for event in ("prompt", "done"):
            self.server._deliver_payload(
                {
                    "source": "codex",
                    "event": event,
                    "session_id": "legacy",
                    "turn_id": "1",
                    "agent_scope": "main",
                },
                PIPE_TRANSPORT,
            )
        self.assert_quiet()
        self.assertEqual(self.projects.effective_scope("legacy"), "unknown")

    def test_log_confirmation_preserves_tools_then_allows_normal_completion(self):
        self.hook(turn="")
        self.hook("PreToolUse", turn="", tool_use_id="tool")
        self.server._deliver_payload(
            {
                "source": "codex",
                "event": "prompt",
                "session_id": "normal",
                "turn_id": "real-turn",
                "agent_scope": "main",
            },
            JSONL_TRANSPORT,
        )
        self.assertEqual(self.activity.snapshot.active_count, 1)
        self.assertEqual(self.projects.activities["normal"].active_tools, {"tool"})
        self.assertIsNone(self.pet.agent_controller.current_presentation.notice)
        self.server._deliver_payload(
            {
                "source": "codex",
                "event": "done",
                "session_id": "normal",
                "turn_id": "real-turn",
                "agent_scope": "main",
            },
            JSONL_TRANSPORT,
        )
        self.assertEqual(len(self.projects.completions), 1)

    def test_new_turn_invalidates_previous_candidate_including_idless(self):
        for turn in ("", "old"):
            with self.subTest(turn=turn):
                self.reset_state()
                self.hook(turn=turn)
                self.hook("Stop", turn=turn)
                self.hook(turn="new")
                self.reply()
                self.assertFalse(self.projects.completions)
                self.assertEqual(self.projects.activities["normal"].turn_id, "new")
                self.hook("Stop", turn="new")
                self.assertEqual(len(self.projects.completions), 1)

    def test_expiry_reset_and_old_delivery_never_restore_completion(self):
        self.hook()
        self.hook("Stop")
        self.advance(301)
        self.projects.set_metadata(ThreadMetadata("normal", agent_scope="main"), 0)
        self.assertFalse(self.projects.completions)
        self.projects.reset()
        self.catalog.receive(ThreadMetadata("normal", agent_scope="main"), 0, 1, 0)
        self.assertFalse(self.projects.metadata)
        self.assertFalse(self.projects.completions)

    def test_verified_identity_survives_unknown_completion_packet(self):
        self.hook()
        self.reply()
        self.server._deliver_payload(
            {
                "source": "codex",
                "event": "done",
                "session_id": "normal",
                "turn_id": "1",
                "agent_scope": "unknown",
            },
            JSONL_TRANSPORT,
        )
        self.assertEqual(len(self.projects.completions), 1)
        self.assertEqual(
            self.pet.agent_controller.current_presentation.notice.event, "done"
        )

    def test_heartbeat_can_confirm_a_hidden_existing_session_without_start_replay(self):
        self.hook()
        self.server._deliver_payload(
            {
                "source": "codex",
                "event": "heartbeat",
                "session_id": "normal",
                "turn_id": "1",
                "agent_scope": "main",
            },
            JSONL_TRANSPORT,
        )
        self.assertEqual(self.activity.snapshot.active_count, 1)
        self.assertEqual(self.projects.cards[0].running, 1)
        self.assertIsNone(self.pet.agent_controller.current_presentation.notice)

    def test_late_parent_evidence_on_an_ended_turn_never_enters_history(self):
        self.hook()
        for event, extra in (("ended", {}), ("done", {"parent_session_id": "parent"})):
            self.server._deliver_payload(
                {
                    "source": "codex",
                    "event": event,
                    "session_id": "normal",
                    "turn_id": "1",
                    "agent_scope": "unknown",
                    **extra,
                },
                JSONL_TRANSPORT,
            )
        self.assert_quiet()
        self.assertEqual(self.projects.effective_scope("normal"), "subagent")

    def test_internal_identity_is_not_overridden_by_a_later_main_packet(self):
        self.hook()
        self.reply(ephemeral=True)
        self.server._deliver_payload(
            {
                "source": "codex",
                "event": "done",
                "session_id": "normal",
                "turn_id": "1",
                "agent_scope": "main",
            },
            JSONL_TRANSPORT,
        )
        self.assert_quiet()
        self.assertEqual(self.projects.effective_scope("normal"), "internal")
        self.assertNotIn("normal", self.worker.targets)

    def test_old_connection_metadata_cannot_confirm_a_new_epoch(self):
        self.hook()
        version = self.catalog._requested["normal"]
        self.catalog.connection_changed(1)
        self.catalog.receive(
            ThreadMetadata("normal", agent_scope="main"), 0, version, 0
        )
        self.assert_quiet()
        self.assertEqual(self.projects.effective_scope("normal"), "unknown")

    def test_parent_identity_cache_expires_with_the_last_child(self):
        self.hook()
        self.reply(parentThreadId="parent", source={"subAgent": {"threadSpawn": {}}})
        self.reply("parent")
        self.assertEqual(self.projects.effective_scope("parent"), "main")
        self.hook("Stop")
        self.advance(301)
        self.assertFalse(self.projects.metadata)
        self.assertEqual(self.projects.effective_scope("parent"), "unknown")

    def test_metadata_confirmation_of_recovery_never_creates_a_pet_session(self):
        self.projects.restore_activity(
            RecoverySnapshot(
                thread_id="normal",
                turn_id="1",
                scope="unknown",
                started_at=0,
                last_activity_at=0,
                observed_at=0,
            )
        )
        self.assert_quiet()
        self.reply()
        self.assertEqual(self.projects.cards[0].uncertain, 1)
        self.assertEqual(self.activity.snapshot.active_count, 0)
        self.assertFalse(self.pet.agent_controller.session_manager.list_sessions())
        self.advance(61)
        self.assert_quiet()
        self.assertFalse(self.projects.activities)

    def test_unknown_retention_is_bounded_and_diagnostics_are_content_free(self):
        with patch(
            "watched_kettle.features.project_activity.service.MAX_UNCONFIRMED_COMPLETIONS",
            2,
        ):
            for thread in ("first", "second", "third"):
                self.hook(thread=thread)
                self.hook("Stop", thread=thread)
        self.assertNotIn("first", self.projects.activities)
        self.assertEqual(
            set(self.projects.unconfirmed_completion_threads), {"second", "third"}
        )
        self.assertNotIn("first", self.worker.targets)
        encoded = json.dumps(self.diagnostics)
        self.assertNotIn('"first"', encoded)
        self.assertIn(diagnostic_ref("first"), encoded)
        self.assertIn("unverified_limit", encoded)


class IdentitySourceTests(unittest.TestCase):
    def test_api_and_rollout_source_spellings(self):
        for source in ("cli", "vscode", "exec", "appServer", "mcp"):
            self.assertEqual(scope_from_session_source(source), "main")
        for key, spawn in (("subagent", "thread_spawn"), ("subAgent", "threadSpawn")):
            self.assertEqual(scope_from_session_source({key: {spawn: {}}}), "subagent")
            self.assertEqual(
                scope_from_session_source({key: {"other": "guardian"}}), "internal"
            )

    def test_missing_malformed_and_future_identity_stays_unknown(self):
        for fields in (
            {},
            {"source": "appServer"},
            {"ephemeral": False},
            {"ephemeral": 0, "source": "cli"},
            {"ephemeral": False, "source": "future-source"},
        ):
            self.assertEqual(scope_from_thread_metadata(fields), "unknown")
