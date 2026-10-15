import io
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from watched_kettle import hook_bridge_entrypoint
from watched_kettle.integrations.claude_code_hooks import (
    normalize_claude_code_hook,
    project_identity,
)
from watched_kettle.integrations.codex_bridge import run_hook_bridge
from watched_kettle.integrations.codex_hooks import (
    MAX_HOOK_INPUT_BYTES,
    sanitize_pet_event,
)
from watched_kettle.state.controller import PetAgentController
from watched_kettle.state.events import build_decision
from watched_kettle.state.session_manager import (
    CLAUDE_CODE_INACTIVITY_LIMIT,
    AgentSessionManager,
    InactivityLimit,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SESSION = "8d4f034a-0000-4000-8000-000000000001"
PROMPT = "69492e26-0000-4000-8000-000000000002"


def hook(name, **fields):
    """Mirror the fields Claude Code 2.1.286 sent during the stage 13 survey."""
    payload = {
        "session_id": SESSION,
        "transcript_path": "C:/Users/example/.claude/projects/x/session.jsonl",
        "cwd": "C:/Users/example/work/kettle-demo",
        "hook_event_name": name,
        "permission_mode": "default",
        "prompt_id": PROMPT,
    }
    payload.update(fields)
    return payload


class FakeClock:
    def __init__(self):
        self.value = 1_700_000_000_000

    def __call__(self):
        return self.value

    def advance(self, milliseconds):
        self.value += int(milliseconds)


class ClaudeCodeHookFilterTests(unittest.TestCase):
    def test_filters_prompt_command_paths_and_tool_output(self):
        event = normalize_claude_code_hook(
            hook(
                "PostToolUse",
                tool_name="Bash",
                tool_input={"command": "type secret.txt", "description": "read"},
                tool_response={"stdout": "secret output", "stderr": ""},
                tool_use_id="toolu_01",
                duration_ms=12,
                scratchpad_dir="C:/Users/example/AppData/Local/Temp/x",
            )
        )

        self.assertEqual(
            event,
            {
                "source": "claude_code",
                "event": "tool_end",
                "session_id": SESSION,
                "agent_scope": "main",
                "collected_at": event["collected_at"],
                "turn_id": PROMPT,
                "event_id": "toolu_01",
                "success": True,
                "tool_status": "succeeded",
                "project_ref": project_identity("C:/Users/example/work/kettle-demo")[
                    "project_ref"
                ],
                "project_label": "kettle-demo",
            },
        )
        encoded = json.dumps(event)
        for private in ("secret", "example", "work", "type ", "Bash", "scratchpad"):
            self.assertNotIn(private, encoded)

    def test_project_identity_is_the_folder_name_and_a_path_hash(self):
        identity = project_identity("C:/Users/example/work/kettle-demo")

        self.assertEqual(identity["project_label"], "kettle-demo")
        self.assertRegex(identity["project_ref"], r"^[0-9a-f]{16}$")
        # Windows paths compare case-insensitively and ignore separators.
        for spelling in (
            "c:\\users\\EXAMPLE\\work\\kettle-demo\\",
            "C:\\Users\\example\\work\\.\\kettle-demo",
        ):
            self.assertEqual(
                project_identity(spelling)["project_ref"], identity["project_ref"]
            )
        self.assertNotEqual(
            project_identity("C:/Users/example/other/kettle-demo")["project_ref"],
            identity["project_ref"],
        )
        self.assertEqual(project_identity(""), {})
        self.assertEqual(project_identity(None), {})
        self.assertEqual(project_identity(["C:/x"]), {})
        self.assertNotIn("project_label", project_identity("C:\\"))
        self.assertEqual(
            project_identity("C:/work/line\nbreak\x7fname")["project_label"],
            "line break name",
        )

    def test_gate_drops_malformed_project_fields(self):
        event = sanitize_pet_event(
            {
                "source": "claude_code",
                "event": "prompt",
                "session_id": "x",
                "project_ref": "C:/Users/example",
                "project_label": "work\\kettle-demo",
            }
        )

        self.assertNotIn("project_ref", event)
        self.assertNotIn("project_label", event)
        codex = sanitize_pet_event(
            {
                "source": "codex",
                "event": "prompt",
                "session_id": "x",
                "project_ref": "0123456789abcdef",
                "project_label": "kettle-demo",
            }
        )
        self.assertNotIn("project_ref", codex)
        self.assertNotIn("project_label", codex)

    def test_prompt_and_stop_text_are_not_forwarded(self):
        prompt = normalize_claude_code_hook(
            hook("UserPromptSubmit", prompt="please read my secret plan")
        )
        stop = normalize_claude_code_hook(
            hook(
                "Stop",
                last_assistant_message="the secret plan is done",
                background_tasks=[],
                stop_hook_active=False,
            )
        )

        self.assertEqual(prompt["event"], "prompt")
        self.assertEqual(prompt["turn_id"], PROMPT)
        self.assertEqual(stop["event"], "done")
        self.assertNotIn("secret", json.dumps([prompt, stop]))

    def test_permission_request_is_a_user_wait(self):
        event = normalize_claude_code_hook(
            hook(
                "PermissionRequest",
                tool_name="Bash",
                tool_input={"command": "exit 3"},
                permission_suggestions=[{"type": "addRules"}],
            )
        )

        self.assertEqual(event["event"], "permission")
        self.assertEqual(event["approval_actor"], "user")
        self.assertNotIn("event_id", event)
        self.assertEqual(build_decision(event).persistent_state, "waiting")

    def test_only_permission_notifications_mean_waiting(self):
        waiting = normalize_claude_code_hook(
            hook(
                "Notification",
                notification_type="permission_prompt",
                message="Claude needs your permission",
            )
        )

        self.assertEqual(waiting["event"], "waiting")
        self.assertNotIn("message", waiting)
        for kind in ("idle_prompt", "auth_success", None):
            self.assertIsNone(
                normalize_claude_code_hook(hook("Notification", notification_type=kind))
            )

    def test_tool_failure_keeps_working_and_interrupt_cancels(self):
        failed = normalize_claude_code_hook(
            hook(
                "PostToolUseFailure",
                tool_use_id="toolu_02",
                error="Exit code 3",
                is_interrupt=False,
            )
        )
        interrupted = normalize_claude_code_hook(
            hook("PostToolUseFailure", tool_use_id="toolu_03", is_interrupt=True)
        )

        self.assertEqual(failed["event"], "tool_failed")
        self.assertEqual(failed["tool_status"], "failed")
        self.assertIs(failed["success"], False)
        decision = build_decision(failed)
        self.assertEqual(decision.persistent_state, "running")
        self.assertIsNone(decision.visual_state)
        self.assertEqual(interrupted["event"], "cancelled")
        self.assertTrue(build_decision(interrupted).terminal)

    def test_unnamed_internal_subagents_are_dropped(self):
        for name in ("SubagentStart", "SubagentStop"):
            self.assertIsNone(
                normalize_claude_code_hook(
                    hook(name, agent_id="a55120966", agent_type="")
                )
            )

    def test_named_subagent_uses_agent_session_with_parent(self):
        start = normalize_claude_code_hook(
            hook("SubagentStart", agent_id="a6cbe57b0", agent_type="general-purpose")
        )
        tool = normalize_claude_code_hook(
            hook(
                "PreToolUse",
                agent_id="a6cbe57b0",
                agent_type="general-purpose",
                tool_name="Read",
                tool_use_id="toolu_04",
            )
        )
        stop = normalize_claude_code_hook(
            hook(
                "SubagentStop",
                agent_id="a6cbe57b0",
                agent_type="general-purpose",
                agent_transcript_path="C:/Users/example/agent.jsonl",
                last_assistant_message="probe",
            )
        )

        for event in (start, tool, stop):
            self.assertEqual(event["session_id"], "a6cbe57b0")
            self.assertEqual(event["parent_session_id"], SESSION)
            self.assertEqual(event["agent_scope"], "subagent")
        self.assertEqual(start["event"], "task_start")
        self.assertEqual(tool["event"], "tool_start")
        self.assertEqual(stop["event"], "done")

    def test_stop_with_background_work_waits_for_it(self):
        for tasks, count in (
            ([{"type": "agent"}], 1),
            ([{"type": "shell", "status": "running"}], 1),
            ([{"type": "subagent", "status": "pending"}], 1),
            # Entries without a type, as older versions may send.
            ([{}], 1),
            ([{"type": "monitor", "status": "running"}, {"type": "shell"}], 1),
            ([{"type": "shell", "description": "secret"}] * 200, 99),
        ):
            with self.subTest(tasks=tasks[:2], count=count):
                event = normalize_claude_code_hook(hook("Stop", background_tasks=tasks))
                self.assertEqual(event["event"], "background_wait")
                self.assertEqual(event["background_count"], count)
                self.assertNotIn("secret", json.dumps(event))

    def test_background_wait_crosses_the_pipe_only_for_claude_code(self):
        event = normalize_claude_code_hook(
            hook("Stop", background_tasks=[{"type": "shell"}])
        )
        self.assertEqual(sanitize_pet_event(event)["background_count"], 1)
        self.assertIsNone(sanitize_pet_event(dict(event, background_count="2")))
        self.assertIsNone(
            sanitize_pet_event(
                {"source": "codex", "event": "background_wait", "session_id": "s"}
            )
        )

    def test_watchers_and_finished_background_work_do_not_hold_the_turn(self):
        # A live subscription stays a running monitor for the whole session
        # (seen in Claude Code 2.1.289); the turn itself is done.
        for tasks in (
            [{"type": "monitor", "status": "running"}] * 2,
            [{"type": "MCP task", "status": "running"}],
            [{"type": "shell", "status": "completed"}],
            [{"type": "shell", "status": "killed"}],
        ):
            with self.subTest(tasks=tasks):
                stop = normalize_claude_code_hook(hook("Stop", background_tasks=tasks))
                self.assertEqual(stop["event"], "done")

    def test_compaction_reports_start_and_end(self):
        start = normalize_claude_code_hook(hook("PreCompact", trigger="manual"))
        restart = normalize_claude_code_hook(
            hook("SessionStart", source="compact", model="claude-haiku-4-5")
        )
        end = normalize_claude_code_hook(
            hook("PostCompact", trigger="manual", compact_summary="secret summary")
        )

        self.assertEqual(
            [event["compaction_phase"] for event in (start, restart, end)],
            ["start", "end", "end"],
        )
        self.assertTrue(all(event["event"] == "review" for event in (start, end)))
        self.assertNotIn("secret", json.dumps(end))

    def test_session_lifecycle(self):
        start = normalize_claude_code_hook(hook("SessionStart", source="startup"))
        end = normalize_claude_code_hook(hook("SessionEnd", reason="prompt_input_exit"))

        self.assertEqual(start["event"], "idle")
        self.assertEqual(end["event"], "session_end")

    def test_unparsed_payload_uses_command_line_event_and_session(self):
        event = normalize_claude_code_hook(
            None, hook_name="PostToolUse", session_id=SESSION
        )

        self.assertEqual(event["source"], "claude_code")
        self.assertEqual(event["event"], "tool_end")
        self.assertEqual(event["session_id"], SESSION)
        for name in ("Notification", "SubagentStart", "SubagentStop", "Unknown"):
            self.assertIsNone(
                normalize_claude_code_hook(None, hook_name=name, session_id=SESSION)
            )

    def test_unknown_sources_are_still_rejected(self):
        self.assertIsNone(
            sanitize_pet_event(
                {"source": "other-agent", "event": "prompt", "session_id": "x"}
            )
        )
        self.assertEqual(
            sanitize_pet_event(
                {"source": "claude-code", "event": "prompt", "session_id": "x"}
            )["source"],
            "claude_code",
        )


class ClaudeCodeHookBridgeTests(unittest.TestCase):
    def test_oversized_payload_still_delivers_a_minimal_event(self):
        delivered = []
        oversized = json.dumps(
            hook("PostToolUse", tool_response={"stdout": "x" * MAX_HOOK_INPUT_BYTES})
        ).encode("utf-8")

        exit_code = run_hook_bridge(
            stream=io.BytesIO(oversized),
            sender=lambda event: delivered.append(event) or True,
            normalize=lambda payload: normalize_claude_code_hook(
                payload, hook_name="PostToolUse", session_id=SESSION
            ),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(delivered), 1)
        self.assertEqual(delivered[0]["event"], "tool_end")
        self.assertEqual(delivered[0]["session_id"], SESSION)

    def test_claude_code_mode_writes_nothing_to_stdout(self):
        stdout = io.StringIO()
        with (
            patch.object(hook_bridge_entrypoint.sys, "stdout", stdout),
            patch.object(
                hook_bridge_entrypoint, "run_hook_bridge", return_value=0
            ) as bridge,
        ):
            exit_code = hook_bridge_entrypoint.main(
                ["--claude-code-hook-bridge", "--event", "SessionStart"]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.getvalue(), "")
        normalize = bridge.call_args.kwargs["normalize"]
        self.assertEqual(normalize.keywords["hook_name"], "SessionStart")
        self.assertTrue(
            str(bridge.call_args.kwargs["health_recorder"].keywords["path"]).endswith(
                "claude-code-hook-health.json"
            )
        )

    def test_packaged_bridge_mode_queues_claude_code_event_silently(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            environment = os.environ.copy()
            environment["WATCHED_KETTLE_SERVER_NAME"] = f"missing-{uuid4().hex}"
            environment["LOCALAPPDATA"] = str(root / "Local App Data")
            environment.pop("WATCHED_KETTLE_SPOOL_DIRECTORY", None)
            environment.pop("WATCHED_KETTLE_HOOK_HEALTH_PATH", None)
            process = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "watched_kettle",
                    "--claude-code-hook-bridge",
                    "--event",
                    "UserPromptSubmit",
                ],
                input=json.dumps(hook("UserPromptSubmit", prompt="secret prompt")),
                text=True,
                capture_output=True,
                cwd=PROJECT_ROOT,
                env=environment,
                timeout=10,
                check=False,
            )

            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(process.stdout, "")
            runtime = root / "Local App Data" / "WatchedKettle" / "runtime"
            queued = list((runtime / "events").glob("*.json"))
            self.assertEqual(len(queued), 1)
            text = queued[0].read_text(encoding="utf-8")
            self.assertIn('"source":"claude_code"', text)
            self.assertNotIn("secret", text)
            self.assertNotIn("example", text)
            self.assertTrue((runtime / "claude-code-hook-health.json").is_file())
            self.assertFalse((runtime / "hook-health.json").exists())


