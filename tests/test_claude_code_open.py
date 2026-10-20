"""Claude Code rows open where the session runs; agent sources get a dot."""

import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication, QWidget

from watched_kettle.features.notifications.actions import (
    ActionTarget,
    NotificationActionRouter,
)
from watched_kettle.features.notifications.service import NotificationService
from watched_kettle.features.project_activity.service import ProjectActivityService
from watched_kettle.integrations.claude_code_hooks import (
    claude_code_client,
    normalize_claude_code_hook,
)
from watched_kettle.integrations.claude_code_launcher import (
    CWD_SCAN_BYTES,
    DETACHED_PROCESS,
    ClaudeCodeLauncher,
    folder_url,
    open_url,
    session_url,
    transcript_cwd,
)
from watched_kettle.integrations.codex_hooks import sanitize_pet_event
from watched_kettle.ui import design_tokens
from watched_kettle.ui.actionable_bubbles import ActionableBubbleController
from watched_kettle.ui.speech_bubble_window import SpeechBubbleWindow


SESSION = "8d4f034a-0000-4000-8000-000000000001"
THREAD = "claude_code:" + SESSION
FOLDER = "C:/Users/example/work/kettle-demo"


def claude(name, client=None, session=SESSION):
    return normalize_claude_code_hook(
        {
            "session_id": session,
            "cwd": FOLDER,
            "hook_event_name": name,
            "prompt_id": "69492e26-0000-4000-8000-000000000002",
        },
        client=client,
    )


