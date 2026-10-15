from dataclasses import replace
from types import SimpleNamespace
import unittest

from PySide6.QtWidgets import QApplication

from watched_kettle.features.tasks.candidates import CandidateAccumulator
from watched_kettle.features.tasks.models import source_version
from watched_kettle.features.tasks.worker import TaskWorker
from watched_kettle.features.tasks.viewmodel import TasksViewModel
from tests.task_support import PreviewTaskService


def thread(identity, project, updated):
    return {
        "id": identity,
        "projectId": project,
        "updatedAt": updated,
        "cwd": "C:/example",
    }


class TaskDiscoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.worker = TaskWorker(None, None)
        self.reads = []

        def read(identity):
            self.reads.append(identity)
            self.worker.catalog.reader.identity = identity

        self.worker.catalog = SimpleNamespace(
            enabled=True,
            account="account",
            archived=False,
            stale=False,
            excluded_projects=set(),
            reader=SimpleNamespace(identity=""),
            threads={
                f"{p}-{i}": thread(f"{p}-{i}", p, i)
                for p in ("a", "b")
                for i in range(14)
            },
            read_thread=read,
        )

    def tearDown(self):
        self.worker.deleteLater()
        self.app.processEvents()

    def test_recent_ten_per_project_and_old_page_eviction(self):
        groups = self.worker.recent_groups()
        self.assertEqual({p: len(ids) for p, ids in groups.items()}, {"a": 10, "b": 10})
        self.assertNotIn("a-0", groups["a"])
        self.worker.candidates = {i: () for i in self.worker.catalog.threads}
        self.worker.versions = {i: "version" for i in self.worker.catalog.threads}
        self.worker.visible_history = {"a-0"}
        self.worker.prune_analysis()
        self.assertEqual(len(self.worker.candidates), 21)
        self.worker.visible_history = {"b-0"}
        self.worker.prune_analysis()
        self.assertNotIn("a-0", self.worker.candidates)
        self.assertNotIn("a-0", self.worker.versions)

    def test_selected_read_has_priority_then_projects_alternate(self):
        self.worker.queue_read("b-0")
        self.assertEqual(self.reads, ["b-0"])
        self.worker.catalog.reader.identity = ""
        self.worker.analyze_next()
        self.assertEqual(self.reads[-1], "a-13")
        self.worker.catalog.reader.identity = ""
        self.worker.analyzed_stamps["a-13"] = 13
        self.worker.analyze_next()
        self.assertEqual(self.reads[-1], "b-13")

    def test_excluded_and_subagent_threads_are_not_automatic_candidates(self):
        self.worker.catalog.excluded_projects.add("a")
        self.worker.catalog.threads["b-13"]["parentThreadId"] = "parent"
        groups = self.worker.recent_groups()
        self.assertNotIn("a", groups)
        self.assertNotIn("b-13", groups["b"])
        self.worker.catalog.archived = True
        self.assertEqual(self.worker.recent_groups(), {})

    def test_older_page_does_not_expand_default_analysis(self):
        service = PreviewTaskService()
        service.state["threads"] = list(self.worker.catalog.threads.values())
        service.state["projects"] = [{"id": "a"}, {"id": "b"}]
        vm = TasksViewModel(service)
        self.assertEqual(len(vm.thread_rows()), 10)
        vm.set_page(1)
        self.assertEqual(len(vm.thread_rows()), 4)
        vm.select_thread("a-0")
        self.assertEqual(service.calls[-1], ("read", "a-0"))
        vm.set_project("b")
        self.assertEqual(vm.page, 0)
        self.assertEqual(service.calls[-1][1]["history"], ())

    def test_assistant_completion_is_hidden_report_not_execution_authority(self):
        parser = CandidateAccumulator(thread("t", "p", 1))
        parser.feed("1", {"id": "a", "type": "agentMessage", "text": "- [ ] 화면 수정"})
        parser.feed("2", {"id": "b", "type": "agentMessage", "text": "- [x] 화면 수정"})
        candidate = parser.finish(source_version([])).candidates[0]
        self.assertTrue(candidate.reported_complete)
        self.assertFalse(candidate.confirmed_plan)
        parser.feed(
            "3",
            {
                "id": "c",
                "type": "userMessage",
                "content": [{"type": "text", "text": "- [ ] 화면  수정"}],
            },
        )
        renewed = parser.finish(source_version([])).candidates
        self.assertEqual(len(renewed), 1)
        self.assertTrue(renewed[0].confirmed_plan)
        self.assertFalse(renewed[0].reported_complete)

    def test_review_of_old_saved_task_keeps_version_until_dialog_closes(self):
        service = PreviewTaskService()
        spec = replace(service.spec, thread_id="a-0", project_id="a")
        self.worker.repository = SimpleNamespace(
            require=lambda _id: SimpleNamespace(
                id="saved", state="draft", batch_id="", revision=1, spec=spec
            )
        )
        self.worker.versions["a-0"] = "new-version"
        self.worker.finish_review(
            {"kind": "item", "id": "saved", "token": "test"},
            {**thread("a-0", "a", 0), "sourceVersion": "new-version"},
            SimpleNamespace(candidates=()),
        )
        self.worker.prune_analysis()
        self.assertEqual(self.worker.versions["a-0"], "new-version")
