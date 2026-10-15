"""Behavioral coverage for project aggregation, delivery and desktop layout."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace
import unittest
from unittest.mock import patch
from contextlib import ExitStack
from dataclasses import replace

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QApplication, QWidget

from watched_kettle.features.project_activity.service import (
    ConversationRow,
    ProjectCard,
    ProjectActivityService,
    ThreadMetadata,
)
from watched_kettle.features.notifications.models import NoticeRequest
from watched_kettle.features.notifications.service import NotificationService
from watched_kettle.features.notifications.actions import NotificationActionRouter
from watched_kettle.ui.actionable_bubbles import ActionableBubbleController
from watched_kettle.ui.speech_bubble_window import bubble_stack_positions


class Clock:
    value = 100.0

    def __call__(self):
        return self.value


class ProjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.clock = Clock()
        self.projects = ProjectActivityService(now=self.clock)

    def event(self, thread="a", event="prompt", turn="1", **extra):
        return self.projects.observe(
            dict(source="codex", session_id=thread, event=event, turn_id=turn, **extra)
        )

    def meta(self, thread, project="p", **extra):
        self.projects.set_metadata(
            ThreadMetadata(thread, project, "프로젝트", **extra),
            self.projects.generation,
        )

    def test_three_conversations_one_project_and_waiting_excludes_running(self):
        for thread in ("a", "b", "c"):
            self.event(thread)
            self.meta(thread)
        self.event("b", "waiting", event_id="request")
        (card,) = self.projects.cards
        self.assertEqual((card.running, card.waiting, len(card.rows)), (2, 1, 3))
        self.assertEqual(card.rows[0].thread_id, "b")
        self.event("a", "done")
        self.clock.value += 9
        self.projects.expire()
        (card,) = self.projects.cards
        self.assertEqual((card.running, card.waiting), (1, 1))

    def test_last_completion_expires_and_hidden_results_do_not_reappear(self):
        self.event()
        self.event(event="done")
        self.assertEqual(self.projects.cards[0].done, 1)
        self.assertEqual(len(self.projects.visible_completions), 1)
        self.clock.value += 9
        self.projects.expire()
        self.assertEqual(self.projects.cards[0].done, 1)
        self.assertEqual(self.projects.recent[-1].state, "done")
        self.clock.value += 291
        self.projects.expire()
        self.assertEqual(self.projects.visible_completions, ())

    def test_summary_omits_zero_counts_including_recent_terminal_results(self):
        for states, expected in (
            (("running", "review", "waiting"), "확인 필요 1개 · 작업 중 2개"),
            (("running", "review"), "작업 중 2개"),
            (("waiting",), "확인 필요 1개"),
            (("done", "failed", "cancelled"), "완료 1개"),
        ):
            with self.subTest(states=states):
                card = ProjectCard(
                    "p",
                    "프로젝트",
                    tuple(
                        ConversationRow(str(i), "대화", state, i)
                        for i, state in enumerate(states)
                    ),
                    0,
                )
                self.assertEqual(card.summary, expected)

    def test_summary_transitions_preserve_terminal_lifetime(self):
        self.event()
        self.assertEqual(self.projects.cards[0].summary, "작업 중 1개")
        self.event(event="waiting", event_id="approval")
        self.assertEqual(self.projects.cards[0].summary, "확인 필요 1개")
        self.event(event="tool_end", event_id="approval")
        self.assertEqual(self.projects.cards[0].summary, "작업 중 1개")
        self.event(event="done")
        self.assertEqual(self.projects.cards[0].done, 1)
        self.clock.value += 7
        self.projects.expire()
        self.assertEqual(len(self.projects.visible_completions), 1)
        self.clock.value += 1
        self.projects.expire()
        self.assertEqual(self.projects.cards[0].done, 1)

    def test_late_completion_and_replay_cannot_end_new_turn(self):
        self.event()
        self.event(turn="2")
        self.assertFalse(self.event(event="done", turn="1"))
        self.assertFalse(self.event(event="done", turn=""))
        self.assertEqual(self.projects.cards[0].running, 1)
        self.event(event="done", turn="2")
        self.assertFalse(self.event(turn="2"))

    def test_waits_clear_only_on_correlated_response(self):
        self.event()
        self.event(event="waiting", event_id="w1")
        self.event(event="waiting", event_id="w2")
        self.event(event="tool_end", event_id="w1")
        self.assertEqual(self.projects.cards[0].waiting, 1)
        self.event(event="tool_end", event_id="w2")
        self.assertEqual(self.projects.cards[0].waiting, 0)

    def test_unidentified_routine_events_can_resume_a_wait(self):
        self.event()
        self.event(event="tool_start")
        self.event(event="waiting")
        self.event(event="tool_start")
        self.assertEqual(self.projects.cards[0].waiting, 0)

    def test_child_folds_into_parent_and_unresolved_child_is_held(self):
        self.event("child", agent_scope="subagent")
        self.assertEqual(self.projects.cards, ())
        self.meta("parent")
        self.meta("child", parent_thread_id="parent")
        self.event("parent")
        self.assertEqual(len(self.projects.cards[0].rows), 1)
        self.event("child", "waiting", agent_scope="subagent", event_id="w")
        self.assertEqual(self.projects.cards[0].waiting, 1)

    def test_metadata_recovery_and_old_generation_response(self):
        self.event()
        self.assertEqual(self.projects.cards[0].key, "thread:a")
        self.meta("a")
        self.assertEqual(self.projects.cards[0].key, "project:p")
        old = self.projects.generation
        self.projects.reset()
        self.projects.set_metadata(ThreadMetadata("a", "old"), old)
        self.assertEqual(self.projects.metadata, {})

    def test_unknown_metadata_stays_per_thread_until_project_is_known(self):
        one = ThreadMetadata("a", cwd="C:/Work/Demo")
        two = ThreadMetadata("b", cwd="c:\\work\\demo\\")
        self.assertEqual(one.project_key, "thread:a")
        self.assertEqual(two.project_key, "thread:b")
        self.assertEqual(one.card_kind, "unknown")
        self.assertEqual(one.label, "Demo")

    def test_projectless_threads_ignore_cwd_and_share_one_card(self):
        for thread, cwd, title in (
            ("a", "C:/Generated/new-chat", "첫 대화"),
            ("b", "D:/Other/new-chat-2", "둘째 대화"),
        ):
            self.event(thread)
            self.projects.set_metadata(
                ThreadMetadata(thread, "", cwd=cwd, title=title),
                self.projects.generation,
            )

        (card,) = self.projects.cards
        self.assertEqual(card.key, "unassigned:codex")
        self.assertEqual(card.kind, "unassigned")
        self.assertEqual(card.label, "프로젝트 없는 대화")
        self.assertEqual({row.thread_id for row in card.rows}, {"a", "b"})

    def test_projectless_and_project_threads_remain_separate(self):
        self.event("assigned")
        self.meta("assigned")
        self.event("unassigned")
        self.projects.set_metadata(
            ThreadMetadata("unassigned", "", cwd="C:/Generated/new-chat"),
            self.projects.generation,
        )
        self.assertEqual(
            {(card.key, card.kind) for card in self.projects.cards},
            {("project:p", "project"), ("unassigned:codex", "unassigned")},
        )

    def test_idle_projectless_metadata_does_not_create_a_card(self):
        self.projects.set_metadata(
            ThreadMetadata("idle", "", cwd="C:/Generated/new-chat"),
            self.projects.generation,
        )
        self.assertEqual(self.projects.cards, ())

    def test_metadata_rekeys_unknown_activity_without_duplication(self):
        self.event("a")
        self.assertEqual(
            [(card.key, card.kind) for card in self.projects.cards],
            [("thread:a", "unknown")],
        )
        self.projects.set_metadata(
            ThreadMetadata("a", "", cwd="C:/Generated/new-chat"),
            self.projects.generation,
        )
        self.assertEqual(
            [(card.key, card.kind, len(card.rows)) for card in self.projects.cards],
            [("unassigned:codex", "unassigned", 1)],
        )

    def test_equal_priority_order_is_stable_and_history_is_bounded(self):
        for index in range(25):
            self.event(str(index))
            self.meta(str(index), str(index))
        before = tuple(c.key for c in self.projects.cards)
        self.event("0", "tool_start", event_id="tool")
        self.assertEqual(tuple(c.key for c in self.projects.cards), before)
        self.assertEqual(len(self.projects.recent), 20)

    def test_heartbeat_refreshes_running_and_stale_limits_are_state_specific(self):
        projects = ProjectActivityService(
            now=self.clock,
            running_stale_seconds=60,
            tool_stale_seconds=180,
        )
        projects.observe(
            dict(source="codex", event="prompt", session_id="plain", turn_id="1")
        )
        self.clock.value += 59
        projects.expire()
        self.assertIn("plain", projects.activities)
        projects.observe(
            dict(
                source="codex",
                event="heartbeat",
                session_id="plain",
                turn_id="1",
            )
        )
        self.clock.value += 60
        projects.expire()
        self.assertIn("plain", projects.activities)
        self.assertTrue(
            projects.observe(
                dict(
                    source="codex",
                    event="done",
                    session_id="plain",
                    turn_id="1",
                )
            )
        )
        self.assertIn("plain", projects.activities)

        projects.observe(
            dict(source="codex", event="prompt", session_id="tool", turn_id="2")
        )
        projects.observe(
            dict(
                source="codex",
                event="tool_start",
                session_id="tool",
                turn_id="2",
                event_id="call",
            )
        )
        self.clock.value += 179
        projects.expire()
        self.assertIn("tool", projects.activities)
        self.clock.value += 1
        projects.expire()
        self.assertTrue(projects.activities["tool"].uncertain)
        self.assertEqual(projects.stale_expired_count, 2)

    def test_waiting_does_not_expire_without_a_correlated_result(self):
        self.event()
        self.event(event="waiting", event_id="approval")
        self.clock.value += 10_000
        self.projects.expire()
        self.assertEqual(self.projects.cards[0].waiting, 1)
        self.event(event="tool_end", event_id="approval")
        self.clock.value += 60
        self.projects.expire()
        self.assertTrue(self.projects.cards[0].rows[0].uncertain)


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.service = NotificationService()
        self.service.managed_delivery = True
        self.service.now = self.clock

    def submit(self, message, category="system", **extra):
        return self.service.submit(
            NoticeRequest("system", message, category=category, **extra)
        )

    def test_independent_lanes_and_nonpreemptive_priority_queue(self):
        self.submit("first")
        (first,) = self.service.candidates()
        self.service.shown(first.record_id)
        self.submit("urgent", urgency="high")
        self.submit("schedule", category="schedule")
        selected = self.service.candidates()
        self.assertEqual([r.message for r in selected], ["first", "schedule"])
        self.clock.value += 8
        self.assertEqual(self.service.candidates()[0].message, "urgent")
        self.assertFalse(
            next(
                r for r in self.service.snapshot.recent if r.message == "first"
            ).confirmed
        )

    def test_queued_alarm_does_not_expire_before_visible(self):
        self.submit("alarm", category="schedule")
        self.clock.value += 1000
        (record,) = self.service.candidates()
        self.service.shown(record.record_id)
        self.clock.value += 7
        self.assertEqual(len(self.service.candidates()), 1)
        self.clock.value += 1
        self.assertEqual(self.service.candidates(), ())

    def test_duplicate_does_not_extend_lifetime_and_higher_warning_replaces(self):
        self.submit(
            "70",
            category="usage",
            deduplication_key="window70",
            replacement_key="window",
        )
        (record,) = self.service.candidates()
        self.service.shown(record.record_id)
        self.clock.value += 7
        self.assertFalse(
            self.submit("70", category="usage", deduplication_key="window70")
        )
        self.clock.value += 1
        self.assertEqual(self.service.candidates(), ())
        self.submit("90", category="usage", replacement_key="window")
        self.assertEqual([r.message for r in self.service.snapshot.recent], ["90"])

    def test_focus_keeps_unread_history_without_replaying(self):
        self.submit("before")
        self.service.set_delivery_enabled(False)
        self.submit("during", category="schedule")
        self.service.set_delivery_enabled(True)
        self.assertEqual(self.service.candidates(), ())
        self.assertTrue(all(not r.confirmed for r in self.service.snapshot.recent))

    def test_bounded_history_confirmation_and_expired_tokens(self):
        for i in range(55):
            self.submit(str(i))
        self.assertEqual(len(self.service.snapshot.recent), 50)
        record = self.service.snapshot.recent[0]
        self.service.confirm(record.record_id)
        self.assertTrue(self.service.snapshot.recent[0].confirmed)
        router = NotificationActionRouter(opener=lambda _: False)
        token = router.register("thread", "valid-id")
        self.assertFalse(router.open(token))
        router.reset()
        self.assertFalse(router.open(token))


class NavigationTests(unittest.TestCase):
    def test_registered_handler_uses_conversation_id_not_title(self):
        urls = []
        router = NotificationActionRouter(
            opener=lambda url: urls.append(url.toString()) or True
        )
        router.app_available = True
        for thread in ("thread-one", "thread-two"):
            self.assertTrue(router.open(router.register("thread", thread)))
        self.assertEqual(
            urls, ["codex://threads/thread-one", "codex://threads/thread-two"]
        )

    def test_fallback_is_not_reported_as_successful_thread_navigation(self):
        urls, errors = [], []
        router = NotificationActionRouter(
            opener=lambda url: urls.append(url.toString())
            or url.toString() == "codex://"
        )
        router.app_available = True
        router.failed.connect(errors.append)
        token = router.register("thread", "target")
        self.assertFalse(router.open(token))
        self.assertEqual(urls, ["codex://threads/target", "codex://"])
        self.assertIn(token, router.targets)
        self.assertTrue(errors)
        router.reset()
        self.assertFalse(router.open(token))

    def test_missing_handler_never_dispatches_thread_link(self):
        urls = []
        router = NotificationActionRouter(
            opener=lambda url: urls.append(url.toString()) or True
        )
        router.app_available = False
        self.assertFalse(router.open(router.register("thread", "target")))
        self.assertEqual(urls, [])

    def test_exact_link_exception_still_opens_codex_root(self):
        urls = []

        def opener(url):
            value = url.toString()
            urls.append(value)
            if value != "codex://":
                raise OSError("unsupported")
            return True

        router = NotificationActionRouter(opener=opener)
        router.app_available = True
        self.assertFalse(router.open(router.register("thread", "target")))
        self.assertEqual(urls, ["codex://threads/target", "codex://"])


class FakePet(QWidget):
    always_on_top = True


class CardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.pet = FakePet()
        self.pet.setGeometry(800, 900, 100, 110)
        self.projects = ProjectActivityService()
        self.notifications = NotificationService()
        self.router = NotificationActionRouter()
        self.controller = ActionableBubbleController(
            self.pet, self.projects, self.notifications, self.router
        )
        self.screen = patch(
            "watched_kettle.ui.actionable_bubbles.QApplication.screenAt",
            return_value=SimpleNamespace(
                availableGeometry=lambda: QRect(0, 0, 1920, 1080)
            ),
        )
        self.screen.start()
        self.pet.show()

    def tearDown(self):
        self.controller.close()
        self.pet.close()
        self.app.processEvents()
        self.screen.stop()

    def test_runtime_then_pet_shutdown_after_deferred_window_deletion(self):
        from shiboken6 import isValid

        self.populate()
        self.controller._render()
        windows = self.controller.visible_windows
        measurer = self.controller._measurer
        self.assertTrue(windows)
        self.controller.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertFalse(isValid(measurer))
        self.assertTrue(all(not isValid(window) for window in windows))
        # Runtime shutdown releases the windows before the pet's Close/Hide.
        self.controller.close()
        self.controller.owner_hidden()
        self.controller.reposition()
        self.assertEqual(self.controller.visible_windows, ())

    def populate(self):
        for project in range(4):
            for task in range(3):
                tid = f"{project}-{task}"
                self.projects.observe(
                    dict(source="codex", event="prompt", session_id=tid, turn_id="1")
                )
                self.projects.set_metadata(
                    ThreadMetadata(tid, str(project), f"프로젝트 {project}"),
                    self.projects.generation,
                )
        self.notifications.submit(
            NoticeRequest("system", "사용량 90%", category="usage")
        )
        self.notifications.submit(
            NoticeRequest("schedule", "일정 테스트", category="schedule")
        )
        self.controller._render()

    def test_five_cards_two_conversations_and_exact_overflow(self):
        self.populate()
        windows = self.controller.visible_windows
        self.assertEqual(len(windows), 5)
        projects = [w for w in windows if w.content.key.startswith("project:")]
        self.assertEqual(len(projects), 3)
        self.assertTrue(all(len(w.content.rows) == 3 for w in projects))
        self.assertIn("외 1개 프로젝트", projects[-1].content.footer)
        self.assertTrue(all("개 대화" not in w.content.footer for w in projects))
        for window in projects:
            self.assertEqual(
                [b.accessibleName() for b in window.buttons if not b.isHidden()],
                [window.content.footer] if window.content.footer else [],
            )
        self.assertTrue(
            all(QRect(8, 8, 1904, 1064).contains(w.frameGeometry()) for w in windows)
        )

    def test_project_shows_only_two_rows_then_summary_and_keeps_actions(self):
        for count in range(1, 5):
            tid = f"conversation-{count}"
            self.projects.observe(
                dict(source="codex", event="prompt", session_id=tid, turn_id="1")
            )
            self.projects.set_metadata(
                ThreadMetadata(tid, "one", "프로젝트", title=f"대화 {count}"),
                self.projects.generation,
            )
            self.controller._render()
            window = self.controller.visible_windows[0]
            visible = [
                window.project_rows.rows[r.thread_id].title
                for r in window.content.project_rows
            ]
            expected = [label for label, _ in window.content.rows]
            self.assertEqual([b.accessibleName() for b in visible], expected)
            self.assertEqual(len(window.content.rows), count)
            with patch.object(self.router, "open", return_value=True) as opened:
                window.activate()
                opened.assert_called_with(window.content.token)
                for button, (_, token) in zip(visible, window.content.rows):
                    button.click()
                    opened.assert_called_with(token)

    def test_projectless_card_groups_rows_and_keeps_exact_thread_actions(self):
        clock = Clock()
        self.projects.now = clock
        for count in range(1, 4):
            clock.value += 1
            thread = f"projectless-{count}"
            self.projects.observe(
                dict(source="codex", event="prompt", session_id=thread, turn_id="1")
            )
            self.projects.set_metadata(
                ThreadMetadata(
                    thread,
                    "",
                    cwd=f"C:/Generated/new-chat-{count}",
                    title=f"프로젝트 없는 대화 {count}",
                ),
                self.projects.generation,
            )

        self.controller._render()
        (window,) = self.controller.visible_windows
        self.assertEqual(window.content.heading, "프로젝트 없는 대화")
        self.assertEqual(window.content.summary, "작업 중 3개")
        self.assertEqual(window.summary_label.toolTip(), "작업 중 3개")
        self.assertEqual(len(window.content.rows), 3)
        self.assertEqual(window.content.footer, "")
        self.assertEqual(
            [label for label, _token in window.content.rows],
            ["프로젝트 없는 대화 3", "프로젝트 없는 대화 2", "프로젝트 없는 대화 1"],
        )
        first_thread = self.projects.cards[0].rows[0].thread_id
        with patch.object(self.router, "open", return_value=True) as opened:
            window.project_rows.rows[first_thread].title.click()
            target_token = window.content.rows[0][1]
            opened.assert_called_once_with(target_token)
            self.assertEqual(self.router.targets[target_token].identifier, first_thread)

    def test_motion_preserves_windows_buttons_and_notification_deadlines(self):
        self.populate()
        windows = self.controller.visible_windows
        deadlines = dict(self.notifications._deadlines)
        with ExitStack() as stack:
            calls = [
                stack.enter_context(patch.object(w, method, wraps=getattr(w, method)))
                for w in windows
                for method in ("hide", "show", "set_content")
            ]
            for step in range(15):
                self.pet.move(800 + step, 900 - step)
                self.pet.resize(100, 110 + step)
                self.controller.reposition()
            self.assertTrue(all(call.call_count == 0 for call in calls))
        self.assertEqual(self.controller.visible_windows, windows)
        self.assertEqual(self.notifications._deadlines, deadlines)

    def test_compact_cards_are_not_reexpanded_on_motion(self):
        self.populate()
        with patch(
            "watched_kettle.ui.actionable_bubbles.QApplication.screenAt",
            return_value=SimpleNamespace(
                availableGeometry=lambda: QRect(0, 0, 600, 450)
            ),
        ):
            self.controller.reposition()
            windows = self.controller.visible_windows
            self.assertTrue(any(w.compact for w in windows))
            with ExitStack() as stack:
                calls = [
                    stack.enter_context(
                        patch.object(w, method, wraps=getattr(w, method))
                    )
                    for w in windows
                    for method in ("hide", "show", "set_content")
                ]
                for step in range(10):
                    self.pet.move(300 + step, 100 + step)
                    self.controller.reposition()
                self.assertTrue(all(call.call_count == 0 for call in calls))

    def test_project_header_stays_inline_after_theme_and_scale_changes(self):
        self.populate()
        self.controller.set_theme(replace(self.controller.theme, maximum_width=360))
        self.controller.set_scale_percent(140)
        self.app.processEvents()
        for window in self.controller.visible_windows:
            if not window.content.key.startswith("project:"):
                self.assertFalse(window.label.isHidden())
                continue
            self.assertTrue(window.label.isHidden())
            self.assertFalse(window.summary_label.isHidden())
            self.assertEqual(
                window.category_label.parent(), window.summary_label.parent()
            )
            self.assertEqual(window.summary_label.toolTip(), window.content.summary)
            self.assertEqual(window.category_label.toolTip(), window.content.heading)
            self.assertLess(
                window.category_label.geometry().right(),
                window.summary_label.geometry().left(),
            )

    def test_summary_changes_reclaim_name_width_without_hiding_card(self):
        self.projects.observe(
            dict(source="codex", event="prompt", session_id="a", turn_id="1")
        )
        self.projects.set_metadata(
            ThreadMetadata("a", "one", "아주 긴 프로젝트 이름 " * 6),
            self.projects.generation,
        )
        self.controller._render()
        window = self.controller.visible_windows[0]
        with (
            patch.object(window, "hide", wraps=window.hide) as hide,
            patch.object(window, "show", wraps=window.show) as show,
        ):
            for event, expected in (
                ("waiting", "확인 필요 1개"),
                ("tool_end", "작업 중 1개"),
                ("cancelled", ""),
            ):
                self.projects.observe(
                    dict(
                        source="codex",
                        event=event,
                        session_id="a",
                        turn_id="1",
                        event_id="approval",
                    )
                )
                self.controller._render()
                self.assertIs(self.controller.visible_windows[0], window)
                self.assertEqual(window.content.summary, expected)
            hide.assert_not_called()
            show.assert_not_called()
        self.assertEqual(
            window.project_rows.rows["a"].accessibleName(), "Codex 대화 · 중단"
        )
        self.assertFalse(window.project_rows.rows["a"].isHidden())
        terminal_content = window.content
        for scale in (100, 125, 150, 200):
            self.controller.set_scale_percent(scale)
            for width in (300, 360):
                window.set_theme(replace(window.theme, maximum_width=width))
                for summary in (
                    "작업 중 2개 · 확인 필요 1개",
                    "작업 중 2개",
                    "확인 필요 1개",
                    "",
                    "작업 중 1개",
                ):
                    window.set_content(replace(terminal_content, summary=summary))
                    self.app.processEvents()
                    self.assertEqual(window.summary_label.isHidden(), not bool(summary))
                    self.assertEqual(window.summary_label.toolTip(), summary)
                    self.assertEqual(
                        window.accessibleName(),
                        " · ".join(filter(None, (terminal_content.heading, summary))),
                    )
                    self.assertTrue(window.label.isHidden())
                    if summary:
                        self.assertLess(
                            window.category_label.geometry().right(),
                            window.summary_label.geometry().left(),
                        )
                    else:
                        self.assertEqual(window.header.layout().spacing(), 0)
                        self.assertEqual(
                            window.category_label.width(), window.header.width()
                        )
                        self.assertEqual(window.summary_label.text(), "")

    def test_project_width_fits_content_and_row_state_only_marks_mixed_rows(self):
        for thread, state, title in (
            ("running", "prompt", "작업 대화"),
            ("waiting", "prompt", "확인 대화"),
        ):
            self.projects.observe(
                dict(source="codex", event=state, session_id=thread, turn_id="1")
            )
            self.projects.set_metadata(
                ThreadMetadata(
                    thread,
                    "project",
                    "watched-kettle",
                    title=title,
                ),
                self.projects.generation,
            )
        self.controller._render()
        window = self.controller.visible_windows[0]
        self.assertEqual(window.category_label.text(), "watched-kettle")
        self.assertLess(window.header.width(), self.controller.theme.maximum_width)
        self.assertNotIn(" · 작업 중", window.content.rows[0][0])

        self.projects.observe(
            dict(
                source="codex",
                event="waiting",
                session_id="waiting",
                turn_id="1",
                event_id="approval",
            )
        )
        self.controller._render()
        window = self.controller.visible_windows[0]
        self.assertEqual(window.project_rows.rows["waiting"].badge.text(), "확인 필요")
        self.assertEqual(window.project_rows.rows["running"].badge.text(), "작업 중")
        self.assertLess(
            window.category_label.geometry().right(),
            window.summary_label.geometry().left(),
        )

        self.projects.reset()
        self.projects.observe(
            dict(source="codex", event="prompt", session_id="mouse", turn_id="2")
        )
        self.projects.set_metadata(
            ThreadMetadata(
                "mouse",
                "project",
                "Sample_app",
                title="포인터 작업",
            ),
            self.projects.generation,
        )
        self.controller._render()
        window = self.controller.visible_windows[0]
        self.assertEqual(window.category_label.text(), "Sample_app")

    def test_title_update_keeps_same_window_and_does_not_hide_it(self):
        self.populate()
        window = self.controller.visible_windows[0]
        thread = self.projects.cards[0].rows[0].thread_id
        metadata = self.projects.metadata[thread]
        with patch.object(window, "hide", wraps=window.hide) as hide:
            self.projects.set_metadata(
                replace(metadata, title="코드/문서 & 검토"), self.projects.generation
            )
            self.assertEqual(hide.call_count, 0)
        self.assertIs(self.controller.visible_windows[0], window)
        self.assertIn(
            "코드/문서 & 검토", window.project_rows.rows[thread].title.toolTip()
        )

    def test_axis_clamp_and_resume_following_without_moving_pet(self):
        area = QRect(0, 0, 800, 700)
        sizes = (QSize(240, 80), QSize(240, 80))
        edge1 = bubble_stack_positions(QRect(750, 400, 100, 100), sizes, area)
        edge2 = bubble_stack_positions(QRect(790, 450, 100, 100), sizes, area)
        self.assertEqual(edge1[0].x(), edge2[0].x())
        self.assertEqual(edge2[0].y() - edge1[0].y(), 50)
        inside = bubble_stack_positions(QRect(300, 450, 100, 100), sizes, area)
        self.assertLess(inside[0].x(), edge2[0].x())
        top = bubble_stack_positions(QRect(300, 0, 100, 100), sizes, area)
        self.assertEqual(top[-1].y(), 8)

    def test_preview_does_not_change_real_history_or_unread(self):
        self.populate()
        before = self.notifications.snapshot
        self.controller.preview("합성 미리보기")
        self.assertEqual(self.notifications.snapshot, before)
        self.controller.finish_transient()
        self.assertEqual(len(self.controller.visible_windows), 5)

    def test_successful_click_confirms_but_failure_does_not(self):
        self.populate()
        self.router.internal_open = lambda _: False
        window = next(w for w in self.controller.visible_windows if w.content.record_id)
        record_id = window.content.record_id
        window.activate()
        self.assertFalse(
            next(
                r
                for r in self.notifications.snapshot.recent
                if r.record_id == record_id
            ).confirmed
        )
        self.router.internal_open = lambda _: True
        window.activate()
        self.assertTrue(
            next(
                r
                for r in self.notifications.snapshot.recent
                if r.record_id == record_id
            ).confirmed
        )

    def test_top_overlap_keeps_pet_position_and_small_screen_is_bounded(self):
        self.populate()
        self.pet.move(20, 0)
        before = self.pet.pos()
        with patch(
            "watched_kettle.ui.actionable_bubbles.QApplication.screenAt",
            return_value=SimpleNamespace(
                availableGeometry=lambda: QRect(0, 0, 500, 450)
            ),
        ):
            self.controller.reposition()
            self.assertEqual(self.pet.pos(), before)
            for window in self.controller.visible_windows:
                overlap = window.frameGeometry().intersected(self.pet.frameGeometry())
                if not overlap.isEmpty():
                    self.assertFalse(
                        window.mask().contains(window.mapFromGlobal(overlap.center()))
                    )
            self.assertTrue(
                all(
                    QRect(8, 8, 484, 434).contains(w.frameGeometry())
                    for w in self.controller.visible_windows
                )
            )

    def test_top_edge_moves_whole_cards_clear_of_pet_and_companion(self):
        self.populate()
        companion = QWidget(self.pet, Qt.WindowType.Tool)
        companion.setObjectName("usageCompanion")
        companion.setGeometry(115, 23, 216, 96)
        companion.show()
        windows = self.controller.visible_windows
        try:
            for x in (-37, 800, 1850):
                with self.subTest(x=x):
                    self.pet.move(x, 0)
                    self.controller.reposition()
                    self.assertEqual(self.controller.visible_windows, windows)
                    for window in windows:
                        self.assertFalse(
                            window.frameGeometry().intersects(self.pet.frameGeometry())
                        )
                        self.assertFalse(
                            window.frameGeometry().intersects(companion.frameGeometry())
                        )
                        self.assertTrue(
                            QRect(8, 8, 1904, 1064).contains(window.frameGeometry())
                        )
                        self.assertTrue(window.mask().isEmpty())
            self.pet.move(800, 900)
            self.controller.reposition()
            self.assertTrue(
                all(w.frameGeometry().bottom() < self.pet.y() for w in windows)
            )
        finally:
            companion.close()

    def test_narrow_top_edge_uses_free_space_below_without_hiding_title(self):
        positions = self.controller._avoid_pet_overlap(
            (QPoint(8, 8),),
            (QSize(296, 103),),
            QRect(0, 0, 320, 800),
            [QRect(100, 0, 144, 156)],
        )
        rect = QRect(positions[0], QSize(296, 103))
        self.assertGreater(rect.top(), 155)
        self.assertTrue(QRect(8, 8, 304, 784).contains(rect))
