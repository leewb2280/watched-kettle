import io
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtNetwork import QLocalServer
from PySide6.QtWidgets import QApplication

from watched_kettle.integrations.codex_bridge import run_hook_bridge
from watched_kettle.integrations.codex_hooks import (
    MAX_HOOK_INPUT_BYTES,
    normalize_codex_hook,
    read_hook_payload,
)
from watched_kettle.integrations.codex_client import send_pet_event
from watched_kettle.integrations.codex_ipc import CodexHookServer
from watched_kettle.integrations.codex_spool import (
    MAX_EVENT_AGE_SECONDS,
    drain_spooled_events,
    read_hook_health,
    record_hook_health,
    spool_pet_event,
)
from watched_kettle.pet.window import DesktopPet


def _windows_powershell():
    return (
        Path(os.environ.get("SystemRoot", r"C:\Windows"))
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )


def _windows_powershell_command(script, *arguments):
    return [
        str(_windows_powershell()),
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(Path(script).resolve()),
        *arguments,
    ]


def _warm_windows_powershell():
    """Pay Windows PowerShell's first start on a fresh CI runner outside deadlines."""
    if os.name != "nt":
        return
    try:
        subprocess.run(
            [str(_windows_powershell()), "-NoLogo", "-NoProfile", "-Command", "exit"],
            capture_output=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


# The development repository ships its own project-level Codex hook; the public
# snapshot does not.
PROJECT_CODEX_HOOKS = Path(__file__).resolve().parents[1] / ".codex"


class CodexHookFilterTests(unittest.TestCase):
    def test_filters_prompt_command_paths_and_tool_output(self):
        event = normalize_codex_hook(
            {
                "session_id": "thr_123",
                "cwd": "C:/secret/project",
                "transcript_path": "C:/secret/transcript.jsonl",
                "hook_event_name": "PostToolUse",
                "prompt": "private prompt",
                "tool_input": {"command": "secret command"},
                "tool_response": {"status": "completed", "output": "secret"},
            }
        )

        self.assertGreater(event.pop("collected_at"), 0)
        self.assertEqual(
            event,
            {
                "source": "codex",
                "event": "tool_end",
                "session_id": "thr_123",
                "agent_scope": "unknown",
                "tool_status": "succeeded",
                "success": True,
            },
        )
        serialized = json.dumps(event)
        self.assertNotIn("secret", serialized)
        self.assertNotIn("cwd", serialized)
        self.assertNotIn("tool_input", serialized)

    def test_maps_all_supported_lifecycle_events(self):
        expected = {
            "SessionStart": "idle",
            "SessionEnd": "session_end",
            "SubagentStart": "task_start",
            "SubagentStop": "done",
            "PreToolUse": "tool_start",
            "PermissionRequest": "permission",
            "PostToolUse": "tool_end",
            "PreCompact": "review",
            "PostCompact": "review",
            "UserPromptSubmit": "prompt",
            "Stop": "done",
        }

        for hook_name, event_name in expected.items():
            with self.subTest(hook_name=hook_name):
                event = normalize_codex_hook(
                    {
                        "hook_event_name": hook_name,
                        "session_id": "one",
                    }
                )
                self.assertEqual(event["event"], event_name)

    def test_compact_session_restart_stays_in_review(self):
        event = normalize_codex_hook(
            {
                "hook_event_name": "SessionStart",
                "source": "compact",
                "session_id": "one",
            }
        )

        self.assertEqual(event["event"], "review")

    def test_failed_tool_is_a_temporary_failure_event(self):
        event = normalize_codex_hook(
            {
                "hook_event_name": "PostToolUse",
                "session_id": "one",
                "tool_response": {"exit_code": 2},
            }
        )

        self.assertEqual(event["event"], "tool_failed")
        self.assertEqual(event["tool_status"], "failed")
        self.assertFalse(event["success"])

    def test_subagent_uses_an_independent_bounded_session_id(self):
        event = normalize_codex_hook(
            {
                "hook_event_name": "SubagentStart",
                "session_id": "root session",
                "agent_id": "agent/one",
            }
        )

        self.assertEqual(event["session_id"], "agent_one")
        self.assertEqual(event["parent_session_id"], "root_session")
        self.assertEqual(event["agent_scope"], "subagent")

    def test_rejects_invalid_and_oversized_hook_input(self):
        self.assertIsNone(read_hook_payload(io.BytesIO(b"not-json")))
        self.assertIsNone(
            read_hook_payload(io.BytesIO(b"{" + b"x" * MAX_HOOK_INPUT_BYTES))
        )

    def test_bridge_always_succeeds_when_delivery_fails(self):
        raw = json.dumps(
            {
                "hook_event_name": "SessionStart",
                "session_id": "one",
            }
        ).encode("utf-8")

        result = run_hook_bridge(
            io.BytesIO(raw),
            sender=lambda payload: (_ for _ in ()).throw(RuntimeError("offline")),
        )

        self.assertEqual(result, 0)

    def test_bridge_records_only_filtered_delivery_health(self):
        raw = json.dumps(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "one",
                "prompt": "private prompt",
            }
        ).encode("utf-8")
        recorded = []

        result = run_hook_bridge(
            io.BytesIO(raw),
            sender=lambda payload: False,
            fallback=lambda payload: True,
            health_recorder=lambda event, outcome: recorded.append((event, outcome)),
        )

        self.assertEqual(result, 0)
        self.assertGreater(recorded[0][0].pop("collected_at"), 0)
        self.assertEqual(
            recorded,
            [
                (
                    {
                        "source": "codex",
                        "event": "prompt",
                        "session_id": "one",
                        "agent_scope": "unknown",
                    },
                    "queued",
                )
            ],
        )
        self.assertNotIn("private", json.dumps(recorded))


class CodexLocalIpcTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        _warm_windows_powershell()

    def setUp(self):
        self.server_name = f"watched-kettle-test-{uuid4().hex}"
        self.server = CodexHookServer(self.server_name)
        self.received = []
        self.pet = None
        self.server.payload_received.connect(self.received.append)

    def tearDown(self):
        if self.pet is not None:
            self.pet.close()
        self.server.close()
        QLocalServer.removeServer(self.server_name)
        self.server.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    @unittest.skipUnless(PROJECT_CODEX_HOOKS.is_dir(), "development repository hook")
    def test_user_scoped_server_receives_one_filtered_event(self):
        self.server.close()
        QLocalServer.removeServer(self.server_name)
        isolated_runtime = TemporaryDirectory()
        self.addCleanup(isolated_runtime.cleanup)
        runtime_root = Path(isolated_runtime.name)
        managed_spool_directory = runtime_root / "user-events"
        self.received = []
        self.server = CodexHookServer(
            self.server_name,
            spool_directory=runtime_root / "project-events",
            managed_spool_directory=managed_spool_directory,
            managed_hook_health_path=None,
        )
        self.server.payload_received.connect(self.received.append)
        self.pet = DesktopPet(Path("pets/mori-bot"))
        self.server.payload_received.connect(self.pet.apply_agent_payload)
        self.assertTrue(self.server.start())
        self.app.processEvents()

        hook_input = json.dumps(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "one",
                "prompt": "must not cross the pipe",
                "tool_input": {"command": "private command"},
            }
        ).encode("utf-8")
        environment = os.environ.copy()
        environment["WATCHED_KETTLE_SERVER_NAME"] = self.server_name
        environment["WATCHED_KETTLE_SPOOL_DIRECTORY"] = str(managed_spool_directory)
        environment["WATCHED_KETTLE_HOOK_HEALTH_PATH"] = str(
            runtime_root / "hook-health.json"
        )
        environment["WATCHED_KETTLE_DEBUG"] = "1"
        if os.name == "nt":
            hooks_config = json.loads(Path(".codex/hooks.json").read_text())
            command = hooks_config["hooks"]["PreToolUse"][0]["hooks"][0][
                "commandWindows"
            ]
            self.assertNotIn("Users\\", command)
            self.assertIn(".codex\\hooks\\codex_pet_bridge.ps1", command)
            self.assertIn("git rev-parse --show-toplevel", command)
            process_args = _windows_powershell_command(
                ".codex/hooks/codex_pet_bridge.ps1"
            )
            use_shell = False
        else:
            process_args = [
                sys.executable,
                str(Path(".codex/hooks/codex_pet_bridge.py")),
            ]
            use_shell = False
        process = subprocess.Popen(
            process_args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            shell=use_shell,
        )
        output = {}

        def communicate():
            output["stdout"], output["stderr"] = process.communicate(hook_input)

        communication = threading.Thread(target=communicate, daemon=True)
        started_at = time.perf_counter()
        communication.start()
        deadline = started_at + 6.0
        while communication.is_alive() and time.perf_counter() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        timed_out = communication.is_alive()
        if timed_out:
            process.kill()
        communication.join(timeout=2)
        self.app.processEvents()
        elapsed = time.perf_counter() - started_at
        stdout = output.get("stdout", b"").decode("utf-8", errors="replace")
        stderr = output.get("stderr", b"").decode("utf-8", errors="replace")
        diagnostic = (
            f"timed_out={timed_out} elapsed={elapsed:.3f}s "
            f"return_code={process.returncode}\nstdout={stdout}\nstderr={stderr}"
        )

        self.assertFalse(communication.is_alive(), diagnostic)
        self.assertFalse(timed_out, diagnostic)
        self.assertEqual(process.returncode, 0, diagnostic)
        self.assertEqual(json.loads(stdout), {})
        self.assertIn("pet-hook bridge-start managed=0", stderr)
        self.assertIn("pet-hook input-bytes=137 prefix=7B22686F", stderr)
        self.assertIn("pet-hook input-json=object", stderr)
        self.assertIn("pet-hook result event=tool_start outcome=delivered", stderr)
        self.assertIn("pet-hook bridge-exit=0", stderr)
        self.assertGreater(self.received[0].pop("collected_at"), 0)
        self.assertEqual(
            self.received,
            [
                {
                    "source": "codex",
                    "event": "tool_start",
                    "session_id": "one",
                    "agent_scope": "unknown",
                    "tool_status": "started",
                }
            ],
            diagnostic,
        )
        self.assertEqual(self.server.event_count, 1)
        diagnostics = self.server.diagnostics()
        self.assertEqual(
            diagnostics["pipe_event_count"] + diagnostics["queue_event_count"],
            1,
        )
        self.assertEqual(diagnostics["last_event"], "tool_start")
        self.assertIn(
            diagnostics["last_transport"],
            {"named_pipe", "workspace_queue"},
        )
        self.assertTrue(diagnostics["hook_config"]["valid"])
        self.assertEqual(diagnostics["hook_config"]["event_count"], 11)
        self.assertEqual(self.pet.current_state, "idle")  # identity is still unverified
        self.assertEqual(diagnostics["schedule_event_count"], 0)
        self.assertEqual(diagnostics["last_event"], "tool_start")
        self.assertEqual(
            self.server.server.socketOptions(),
            QLocalServer.UserAccessOption,
        )

    def test_missing_pet_process_fails_open_quickly(self):
        started = time.perf_counter()
        delivered = send_pet_event(
            {
                "source": "codex",
                "event": "session_start",
                "session_id": "one",
            },
            self.server_name,
        )
        elapsed = time.perf_counter() - started

        self.assertFalse(delivered)
        self.assertLess(elapsed, 1.0)

    def test_provider_neutral_schedule_notification_crosses_local_pipe(self):
        self.server.close()
        QLocalServer.removeServer(self.server_name)
        schedule_runtime = TemporaryDirectory()
        self.addCleanup(schedule_runtime.cleanup)
        self.received = []
        self.server = CodexHookServer(
            self.server_name,
            spool_directory=Path(schedule_runtime.name) / "spool",
            managed_spool_directory=None,
            managed_hook_health_path=None,
        )
        self.server.payload_received.connect(self.received.append)
        self.assertTrue(self.server.start())
        self.app.processEvents()
        environment = os.environ.copy()
        environment["WATCHED_KETTLE_SERVER_NAME"] = self.server_name
        environment["WATCHED_KETTLE_SPOOL_DIRECTORY"] = str(
            Path(schedule_runtime.name) / "spool"
        )
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "watched_kettle",
                "--assistant-notification",
                "--message",
                "10분 뒤 회의가 시작돼요",
                "--urgency",
                "high",
                "--notification-id",
                "meeting-123",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )

        for _ in range(200):
            self.app.processEvents()
            if self.received and process.poll() is not None:
                break
            time.sleep(0.005)
        if process.poll() is None:
            process.terminate()
        return_code = process.wait(timeout=1)
        stdout = process.stdout.read().decode("utf-8", errors="replace")
        process.stdout.close()
        stderr = process.stderr.read().decode("utf-8", errors="replace")
        process.stderr.close()

        self.assertEqual(return_code, 0, stderr)
        response = json.loads(stdout)
        self.assertTrue(response["accepted"])
        self.assertIn(response["outcome"], {"delivered", "queued"})
        self.assertEqual(
            self.received,
            [
                {
                    "source": "schedule",
                    "event": "notification",
                    "session_id": "meeting-123",
                    "event_id": "meeting-123",
                    "message": "10분 뒤 회의가 시작돼요",
                    "urgency": "high",
                }
            ],
        )
        diagnostics = self.server.diagnostics()
        self.assertEqual(diagnostics["schedule_event_count"], 1)
        self.assertEqual(diagnostics["codex_hook_event_count"], 0)
        self.assertIsNotNone(diagnostics["last_schedule_received_at"])
        self.assertIsNone(diagnostics["last_hook_received_at"])

    def test_diagnostics_reports_saved_hook_approval_records(self):
        with TemporaryDirectory() as directory:
            directory = Path(directory)
            hook_config = directory / ".codex" / "hooks.json"
            hook_config.parent.mkdir()
            hook_config.write_text(
                json.dumps({"hooks": {"SessionStart": [], "Stop": []}}),
                encoding="utf-8",
            )
            codex_config = directory / "config.toml"
            key_prefix = str(hook_config.resolve())
            codex_config.write_text(
                "[hooks.state]\n"
                f"[hooks.state.'{key_prefix}:session_start:0:0']\n"
                'trusted_hash = "sha256:one"\n'
                f"[hooks.state.'{key_prefix}:stop:0:0']\n"
                'trusted_hash = "sha256:two"\n',
                encoding="utf-8",
            )
            server = CodexHookServer(
                f"watched-kettle-trust-{uuid4().hex}",
                hook_config_path=hook_config,
                codex_config_path=codex_config,
            )
            try:
                trust = server.diagnostics()["hook_trust"]
            finally:
                server.close()

            self.assertTrue(trust["valid"])
            self.assertEqual(trust["approved_count"], 2)
            self.assertEqual(trust["expected_count"], 2)

    def test_diagnostics_separates_global_hook_approval_records(self):
        with TemporaryDirectory() as directory:
            directory = Path(directory)
            project_hook = directory / "project-hooks.json"
            project_hook.write_text(
                json.dumps({"hooks": {"SessionStart": []}}),
                encoding="utf-8",
            )
            global_hook = directory / "global-hooks.json"
            global_hook.write_text(
                json.dumps(
                    {
                        "hooks": {"SessionStart": [], "Stop": []},
                    }
                ),
                encoding="utf-8",
            )
            codex_config = directory / "config.toml"
            key_prefix = str(global_hook.resolve())
            codex_config.write_text(
                "[hooks.state]\n"
                f"[hooks.state.'{key_prefix}:session_start:0:0']\n"
                'trusted_hash = "sha256:one"\n'
                f"[hooks.state.'{key_prefix}:stop:0:0']\n"
                'trusted_hash = "sha256:two"\n',
                encoding="utf-8",
            )
            server = CodexHookServer(
                f"watched-kettle-global-trust-{uuid4().hex}",
                hook_config_path=project_hook,
                global_hook_config_path=global_hook,
                codex_config_path=codex_config,
            )
            try:
                diagnostics = server.diagnostics()
            finally:
                server.close()

            self.assertEqual(
                diagnostics["hook_trust"]["approved_count"],
                0,
            )
            self.assertEqual(
                diagnostics["global_hook_trust"]["approved_count"],
                2,
            )
            self.assertEqual(
                diagnostics["global_hook_trust"]["expected_count"],
                2,
            )

    def test_diagnostics_flags_approval_as_possibly_stale_after_hook_change(self):
        with TemporaryDirectory() as directory:
            directory = Path(directory)
            hook_config = directory / ".codex" / "hooks.json"
            hook_config.parent.mkdir()
            hook_config.write_text(
                json.dumps({"hooks": {"SessionStart": []}}),
                encoding="utf-8",
            )
            codex_config = directory / "config.toml"
            key_prefix = str(hook_config.resolve())
            codex_config.write_text(
                "[hooks.state]\n"
                f"[hooks.state.'{key_prefix}:session_start:0:0']\n"
                'trusted_hash = "sha256:one"\n',
                encoding="utf-8",
            )
            config_mtime = codex_config.stat().st_mtime
            os.utime(
                hook_config,
                (config_mtime + 5, config_mtime + 5),
            )
            server = CodexHookServer(
                f"watched-kettle-stale-trust-{uuid4().hex}",
                hook_config_path=hook_config,
                codex_config_path=codex_config,
            )
            try:
                trust = server.diagnostics()["hook_trust"]
            finally:
                server.close()

            self.assertTrue(trust["valid"])
            self.assertEqual(trust["approved_count"], 1)
            self.assertTrue(trust["possibly_stale"])

    def test_workspace_spool_crosses_a_blocked_pipe_boundary(self):
        with TemporaryDirectory() as directory:
            queued = run_hook_bridge(
                io.BytesIO(
                    json.dumps(
                        {
                            "hook_event_name": "UserPromptSubmit",
                            "session_id": "sandboxed",
                            "prompt": "must remain filtered",
                        }
                    ).encode("utf-8")
                ),
                sender=lambda payload: (_ for _ in ()).throw(
                    PermissionError("sandbox boundary")
                ),
                fallback=lambda payload: spool_pet_event(payload, directory),
            )
            self.assertEqual(queued, 0)

            events = list(drain_spooled_events(directory))
            self.assertGreater(events[0].pop("collected_at"), 0)
            self.assertEqual(
                events,
                [
                    {
                        "source": "codex",
                        "event": "prompt",
                        "session_id": "sandboxed",
                        "agent_scope": "unknown",
                    }
                ],
            )
            self.assertEqual(list(Path(directory).glob("*.json")), [])

    def test_hook_health_file_contains_no_raw_payload(self):
        with TemporaryDirectory() as directory:
            health_path = Path(directory) / "hook-health.json"
            self.assertTrue(
                record_hook_health(
                    {
                        "source": "codex",
                        "event": "waiting",
                        "session_id": "one",
                        "message": "private prompt",
                    },
                    "queued",
                    health_path,
                )
            )

            health = read_hook_health(health_path)
            self.assertTrue(health["valid"])
            self.assertEqual(health["event"], "waiting")
            self.assertEqual(health["outcome"], "queued")
            self.assertNotIn("private", health_path.read_text("utf-8"))

    def test_spool_server_delivers_fresh_event_and_discards_stale_event(self):
        with TemporaryDirectory() as directory:
            server = CodexHookServer(
                f"watched-kettle-spool-{uuid4().hex}",
                spool_directory=directory,
            )
            received = []
            server.payload_received.connect(received.append)
            self.assertTrue(
                spool_pet_event(
                    {
                        "source": "codex",
                        "event": "tool_start",
                        "session_id": "fresh",
                    },
                    directory,
                )
            )
            self.assertTrue(
                spool_pet_event(
                    {
                        "source": "codex",
                        "event": "done",
                        "session_id": "stale",
                    },
                    directory,
                )
            )
            # Pick by content: both names can share a coarse time_ns() prefix,
            # so filename ordering is not an event-identity guarantee.
            stale_path = next(
                path
                for path in Path(directory).glob("*.json")
                if b'"stale"' in path.read_bytes()
            )
            stale_time = time.time() - MAX_EVENT_AGE_SECONDS - 1
            os.utime(stale_path, (stale_time, stale_time))

            try:
                self.assertTrue(server.start())
                self.app.processEvents()
                self.assertEqual(
                    received,
                    [
                        {
                            "source": "codex",
                            "event": "tool_start",
                            "session_id": "fresh",
                            "agent_scope": "unknown",
                        }
                    ],
                )
                self.assertEqual(server.event_count, 1)
                diagnostics = server.diagnostics()
                self.assertEqual(diagnostics["queue_event_count"], 1)
                self.assertEqual(
                    diagnostics["last_transport"],
                    "workspace_queue",
                )
                self.assertEqual(list(Path(directory).glob("*.json")), [])
            finally:
                server.close()

    def test_server_drains_user_managed_hook_queue(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            project_queue = root / "project-events"
            managed_queue = root / "managed-events"
            self.assertTrue(
                spool_pet_event(
                    {
                        "source": "codex",
                        "event": "prompt",
                        "session_id": "managed",
                    },
                    managed_queue,
                )
            )
            server = CodexHookServer(
                f"watched-kettle-managed-spool-{uuid4().hex}",
                spool_directory=project_queue,
                managed_spool_directory=managed_queue,
                managed_hook_health_path=None,
            )
            received = []
            server.payload_received.connect(received.append)
            try:
                server._drain_spool()

                self.assertEqual(len(received), 1)
                self.assertEqual(received[0]["session_id"], "managed")
                self.assertEqual(server.queued_event_count(), 0)
            finally:
                server.close()
                server.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


if __name__ == "__main__":
    unittest.main()