class ClientTests(unittest.TestCase):
    def test_environment_names_where_the_session_runs(self):
        self.assertEqual(
            claude_code_client({"CLAUDE_CODE_ENTRYPOINT": "claude-vscode"}),
            "vscode-panel",
        )
        self.assertEqual(
            claude_code_client(
                {"CLAUDE_CODE_ENTRYPOINT": "cli", "TERM_PROGRAM": "vscode"}
            ),
            "vscode-terminal",
        )
        self.assertEqual(
            claude_code_client({"CLAUDE_CODE_ENTRYPOINT": "cli"}), "terminal"
        )
        self.assertIsNone(claude_code_client({"CLAUDE_CODE_ENTRYPOINT": "sdk-cli"}))
        self.assertIsNone(claude_code_client({}))

    def test_only_known_clients_cross_the_pipe(self):
        self.assertEqual(
            claude("UserPromptSubmit", "vscode-panel")["client"], "vscode-panel"
        )
        self.assertNotIn("client", claude("UserPromptSubmit", "emacs"))
        forged = dict(claude("UserPromptSubmit"), client="C:/secret")
        self.assertNotIn("client", sanitize_pet_event(forged))

    def test_service_remembers_the_client_per_session(self):
        projects = ProjectActivityService()
        projects.observe(claude("UserPromptSubmit", "vscode-terminal"))
        self.assertEqual(projects.claude_code_client(THREAD), "vscode-terminal")
        self.assertEqual(projects.claude_code_client("claude_code:other"), "")


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.opened = []
        self.results = {}

    def opener(self, url):
        self.opened.append(url.toString())
        return self.results.get(url.host(), True)

    def launcher(self, vscode=True, cwd="C:\\work\\kettle"):
        return ClaudeCodeLauncher(
            self.opener, vscode_available=vscode, cwd_reader=lambda _id: cwd
        )

    def test_urls_accept_only_session_ids_and_local_folders(self):
        self.assertEqual(
            session_url(SESSION).toString(),
            f"vscode://anthropic.claude-code/open?session={SESSION}",
        )
        self.assertIsNone(session_url("../../etc"))
        self.assertEqual(
            folder_url("C:\\work\\kettle demo\\").toString(),
            "vscode://file/C:/work/kettle demo",
        )
        for cwd in ("work/kettle", "\\\\server\\share", None):
            self.assertIsNone(folder_url(cwd))

    def test_each_client_opens_its_own_target(self):
        launcher = self.launcher()
        self.assertEqual(launcher.open(SESSION, "vscode-panel"), (True, ""))
        self.assertEqual(launcher.open(SESSION, "vscode-terminal"), (True, ""))
        self.assertEqual(
            self.opened,
            [
                f"vscode://anthropic.claude-code/open?session={SESSION}",
                "vscode://file/C:/work/kettle",
            ],
        )
        self.assertEqual(launcher.label("vscode-panel"), "대화 열기")
        self.assertEqual(launcher.label("vscode-terminal"), "창 열기")
        self.assertEqual(launcher.label("terminal"), "목록 보기")

    def test_cli_sessions_are_never_reopened_in_the_panel(self):
        opened, message = self.launcher().open(SESSION, "terminal")
        self.assertFalse(opened)
        self.assertIn("터미널", message)
        self.assertEqual(self.opened, [])

    def test_a_failed_session_link_falls_back_to_the_folder_window(self):
        self.results["anthropic.claude-code"] = False
        opened, message = self.launcher().open(SESSION, "vscode-panel")
        self.assertTrue(opened)
        self.assertIn("작업 폴더", message)
        self.results["file"] = False
        self.assertEqual(
            self.launcher().open(SESSION, "vscode-panel"),
            (False, "VS Code에서 이 대화를 열지 못했습니다."),
        )

    def test_without_vscode_every_row_shows_the_list(self):
        launcher = self.launcher(vscode=False)
        self.assertEqual(launcher.label("vscode-panel"), "목록 보기")
        self.assertEqual(launcher.open(SESSION, "vscode-panel"), (False, ""))
        self.assertEqual(self.opened, [])

    def write_transcript(self, config, lines):
        folder = Path(config, "projects", "c--work")
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{SESSION}.jsonl").write_text(
            "\n".join(json.dumps(line) for line in lines), encoding="utf-8"
        )

    def test_folder_is_where_the_session_started(self):
        # The VS Code window stays on the start folder after the session moves
        # into a worktree.
        with tempfile.TemporaryDirectory() as config:
            self.write_transcript(
                config,
                [
                    {"type": "mode", "mode": "normal"},
                    {"type": "user", "cwd": "C:\\work\\kettle"},
                    {"type": "user", "cwd": "C:\\work\\kettle\\.claude\\worktrees\\x"},
                    {"type": "ai-title", "aiTitle": "제목"},
                ],
            )
            self.assertEqual(transcript_cwd(SESSION, config), "C:\\work\\kettle")
            self.assertIsNone(transcript_cwd("missing-0000", config))

    def test_a_start_too_long_to_read_falls_back_to_the_newest_folder(self):
        with tempfile.TemporaryDirectory() as config:
            self.write_transcript(
                config,
                [
                    {"type": "user", "text": "x" * CWD_SCAN_BYTES, "cwd": "C:\\old"},
                    {"type": "user", "cwd": "C:\\work\\kettle"},
                    {"type": "assistant", "cwd": "C:\\work\\kettle\\sub"},
                ],
            )
            self.assertEqual(transcript_cwd(SESSION, config), "C:\\work\\kettle\\sub")


class OpenUrlTests(unittest.TestCase):
    URL = "vscode://file/C:/work/kettle demo"

    def test_console_runs_open_links_through_a_detached_process(self):
        # VS Code's link handler attaches to the caller's console and leaves a
        # blank line in the terminal of a source run.
        started, shell = [], []

        def popen(args, **options):
            started.append((args, options))

        from PySide6.QtCore import QUrl

        self.assertTrue(open_url(QUrl(self.URL), shell.append, True, popen))
        args, options = started[0]
        self.assertEqual(args[:2], ["rundll32.exe", "url.dll,FileProtocolHandler"])
        self.assertEqual(args[2], "vscode://file/C:/work/kettle%20demo")
        self.assertEqual(options["creationflags"], DETACHED_PROCESS)
        self.assertEqual(shell, [])

    def test_installed_app_and_failed_starts_use_the_shell(self):
        from PySide6.QtCore import QUrl

        def broken(*_args, **_options):
            raise OSError("no rundll32")

        for console, popen in ((False, None), (True, broken)):
            with self.subTest(console=console):
                opened = []
                self.assertTrue(
                    open_url(
                        QUrl(self.URL),
                        lambda url: opened.append(url) or True,
                        console,
                        popen,
                    )
                )
                self.assertEqual(len(opened), 1)


