"""Project-first aggregation, saved order and the full history workspace."""

import unittest


from tests import test_usage_conversations as fixtures
from tests.test_pet_preferences import FakeSettings
from watched_kettle.app_preferences import ApplicationPreferences
from watched_kettle.features.usage.viewmodel import UsageViewModel
from watched_kettle.storage.usage_repository import VolatileUsageRepository
from watched_kettle.usage.conversation_models import UNCLASSIFIED_PROJECT_KEY
from watched_kettle.usage.identifiers import hash_identifier
from watched_kettle.usage.models import UsageSnapshot


class UsageProjectsTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.UsageConversationsTests.setUpClass.__func__)
    setUp = fixtures.UsageConversationsTests.setUp
    tearDown = fixtures.UsageConversationsTests.tearDown
    record = fixtures.UsageConversationsTests.record
    fill = fixtures.UsageConversationsTests.fill

    def project(self, i, project, name=None, thread=None, title=None, **kwargs):
        thread = thread or f"t-{i}"
        self.repo.append(self.record(i, thread=thread, **kwargs))
        self.repo.set_thread_labels(
            "a",
            {hash_identifier(thread): (title or f"대화 {i}", project, name or project)},
        )

    def test_project_count_search_and_order_are_not_limited_to_conversation_page(self):
        for i in range(230):
            self.project(i, "p", "프로젝트 10", title="찾을 제목" if i == 229 else None)
        self.project(300, "q", "프로젝트 2")
        page = self.repo.query_projects("a", order="name")
        self.assertEqual([r.project_key for r in page.records], ["q", "p"])
        self.assertEqual(page.records[1].conversation_count, 230)
        match = self.repo.query_projects("a", search="찾을 제목").records[0]
        self.assertEqual((match.conversation_count, match.matched_count), (230, 1))
        self.assertEqual(
            len(self.repo.query_conversations("a", project_key="p").records), 100
        )
        self.assertTrue(self.repo.query_conversations("a", project_key="p").has_more)
        self.assertEqual(self.repo.query_projects("b").records, ())
        self.assertEqual(
            self.repo.query_projects("a", search="프로젝트 10")
            .records[0]
            .matched_count,
            230,
        )

    def test_korean_names_special_groups_and_renames_are_stable(self):
        for i, name in enumerate(("다람쥐", "나무 10", "나무 2", "가방")):
            self.project(i, str(i), name)
        self.assertEqual(
            [r.name for r in self.repo.query_projects("a", order="name").records],
            ["가방", "나무 2", "나무 10", "다람쥐"],
        )
        self.project(8, "none", "프로젝트 없음")
        self.project(9, "unknown", "프로젝트 확인 불가")
        self.assertEqual(self.repo.query_projects("a").total_count, 5)
        self.repo.set_thread_labels(
            "a", {hash_identifier("t-0"): ("이름 변경", "0", "가나다")}
        )
        self.assertEqual(
            self.repo.query_projects("a", search="가나다").records[0].project_key, "0"
        )

    def test_unclassified_custom_position_changes_only_when_it_is_moved(self):
        self.project(0, "none", "프로젝트 없음")
        self.project(1, "unknown", "프로젝트 확인 불가")
        self.project(2, "p", "프로젝트 P")
        self.service.set_project_query(order="custom", custom=("none", "unknown", "p"))
        self.assertEqual(
            self.service.snapshot.project_custom_order, ("p", UNCLASSIFIED_PROJECT_KEY)
        )
        self.project(3, "q", "프로젝트 Q")
        self.service.project_history.publish()
        self.assertEqual(
            self.service.snapshot.project_custom_order,
            ("p", "q", UNCLASSIFIED_PROJECT_KEY),
        )
        self.assertFalse(self.service.move_usage_project("q", direction=1))
        self.assertEqual(
            self.service.snapshot.project_custom_order[-1], UNCLASSIFIED_PROJECT_KEY
        )
        self.assertTrue(
            self.service.move_usage_project(UNCLASSIFIED_PROJECT_KEY, direction=-1)
        )
        self.assertEqual(
            [row.project_key for row in self.service.snapshot.projects],
            ["p", UNCLASSIFIED_PROJECT_KEY, "q"],
        )
        self.service.set_project_query(order="recent")
        self.assertEqual(
            self.service.snapshot.projects[-1].project_key, UNCLASSIFIED_PROJECT_KEY
        )
        self.service.set_project_query(order="custom")
        self.assertEqual(
            self.service.snapshot.projects[1].project_key, UNCLASSIFIED_PROJECT_KEY
        )

    def test_custom_move_crosses_pages_and_appends_new_projects(self):
        for i in range(105):
            self.project(i, f"p-{i}", f"프로젝트 {i}")
        self.service.set_project_query(order="name")
        self.service.set_project_query(order="custom")
        before = self.service.snapshot.project_custom_order
        self.assertEqual(before[99:101], ("p-99", "p-100"))
        self.assertTrue(self.service.move_usage_project("p-99", direction=1))
        self.assertEqual(self.service.snapshot.project_offset, 100)
        self.assertEqual(self.service.snapshot.projects[0].project_key, "p-99")
        self.service.set_project_query(order="recent")
        self.service.set_project_query(order="custom")
        self.assertEqual(self.service.snapshot.project_custom_order[100], "p-99")
        self.project(1000, "new", "가장 먼저 정렬될 이름")
        self.service.project_history.publish()
        self.assertEqual(self.service.snapshot.project_custom_order[-1], "new")
        self.service.set_project_query(search="프로젝트", order="custom")
        self.assertFalse(self.service.move_usage_project("p-99", direction=-1))

    def test_order_persists_per_account_without_names(self):
        self.project(0, "hashed-project-a", "PRIVATE NAME A")
        self.project(1, "hashed-project-b", "PRIVATE NAME B")
        settings = FakeSettings()
        prefs = ApplicationPreferences(settings)
        vm = UsageViewModel(self.service, prefs)
        vm.set_project_query(order="custom")
        vm.move_usage_project(
            "hashed-project-b", target="hashed-project-a", before=True
        )
        self.assertEqual(
            prefs.load_usage_project_order("a"),
            ("custom", ("hashed-project-b", "hashed-project-a")),
        )
        self.assertNotIn("PRIVATE", str(settings.values))
        self.service._reset_account("signed_out")
        self.assertFalse(self.service.snapshot.project_custom_order)
        self.service.snapshot = UsageSnapshot(account_hash="b")
        vm.set_project_query()
        self.assertEqual(self.service.snapshot.project_order, "recent")
        self.service._reset_account("signed_out")
        self.service.snapshot = UsageSnapshot(account_hash="a")
        vm.set_project_query()
        self.assertEqual(
            self.service.snapshot.project_custom_order[:2],
            ("hashed-project-b", "hashed-project-a"),
        )

    def test_old_project_and_account_requests_do_not_change_new_selection(self):
        self.project(0, "p")
        self.project(1, "q")
        self.service.set_project_query()
        self.service.select_usage_project("q")
        before = self.service.snapshot
        self.assertFalse(
            self.service.set_conversation_query(offset=100, project_key="p")
        )
        self.assertEqual(before, self.service.snapshot)
        self.assertFalse(
            self.service.move_usage_project(
                "p", expected_account="b", expected_generation=0
            )
        )

    def test_volatile_project_results_match_sqlite(self):
        self.fill()
        other = VolatileUsageRepository(lambda: self.now)
        other.records = list(self.repo.load_all_for_maintenance())
        other.thread_labels = dict(self.repo.thread_labels)
        for search in ("", "일반", "windows"):
            for order in ("recent", "name", "custom"):
                self.assertEqual(
                    self.repo.query_projects("a", search, order),
                    other.query_projects("a", search, order),
                )