class _ControllerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.clock = FakeClock()
        self.displayed = []
        self.controller = PetAgentController(
            self.displayed.append,
            session_manager=AgentSessionManager(now_ms=self.clock),
        )

    def tearDown(self):
        self.controller.deleteLater()

    def apply(self, name, **fields):
        event = normalize_claude_code_hook(hook(name, **fields))
        return self.controller.apply_payload(event)


class ClaudeCodeSessionStateTests(_ControllerCase):
    def test_permission_wait_clears_on_the_next_tool_event(self):
        self.apply("UserPromptSubmit")
        self.apply("PreToolUse", tool_use_id="toolu_05")
        self.apply("PermissionRequest", tool_name="Bash")
        self.assertEqual(self.controller.desired_state, "waiting")

        self.apply("PostToolUseFailure", tool_use_id="toolu_05", error="Exit code 3")

        self.assertEqual(self.controller.aggregate_state.state, "running")
        self.assertNotIn("failed", self.displayed)

    def test_silent_interrupt_is_released_after_ten_minutes(self):
        self.apply("UserPromptSubmit")
        self.clock.advance(CLAUDE_CODE_INACTIVITY_LIMIT.work_ms - 1)
        self.assertEqual(self.controller.expire_stale_sessions(), ())

        self.clock.advance(1)

        self.assertEqual(len(self.controller.expire_stale_sessions()), 1)
        self.assertEqual(self.displayed[-1], "idle")

    def test_silent_denial_is_released_after_thirty_minutes(self):
        self.apply("UserPromptSubmit")
        self.apply("PermissionRequest", tool_name="Bash")
        self.clock.advance(CLAUDE_CODE_INACTIVITY_LIMIT.work_ms)
        self.assertEqual(self.controller.expire_stale_sessions(), ())
        self.assertEqual(self.controller.desired_state, "waiting")

        self.clock.advance(
            CLAUDE_CODE_INACTIVITY_LIMIT.waiting_ms
            - CLAUDE_CODE_INACTIVITY_LIMIT.work_ms
        )

        self.assertEqual(len(self.controller.expire_stale_sessions()), 1)
        self.assertEqual(self.controller.desired_state, "idle")

    def test_codex_sessions_keep_the_general_rule(self):
        self.controller.apply_payload(
            {
                "source": "codex",
                "event": "PermissionRequest",
                "approval_actor": "user",
                "session_id": "codex-one",
            }
        )
        self.clock.advance(24 * 60 * 60 * 1_000)

        self.assertEqual(self.controller.expire_stale_sessions(), ())
        self.assertEqual(self.controller.desired_state, "waiting")

    def test_inactivity_limit_can_be_replaced(self):
        self.controller.set_inactivity_limit(
            "claude_code", InactivityLimit(work_ms=60_000, waiting_ms=0)
        )
        self.apply("UserPromptSubmit")
        self.clock.advance(60_000)
        self.assertEqual(len(self.controller.expire_stale_sessions()), 1)

        self.apply("PermissionRequest", tool_name="Bash")
        self.clock.advance(24 * 60 * 60 * 1_000)
        self.assertEqual(self.controller.expire_stale_sessions(), ())

    def test_messages_name_claude_code(self):
        result = self.apply("UserPromptSubmit")

        self.assertEqual(result.display.message, "Claude Code가 작업하고 있어요")
        self.assertEqual(result.display.source, "claude_code")


