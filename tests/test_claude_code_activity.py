"""Claude Code project cards, source labels and navigation (stage 13, BA-01~10)."""

import os
from types import SimpleNamespace
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from watched_kettle.features.agent_activity.service import AgentActivityService
from watched_kettle.features.history.viewmodel import HistoryViewModel
from watched_kettle.features.notifications.actions import (
    ActionTarget,
    NotificationActionRouter,
)
from watched_kettle.features.notifications.service import NotificationService
from watched_kettle.features.project_activity.service import (
    ProjectActivityService,
    state_label,
    thread_source,
)
from watched_kettle.integrations.claude_code_hooks import normalize_claude_code_hook
from watched_kettle.state.controller import PetAgentController
from watched_kettle.state.presentation import working_sources
from watched_kettle.state.events import build_decision
from watched_kettle.state.session_manager import AgentSessionManager, InactivityLimit
from watched_kettle.ui.activity_caption import activity_message
from watched_kettle.ui import design_tokens
from watched_kettle.ui.bubble_models import source_mark_color, source_marked_text
from watched_kettle.ui.project_bubble_rows import _badge_presentation


SESSION = "8d4f034a-0000-4000-8000-000000000001"
PROMPT = "69492e26-0000-4000-8000-000000000002"
NOTIFICATION = "e044aa1d-0000-4000-8000-000000000003"
FOLDER = "C:/Users/example/work/kettle-demo"


def claude(name, session=SESSION, cwd=FOLDER, **fields):
    payload = {
        "session_id": session,
        "cwd": cwd,
        "hook_event_name": name,
        "prompt_id": PROMPT,
    }
    payload.update(fields)
    return normalize_claude_code_hook(payload)


class Clock:
    def __init__(self):
        self.value = 1000.0

    def __call__(self):
        return self.value


class ClaudeCodeCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.clock = Clock()
        self.projects = ProjectActivityService(now=self.clock)
        self.requested = []
        self.projects.metadata_requested.connect(self.requested.append)

    def observe(self, event):
        self.assertIsNotNone(event)
        return self.projects.observe(event)

    def card(self):
        cards = self.projects.bubble_cards
        self.assertEqual(len(cards), 1)
        return cards[0]

    def test_prompt_shows_a_folder_card_without_codex_metadata_lookup(self):
        self.observe(claude("UserPromptSubmit"))

        card = self.card()
        self.assertEqual(card.label, "kettle-demo")
        self.assertEqual(card.source, "claude_code")
        self.assertEqual(card.kind, "project")
        self.assertTrue(card.key.startswith("project:claude_code:"))
        self.assertEqual(card.rows[0].title, "Claude Code 대화")
        self.assertEqual(card.rows[0].state, "running")
        self.assertEqual(card.rows[0].source, "claude_code")
        self.assertEqual(thread_source(card.rows[0].thread_id), "claude_code")
        self.assertEqual(self.requested, [])

    def test_same_folder_and_session_id_stay_apart_from_codex(self):
        self.observe(claude("UserPromptSubmit"))
        self.projects.observe(
            {
                "source": "codex",
                "event": "prompt",
                "session_id": SESSION,
                "turn_id": "codex-turn",
            }
        )
        self.projects.set_project_relation(
            SESSION, "kettle-demo", "kettle-demo", self.projects.generation
        )

        cards = {card.source: card for card in self.projects.bubble_cards}
        self.assertEqual(set(cards), {"codex", "claude_code"})
        self.assertNotEqual(cards["codex"].key, cards["claude_code"].key)
        self.assertEqual(cards["codex"].rows[0].title, "Codex 대화")
        self.assertEqual(self.requested, [SESSION])

    def test_background_command_turn_waits_then_completes_once(self):
        # A Stop with a background command shows the wait, not a completion.
        # Claude Code then reads the result in a turn it starts itself, with a
        # new prompt ID and no prompt hook; its tools show work again and its
        # Stop completes the conversation once.
        self.observe(claude("UserPromptSubmit"))
        self.observe(
            claude(
                "Stop",
                background_tasks=[
                    {"type": "shell", "status": "running"},
                    {"type": "subagent", "status": "running"},
                    {"type": "monitor", "status": "running"},
                ],
            )
        )
        row = self.card().rows[0]
        self.assertEqual((row.state, row.background_count), ("background", 2))
        self.assertEqual(self.card().summary, "백그라운드 대기 1개")
        self.assertEqual(self.projects.completions, ())

        self.observe(claude("PreToolUse", prompt_id=NOTIFICATION, tool_use_id="t2"))
        self.assertEqual(self.card().rows[0].state, "running")
        self.observe(claude("PostToolUse", prompt_id=NOTIFICATION, tool_use_id="t2"))
        self.observe(claude("Stop", prompt_id=NOTIFICATION, background_tasks=[]))

        self.assertEqual(self.card().rows[0].state, "done")
        self.assertEqual(len(self.projects.completions), 1)

    def test_background_wait_uses_the_confirmation_inactivity_limit(self):
        self.observe(claude("UserPromptSubmit"))
        self.observe(claude("Stop", background_tasks=[{"type": "shell"}]))
        self.clock.value += 11 * 60
        self.projects.expire()
        self.assertEqual(self.card().rows[0].state, "background")
        self.clock.value += 20 * 60
        self.projects.expire()
        self.assertEqual(self.projects.bubble_cards, ())

    def test_late_stop_of_a_replaced_turn_does_not_end_the_new_one(self):
        self.observe(claude("UserPromptSubmit"))
        self.observe(claude("UserPromptSubmit", prompt_id=NOTIFICATION))

        self.projects.observe(claude("Stop", background_tasks=[]))

        self.assertEqual(self.card().rows[0].state, "running")

    def test_card_stays_on_the_first_folder(self):
        self.observe(claude("UserPromptSubmit"))
        key = self.card().key
        self.observe(
            claude("PreToolUse", cwd="C:/elsewhere/other", tool_use_id="toolu_1")
        )

        self.assertEqual(self.card().key, key)
        self.assertEqual(self.card().label, "kettle-demo")

    def test_event_without_folder_uses_the_unassigned_card(self):
        self.observe(
            normalize_claude_code_hook(
                None, hook_name="UserPromptSubmit", session_id=SESSION
            )
        )

        card = self.card()
        self.assertEqual(card.key, "unassigned:claude_code")
        self.assertEqual(card.kind, "unassigned")

    def test_card_never_blocks_the_pet_event(self):
        # An unmatched tool end is rejected by the card but still reaches the pet.
        self.assertTrue(
            self.observe(claude("PostToolUse", tool_use_id="toolu_unknown"))
        )
        self.assertEqual(self.projects.bubble_cards, ())
        self.assertEqual(self.projects.rejected_events, {"missing_start": 1})

    def test_permission_wait_then_completion(self):
        self.observe(claude("UserPromptSubmit"))
        self.observe(claude("PreToolUse", tool_use_id="toolu_1"))
        self.observe(claude("PermissionRequest", tool_name="Bash"))
        self.assertEqual(self.card().rows[0].state, "waiting")

        self.observe(claude("PostToolUse", tool_use_id="toolu_1"))
        self.assertEqual(self.card().rows[0].state, "running")

        self.observe(claude("Stop", background_tasks=[]))
        row = self.card().rows[0]
        self.assertEqual(row.state, "done")
        self.assertTrue(row.completion_id)

    def test_transcript_cancellation_without_prompt_id_ends_the_turn(self):
        self.observe(claude("UserPromptSubmit"))
        self.observe(claude("PermissionRequest", tool_name="Bash"))
        self.projects.observe(
            {"source": "claude_code", "event": "cancelled", "session_id": SESSION}
        )

        self.assertEqual(self.card().rows[0].state, "cancelled")

    def test_session_end_without_prompt_id_removes_the_row(self):
        self.observe(claude("UserPromptSubmit"))
        self.observe(claude("SessionEnd", prompt_id=None, reason="prompt_input_exit"))

        self.assertEqual(self.projects.bubble_cards, ())

    def test_silence_follows_the_inactivity_limit_not_stale_marking(self):
        self.observe(claude("UserPromptSubmit"))
        self.clock.value += 9 * 60
        self.projects.expire()
        row = self.card().rows[0]
        self.assertEqual(row.state, "running")
        self.assertFalse(row.uncertain)

        self.clock.value += 60
        self.projects.expire()
        self.assertEqual(self.projects.bubble_cards, ())
        self.assertEqual(self.projects.visible_completions, ())

    def test_waiting_uses_the_longer_limit_and_limits_can_change(self):
        self.observe(claude("UserPromptSubmit"))
        self.observe(claude("PermissionRequest", tool_name="Bash"))
        self.clock.value += 29 * 60
        self.projects.expire()
        self.assertEqual(self.card().rows[0].state, "waiting")

        self.projects.set_inactivity_limit(
            "claude_code", InactivityLimit(work_ms=60_000, waiting_ms=60_000)
        )
        self.projects.expire()
        self.assertEqual(self.projects.bubble_cards, ())

    def test_codex_keeps_marking_silent_rows_uncertain(self):
        self.projects.observe(
            {"source": "codex", "event": "prompt", "session_id": "c", "turn_id": "t"}
        )
        self.clock.value += 61
        self.projects.expire()

        self.assertTrue(self.projects.cards[0].rows[0].uncertain)

    def test_transcript_title_names_the_row_even_before_the_first_event(self):
        self.projects.set_claude_code_title(SESSION, "13 단계 남은 작업")
        self.observe(claude("UserPromptSubmit"))
        self.assertEqual(self.card().rows[0].title, "13 단계 남은 작업")

        self.projects.set_claude_code_title(SESSION, "새 제목")
        self.assertEqual(self.card().rows[0].title, "새 제목")

    def test_codex_account_reset_keeps_claude_code_work(self):
        self.observe(claude("UserPromptSubmit"))
        self.projects.observe(
            {"source": "codex", "event": "prompt", "session_id": "c", "turn_id": "t"}
        )
        self.projects.reset()

        self.assertEqual(
            [card.source for card in self.projects.bubble_cards], ["claude_code"]
        )
        self.observe(claude("Stop", background_tasks=[]))
        self.assertEqual(self.card().rows[0].state, "done")

    def test_subagent_joins_its_parent_card_before_the_parent_reports(self):
        self.observe(
            claude(
                "PreToolUse",
                tool_use_id="toolu_child",
                agent_id="agent-1",
                agent_type="Explore",
            )
        )

        card = self.card()
        self.assertEqual(card.label, "kettle-demo")
        self.assertEqual(card.source, "claude_code")
        self.assertEqual(len(card.rows), 1)
        self.assertEqual(card.rows[0].thread_id, "claude_code:" + SESSION)

    def compaction(self):
        return [
            self.projects.observe(claude("PreCompact", trigger="manual")),
            self.projects.observe(claude("SessionStart", source="compact")),
            self.projects.observe(claude("PostCompact", trigger="manual")),
        ]

    def test_compaction_reaches_the_pet_only_inside_an_open_turn(self):
        self.observe(claude("UserPromptSubmit"))
        self.assertEqual(self.compaction(), [True, True, True])

        # /compact between turns sends no Stop; the pet must not start work.
        self.observe(claude("Stop", background_tasks=[]))
        self.assertEqual(self.compaction(), [False, False, False])
        self.assertEqual(self.card().rows[0].state, "done")

    def test_compaction_during_a_background_wait_does_not_reach_the_pet(self):
        self.observe(claude("UserPromptSubmit"))
        self.observe(claude("Stop", background_tasks=[{"type": "shell"}]))

        self.assertEqual(self.compaction(), [False, False, False])
        self.assertEqual(self.card().rows[0].state, "background")

    def test_subagent_work_keeps_the_parent_turn_until_its_completion(self):
        self.observe(claude("UserPromptSubmit"))
        self.observe(claude("PreToolUse", tool_use_id="toolu_agent"))
        self.observe(claude("SubagentStart", agent_id="agent-1", agent_type="Explore"))
        for minute in range(12):
            self.clock.value += 60
            self.projects.expire()
            for name in ("PreToolUse", "PostToolUse"):
                self.observe(
                    claude(
                        name,
                        tool_use_id=f"toolu_child_{minute}",
                        agent_id="agent-1",
                        agent_type="Explore",
                    )
                )
        self.observe(claude("SubagentStop", agent_id="agent-1", agent_type="Explore"))
        self.observe(claude("PostToolUse", tool_use_id="toolu_agent"))
        self.observe(claude("Stop", background_tasks=[]))

        row = self.card().rows[0]
        self.assertEqual(row.thread_id, "claude_code:" + SESSION)
        self.assertEqual(row.state, "done")
        self.assertEqual(len(self.projects.visible_completions), 1)

    def test_an_open_tool_uses_the_confirmation_inactivity_limit(self):
        self.observe(claude("UserPromptSubmit"))
        self.observe(claude("PreToolUse", tool_use_id="toolu_build"))
        self.clock.value += 29 * 60
        self.projects.expire()
        self.assertEqual(self.card().rows[0].state, "running")
        self.clock.value += 60
        self.projects.expire()
        self.assertEqual(self.projects.bubble_cards, ())

    def test_a_finished_tool_returns_to_the_work_limit(self):
        self.observe(claude("UserPromptSubmit"))
        self.observe(claude("PreToolUse", tool_use_id="toolu_read"))
        self.observe(claude("PostToolUse", tool_use_id="toolu_read"))
        self.clock.value += 10 * 60
        self.projects.expire()
        self.assertEqual(self.projects.bubble_cards, ())

    def test_claude_code_wait_is_named_a_permission_request(self):
        theme = SimpleNamespace(text="#000000")
        self.observe(claude("UserPromptSubmit"))
        self.observe(claude("PreToolUse", tool_use_id="toolu_1"))
        self.observe(claude("PermissionRequest", tool_name="Bash"))

        card = self.card()
        label, tooltip, _foreground, background = _badge_presentation(
            card.rows[0], theme
        )
        self.assertEqual(card.summary, "권한 요청 1개")
        self.assertEqual(label, "권한 요청")
        self.assertIn("승인한 뒤에도", tooltip)
        self.assertEqual(background, "#fff0b5")
        self.assertEqual(state_label("waiting", "claude_code"), "권한 요청")

        codex_turn = {"source": "codex", "session_id": "c", "turn_id": "t"}
        self.projects.observe({**codex_turn, "event": "prompt"})
        self.projects.observe(
            {**codex_turn, "event": "PermissionRequest", "approval_actor": "user"}
        )
        codex = next(c for c in self.projects.cards if c.source == "codex")
        self.assertEqual(codex.summary, "확인 필요 1개")
        self.assertEqual(
            _badge_presentation(codex.rows[0], theme)[:2], ("확인 필요", "")
        )


class ClaudeCodePresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_pet_forgets_only_codex_sessions_on_account_change(self):
        manager = AgentSessionManager()
        for source in ("codex", "claude_code"):
            manager.apply(
                build_decision(
                    {"source": source, "event": "prompt", "session_id": "same"}
                )
            )

        aggregate = manager.clear("codex")

        self.assertEqual(aggregate.source, "claude_code")
        self.assertEqual([s.source for s in manager.list_sessions()], ["claude_code"])

    def test_compaction_between_turns_leaves_the_pet_idle(self):
        clock = Clock()
        controller = PetAgentController(
            lambda _state: None,
            session_manager=AgentSessionManager(now_ms=lambda: int(clock() * 1000)),
        )
        surface = SimpleNamespace(
            agent_controller=controller,
            apply_agent_payload=controller.apply_payload,
            current_state="idle",
        )
        service = AgentActivityService(
            surface, projects=ProjectActivityService(now=clock)
        )
        service.observe(claude("UserPromptSubmit"))
        service.observe(claude("Stop", background_tasks=[]))
        service.observe(claude("PreCompact", trigger="manual"))
        service.observe(claude("SessionStart", source="compact"))
        service.observe(claude("PostCompact", trigger="manual"))

        self.assertEqual(controller.aggregate_state.state, "idle")
        self.assertEqual(controller.current_presentation.working_sources, ())
        controller.deleteLater()

    def test_only_agent_sources_get_a_dot_and_a_spoken_name(self):
        self.assertEqual(
            source_mark_color("claude_code"),
            design_tokens.LIGHT_THEME["source-claude-code"],
        )
        self.assertEqual(
            source_mark_color("codex"), design_tokens.LIGHT_THEME["source-codex"]
        )
        self.assertEqual(source_mark_color("schedule"), "")
        self.assertEqual(
            source_marked_text("kettle-demo", "claude_code"),
            "Claude Code · kettle-demo",
        )
        self.assertEqual(source_marked_text("사용량", "system"), "사용량")

    def test_caption_names_working_sources(self):
        self.assertEqual(
            activity_message("running", ("claude_code",)),
            "Claude Code 작업을 돕는 중",
        )
        self.assertEqual(
            activity_message("running", ("codex", "claude_code")),
            "Codex·Claude Code 작업을 돕는 중",
        )
        self.assertEqual(activity_message("running"), "작업을 돕는 중")
        self.assertEqual(
            activity_message("waiting", ("claude_code",)), "확인을 기다리는 중"
        )

    def test_working_sources_skip_waiting_sessions_and_duplicates(self):
        sessions = (
            SimpleNamespace(state="waiting", source="codex"),
            SimpleNamespace(state="running", source="claude_code"),
            SimpleNamespace(state="review", source="claude_code"),
        )

        self.assertEqual(working_sources(sessions), ("claude_code",))

    def test_claude_code_row_opens_the_activity_list_not_codex(self):
        opened = []
        router = NotificationActionRouter(opener=lambda url: opened.append(url))
        router.app_available = True
        router.internal_open = lambda target: opened.append(target) or True

        self.assertTrue(
            router.open(router.register("thread", "claude_code:" + SESSION))
        )
        self.assertEqual(opened, [ActionTarget("projects")])
        self.assertEqual(router.label("thread", "claude_code:" + SESSION), "목록 보기")
        self.assertEqual(router.label("thread", SESSION), "대화 열기")

    def test_history_names_the_source_and_folder(self):
        projects = ProjectActivityService()
        projects.observe(claude("UserPromptSubmit"))
        projects.observe(claude("Stop", background_tasks=[]))
        router = NotificationActionRouter(opener=lambda _url: False)
        history = HistoryViewModel(
            NotificationService(), projects=projects, router=router
        )

        entries = {entry.group: entry for entry in history.snapshot.entries}
        for group in ("progress", "completion"):
            self.assertEqual(entries[group].source, "Claude Code")
            self.assertEqual(entries[group].summary, "kettle-demo · Claude Code 대화")


if __name__ == "__main__":
    unittest.main()