class RouterTests(unittest.TestCase):
    def setUp(self):
        self.opened = []
        self.failures = []
        self.router = NotificationActionRouter(opener=lambda url: True)
        self.router.claude_code_launcher = ClaudeCodeLauncher(
            lambda url: self.opened.append(url.toString()) or True,
            vscode_available=True,
            cwd_reader=lambda _id: "C:\\work",
        )
        self.router.internal_open = lambda target: self.opened.append(target) or True
        self.router.failed.connect(self.failures.append)
        self.clients = {}
        self.router.claude_code_client = self.clients.get

    def test_label_and_target_follow_the_session_client(self):
        self.clients[THREAD] = "vscode-panel"
        self.assertEqual(self.router.label("thread", THREAD), "대화 열기")
        self.assertTrue(self.router.open(self.router.register("thread", THREAD)))
        self.assertEqual(
            self.opened, [f"vscode://anthropic.claude-code/open?session={SESSION}"]
        )

    def test_terminal_session_opens_the_list_and_says_why(self):
        self.clients[THREAD] = "terminal"
        self.assertTrue(self.router.open(self.router.register("thread", THREAD)))
        self.assertEqual(self.opened, [ActionTarget("projects")])
        self.assertEqual(len(self.failures), 1)

    def test_unknown_client_keeps_the_list_quietly(self):
        self.assertEqual(self.router.label("thread", THREAD), "목록 보기")
        self.assertTrue(self.router.open(self.router.register("thread", THREAD)))
        self.assertEqual(self.opened, [ActionTarget("projects")])
        self.assertEqual(self.failures, [])


class SourceMarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_notice_chip_shows_a_dot_only_when_marks_are_on(self):
        pet = QWidget()
        pet.always_on_top = False
        window = SpeechBubbleWindow(pet)
        window.set_message("확인해 주세요", "waiting", "claude_code")
        self.assertEqual(window.category_label.text(), "확인 필요")
        self.assertEqual(window.category_label.mark_color, "")
        plain_width = window.category_label.sizeHint().width()

        window.set_source_marks_shown(True)
        self.assertEqual(window.category_label.text(), "확인 필요")
        self.assertEqual(
            window.category_label.mark_color,
            design_tokens.LIGHT_THEME["source-claude-code"],
        )
        self.assertGreater(window.category_label.sizeHint().width(), plain_width)
        self.assertEqual(window.category_label.toolTip(), "Claude Code · 확인 필요")

        # Other sources keep their name as text.
        window.set_message("회의 10분 전", "notification", "schedule")
        self.assertEqual(window.category_label.mark_color, "")
        window.close()
        pet.close()

    def test_cards_carry_the_source_only_when_marks_are_on(self):
        pet = QWidget()
        pet.always_on_top = False
        pet.setGeometry(800, 900, 100, 110)
        projects = ProjectActivityService()
        projects.observe(claude("UserPromptSubmit", "vscode-panel"))
        controller = ActionableBubbleController(
            pet,
            projects,
            NotificationService(),
            NotificationActionRouter(opener=lambda _url: True),
        )
        screen = patch(
            "watched_kettle.ui.actionable_bubbles.QApplication.screenAt",
            return_value=SimpleNamespace(
                availableGeometry=lambda: QRect(0, 0, 1920, 1080)
            ),
        )
        screen.start()
        try:
            cards = [c for c in controller._contents() if c.key.startswith("project:")]
            self.assertEqual([c.heading for c in cards], ["kettle-demo"])
            self.assertEqual(cards[0].mark, "")
            pet.show()
            controller.reposition()
            controller.set_source_marks_shown(True)
            self.app.processEvents()
            cards = [c for c in controller._contents() if c.key.startswith("project:")]
            self.assertEqual(cards[0].mark, "claude_code")
            # The painted dot, not only the content: set_message must not reset it.
            window = controller.card_windows[cards[0].key]
            self.assertEqual(
                window.category_label.mark_color,
                design_tokens.LIGHT_THEME["source-claude-code"],
            )
            self.assertEqual(window.category_label.text(), "kettle-demo")
            self.assertEqual(
                window.category_label.toolTip(), "Claude Code · kettle-demo"
            )
        finally:
            screen.stop()
            controller.close()
            pet.close()


if __name__ == "__main__":
    unittest.main()
