"""Metadata contract tests without a live account or external process."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from watched_kettle.features.project_activity.service import (
    conversation_title,
    ProjectActivityService,
)
from watched_kettle.features.project_activity.metadata import (
    ConversationMetadataService,
)
from unittest.mock import patch

from watched_kettle.features.project_activity.metadata import _MetadataWorker
from watched_kettle.features.project_activity.service import ThreadMetadata
from watched_kettle.features.notifications.actions import installed_codex_app


class Client:
    ready = True

    def __init__(self):
        self.calls = []

    def request(self, method, params):
        self.calls.append((method, params))
        return len(self.calls)


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.desktop_state_path = Path(self.temp.name) / ".codex-global-state.json"
        self.worker = _MetadataWorker(Client, self.desktop_state_path)
        self.worker.client = Client()
        self.results = []
        self.worker.result.connect(
            lambda metadata, generation: self.results.append((metadata, generation))
        )

    def tearDown(self):
        self.temp.cleanup()

    def write_desktop_state(self, payload):
        self.desktop_state_path.write_text(json.dumps(payload), encoding="utf-8")

    def reply_with_cwd(self, cwd, **extra):
        self.worker.pending[1] = ("t", self.worker.generation)
        self.worker.response(
            1,
            "thread/read",
            {},
            {"thread": {"id": "t", "projectId": None, "cwd": cwd, **extra}},
            None,
        )
        return self.results[-1][0]

    def local_projects(self):
        return {
            "local-projects": {
                "todo": {"name": "Todo_app", "rootPaths": ["C:/Work/Todo_app"]}
            }
        }

    def test_missing_assignment_resolves_actual_project_card_from_cwd(self):
        self.write_desktop_state(self.local_projects())
        activity = ProjectActivityService(now=lambda: 100.0)
        activity.observe(
            dict(source="codex", session_id="t", event="prompt", agent_scope="main")
        )
        self.worker.result.connect(activity.set_metadata)
        metadata = self.reply_with_cwd("C:/Work/Todo_app", name="프로그램 점검")
        self.assertEqual(metadata.project_id, "todo")
        self.assertEqual(activity.cards[0].label, "Todo_app")
        self.assertEqual(activity.cards[0].rows[0].title, "프로그램 점검")

    def test_cwd_matching_normalizes_windows_paths_and_accepts_descendants(self):
        self.write_desktop_state(self.local_projects())
        for cwd in (
            "c:\\WORK\\todo_app\\",
            "C:/Work/Todo_app/src",
            "C:/Work/other/../Todo_app",
        ):
            with self.subTest(cwd=cwd):
                self.assertEqual(self.reply_with_cwd(cwd).project_id, "todo")

    def test_similar_names_and_invalid_cwds_stay_unknown(self):
        self.write_desktop_state(self.local_projects())
        for cwd in (
            "D:/Work/Todo_app",
            "C:/Work/Todo_app-copy",
            "C:/Other/Todo_app",
            "C:/Work/Todo_app/../other",
            "Todo_app",
            "C:Work/Todo_app",
            "/Work/Todo_app",
            "",
            None,
            42,
        ):
            with self.subTest(cwd=cwd):
                self.assertIsNone(self.reply_with_cwd(cwd).project_id)

    def test_explicit_projectless_membership_prevents_cwd_inference(self):
        payload = self.local_projects()
        payload["projectless-thread-ids"] = ["t"]
        self.write_desktop_state(payload)
        self.assertEqual(self.reply_with_cwd("C:/Work/Todo_app").project_id, "")

    def test_explicit_assignment_precedes_projectless_and_cwd(self):
        payload = self.local_projects()
        payload["thread-project-assignments"] = {"t": {"projectId": "assigned"}}
        payload["projectless-thread-ids"] = ["t"]
        self.write_desktop_state(payload)
        self.assertEqual(self.reply_with_cwd("C:/Work/Todo_app").project_id, "assigned")

    def test_api_assignment_including_projectless_precedes_desktop_and_cwd(self):
        payload = self.local_projects()
        payload["thread-project-assignments"] = {"t": {"projectId": "assigned"}}
        self.write_desktop_state(payload)
        for project in ("api-project", ""):
            with self.subTest(project=project):
                metadata = self.reply_with_cwd("C:/Work/Todo_app", projectId=project)
                self.assertEqual(metadata.project_id, project)

    def test_nested_project_root_takes_precedence_over_parent(self):
        payload = self.local_projects()
        payload["local-projects"]["parent"] = {"rootPaths": ["C:/Work"]}
        self.write_desktop_state(payload)
        self.assertEqual(self.reply_with_cwd("C:/Work/Todo_app/src").project_id, "todo")

    def test_shared_project_root_is_ambiguous(self):
        payload = self.local_projects()
        payload["local-projects"]["duplicate"] = {"rootPaths": ["c:/work/todo_app/"]}
        self.write_desktop_state(payload)
        self.assertIsNone(self.reply_with_cwd("C:/Work/Todo_app").project_id)

    def test_multiple_roots_and_unc_paths_use_one_project_identity(self):
        payload = self.local_projects()
        payload["local-projects"]["todo"]["rootPaths"].extend(
            ["C:/Work/Todo_app/", "//server/share/todo"]
        )
        self.write_desktop_state(payload)
        for cwd in ("C:/Work/Todo_app", "\\\\SERVER\\share\\todo\\src"):
            with self.subTest(cwd=cwd):
                self.assertEqual(self.reply_with_cwd(cwd).project_id, "todo")

    def test_invalid_root_schema_does_not_infer_membership(self):
        for roots in ("C:/Work/Todo_app", [None, 42, "Todo_app", "C:Work/Todo_app"]):
            with self.subTest(roots=roots):
                payload = self.local_projects()
                payload["local-projects"]["todo"]["rootPaths"] = roots
                self.write_desktop_state(payload)
                self.worker.desktop_state_mtime = None
                self.assertIsNone(self.reply_with_cwd("C:/Work/Todo_app").project_id)

    def test_relation_poll_uses_cwd_and_observes_new_explicit_assignment(self):
        payload = self.local_projects()
        self.write_desktop_state(payload)
        self.reply_with_cwd("C:/Work/Todo_app")
        self.worker.targets["t"] = 1
        relations = []
        self.worker.relation.connect(lambda *args: relations.append(args))
        self.worker.publish_relation("t")
        self.assertEqual(relations[-1][1:3], ("todo", "Todo_app"))
        payload["thread-project-assignments"] = {"t": {"projectId": "moved"}}
        self.write_desktop_state(payload)
        self.worker.desktop_state_mtime = None
        self.worker.publish_relation("t")
        self.assertEqual(relations[-1][1], "moved")

    def test_new_null_api_assignment_does_not_restore_stale_project_on_poll(self):
        self.write_desktop_state(self.local_projects())
        self.reply_with_cwd("C:/Work/Todo_app", projectId="old")
        self.assertEqual(self.reply_with_cwd("C:/Work/Todo_app").project_id, "todo")
        self.worker.targets["t"] = 1
        relations = []
        self.worker.relation.connect(lambda *args: relations.append(args))
        self.worker.publish_relation("t")
        self.assertEqual(relations[-1][1], "todo")

    def test_cwd_evidence_is_cleared_when_target_or_account_is_invalidated(self):
        self.write_desktop_state(self.local_projects())
        self.reply_with_cwd("C:/Work/Todo_app")
        self.worker._remove_target("t")
        self.assertIsNone(self.worker.project_for_thread("t"))
        self.reply_with_cwd("C:/Work/Todo_app")
        self.worker.invalidate(1)
        self.worker.refresh_desktop_project_index()
        self.assertIsNone(self.worker.project_for_thread("t"))

    def test_reads_only_requested_metadata_and_never_turn_contents(self):
        self.worker.request("thread", 0)
        self.worker.pump()
        method, params = self.worker.client.calls[-1]
        self.assertEqual(
            (method, params),
            ("thread/read", {"threadId": "thread", "includeTurns": False}),
        )
        rid = len(self.worker.client.calls)
        self.worker.response(
            rid,
            method,
            params,
            {
                "thread": {
                    "id": "thread",
                    "projectId": "p",
                    "cwd": "C:/Work",
                    "preview": "SECRET",
                    "name": "실제 대화 제목",
                    "turns": [{"secret": "SECRET"}],
                }
            },
            None,
        )
        metadata, generation = self.results[0]
        self.assertEqual(metadata.title, "실제 대화 제목")
        self.assertNotIn("SECRET", repr(metadata))
        self.assertEqual(generation, 0)

    def test_title_preserves_special_characters_and_does_not_use_preview(self):
        self.assertEqual(
            conversation_title("  제목/경로 & <검토>\n다음\x00줄 "),
            "제목/경로 & <검토> 다음 줄",
        )
        for value in (None, 42, " "):
            self.assertEqual(conversation_title(value), "Codex 대화")
        self.worker.pending[1] = ("t", 0)
        self.worker.response(
            1, "thread/read", {}, {"thread": {"id": "t", "preview": "SECRET"}}, None
        )
        self.assertEqual(self.results[-1][0].title, "Codex 대화")

    def test_missing_project_id_is_confirmed_as_projectless(self):
        self.write_desktop_state({"projectless-thread-ids": ["t"]})
        self.worker.pending[1] = ("t", 0)
        self.worker.response(
            1,
            "thread/read",
            {},
            {
                "thread": {
                    "id": "t",
                    "cwd": "C:/Generated/new-chat",
                    "name": "프로젝트 없는 작업",
                }
            },
            None,
        )
        metadata, generation = self.results[-1]
        self.assertEqual(generation, 0)
        self.assertEqual(metadata.project_id, "")
        self.assertEqual(metadata.project_key, "unassigned:codex")
        self.assertEqual(metadata.card_kind, "unassigned")
        self.assertEqual(metadata.label, "프로젝트 없는 대화")

    def test_missing_project_id_uses_desktop_assignment_before_projectless(self):
        self.write_desktop_state(
            {
                "thread-project-assignments": {
                    "t": {"projectKind": "local", "projectId": "project"}
                },
                "projectless-thread-ids": ["t"],
                "local-projects": {
                    "project": {"id": "project", "name": "실제 프로젝트"}
                },
            }
        )
        self.worker.pending[1] = ("t", 0)
        self.worker.response(
            1,
            "thread/read",
            {},
            {"thread": {"id": "t", "cwd": "C:/Work", "name": "작업"}},
            None,
        )
        metadata, _generation = self.results[-1]
        self.assertEqual(metadata.project_id, "project")
        self.assertEqual(metadata.project_key, "project:project")
        self.assertEqual(metadata.card_kind, "project")
        self.assertEqual(metadata.label, "실제 프로젝트")

    def test_missing_project_id_without_desktop_relation_stays_unknown(self):
        self.write_desktop_state({})
        self.worker.pending[1] = ("t", 0)
        self.worker.response(
            1,
            "thread/read",
            {},
            {"thread": {"id": "t", "cwd": "C:/Work", "name": "작업"}},
            None,
        )
        metadata, _generation = self.results[-1]
        self.assertIsNone(metadata.project_id)
        self.assertEqual(metadata.project_key, "thread:t")
        self.assertEqual(metadata.card_kind, "unknown")

    def test_target_refresh_retains_displayed_completions_without_duplicate_registration(
        self,
    ):
        activity = ProjectActivityService()
        service = ConversationMetadataService(activity)
        now = [100.0]
        service._clock = lambda: now[0]
        calls = []
        service.requested.connect(lambda thread, generation: calls.append(thread))
        activity.observe(
            dict(source="codex", event="prompt", session_id="active", turn_id="1")
        )
        activity.observe(
            dict(source="codex", event="prompt", session_id="ended", turn_id="1")
        )
        activity.observe(
            dict(source="codex", event="done", session_id="ended", turn_id="1")
        )
        calls.clear()
        service.refresh_active()
        self.assertEqual(calls, [])
        now[0] += 30
        service.refresh_active()
        self.assertEqual(calls, [])
        self.assertEqual(set(service._requested), {"active", "ended"})
        service.close()

    def test_project_pages_follow_cursor_and_stop_repeated_cursor(self):
        self.worker.control_request("project/list", {})
        self.worker.response(
            1,
            "project/list",
            {},
            {"data": [{"id": "p", "name": "Project"}], "nextCursor": "page2"},
            None,
        )
        self.assertEqual(
            self.worker.client.calls[-1], ("project/list", {"cursor": "page2"})
        )
        self.worker.response(
            2, "project/list", {}, {"data": [], "nextCursor": "page2"}, None
        )
        self.assertEqual(len(self.worker.client.calls), 2)

    def test_old_generation_and_mismatched_id_are_discarded(self):
        self.worker.pending[1] = ("thread", 0)
        self.worker.generation = 1
        self.worker.response(1, "thread/read", {}, {"thread": {"id": "thread"}}, None)
        self.assertEqual(self.results, [])
        self.worker.pending[2] = ("thread", 1)
        self.worker.response(2, "thread/read", {}, {"thread": {"id": "other"}}, None)
        self.assertEqual(self.results, [])

    def test_queue_is_bounded_and_errors_leave_fallback_available(self):
        for index in range(600):
            self.worker.request(str(index), 0)
        self.assertEqual(len(self.worker.queue), 512)
        self.worker.pending[1] = ("x", 0)
        self.worker.response(1, "thread/read", {}, None, {"code": "timeout"})
        self.assertEqual(self.results, [])
        self.assertEqual(ThreadMetadata("x").label, "Codex 작업")

    def test_account_changes_invalidate_session_metadata(self):
        resets = []
        self.worker.reset.connect(lambda: resets.append(True))
        for index, account in enumerate(({"id": "a"}, {"id": "b"}, None), 1):
            self.worker.control_request("account/read", {})
            self.worker.response(index, "account/read", {}, {"account": account}, None)
        self.assertEqual(len(resets), 2)

    def test_packaged_codex_registration_is_version_independent_fallback(self):
        with (
            patch("winreg.OpenKey", side_effect=FileNotFoundError),
            patch("pathlib.Path.is_dir", return_value=True) as is_dir,
        ):
            self.assertTrue(installed_codex_app())
        is_dir.assert_called_once_with()

    def test_inaccessible_uri_handler_is_a_capability_failure(self):
        with (
            patch("winreg.OpenKey", side_effect=PermissionError),
            patch("pathlib.Path.is_dir", side_effect=PermissionError),
        ):
            self.assertFalse(installed_codex_app())
