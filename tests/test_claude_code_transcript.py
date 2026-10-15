import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from watched_kettle.integrations.claude_code_hooks import normalize_claude_code_hook
from watched_kettle.integrations.claude_code_transcript import (
    MAX_CLASSIFIED_LINE_BYTES,
    PROMPT_GRACE_SECONDS,
    TITLE_SCAN_BYTES,
    ClaudeCodeTranscriptMonitor,
    TranscriptTail,
    classify_transcript_line,
)
from watched_kettle.integrations.codex_ipc import (
    PIPE_TRANSPORT,
    TRANSCRIPT_TRANSPORT,
    CodexHookServer,
)
from watched_kettle.state.controller import PetAgentController


SESSION = "0c1a0de0-0000-4000-8000-000000000001"


def entry(kind, content, **flags):
    """Shape of the transcript lines Claude Code 2.1.286 wrote in the survey."""
    line = {"type": kind, "message": {"role": kind, "content": content}}
    line.update(flags)
    return (json.dumps(line) + "\n").encode("utf-8")


PANEL_PROMPT = entry("user", [{"type": "text", "text": "please do secret work"}])
CLI_PROMPT = entry("user", "please do secret work")
INTERRUPT = entry("user", [{"type": "text", "text": "[Request interrupted by user]"}])
TOOL_ERROR = entry(
    "user",
    [{"type": "tool_result", "is_error": True, "content": "denied"}],
)
ASSISTANT = entry("assistant", [{"type": "text", "text": "working"}])


def title(kind, value):
    """``ai-title``/``custom-title`` lines as Claude Code 2.1.286 writes them."""
    field = {"ai-title": "aiTitle", "custom-title": "customTitle"}[kind]
    line = json.dumps({"type": kind, field: value, "sessionId": SESSION})
    return (line + "\n").encode("utf-8")


class FakeClock:
    def __init__(self):
        self.value = 1_000.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class TranscriptLineTests(unittest.TestCase):
    def test_only_plain_user_text_is_user_text(self):
        for line in (PANEL_PROMPT, CLI_PROMPT, INTERRUPT):
            self.assertEqual(classify_transcript_line(line.strip()), "user_text")
        for line in (
            TOOL_ERROR,
            ASSISTANT,
            entry("user", "caveat", isMeta=True),
            entry("user", "summary", isCompactSummary=True),
            entry("user", "agent prompt", isSidechain=True),
            entry("user", "   "),
            entry("queue-operation", None),
            # A finished background command's result (Claude Code 2.1.288).
            entry(
                "user",
                "<task-notification>done</task-notification>",
                promptSource="system",
                turnOrigin="task_notification",
            ),
            b"{not json",
        ):
            self.assertEqual(classify_transcript_line(line.strip()), "other")

    def test_oversized_lines_are_not_parsed(self):
        line = entry("user", "x" * MAX_CLASSIFIED_LINE_BYTES)

        self.assertEqual(classify_transcript_line(line.strip()), "other")


class TranscriptTailTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.path = Path(self.directory.name) / "session.jsonl"
        self.path.write_bytes(CLI_PROMPT + ASSISTANT)

    def tearDown(self):
        self.directory.cleanup()

    def append(self, data):
        with self.path.open("ab") as stream:
            stream.write(data)

    def test_reads_only_lines_appended_after_start(self):
        tail = TranscriptTail(self.path)
        self.assertEqual(tail.read_kinds(), [])

        self.append(TOOL_ERROR + INTERRUPT)

        self.assertEqual(tail.read_kinds(), ["other", "user_text"])
        self.assertEqual(tail.read_kinds(), [])

    def test_partial_line_waits_for_its_newline(self):
        tail = TranscriptTail(self.path)
        self.append(INTERRUPT[:10])
        self.assertEqual(tail.read_kinds(), [])

        self.append(INTERRUPT[10:])

        self.assertEqual(tail.read_kinds(), ["user_text"])

    def test_oversized_partial_line_is_skipped_without_buffering(self):
        tail = TranscriptTail(self.path)
        big = entry("user", [{"type": "tool_result", "content": "x" * 200_000}])
        self.append(big[:-1])
        self.assertEqual(tail.read_kinds(), [])

        self.append(b"\n" + INTERRUPT)

        self.assertEqual(tail.read_kinds(), ["other", "user_text"])

    def test_rewritten_file_restarts_from_the_beginning(self):
        tail = TranscriptTail(self.path)
        self.path.write_bytes(INTERRUPT)

        self.assertEqual(tail.read_kinds(), ["user_text"])

    def test_existing_title_is_read_and_user_title_wins(self):
        self.append(title("ai-title", "Generated name") + ASSISTANT)
        tail = TranscriptTail(self.path)
        self.assertEqual(tail.title, "Generated name")

        self.append(title("custom-title", "My\tname") + title("ai-title", "Newer"))
        self.assertEqual(tail.read_kinds(), ["other", "other"])

        self.assertEqual(tail.title, "My name")

    def test_title_scan_is_bounded_to_the_end_of_the_file(self):
        self.path.write_bytes(
            title("ai-title", "Old")
            + entry("assistant", "x" * (TITLE_SCAN_BYTES + 10))
            + ASSISTANT
        )

        self.assertEqual(TranscriptTail(self.path).title, "")


class TranscriptMonitorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = TemporaryDirectory()
        self.config = Path(self.directory.name)
        project = self.config / "projects" / "C--work-project"
        project.mkdir(parents=True)
        self.transcript = project / f"{SESSION}.jsonl"
        self.transcript.write_bytes(b"")
        self.clock = FakeClock()
        self.monitor = ClaudeCodeTranscriptMonitor(
            config_dir=self.config, now=self.clock
        )
        self.detected = []
        self.monitor.payload_detected.connect(self.detected.append)

    def tearDown(self):
        self.monitor.close()
        self.monitor.deleteLater()
        self.directory.cleanup()

    def hook(self, name, **fields):
        payload = {"session_id": SESSION, "hook_event_name": name, **fields}
        self.monitor.observe(normalize_claude_code_hook(payload))

    def append(self, data):
        with self.transcript.open("ab") as stream:
            stream.write(data)

    def start_turn(self):
        self.hook("UserPromptSubmit", prompt_id="p1")
        self.monitor.poll()  # locates the transcript at its current end
        self.append(PANEL_PROMPT)
        self.clock.advance(0.5)
        self.monitor.poll()

    def test_denied_permission_ends_the_turn_after_the_grace_period(self):
        self.start_turn()
        self.hook("PreToolUse", tool_use_id="t1")
        self.hook("PermissionRequest")
        self.clock.advance(5)
        self.append(TOOL_ERROR + INTERRUPT)
        self.monitor.poll()
        self.assertEqual(self.detected, [])

        self.clock.advance(PROMPT_GRACE_SECONDS)
        self.monitor.poll()

        self.assertEqual(
            self.detected,
            [
                {
                    "source": "claude_code",
                    "event": "cancelled",
                    "session_id": SESSION,
                    "agent_scope": "main",
                    "collected_at": self.detected[0]["collected_at"],
                }
            ],
        )
        self.assertEqual(self.monitor.watched_sessions, ())
        self.assertFalse(self.monitor.timer.isActive())

    def test_prompt_hook_arriving_after_its_line_is_not_an_interrupt(self):
        self.start_turn()
        self.clock.advance(30)
        self.append(CLI_PROMPT)
        self.monitor.poll()
        self.clock.advance(0.5)
        self.hook("UserPromptSubmit", prompt_id="p2")

        self.clock.advance(PROMPT_GRACE_SECONDS)
        self.monitor.poll()

        self.assertEqual(self.detected, [])
        self.assertEqual(self.monitor.watched_sessions, (SESSION,))

    def test_tool_results_and_assistant_text_do_not_end_the_turn(self):
        self.start_turn()
        self.clock.advance(10)
        self.append(TOOL_ERROR + ASSISTANT)
        self.monitor.poll()
        self.clock.advance(10)
        self.monitor.poll()

        self.assertEqual(self.detected, [])

    def test_turn_end_hook_stops_watching(self):
        self.start_turn()
        self.hook("Stop", background_tasks=[])
        self.assertEqual(self.monitor.watched_sessions, ())

        self.append(INTERRUPT)
        self.clock.advance(10)
        self.monitor.poll()

        self.assertEqual(self.detected, [])

    def test_background_stop_and_subagent_events_keep_the_parent_watched(self):
        self.start_turn()
        self.hook("Stop", background_tasks=[{"type": "agent"}])
        self.hook("SubagentStop", agent_id="a6cbe57b0", agent_type="general-purpose")

        self.assertEqual(self.monitor.watched_sessions, (SESSION,))

    def test_compaction_and_session_start_do_not_start_a_watch(self):
        self.hook("SessionStart", source="startup")
        self.hook("PreCompact", trigger="manual")
        self.hook("PostCompact", trigger="manual")

        self.assertEqual(self.monitor.watched_sessions, ())
        self.assertFalse(self.monitor.timer.isActive())

    def test_title_is_reported_once_per_change(self):
        titles = []
        self.monitor.title_detected.connect(
            lambda session, value: titles.append((session, value))
        )
        self.append(title("ai-title", "First"))
        self.start_turn()
        self.append(title("ai-title", "First"))
        self.monitor.poll()
        self.append(title("custom-title", "Renamed"))
        self.monitor.poll()

        self.assertEqual(titles, [(SESSION, "First"), (SESSION, "Renamed")])

    def test_unsafe_session_ids_are_never_globbed(self):
        self.monitor.observe(
            {"source": "claude_code", "event": "prompt", "session_id": "*"}
        )

        self.assertEqual(self.monitor.watched_sessions, ())

    def test_missing_transcript_is_given_up_after_bounded_attempts(self):
        other = str(uuid4())
        self.monitor.observe(
            {"source": "claude_code", "event": "prompt", "session_id": other}
        )
        for _ in range(40):
            self.monitor.poll()

        self.assertEqual(self.monitor.watched_sessions, ())


class TranscriptServerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = TemporaryDirectory()
        root = Path(self.directory.name)
        project = root / "claude" / "projects" / "C--work"
        project.mkdir(parents=True)
        self.transcript = project / f"{SESSION}.jsonl"
        self.transcript.write_bytes(b"")
        self.clock = FakeClock()
        self.server = CodexHookServer(
            server_name=f"watched-kettle-test-{uuid4().hex}",
            spool_directory=root / "events",
            hook_config_path=root / "hooks.json",
            global_hook_config_path=root / "global-hooks.json",
            codex_config_path=root / "config.toml",
            hook_health_path=root / "hook-health.json",
            managed_spool_directory=None,
            managed_hook_health_path=None,
        )
        self.monitor = ClaudeCodeTranscriptMonitor(
            config_dir=root / "claude", now=self.clock
        )
        self.server.attach_transcript_monitor(self.monitor)
        self.displayed = []
        self.controller = PetAgentController(self.displayed.append)
        self.server.payload_received.connect(self.controller.apply_payload)

    def tearDown(self):
        self.server.close()
        self.monitor.close()
        self.controller.deleteLater()
        self.server.deleteLater()
        self.monitor.deleteLater()
        self.directory.cleanup()

    def deliver(self, name, **fields):
        payload = {"session_id": SESSION, "hook_event_name": name, **fields}
        self.server._deliver_payload(
            normalize_claude_code_hook(payload), PIPE_TRANSPORT
        )

    def test_denial_releases_the_confirmation_wait(self):
        self.deliver("UserPromptSubmit", prompt_id="p1")
        self.monitor.poll()
        self.deliver("PreToolUse", tool_use_id="t1", prompt_id="p1")
        self.deliver("PermissionRequest", prompt_id="p1")
        self.assertEqual(self.controller.desired_state, "waiting")

        self.clock.advance(5)
        with self.transcript.open("ab") as stream:
            stream.write(TOOL_ERROR + INTERRUPT)
        self.monitor.poll()
        self.clock.advance(PROMPT_GRACE_SECONDS)
        self.monitor.poll()

        self.assertEqual(self.controller.desired_state, "idle")
        self.assertEqual(self.server.transport_event_counts[TRANSCRIPT_TRANSPORT], 1)
        self.assertIsNotNone(self.server.last_hook_received_at)

    def test_closing_the_server_detaches_the_monitor(self):
        self.server.close()

        self.assertIsNone(self.server.transcript_monitor)


if __name__ == "__main__":
    unittest.main()
