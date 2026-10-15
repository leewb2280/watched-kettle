"""Claude Code task history from transcripts (stage 13)."""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from watched_kettle.storage.claude_code_repository import ClaudeCodeRepository
from watched_kettle.storage.database import DatabaseManager
from watched_kettle.usage.claude_code_service import ClaudeCodeUsageService
from watched_kettle.usage.claude_code_transcripts import FilePass
from watched_kettle.usage.identifiers import hash_identifier


SESSION = "0d5c1c00-0000-4000-8000-000000000001"
NOW = datetime.now(timezone.utc).replace(microsecond=0)


def stamp(minutes):
    return (NOW - timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def user(prompt, minutes, cwd="C:/work/kettle-demo", text="secret prompt"):
    return {
        "type": "user",
        "promptId": prompt,
        "sessionId": SESSION,
        "cwd": cwd,
        "timestamp": stamp(minutes),
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
    }


def assistant(message, minutes, output, stop="tool_use", request="r1"):
    return {
        "type": "assistant",
        "sessionId": SESSION,
        "requestId": request,
        "timestamp": stamp(minutes),
        "message": {
            "id": message,
            "model": "claude-opus-5-5",
            "stop_reason": stop,
            "content": [{"type": "text", "text": "secret answer"}],
            "usage": {
                "input_tokens": 10,
                "cache_creation_input_tokens": 100,
                "cache_read_input_tokens": 1000,
                "output_tokens": output,
            },
        },
    }


def write(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        for entry in entries:
            stream.write(json.dumps(entry) + "\n")


def session_entries():
    return [
        user("p1", 30),
        # Two content blocks of one message repeat its usage.
        assistant("m1", 29, 5),
        assistant("m1", 29, 7),
        assistant("m2", 28, 3, stop="end_turn", request="r2"),
        {"type": "ai-title", "aiTitle": "Generated", "sessionId": SESSION},
        user("p2", 20),
        assistant("m3", 19, 4, request="r3"),
        user("p3", 2),
        assistant("m4", 1, 6, request="r4"),
    ]


class FilePassTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.path = Path(self.directory.name) / f"{SESSION}.jsonl"
        write(self.path, session_entries())

    def tearDown(self):
        self.directory.cleanup()

    def parse(self, offset=0, idle=False):
        current = FilePass(self.path, SESSION, "main", offset)
        while not current.read(64):
            pass
        return current, current.finish(idle)

    def test_turns_outcomes_and_deduplicated_tokens(self):
        current, parts = self.parse()

        self.assertEqual(
            [p.outcome for p in parts], ["completed", "cancelled", "running"]
        )
        first = parts[0]
        self.assertEqual(first.tokens["output_tokens"], 7 + 3)
        self.assertEqual(first.input_tokens, 2 * 1110)
        self.assertEqual(first.total_tokens, 2 * 1110 + 10)
        self.assertEqual(first.model, "claude-opus-5-5")
        self.assertEqual(current.title, "Generated")
        self.assertEqual(current.project_label, "kettle-demo")
        self.assertRegex(current.project_hash, r"^[0-9a-f]{16}$")
        self.assertEqual(first.turn_hash, hash_identifier("p1"))
        self.assertEqual(self.parse(idle=True)[1][-1].outcome, "cancelled")

    def test_resume_starts_at_the_last_turn(self):
        current, _parts = self.parse()
        write(self.path, [assistant("m5", 0, 9, stop="end_turn", request="r5")])

        resumed, parts = self.parse(current.resume_offset)

        self.assertEqual([p.turn_hash for p in parts], [hash_identifier("p3")])
        self.assertEqual(parts[0].outcome, "completed")
        self.assertEqual(parts[0].tokens["output_tokens"], 6 + 9)

    def test_no_content_or_path_is_kept(self):
        current, parts = self.parse()

        kept = repr((current.titles, [vars(p) for p in parts]))
        for private in ("secret", "C:/work"):
            self.assertNotIn(private, kept)


class ServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = TemporaryDirectory()
        root = Path(self.directory.name)
        self.config = root / "claude"
        self.folder = self.config / "projects" / "C--work-kettle-demo"
        self.transcript = self.folder / f"{SESSION}.jsonl"
        write(self.transcript, session_entries())
        self.database = DatabaseManager(root / "usage.sqlite3")
        self.assertTrue(self.database.start().available)
        self.repository = ClaudeCodeRepository(self.database)
        self.service = ClaudeCodeUsageService(self.repository, config_dir=self.config)

    def tearDown(self):
        self.service.close()
        self.database.close()
        self.directory.cleanup()

    def drain(self):
        for _ in range(100):
            self.service.tick()
            if self.service.snapshot.availability.state == "ready":
                return self.service.snapshot
        self.fail("import did not finish")

    def test_import_builds_project_conversation_and_task_pages(self):
        snapshot = self.drain()

        self.assertEqual([p.name for p in snapshot.projects], ["kettle-demo"])
        self.assertEqual(snapshot.conversations[0].title, "Generated")
        self.assertEqual(snapshot.conversations[0].task_count, 3)
        self.assertEqual(len(snapshot.latest_tasks), 3)
        self.assertEqual(snapshot.latest_tasks[0].outcome, "running")

        self.service.select_usage_conversation(hash_identifier(SESSION))
        tasks = self.service.snapshot.recent_tasks
        self.assertEqual(
            [t.outcome for t in tasks], ["running", "cancelled", "completed"]
        )
        self.assertEqual(tasks[-1].cached_input_tokens, 2 * 1000)

    def test_user_title_file_wins_and_new_turns_are_picked_up(self):
        (self.folder / SESSION).mkdir()
        (self.folder / SESSION / "custom-title.json").write_text(
            json.dumps({"customTitle": "내 이름"}), encoding="utf-8"
        )
        self.drain()
        write(self.transcript, [assistant("m5", 0, 9, stop="end_turn", request="r5")])

        snapshot = self.drain()

        self.assertEqual(snapshot.conversations[0].title, "내 이름")
        self.assertEqual(snapshot.latest_tasks[0].outcome, "completed")
        self.assertEqual(len(snapshot.latest_tasks), 3)

    def test_subagent_tokens_join_the_parent_turn(self):
        agent = self.folder / SESSION / "subagents" / "agent-a1.jsonl"
        write(
            agent,
            [
                {**user("p3", 2), "isSidechain": True},
                assistant("sub", 1, 40, stop="end_turn", request="rs"),
            ],
        )

        snapshot = self.drain()

        running = snapshot.latest_tasks[0]
        self.assertEqual(running.outcome, "running")
        self.assertEqual(running.output_tokens, 6 + 40)

    def test_cleared_history_is_not_imported_again(self):
        self.drain()
        self.service.clear_history()
        self.assertEqual(self.service.snapshot.latest_tasks, ())

        self.transcript.touch()
        os.utime(self.transcript, None)
        # Negative minutes: after the clear, which happened after NOW was taken.
        write(
            self.transcript,
            [user("p4", -1), assistant("m6", -1, 1, stop="end_turn", request="r6")],
        )
        snapshot = self.drain()

        self.assertEqual(
            [t.turn_hash for t in snapshot.latest_tasks], [hash_identifier("p4")]
        )

    def test_disabled_service_reads_nothing(self):
        self.service.set_enabled(False)
        self.service.tick()

        self.assertEqual(self.service.snapshot.availability.state, "disabled")
        self.assertEqual(self.repository.latest_turns(), ())


if __name__ == "__main__":
    unittest.main()
