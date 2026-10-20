"""Integrated completion rows, stable ordering, scroll anchors and history."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PySide6.QtCore import QRect, QSettings, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QWidget

from watched_kettle.app_preferences import ApplicationPreferences
from watched_kettle.bubble_timing import BubbleDurationPolicy
from watched_kettle.features.notifications.actions import NotificationActionRouter
from watched_kettle.features.notifications.service import NotificationService
from watched_kettle.features.project_activity.service import (
    ConversationRow,
    ProjectActivityService,
    ThreadMetadata,
)
from watched_kettle.pet.bubble_theme import DEFAULT_BUBBLE_THEME
from tests.bubble_frame_support import layout_test_themes
from watched_kettle.ui.actionable_bubbles import ActionableBubbleController
from watched_kettle.ui.project_bubble_rows import ProjectConversationRow


class CompletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.now = 100.0
        self.projects = ProjectActivityService(now=lambda: self.now)
        self.pet = QWidget()
        self.pet.always_on_top = False
        self.pet.setGeometry(800, 900, 100, 110)
        self.router = NotificationActionRouter(opener=lambda _url: True)
        self.router.app_available = True
        self.controller = ActionableBubbleController(
            self.pet, self.projects, NotificationService(), self.router
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

    def event(self, thread="a", event="prompt", turn="1", **extra):
        return self.projects.observe(
            dict(source="codex", session_id=thread, event=event, turn_id=turn, **extra)
        )

    def start(self, thread="a", title="펫 작업 테스트 확인", project="p"):
        self.event(thread)
        self.projects.set_metadata(
            ThreadMetadata(thread, project, "프로젝트", title=title),
            self.projects.generation,
        )

    def advance(self, seconds):
        self.now += seconds
        self.controller._tick()
        self.app.processEvents()

    def window(self):
        return self.controller.visible_windows[0]

    def row(self, thread="a"):
        return self.window().project_rows.rows[thread]

    def test_first_project_join_moves_immediate_placeholder_without_duplicate(self):
        self.start("a")
        window = self.window()
        row = self.row("a")
        self.event("b")
        self.assertEqual(len(self.controller.visible_windows), 2)
        self.assertNotIn("b", window.project_rows.rows)
        self.projects.set_project_relation(
            "b", "p", "프로젝트", self.projects.generation
        )
        self.assertEqual(self.controller.visible_windows, (window,))
        self.assertIs(self.row("a"), row)
        self.assertIn("b", window.project_rows.rows)

    def test_uncertain_row_and_recovery_preserve_window_scroll_and_target(self):
        for key in ("a", "b", "c"):
            self.start(key)
            self.now += 1
        window = self.window()
        rows = dict(window.project_rows.rows)
        bar = window.project_rows.verticalScrollBar()
        bar.setValue(bar.maximum())
        anchor = window.project_rows.anchor()
        self.advance(60)
        self.assertEqual(window.content.summary, "응답 없음 3개")
        self.assertEqual(window.project_rows.anchor(), anchor)
        for key, row in rows.items():
            self.assertIs(window.project_rows.rows[key], row)
            self.assertEqual(row.badge.text(), "응답 없음")
            self.assertFalse(row.close_button.isHidden())
        self.event("b", "heartbeat")
        self.assertIs(self.window(), window)
        self.assertEqual(rows["b"].badge.text(), "작업 중")
        self.assertIn("작업 중 1개", window.content.summary)
        self.assertEqual(rows["b"].row.thread_id, "b")

    def test_unresolved_conversations_share_one_card_immediately(self):
        self.event("a")
        self.event("b")
        self.assertEqual(len(self.controller.visible_windows), 1)
        self.assertEqual(self.window().content.heading, "프로젝트 확인 중")
        self.assertEqual(set(self.window().project_rows.rows), {"a", "b"})

    def test_running_badges_restore_width_and_alignment_after_long_status(self):
        self.start("a", title="말풍선 작업 완료 오표시 확인")
        self.start("b", title="짧은 제목")
        self.app.processEvents()
        window = self.window()
        row, other = self.row("a"), self.row("b")
        original_size = row.badge.size()
        original_style = row.badge.styleSheet()
        original_window_width = window.width()
        for index, state in enumerate(("uncertain", "compacting", "uncertain")):
            with self.subTest(state=state, index=index):
                if state == "uncertain":
                    self.now += 61
                    self.event("b", "heartbeat")
                    self.controller._tick()
                else:
                    self.event(
                        "a",
                        "review",
                        compaction_phase="start",
                        event_id="compact-start",
                    )
                self.app.processEvents()
                self.assertGreater(row.badge.width(), original_size.width())
                self.assertEqual(row.badge.styleSheet(), original_style)
                self.assertEqual(bool(row.badge.toolTip()), state == "uncertain")
                if state == "uncertain":
                    self.event("a", "heartbeat")
                else:
                    self.event(
                        "a", "review", compaction_phase="end", event_id="compact-end"
                    )
                self.app.processEvents()
                self.assertIs(self.row("a"), row)
                self.assertEqual(row.badge.text(), "작업 중")
                self.assertEqual(row.badge.size(), original_size)
                self.assertEqual(row.badge.styleSheet(), original_style)
                self.assertEqual(row.badge.toolTip(), "")
                self.assertEqual(
                    row.badge.geometry().right(), other.badge.geometry().right()
                )
                self.assertEqual(
                    row.badge.geometry().left(), other.badge.geometry().left()
                )
                self.assertEqual(window.width(), original_window_width)
                self.assertLess(
                    row.title.geometry().right(), row.badge.geometry().left()
                )
                self.assertTrue(row.close_button.isHidden())

    def test_compaction_label_retains_window_row_scroll_and_sort(self):
        self.start("a")
        self.start("b")
        self.start("c")
        window = self.window()
        row = window.project_rows.rows["b"]
        token = row.token
        bar = window.project_rows.verticalScrollBar()
        bar.setValue(bar.maximum())
        anchor = window.project_rows.anchor()
        order = window.project_rows.ordered_ids
        self.event("b", "review", compaction_phase="start")
        self.assertIs(self.window(), window)
        self.assertIs(window.project_rows.rows["b"], row)
        self.assertEqual(row.badge.text(), "컨텍스트 압축 중")
        self.assertEqual(window.content.summary, "작업 중 3개")
        self.assertEqual(window.project_rows.anchor(), anchor)
        self.assertEqual(window.project_rows.ordered_ids, order)
        self.assertEqual(row.token, token)
        self.assertIn("컨텍스트 압축 중", row.accessibleName())
        self.assertLess(row.title.geometry().right(), row.badge.geometry().left())
        self.event("b", "review", compaction_phase="end")
        self.assertEqual(row.badge.text(), "작업 중")
        self.assertEqual(window.project_rows.anchor(), anchor)

    def test_same_window_and_row_return_to_running_without_close(self):
        self.start()
        window, row = self.window(), self.row()
        self.event(event="done")
        self.assertIs(self.window(), window)
        self.assertIs(self.row(), row)
        self.assertEqual(row.badge.text(), "완료")
        self.assertFalse(row.close_button.isHidden())
        self.assertEqual(window.content.summary, "완료 1개")
        self.event(turn="2")
        self.assertIs(self.row(), row)
        self.assertEqual(row.badge.text(), "작업 중")
        self.assertTrue(row.close_button.isHidden())
        self.assertEqual(window.content.summary, "작업 중 1개")
        self.assertFalse(self.projects.visible_completions)
        self.assertEqual(len(self.projects.completions), 1)
        self.assertFalse(self.event(event="done", turn="1"))
        self.assertEqual(self.row().badge.text(), "작업 중")

    def test_highlight_ends_but_badge_remains_until_300_seconds(self):
        self.start()
        self.event(event="done")
        record = self.projects.completions[0]
        self.assertEqual((record.highlight_until, record.expires_at), (115, 400))
        self.assertTrue(self.row().row.highlighted)
        self.assertIn("background-color", self.window().summary_label.text())
        self.advance(15)
        self.assertFalse(self.row().row.highlighted)
        self.assertEqual(self.row().badge.text(), "완료")
        self.assertIn("#d7f1df", self.row().badge.styleSheet())
        self.assertNotIn("background-color", self.window().summary_label.text())
        self.advance(285)
        self.assertFalse(self.controller.visible_windows)
        self.assertEqual(len(self.projects.completions), 1)

    def test_title_open_preserves_completion_and_x_removes_only_one(self):
        for thread in ("a", "b"):
            self.start(thread)
            self.event(thread, "done")
        with patch.object(self.router, "open", return_value=True) as opened:
            self.row("a").title.click()
            opened.assert_called_once_with(self.row("a").token)
        self.assertEqual(len(self.projects.visible_completions), 2)
        with patch.object(self.router, "open", return_value=False):
            self.row("a").title.click()
        self.row("a").close_button.click()
        self.assertEqual(
            [r.thread_id for r in self.projects.visible_completions], ["b"]
        )
        self.assertEqual(self.window().content.summary, "완료 1개")
        self.assertEqual(len(self.projects.completions), 2)

    def test_only_main_success_and_never_duplicate_old_or_child_completion(self):
        for scope in ("subagent", "internal", "unknown"):
            self.event(scope, agent_scope=scope)
            self.event(scope, "done", agent_scope=scope)
        for event in ("failed", "cancelled", "idle", "session_end"):
            self.start(event)
            self.event(event, event)
        self.assertFalse(self.projects.completions)
        self.start()
        self.event(turn="2")
        self.assertFalse(self.event(event="done", turn="1"))
        self.event(event="done", turn="2")
        self.assertFalse(self.event(event="done", turn="2"))
        self.assertEqual(len(self.projects.completions), 1)

    def test_parent_metadata_blocks_mislabelled_child_success(self):
        self.start("parent")
        self.start("child")
        self.projects.set_metadata(
            ThreadMetadata("child", parent_thread_id="parent"), self.projects.generation
        )
        self.event("child", "done")
        self.assertFalse(self.projects.completions)

    def test_state_then_latest_sort_is_stable_during_heartbeat_and_tools(self):
        for thread in (
            "work-old",
            "work-new",
            "wait-old",
            "wait-new",
            "done-old",
            "done-new",
        ):
            self.start(thread)
            if thread.startswith("wait"):
                self.event(thread, "waiting", event_id=thread)
            if thread.startswith("done"):
                self.event(thread, "done")
            self.now += 1
        expected = (
            "done-new",
            "done-old",
            "wait-new",
            "wait-old",
            "work-new",
            "work-old",
        )
        self.assertEqual(self.window().project_rows.ordered_ids, expected)
        for _ in range(3):
            self.event("work-old", "heartbeat")
            self.event("work-old", "tool_start", event_id="tool")
            self.event("work-old", "tool_end", event_id="tool")
        self.assertEqual(self.window().project_rows.ordered_ids, expected)
        self.assertEqual(
            self.window().content.summary, "완료 2개 · 확인 필요 2개 · 작업 중 2개"
        )

    def test_tied_times_use_identifier_not_metadata_arrival(self):
        for thread in ("c", "a", "b"):
            self.start(thread)
        self.assertEqual(self.window().project_rows.ordered_ids, ("a", "b", "c"))
        self.projects.set_metadata(
            replace(self.projects.metadata["c"], title="새 제목"),
            self.projects.generation,
        )
        self.assertEqual(self.window().project_rows.ordered_ids, ("a", "b", "c"))

    def test_review_and_failure_badges_and_priority(self):
        for thread, state in (
            ("work", "prompt"),
            ("review", "review"),
            ("cancel", "cancelled"),
            ("wait", "waiting"),
            ("fail", "failed"),
            ("done", "done"),
        ):
            self.start(thread)
            self.event(thread, state)
            self.now += 1
        rows = self.window().project_rows
        self.assertEqual(
            rows.ordered_ids, ("done", "fail", "wait", "cancel", "review", "work")
        )
        for key, text, color in (
            ("done", "완료", "#d7f1df"),
            ("wait", "확인 필요", "#fff0b5"),
            ("fail", "실패", "#f9dddd"),
            ("cancel", "중단", "transparent"),
            ("review", "검토 중", "transparent"),
        ):
            self.assertEqual(rows.rows[key].badge.text(), text)
            self.assertIn(color, rows.rows[key].badge.styleSheet())

    def test_badge_presentation_matrix_across_themes_and_scales(self):
        widget = ProjectConversationRow(self.router, lambda _ids: None, self.pet)
        base = ConversationRow("badge", "한글 English 긴 대화 제목 " * 10, "running", 0)
        tooltip = "최근 활동을 받지 못했습니다. 작업이 끝났는지는 확인되지 않았습니다."
        cases = [
            ({"state": "running"}, "작업 중", "", None, "transparent"),
            ({"state": "review"}, "검토 중", "", None, "transparent"),
            ({"state": "permission"}, "권한 처리 중", "", None, "transparent"),
            ({"state": "cancelled"}, "중단", "", None, "transparent"),
            ({"state": "future"}, "future", "", None, "transparent"),
            ({"state": "waiting"}, "확인 필요", "", "#715000", "#fff0b5"),
            ({"state": "failed"}, "실패", "", "#922f35", "#f9dddd"),
            ({"state": "done"}, "완료", "", "#17633a", "#d7f1df"),
            ({"uncertain": True}, "응답 없음", tooltip, None, "transparent"),
            ({"compacting": True}, "컨텍스트 압축 중", "", None, "transparent"),
            # Synthetic combinations verify presentation precedence, not service transitions.
            (
                {"state": "failed", "compacting": True},
                "컨텍스트 압축 중",
                "",
                None,
                "transparent",
            ),
            (
                {"state": "waiting", "compacting": True, "uncertain": True},
                "응답 없음",
                tooltip,
                None,
                "transparent",
            ),
            ({"state": "running"}, "작업 중", "", None, "transparent"),
        ]
        themes = (
            DEFAULT_BUBBLE_THEME,
            replace(DEFAULT_BUBBLE_THEME, background="#20242b", text="#f2f4f8"),
        )
        widget.show()
        for theme in themes:
            for scale in (80, 100, 140):

                def scaled(value):
                    return round(value * scale / 100)

                font = QFont(self.app.font())
                font.setPixelSize(scaled(14))
                for values, label, tip, foreground, background in cases:
                    with self.subTest(theme=theme.text, scale=scale, values=values):
                        row = replace(base, **values)
                        widget.configure(row, "test-token", font, theme, scaled)
                        widget.fit(scaled(420), scaled)
                        widget.line.activate()
                        self.app.processEvents()
                        self.assertEqual(widget.badge.text(), label)
                        self.assertEqual(widget.badge.toolTip(), tip)
                        self.assertIn(
                            f"color: {foreground or theme.text};",
                            widget.badge.styleSheet(),
                        )
                        self.assertIn(
                            f"background: {background};", widget.badge.styleSheet()
                        )
                        self.assertEqual(widget.badge.font(), font)
                        self.assertEqual(
                            widget.badge.alignment(),
                            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                        )
                        self.assertLess(
                            widget.title.geometry().right(),
                            widget.badge.geometry().left(),
                        )
                        self.assertLessEqual(len(widget.title.text().splitlines()), 2)
                        self.assertEqual(widget.title.toolTip(), base.title)
                        if row.state == "done":
                            self.assertFalse(widget.close_button.isHidden())
                            self.assertLess(
                                widget.badge.geometry().right(),
                                widget.close_button.geometry().left(),
                            )
                        else:
                            self.assertTrue(widget.close_button.isHidden())
                        self.assertEqual(
                            widget.accessibleName(), f"{base.title} · {label}"
                        )
        widget.close()

    def test_two_rows_visible_all_rows_scrollable_and_header_counts_all(self):
        for count in range(6):
            self.start(str(count))
        view = self.window().project_rows
        self.app.processEvents()
        self.assertEqual(len(view.rows), 6)
        self.assertEqual(self.window().content.summary, "작업 중 6개")
        two_height = (
            sum(view.rows[k].height() for k in view.ordered_ids[:2])
            + view.body_layout.spacing()
        )
        self.assertEqual(view.height(), two_height)
        self.assertGreater(view.verticalScrollBar().maximum(), 0)
        view.verticalScrollBar().setValue(view.verticalScrollBar().maximum())
        last = view.rows[view.ordered_ids[-1]]
        self.assertLessEqual(
            last.y() + last.height() - view.verticalScrollBar().value(),
            view.viewport().height(),
        )
        self.assertEqual(view.horizontalScrollBar().maximum(), 0)

    def test_scroll_anchor_survives_completion_reorder_and_title_change(self):
        for index in range(6):
            self.start(str(index))
        view = self.window().project_rows
        self.app.processEvents()
        view.verticalScrollBar().setValue(view.rows["2"].y() + 2)
        self.assertEqual(view.anchor(), ("2", 2))
        self.event("5", "done")
        self.app.processEvents()
        self.assertEqual(view.anchor(), ("2", 2))
        self.projects.set_metadata(
            replace(
                self.projects.metadata["1"],
                title="긴 제목의 높이가 달라져도 위치 유지 " * 4,
            ),
            self.projects.generation,
        )
        self.app.processEvents()
        self.assertEqual(view.anchor(), ("2", 2))

    def test_top_stays_top_when_new_completion_arrives(self):
        for thread in ("a", "b", "c"):
            self.start(thread)
        self.event("c", "done")
        self.assertEqual(self.window().project_rows.verticalScrollBar().value(), 0)
        self.assertEqual(self.window().project_rows.ordered_ids[0], "c")

    def test_removed_scroll_anchor_keeps_next_surviving_conversation(self):
        for index in range(6):
            self.start(str(index))
            self.event(str(index), "done")
        view = self.window().project_rows
        self.app.processEvents()
        view.verticalScrollBar().setValue(view.rows["2"].y())
        self.row("2").close_button.click()
        self.app.processEvents()
        self.assertEqual(view.anchor(), ("3", 0))
        with patch.object(self.router, "open", return_value=True) as opened:
            view.rows["3"].title.click()
            token = opened.call_args.args[0]
            self.assertEqual(self.router.targets[token].identifier, "3")

    def test_stale_close_identifier_cannot_dismiss_a_later_turn(self):
        self.start()
        self.event(event="done")
        old_id = self.row().row.completion_id
        self.event(turn="2")
        self.event(event="done", turn="2")
        self.projects.dismiss_completions((old_id,))
        self.assertEqual(self.window().content.summary, "완료 1개")
        self.assertNotEqual(self.row().row.completion_id, old_id)
        self.assertEqual(len(self.projects.completions), 2)

    def test_failed_and_cancelled_keep_independent_result_duration(self):
        self.projects.duration = 7
        for state in ("failed", "cancelled", "done"):
            self.start(state)
            self.event(state, state)
        self.advance(7)
        self.assertEqual(self.window().project_rows.ordered_ids, ("done",))
        self.assertTrue(self.row("done").row.highlighted)

    def test_history_and_navigation_tokens_clear_on_generation_reset(self):
        self.start()
        self.event(event="done")
        token = self.row().token
        self.projects.reset()
        self.assertFalse(self.projects.completions)
        self.assertNotIn(token, self.router.targets)
        self.assertFalse(self.controller.visible_windows)

    def test_history_limit_does_not_limit_visible_completion_rows(self):
        self.controller.set_enabled(False)
        for index in range(110):
            self.start(str(index))
            self.event(str(index), "done")
        self.assertEqual(len(self.projects.completions), 100)
        self.assertEqual(len(self.projects.visible_completions), 110)
        self.assertEqual(len(self.projects.cards[0].rows), 110)
        oldest = self.projects.pending_completions["0"]
        self.projects.dismiss_completions((oldest.record_id,))
        self.assertEqual(len(self.projects.visible_completions), 109)
        self.advance(300)
        self.assertFalse(self.projects.pending_completions)
        self.assertNotIn("0", self.projects.metadata)
        self.assertNotIn("0", [t.identifier for t in self.router.targets.values()])

    def test_later_completion_and_settings_do_not_extend_deadlines(self):
        self.start()
        self.event(event="done")
        first = self.projects.completions[0]
        self.controller.set_duration_policy(BubbleDurationPolicy(completion=30))
        self.advance(10)
        self.start("b")
        self.event("b", "done")
        self.assertEqual(self.projects.completions[0], first)
        self.advance(5)
        self.assertFalse(self.row("a").row.highlighted)
        self.assertTrue(self.row("b").row.highlighted)

    def test_motion_reuses_window_rows_and_scroll_position(self):
        for index in range(4):
            self.start(str(index))
        window = self.window()
        rows = dict(window.project_rows.rows)
        window.project_rows.verticalScrollBar().setValue(20)
        with patch.object(window, "set_content", wraps=window.set_content) as update:
            for step in range(8):
                self.pet.move(800 + step, 900)
                self.controller.reposition()
            update.assert_not_called()
        self.assertEqual(window.project_rows.rows, rows)
        self.assertEqual(window.project_rows.verticalScrollBar().value(), 20)

    def test_progress_title_width_and_height_shrink_in_place(self):
        self.start(title="짧음")
        window = self.window()
        initial = window.size()
        metadata = self.projects.metadata["a"]
        self.projects.set_metadata(
            replace(metadata, title="줄바꿈이 필요한 매우 긴 대화 제목 " * 5),
            self.projects.generation,
        )
        self.app.processEvents()
        self.assertGreater(window.width(), initial.width())
        self.assertGreater(window.height(), initial.height())
        self.projects.set_metadata(metadata, self.projects.generation)
        self.app.processEvents()
        self.assertEqual(window.size(), initial)

    def test_hidden_snoozed_and_reset_results_never_reappear(self):
        self.start()
        self.event(event="done")
        self.controller.snooze(60_000)
        self.assertFalse(self.controller.visible_windows)
        self.advance(300)
        self.controller.resume()
        self.assertFalse(self.controller.visible_windows)
        self.start("b")
        self.event("b", "done")
        self.controller.set_enabled(False)
        self.projects.reset()
        self.assertFalse(self.controller.card_windows)
        self.assertIsNone(self.controller._measurer)
        self.assertFalse(self.projects.pending_completions)
        self.assertFalse(self.projects.completions)

    def test_small_screen_uses_one_scrollable_row(self):
        for index in range(4):
            self.start(
                str(index), title="두 줄까지 사용할 수 있는 긴 대화 제목입니다 " * 3
            )
        with patch(
            "watched_kettle.ui.actionable_bubbles.QApplication.screenAt",
            return_value=SimpleNamespace(
                availableGeometry=lambda: QRect(0, 0, 380, 125)
            ),
        ):
            self.controller.reposition()
            self.assertTrue(self.window().compact)
            self.assertEqual(len(self.window().project_rows.rows), 4)
            self.assertTrue(
                QRect(8, 8, 364, 109).contains(self.window().frameGeometry())
            )

    def test_themes_scales_and_two_line_title_accessibility(self):
        self.start(title="한글 English & 작업 제목 " * 10)
        self.event(event="done")
        themes = layout_test_themes(DEFAULT_BUBBLE_THEME)
        for theme in themes:
            for scale in (80, 100, 140):
                self.controller.set_theme(theme)
                self.controller.set_scale_percent(scale)
                self.app.processEvents()
                window = self.window()
                row = self.row()
                self.assertEqual(window.scale_percent, scale)
                self.assertTrue(
                    QRect(8, 8, 1904, 1064).contains(window.frameGeometry())
                )
                self.assertLessEqual(len(row.title.text().splitlines()), 2)
                self.assertEqual(
                    row.title.toolTip(), self.projects.metadata["a"].title.strip()
                )
                self.assertLess(
                    row.title.geometry().right(), row.badge.geometry().left()
                )
                self.assertLess(
                    row.badge.geometry().right(), row.close_button.geometry().left()
                )

    def test_completion_settings_persist_independently(self):
        with TemporaryDirectory() as directory:
            settings = QSettings(
                str(Path(directory) / "test.ini"), QSettings.Format.IniFormat
            )
            prefs = ApplicationPreferences(settings)
            policy = BubbleDurationPolicy(common=8).with_override("completion", 30)
            prefs.save_bubble_duration_policy(policy)
            self.assertEqual(prefs.load_bubble_duration_policy(), policy)
            self.assertEqual(BubbleDurationPolicy(common=60).seconds("completion"), 15)

    def test_full_single_line_header_can_exceed_theme_width(self):
        for thread in ("done", "waiting", "work"):
            self.start(thread, title="짧음")
            self.projects.set_metadata(
                replace(
                    self.projects.metadata[thread],
                    project_label="Demo_app 프로젝트",
                ),
                self.projects.generation,
            )
        self.event("waiting", "waiting")
        self.event("done", "done")
        for theme in layout_test_themes(DEFAULT_BUBBLE_THEME):
            self.controller.set_theme(replace(theme, maximum_width=240))
            for scale in (80, 100, 140):
                self.controller.set_scale_percent(scale)
                self.app.processEvents()
                window = self.window()
                self.assertEqual(window.category_label.text(), "Demo_app 프로젝트")
                self.assertFalse(window.summary_label.wordWrap())
                self.assertGreater(window.width(), window._scaled(240))
                self.assertGreaterEqual(
                    window.category_label.width(),
                    window.category_label.sizeHint().width(),
                )
                self.assertGreaterEqual(
                    window.summary_label.width(),
                    window.summary_label.sizeHint().width(),
                )
                self.assertLess(
                    window.category_label.geometry().right(),
                    window.summary_label.geometry().left(),
                )
                self.assertLessEqual(
                    window.summary_label.geometry().right(), window.header.width()
                )

    def test_header_shrinks_after_counts_or_project_name_get_shorter(self):
        self.start(title="짧음")
        original = self.projects.metadata["a"]
        self.projects.set_metadata(
            replace(
                original, project_label="긴 프로젝트 이름을 생략하지 않고 모두 표시"
            ),
            self.projects.generation,
        )
        long_width = self.window().width()
        self.projects.set_metadata(original, self.projects.generation)
        self.assertLess(self.window().width(), long_width)
        self.assertEqual(self.window().category_label.text(), original.project_label)
        for thread in ("b", "c"):
            self.start(thread, title="짧음")
        self.event("b", "waiting")
        self.event("c", "done")
        mixed_width = self.window().width()
        self.row("c").close_button.click()
        self.assertLess(self.window().width(), mixed_width)

    def test_header_only_scales_type_when_entire_screen_is_too_narrow(self):
        self.start(title="짧음")
        heading = "프로젝트 이름 전체가 작은 화면에서도 한 줄로 남아야 합니다"
        self.projects.set_metadata(
            replace(self.projects.metadata["a"], project_label=heading),
            self.projects.generation,
        )
        ordinary_font = self.window().summary_label.fontMetrics().height()
        with patch(
            "watched_kettle.ui.actionable_bubbles.QApplication.screenAt",
            return_value=SimpleNamespace(
                availableGeometry=lambda: QRect(0, 0, 300, 500)
            ),
        ):
            self.controller.reposition()
            self.app.processEvents()
            window = self.window()
            self.assertEqual(window.category_label.text(), heading)
            self.assertFalse(window.summary_label.wordWrap())
            self.assertLess(window.summary_label.fontMetrics().height(), ordinary_font)
            self.assertTrue(QRect(8, 8, 284, 484).contains(window.frameGeometry()))
            self.assertGreaterEqual(
                window.summary_label.width(), window.summary_label.sizeHint().width()
            )
        self.controller.reposition()
        self.assertEqual(
            self.window().summary_label.fontMetrics().height(), ordinary_font
        )

    def test_history_is_only_existing_projection_and_open_does_not_dismiss(self):
        from watched_kettle.features.history.viewmodel import HistoryViewModel

        self.start()
        history = HistoryViewModel(
            self.controller.notifications,
            projects=self.projects,
            router=self.router,
        )
        events = [r for r in history.snapshot.entries if r.group == "progress"]
        self.assertTrue(events)
        self.assertEqual(
            {r.summary for r in events}, {self.projects.metadata["a"].title}
        )
        self.event(event="done")
        history.refresh()
        entries = [r for r in history.snapshot.entries if r.group == "completion"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].summary, self.projects.metadata["a"].title)
        self.assertTrue(self.router.open(entries[0].action_token))
        self.assertEqual(len(self.projects.visible_completions), 1)
        self.row().close_button.click()
        history.refresh()
        self.assertEqual(
            len([r for r in history.snapshot.entries if r.group == "completion"]), 1
        )
        self.assertFalse(hasattr(self.controller, "completion_dialog"))
        self.assertNotIn("completion", self.controller.card_windows)

    def test_history_groups_project_events_by_what_they_ask(self):
        from watched_kettle.features.history.viewmodel import HistoryViewModel

        self.start()
        self.event(event="waiting")
        history = HistoryViewModel(
            self.controller.notifications, projects=self.projects, router=self.router
        )
        events = [r for r in history.snapshot.entries if r.group != "notice"]
        self.assertEqual(
            [(r.group, r.kind, r.result) for r in events],
            [("attention", "확인 필요", ""), ("progress", "작업 중", "")],
        )
        self.assertTrue(all(r.action_token for r in events))