class MixedAgentSourceTests(_ControllerCase):
    """Codex and Claude Code sessions in one pet must not end each other."""

    def codex(self, event, session="shared-id", **fields):
        return self.controller.apply_payload(
            {"source": "codex", "event": event, "session_id": session, **fields}
        )

    def sessions(self):
        return {
            (session.source, session.session_id, session.state)
            for session in self.controller.session_manager.list_sessions()
        }

    def test_same_raw_session_id_stays_separate_per_source(self):
        self.codex("prompt", session=SESSION)
        self.apply("UserPromptSubmit")

        self.apply("SessionEnd", reason="prompt_input_exit")

        self.assertEqual(self.sessions(), {("codex", f"codex:{SESSION}", "running")})
        self.assertEqual(self.controller.aggregate_state.source, "codex")

    def test_claude_code_turn_end_keeps_a_codex_confirmation_wait(self):
        self.codex("permission", approval_actor="user", event_id="call-1")
        self.apply("UserPromptSubmit")
        self.assertEqual(self.controller.desired_state, "waiting")
        self.assertEqual(self.controller.aggregate_state.source, "codex")

        self.apply("Stop", background_tasks=[])
        self.controller.apply_payload(
            {"source": "claude_code", "event": "cancelled", "session_id": SESSION}
        )

        self.assertEqual(self.controller.desired_state, "waiting")
        self.assertEqual(self.controller.aggregate_state.source, "codex")

    def test_claude_code_wait_outranks_codex_work_and_clears_alone(self):
        self.codex("prompt")
        self.apply("UserPromptSubmit")
        self.apply("PermissionRequest", tool_name="Bash")
        self.assertEqual(self.controller.aggregate_state.source, "claude_code")
        self.assertEqual(self.controller.desired_state, "waiting")

        self.apply("PostToolUse", tool_use_id="toolu_06")

        self.assertEqual(self.controller.desired_state, "running")
        self.assertEqual(
            {state for _source, _id, state in self.sessions()}, {"running"}
        )

    def test_claude_code_silence_expires_without_touching_codex(self):
        self.codex("prompt")
        self.apply("UserPromptSubmit")
        self.clock.advance(CLAUDE_CODE_INACTIVITY_LIMIT.work_ms)

        expired = self.controller.expire_stale_sessions()

        self.assertEqual([session.source for session in expired], ["claude_code"])
        self.assertEqual(self.sessions(), {("codex", "codex:shared-id", "running")})
        self.assertEqual(self.controller.desired_state, "running")

    def test_codex_tool_failure_and_claude_failure_are_both_quiet(self):
        self.codex("prompt")
        self.apply("UserPromptSubmit")

        self.codex("tool_failed", success=False, event_id="call-2")
        self.apply("PostToolUseFailure", tool_use_id="toolu_07", error="Exit 1")

        self.assertNotIn("failed", self.displayed)
        self.assertEqual(len(self.sessions()), 2)


if __name__ == "__main__":
    unittest.main()
