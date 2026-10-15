"""End-to-end observation contracts without changing activity or navigation."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from PySide6.QtWidgets import QApplication

from tests import test_project_completion_rows as helpers
from tests.test_project_metadata import Client
from watched_kettle.activity_diagnostics import (
    DiagnosticRecorder,
    diagnostic_ref,
    diagnostic_thread_ref,
)
from watched_kettle.application.diagnostics import DiagnosticsExporter
from watched_kettle.application.logging import configure_logging, close_logging
from watched_kettle.application.paths import AppPaths
from watched_kettle.application.runtime import ApplicationRuntime
from watched_kettle.features.notifications.actions import NotificationActionRouter
from watched_kettle.features.project_activity.metadata import (
    _MetadataWorker,
    ConversationMetadataService,
)
from watched_kettle.features.project_activity.service import (
    ProjectActivityService,
    ThreadMetadata,
    trace_ref,
)
from watched_kettle.integrations.activity_recovery import RecoverySnapshot
from watched_kettle.integrations.codex_ipc import (
    CodexHookServer,
    PIPE_TRANSPORT,
    JSONL_TRANSPORT,
)
from watched_kettle.integrations.claude_code_hooks import normalize_claude_code_hook
from watched_kettle.state.session_manager import InactivityLimit


def listen(owner, records, component=""):
    owner.activity_diagnostics.callback = lambda event, **fields: records.append(
        (component, event, fields)
    )


def entries(records, event):
    return [fields for _component, name, fields in records if name == event]


def broken(*args, **kwargs):
    raise RuntimeError("private diagnostic failure")


class RecorderTests(unittest.TestCase):
    def test_refs_preserve_codex_and_namespace_claude_consistently(self):
        self.assertEqual(diagnostic_thread_ref("codex", "t"), trace_ref("t"))
        self.assertEqual(
            diagnostic_thread_ref("claude_code", "t"), trace_ref("claude_code:t")
        )
        self.assertEqual(
            diagnostic_thread_ref("claude_code", "claude_code:t"),
            trace_ref("claude_code:t"),
        )
        self.assertEqual(diagnostic_thread_ref("claude_code", ""), "")

    def test_repeats_counts_changed_failures_and_capacity(self):
        recorder = DiagnosticRecorder()
        records = []
        recorder.callback = lambda event, **fields: records.append(fields)
        for now, attempt, reason in (
            (0, 1, "timeout"),
            (30, 2, "timeout"),
            (60, 3, "timeout"),
            (61, 4, "rpc_error"),
        ):
            recorder.record(
                "failed",
                "t",
                now=now,
                repeat_seconds=60,
                attempt=attempt,
                error_code=reason,
            )
        self.assertEqual([r["attempt"] for r in records], [1, 3, 4])
        for index in range(600):
            recorder.record("changed", str(index), state="running")
        self.assertEqual(len(recorder.states), 512)
        recorder.callback = broken
        recorder.record("failed", "new", error_code="timeout")


class ActivityTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.service = ProjectActivityService(
            now=lambda: self.now, wall_now=lambda: 10000
        )
        self.records = []
        listen(self.service, self.records)

    def event(self, event, thread="t", turn="1", **fields):
        return self.service.observe(
            dict(
                source="codex",
                event=event,
                session_id=thread,
                turn_id=turn,
                agent_scope="main",
                **fields,
            )
        )

    def test_minimal_records_changes_but_not_heartbeats_or_tools(self):
        self.event("prompt")
        self.event("heartbeat")
        self.event("tool_start", event_id="call")
        self.event("tool_end", event_id="call")
        self.assertEqual(len(entries(self.records, "activity_changed")), 1)
        self.event("prompt", turn="2")
        self.event("done", turn="2")
        self.assertEqual(
            [r["turn_ref"] for r in entries(self.records, "activity_changed")],
            [trace_ref("1"), trace_ref("2"), trace_ref("2")],
        )
        self.now += 301
        self.service.expire()
        self.assertEqual(
            entries(self.records, "completion_removed")[0]["reason"],
            "completion_expired",
        )

    def test_parent_project_membership_and_metadata_flags(self):
        self.event("prompt")
        self.service.set_metadata(ThreadMetadata("t", "p", title="private title"), 0)
        self.service.set_metadata(
            ThreadMetadata("t", "q", title="private title", parent_thread_id="parent"),
            0,
        )
        changes = entries(self.records, "activity_changed")
        self.assertEqual(changes[-1]["project_ref"], diagnostic_ref("project:q"))
        self.assertEqual(changes[-1]["parent_ref"], trace_ref("parent"))
        self.assertTrue(changes[-1]["title_present"])
        self.assertNotIn("private title", json.dumps(self.records))

    def test_reset_dismissal_inactivity_and_recovery_have_distinct_causes(self):
        self.event("prompt")
        self.event("done")
        self.service.dismiss_completions(
            [self.service.visible_completions[0].record_id]
        )
        self.assertEqual(
            entries(self.records, "completion_removed")[-1]["reason"], "dismissed"
        )
        self.event("prompt", turn="2")
        self.service.reset()
        self.assertEqual(
            entries(self.records, "activity_reset")[-1]["reason"], "account_reset"
        )
        self.service.set_inactivity_limit(
            "codex", InactivityLimit(work_ms=1000, waiting_ms=1000)
        )
        self.event("prompt", thread="silent")
        self.now += 2
        self.service.expire()
        self.assertEqual(
            entries(self.records, "activity_inactive")[-1]["reason"], "inactivity"
        )
        snapshot = RecoverySnapshot("recovered", "turn", "main", 9995, 9999, 10000)
        self.service.restore_activity(snapshot)
        self.now += 61
        self.service.expire()
        self.assertEqual(
            entries(self.records, "recovery_dropped")[-1]["reason"], "recovery_expired"
        )

    def test_parent_aggregation_logs_selection_without_repeated_reads(self):
        self.event("prompt", thread="parent")
        self.event("prompt", thread="child", parent_session_id="parent")
        self.service.set_metadata(ThreadMetadata("parent", "p"), 0)
        self.service.set_metadata(ThreadMetadata("child", parent_thread_id="parent"), 0)
        self.event(
            "permission_request",
            thread="child",
            approval_actor="user",
            event_id="request",
        )
        cards = self.service.cards
        fields = entries(self.records, "activity_aggregated")[-1]
        self.assertEqual(fields["thread_ref"], trace_ref("parent"))
        self.assertEqual(fields["selected_ref"], trace_ref("child"))
        self.assertEqual(fields["member_count"], 2)
        self.assertEqual(fields["state"], cards[0].rows[0].state)
        before = len(self.records)
        self.assertEqual(self.service.cards, cards)
        self.assertEqual(len(self.records), before)
        self.service.activity_diagnostics.callback = broken
        self.assertEqual(self.service.cards, cards)

    def test_diagnostic_callback_failure_preserves_completion(self):
        self.service.activity_diagnostics.callback = broken
        self.assertTrue(self.event("prompt"))
        self.assertTrue(self.event("done"))
        self.assertEqual(len(self.service.visible_completions), 1)
        with patch.object(self.service, "diagnostic_summary", side_effect=broken):
            self.service.reset()
        self.assertFalse(self.service.activities)
        self.assertFalse(self.service.visible_completions)

    def test_completion_dismissal_survives_hash_preparation_failure(self):
        self.event("prompt")
        self.event("done")
        record_id = self.service.visible_completions[0].record_id
        with patch(
            "watched_kettle.features.project_activity.service.trace_ref",
            side_effect=broken,
        ):
            self.service.dismiss_completions([record_id])
        self.assertFalse(self.service.visible_completions)


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "state.json"
        self.worker = _MetadataWorker(Client, self.path)
        self.worker.client = Client()
        self.now = 100.0
        self.worker.clock = lambda: self.now
        self.records = []
        self.worker.diagnostic_event.connect(
            lambda event, fields: self.records.append(("metadata", event, fields))
        )
        self.results = []
        self.worker.result.connect(
            lambda metadata, generation: self.results.append(metadata)
        )

    def reply(self, rid=1, thread="t", data=None, error=None, stamp=None, generation=0):
        self.worker.pending[rid] = (thread, generation)
        if stamp is not None:
            self.worker.stamps[rid] = stamp
        self.worker.response(
            rid, "thread/read", {}, {"thread": {"id": thread, **(data or {})}}, error
        )

    def test_failure_summaries_recovery_and_success_suppression(self):
        for index, moment in enumerate((100, 130, 160), 1):
            self.now = moment
            self.reply(
                rid=index,
                error={"code": "timeout", "message": "private title and path"},
            )
        self.assertEqual(
            [r["attempt"] for r in entries(self.records, "metadata_failed")], [1, 3]
        )
        self.reply(data={"name": "private title", "projectId": "p"})
        self.reply(data={"name": "private title", "projectId": "p"})
        self.assertEqual(len(entries(self.records, "metadata_resolved")), 1)
        self.assertEqual(len(entries(self.records, "metadata_recovered")), 1)
        self.assertEqual(
            entries(self.records, "metadata_resolved")[0]["project_ref"],
            diagnostic_ref("project:p"),
        )
        self.reply(error={"code": "timeout"})
        self.assertTrue(
            entries(self.records, "metadata_failed")[-1]["information_retained"]
        )
        self.assertNotIn("private", json.dumps(self.records))

    def test_invalid_id_numeric_rpc_and_old_stamps(self):
        self.reply(data={"id": "other"})
        self.reply(error={"code": -32600, "message": "private message"})
        self.reply(rid=3, generation=-1)
        self.worker.targets["t"] = 2
        self.reply(rid=4, stamp=(1, 0))
        self.assertEqual(
            [r["error_code"] for r in entries(self.records, "metadata_failed")],
            ["id_mismatch", "rpc_error"],
        )
        self.assertEqual(
            entries(self.records, "metadata_failed")[-1]["rpc_code"], -32600
        )
        self.assertEqual(
            [r["reason"] for r in entries(self.records, "metadata_discarded")],
            ["old_generation", "stale_registration_or_epoch"],
        )
        self.assertEqual(self.results, [])

    def test_evidence_and_detail_mode(self):
        self.path.write_text(
            json.dumps({"local-projects": {"p": {"rootPaths": ["C:/Work/p"]}}}),
            encoding="utf-8",
        )
        self.reply(data={"cwd": "C:/Work/p"})
        self.assertEqual(
            entries(self.records, "metadata_resolved")[-1]["reason"], "cwd_match"
        )
        self.assertFalse(entries(self.records, "metadata_response"))
        self.worker.activity_diagnostics.detailed = True
        self.reply(data={"projectId": "", "parentThreadId": "parent"})
        self.assertEqual(
            entries(self.records, "metadata_response")[-1]["reason"], "api"
        )
        self.assertEqual(
            entries(self.records, "metadata_response")[-1]["parent_ref"],
            trace_ref("parent"),
        )
        self.worker.request("t", 0)
        self.worker.pump()
        self.assertTrue(entries(self.records, "metadata_requested"))

    def test_cleared_requests_still_identify_late_responses(self):
        for operation in ("invalidate", "reconnect"):
            with self.subTest(operation=operation):
                self.worker.account_verified = True
                self.worker.sync_targets({"t": (7, 0, 3)}, self.worker.generation)
                rid = next(iter(self.worker.pending))
                generation, epoch = self.worker.generation, self.worker.epoch
                if operation == "invalidate":
                    self.worker.invalidate(generation + 1)
                else:
                    self.worker.ready(False)
                self.worker.response(
                    rid, "thread/read", {}, {"thread": {"id": "t"}}, None
                )
                fields = entries(self.records, "metadata_discarded")[-1]
                self.assertEqual(fields["reason"], "request_invalidated")
                self.assertEqual(fields["thread_ref"], trace_ref("t"))
                self.assertEqual(fields["request_id"], rid)
                self.assertEqual(fields["request_generation"], generation)
                self.assertEqual(fields["request_epoch"], epoch)
                self.assertEqual(fields["request_version"], 7)
                self.assertFalse(self.results)
                self.assertNotIn(rid, self.worker._diagnostic_requests)

    def test_request_history_is_bounded_private_and_failure_is_isolated(self):
        self.worker.targets["private-thread"] = 1
        for rid in range(600):
            self.worker._remember_diagnostic_request(rid, "private-thread")
        self.assertEqual(len(self.worker._diagnostic_requests), 512)
        self.assertNotIn("private-thread", json.dumps(self.worker._diagnostic_requests))
        with patch(
            "watched_kettle.features.project_activity.metadata.diagnostic_thread_ref",
            side_effect=broken,
        ):
            self.worker.sync_targets({"t": (1, 0, 3)}, 0)
        rid = next(iter(self.worker.pending))
        self.worker.response(rid, "thread/read", {}, {"thread": {"id": "t"}}, None)
        self.assertEqual(len(self.results), 1)

    def test_broken_sink_preserves_response_and_registration_source(self):
        self.worker.activity_diagnostics.callback = broken
        self.reply(data={"name": "private title"})
        self.assertEqual(len(self.results), 1)
        self.worker.activity_diagnostics.callback = (
            lambda event, **fields: self.records.append(("metadata", event, fields))
        )
        self.worker.sync_targets({"claude_code:t": (1, 1, 3)}, 0)
        self.assertEqual(
            entries(self.records, "metadata_target_registered")[-1]["source"],
            "claude_code",
        )

    def test_recovery_with_unchanged_metadata_refreshes_failure_snapshot(self):
        service = ConversationMetadataService(ProjectActivityService())
        self.addCleanup(service.close)
        self.worker.diagnostic_event.connect(service.receive_diagnostic)
        self.reply(data={"name": "title", "projectId": "p"})
        self.reply(error={"code": "timeout"})
        self.reply(data={"name": "title", "projectId": "p"})
        self.assertEqual(
            service.last_diagnostics[trace_ref("t")]["lookup_result"],
            "metadata_resolved",
        )

    def test_hash_preparation_failure_preserves_delivery_relation_and_removal(self):
        self.worker.targets["t"] = 1
        delivered, relations = [], []
        self.worker.delivered.connect(lambda *args: delivered.append(args))
        self.worker.relation.connect(lambda *args: relations.append(args))
        with patch(
            "watched_kettle.features.project_activity.metadata.diagnostic_ref",
            side_effect=broken,
        ):
            self.reply(data={"projectId": "p"}, stamp=(1, 0))
            self.worker.publish_relation("t")
            self.worker._remove_target("t")
        self.assertEqual(len(delivered), 1)
        self.assertEqual(len(relations), 1)
        self.assertNotIn("t", self.worker.targets)

    def test_service_snapshot_is_bounded_and_cleared_on_invalidation(self):
        service = ConversationMetadataService(ProjectActivityService())
        self.addCleanup(service.close)
        for index in range(600):
            service.receive_diagnostic(
                "metadata_failed", {"thread_ref": diagnostic_ref(str(index))}
            )
        self.assertEqual(len(service.last_diagnostics), 512)
        service.receive_diagnostic("metadata_invalidated", {"generation": 1})
        self.assertEqual(len(service.last_diagnostics), 0)

    def test_service_registration_and_stale_relation_diagnostics_are_isolated(self):
        activity = ProjectActivityService()
        service = ConversationMetadataService(activity)
        self.addCleanup(service.close)
        selected, records = [], []
        service.targets_changed.connect(lambda *args: selected.append(args))
        listen(service, records)
        with patch(
            "watched_kettle.features.project_activity.metadata.diagnostic_ref",
            side_effect=broken,
        ):
            activity.observe(
                dict(source="codex", event="prompt", session_id="t", agent_scope="main")
            )
        self.assertTrue(selected)
        self.assertIn("t", selected[-1][0])
        service.receive_relation("t", "p", "label", -1, 1, 0)
        self.assertEqual(
            entries(records, "metadata_delivery_discarded")[-1]["reason"],
            "stale_relation",
        )
        self.assertIsNone(activity.metadata["t"].project_id)


class DeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_scope_before_after_and_claude_parent_hashes(self):
        with TemporaryDirectory() as directory:
            server = CodexHookServer(
                server_name="test-diagnostics",
                spool_directory=Path(directory),
                managed_spool_directory=None,
                managed_hook_health_path=None,
            )
            records = []
            listen(server, records)
            server.log_monitor = SimpleNamespace(session_scope=lambda _id: "internal")
            payload = dict(
                source="codex",
                event="prompt",
                session_id="t",
                turn_id="1",
                agent_scope="main",
            )
            server._deliver_payload(payload, PIPE_TRANSPORT)
            server._deliver_payload(payload, JSONL_TRANSPORT)
            row = entries(records, "activity_input")[0]
            self.assertEqual(
                (row["incoming_scope"], row["known_scope"], row["scope"]),
                ("main", "internal", "internal"),
            )
            self.assertEqual(len(entries(records, "activity_input")), 1)
            server.trace = lambda event, **fields: records.append(
                ("trace", event, fields)
            )
            service = ProjectActivityService()
            service.trace = server.trace
            server.payload_received.connect(service.observe)
            child = dict(
                source="claude_code",
                event="prompt",
                session_id="child",
                parent_session_id="parent",
                turn_id="1",
                agent_scope="subagent",
            )
            server._deliver_payload(child, PIPE_TRANSPORT)
            observed = entries(records, "event_observed")[-1]
            received = entries(records, "event_received")[-1]
            self.assertEqual(observed["parent_ref"], received["parent_ref"])
            self.assertEqual(observed["thread_ref"], received["thread_ref"])
            server.log_monitor = None
            server.close()


class NavigationTests(unittest.TestCase):
    def test_failed_dispatch_fallback_expiry_and_context(self):
        router = NotificationActionRouter(
            opener=lambda url: url.toString() == "codex://"
        )
        router.app_available = True
        records = []
        listen(router, records)
        router.diagnostic_context = lambda ref: {
            "lookup_result": "metadata_failed",
            "card_ref": "abc",
        }
        token = router.register("thread", "t")
        self.assertFalse(router.open(token))
        result = entries(records, "navigation_result")[-1]
        self.assertEqual((result["result"], result["reason"]), ("fallback", "app_root"))
        self.assertEqual(
            entries(records, "navigation_context")[-1]["thread_ref"], trace_ref("t")
        )
        router.reset()
        self.assertFalse(router.open(token))
        self.assertEqual(
            entries(records, "navigation_result")[-1]["reason"], "token_expired"
        )
        self.assertNotIn(token, json.dumps(records))

    def test_dispatch_acceptance_is_not_screen_confirmation_and_sink_failure_is_safe(
        self,
    ):
        router = NotificationActionRouter(opener=lambda _url: True)
        router.app_available = True
        records = []
        listen(router, records)
        self.assertTrue(router.open(router.register("thread", "t")))
        self.assertEqual(
            entries(records, "navigation_result")[-1]["result"], "dispatch_accepted"
        )
        router.activity_diagnostics.callback = broken
        router.diagnostic_context = broken
        self.assertTrue(router.open(router.register("thread", "t")))
        with patch(
            "watched_kettle.features.notifications.actions.diagnostic_ref",
            side_effect=ValueError,
        ):
            self.assertTrue(router.open(router.register("thread", "t")))

    def test_failure_reason_types_and_bounds(self):
        router = NotificationActionRouter(opener=broken)
        router.app_available = True
        records = []
        listen(router, records)
        self.assertFalse(router.open(router.register("thread", "t")))
        self.assertEqual(
            entries(records, "navigation_result")[-1]["reason"], "dispatch_exception"
        )
        self.assertFalse(router.open(router.register("thread", "bad/id")))
        self.assertEqual(
            entries(records, "navigation_result")[-1]["reason"], "invalid_identifier"
        )
        router.app_available = False
        router.diagnostic_context = broken
        self.assertFalse(router.open(router.register("thread", "t")))
        self.assertEqual(
            entries(records, "navigation_result")[-1]["reason"], "handler_unconfirmed"
        )
        for index in range(600):
            router.register("thread", str(index))
        self.assertEqual(len(router._diagnostic_targets), 512)
        self.assertNotIn("private diagnostic failure", json.dumps(records))


class DisplayTests(unittest.TestCase):
    setUpClass = classmethod(helpers.CompletionTests.setUpClass.__func__)

    def setUp(self):
        helpers.CompletionTests.setUp(self)
        self.records = []
        listen(self.projects, self.records, "activity")
        listen(self.controller, self.records, "display")
        listen(self.router, self.records, "navigation")

    def tearDown(self):
        helpers.CompletionTests.tearDown(self)

    def event(self, thread="t", event="prompt", turn="1"):
        self.projects.observe(
            dict(
                source="codex",
                session_id=thread,
                event=event,
                turn_id=turn,
                agent_scope="main",
            )
        )

    def test_claude_completion_codex_work_and_extra_unknown_card_chain(self):
        for name in ("UserPromptSubmit", "Stop"):
            self.projects.observe(
                normalize_claude_code_hook(
                    dict(
                        hook_event_name=name,
                        session_id="claude",
                        prompt_id="1",
                        cwd="C:/Work/p",
                    )
                )
            )
        self.event()
        self.projects.set_metadata(ThreadMetadata("t", "p", title="private title"), 0)
        self.assertEqual(len(self.projects.bubble_cards), 2)
        self.event("ghost")
        self.assertEqual(len(self.projects.bubble_cards), 3)
        ref = trace_ref("ghost")
        row = next(
            r
            for r in entries(self.records, "bubble_row_membership")
            if r["thread_ref"] == ref
        )
        self.assertEqual(row["project_kind"], "unknown")
        self.assertTrue(
            any(
                r["card_ref"] == row["card_ref"] and r["visible"]
                for r in entries(self.records, "bubble_card_visibility")
            )
        )
        self.router.opener = lambda _url: False
        self.assertFalse(self.router.open(self.router.register("thread", "ghost")))
        self.event("ghost", "cancelled")
        self.now += 9
        self.controller._tick()
        self.assertTrue(
            any(
                r["thread_ref"] == ref and r["result"] == "removed"
                for r in entries(self.records, "bubble_row_membership")
            )
        )
        self.assertNotIn("private title", json.dumps(self.records))

    def test_move_hide_and_repeated_render_do_not_reset_state(self):
        self.event()
        self.projects.set_metadata(ThreadMetadata("t", "p", title="private title"), 0)
        self.projects.set_metadata(ThreadMetadata("t", "q", title="private title"), 0)
        self.assertEqual(
            entries(self.records, "bubble_row_membership")[-1]["result"], "moved"
        )
        before = len(self.records)
        self.pet.move(820, 880)
        self.controller._render()
        self.controller._render()
        self.assertEqual(len(self.records), before)
        self.controller.enabled = False
        self.controller._render()
        self.assertEqual(
            entries(self.records, "bubble_card_visibility")[-1]["reason"], "disabled"
        )
        self.assertEqual(self.projects.activities["t"].state, "running")
        self.controller.enabled = True
        self.controller._render()
        self.assertTrue(entries(self.records, "bubble_card_visibility")[-1]["visible"])

    def test_scroll_membership_is_not_claimed_as_row_visibility(self):
        for index in range(4):
            self.event(str(index))
            self.projects.set_metadata(ThreadMetadata(str(index), "p"), 0)
        self.assertEqual(len(self.controller._diagnostic_rows), 4)
        self.assertTrue(
            all(
                "visible" not in r
                for r in entries(self.records, "bubble_row_membership")
            )
        )
        self.controller.activity_diagnostics.callback = broken
        self.controller._render()
        self.assertTrue(self.controller.visible_windows)

    def test_runtime_wiring_default_logging_zip_and_failure_context(self):
        metadata = ConversationMetadataService(self.projects)
        self.addCleanup(metadata.close)
        runtime = SimpleNamespace(
            projects=self.projects,
            codex_server=SimpleNamespace(activity_diagnostics=DiagnosticRecorder()),
            metadata_service=metadata,
            bubbles=self.controller,
            action_router=self.router,
        )
        runtime._navigation_diagnostic_context = (
            lambda ref: ApplicationRuntime._navigation_diagnostic_context(runtime, ref)
        )
        with TemporaryDirectory() as directory:
            paths = AppPaths(Path(directory))
            configure_logging(paths.logs)
            try:
                ApplicationRuntime._enable_activity_diagnostics(runtime)
                self.event()
                metadata.receive_diagnostic(
                    "metadata_failed",
                    dict(
                        thread_ref=trace_ref("t"),
                        error_code="timeout",
                        epoch=1,
                        generation=2,
                        target_version=3,
                        request_id=4,
                    ),
                )
                self.router.opener = lambda _url: False
                self.assertFalse(self.router.open(self.router.register("thread", "t")))
                exported = DiagnosticsExporter(paths, 1).export(
                    Path(directory) / "support.zip"
                )
            finally:
                close_logging()
            with zipfile.ZipFile(exported) as archive:
                content = archive.read("logs/app.log").decode("utf-8")
            rows = [json.loads(line) for line in content.splitlines()]
            context = next(r for r in rows if r["event"] == "navigation_context")
            self.assertEqual(context["lookup_result"], "metadata_failed")
            self.assertEqual(context["lookup_error_code"], "timeout")
            self.assertEqual(context["lookup_generation"], 2)
            self.assertEqual(context["lookup_version"], 3)
            self.assertEqual(context["lookup_request_id"], 4)
            self.assertTrue(context["included"])
            self.assertTrue(context["visible"])
            self.assertIn("activity_diagnostics_enabled", content)

    def test_detailed_runtime_logs_lifecycle_once_and_ignores_logging_failure(self):
        metadata = ConversationMetadataService(self.projects)
        self.addCleanup(metadata.close)
        runtime = SimpleNamespace(
            projects=self.projects,
            codex_server=SimpleNamespace(activity_diagnostics=DiagnosticRecorder()),
            metadata_service=metadata,
            bubbles=self.controller,
            action_router=self.router,
            _navigation_diagnostic_context=lambda ref: {},
        )
        with patch("watched_kettle.application.runtime.log_event") as logger:
            ApplicationRuntime._enable_activity_diagnostics(runtime)
            ApplicationRuntime._enable_activity_trace(runtime)
            self.event()
            self.projects.set_metadata(ThreadMetadata("t", "p", title="title"), 0)
            names = [call.args[1] for call in logger.call_args_list]
            self.assertEqual(names.count("metadata_applied"), 1)
            self.assertEqual(names.count("event_observed"), 1)
        with patch("watched_kettle.application.runtime.log_event", side_effect=broken):
            ApplicationRuntime._enable_activity_diagnostics(runtime)
            ApplicationRuntime._enable_activity_trace(runtime)
            self.event(event="done")
        self.assertEqual(len(self.projects.visible_completions), 1)

    def test_suppressed_cards_and_cache_limit_are_observations_only(self):
        for index in range(4):
            self.event(str(index))
            self.projects.set_metadata(ThreadMetadata(str(index), str(index)), 0)
        self.assertTrue(
            any(
                r["reason"] == "project_limit" and not r["visible"]
                for r in entries(self.records, "bubble_card_visibility")
            )
        )

        def row(index):
            return SimpleNamespace(
                thread_id=str(index), source="codex", state="running", uncertain=False
            )

        cards = (
            SimpleNamespace(
                key="project:many",
                source="codex",
                kind="project",
                rows=tuple(row(index) for index in range(600)),
            ),
        )
        self.controller._diagnose_membership(cards)
        self.assertEqual(len(self.controller._diagnostic_rows), 512)
        self.assertEqual(len(self.projects.activities), 4)


if __name__ == "__main__":
    unittest.main()
