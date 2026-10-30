"""Per-user pipe names and the hook client's pipe handling (SEC-03, SEC-12)."""

import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from watched_kettle.integrations import codex_client
from watched_kettle.integrations.pipe_names import (
    AGENT_PIPE_PREFIX,
    INSTANCE_PIPE_PREFIX,
    LEGACY_INSTANCE_PIPE,
    agent_pipe_name,
    ensure_pipe_id,
    instance_pipe_name,
    read_pipe_id,
)

EVENT = {"source": "codex", "event": "prompt", "session_id": "session"}


class PipeNameTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "runtime" / "pipe-id"
        environment = patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        os.environ.pop("WATCHED_KETTLE_SERVER_NAME", None)
        os.environ.pop("WATCHED_KETTLE_INSTANCE_SERVER_NAME", None)

    def test_hooks_have_no_name_until_the_app_creates_one(self):
        self.assertEqual(agent_pipe_name(self.path), "")
        self.assertFalse(self.path.exists())

        instance = instance_pipe_name(self.path)

        value = read_pipe_id(self.path)
        self.assertRegex(value, r"^[0-9a-f]{32}$")
        self.assertEqual(instance, INSTANCE_PIPE_PREFIX + value)
        self.assertEqual(agent_pipe_name(self.path), AGENT_PIPE_PREFIX + value)
        self.assertEqual(ensure_pipe_id(self.path), value)

    def test_damaged_identifier_is_replaced(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("not-an-id", encoding="ascii")

        self.assertEqual(agent_pipe_name(self.path), "")
        value = ensure_pipe_id(self.path)
        self.assertRegex(value, r"^[0-9a-f]{32}$")
        self.assertEqual(read_pipe_id(self.path), value)

    def test_unstorable_identifier_falls_back_to_the_shared_name(self):
        # Every process must agree on one name, so an identifier that was not
        # saved is never used.
        with patch("os.replace", side_effect=PermissionError):
            self.assertEqual(ensure_pipe_id(self.path), "")
            self.assertEqual(instance_pipe_name(self.path), LEGACY_INSTANCE_PIPE)
        self.assertEqual(agent_pipe_name(self.path), "")

    def test_apps_starting_together_agree_on_one_identifier(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("", encoding="ascii")
        code = (
            "import sys; from pathlib import Path; "
            "from watched_kettle.integrations.pipe_names import ensure_pipe_id; "
            "print(ensure_pipe_id(Path(sys.argv[1])))"
        )
        processes = [
            subprocess.Popen(
                [sys.executable, "-c", code, str(self.path)],
                stdout=subprocess.PIPE,
                text=True,
                cwd=Path(__file__).resolve().parents[1],
            )
            for _ in range(6)
        ]
        values = {process.communicate(timeout=30)[0].strip() for process in processes}

        self.assertEqual(values, {read_pipe_id(self.path)})
        self.assertRegex(values.pop(), r"^[0-9a-f]{32}$")

    def test_isolation_overrides_win(self):
        os.environ["WATCHED_KETTLE_SERVER_NAME"] = "agent-x"
        os.environ["WATCHED_KETTLE_INSTANCE_SERVER_NAME"] = "instance-x"

        self.assertEqual(agent_pipe_name(self.path), "agent-x")
        self.assertEqual(instance_pipe_name(self.path), "instance-x")
        self.assertFalse(self.path.exists())

    def test_without_a_name_the_client_does_not_connect(self):
        with (
            patch.object(codex_client, "agent_pipe_name", return_value=""),
            patch.object(codex_client, "_send_windows_named_pipe") as send,
        ):
            self.assertFalse(codex_client.send_pet_event(EVENT))
        send.assert_not_called()


@unittest.skipUnless(os.name == "nt", "Windows named pipes")
class PipeClientTests(unittest.TestCase):
    """A raw Win32 server, since the client blocks the calling thread."""

    def serve(self, reply):
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateNamedPipeW.restype = wintypes.HANDLE
        kernel32.CreateNamedPipeW.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
        )
        name = f"watched-kettle-test-{uuid4().hex}"
        handle = kernel32.CreateNamedPipeW(
            rf"\\.\pipe\{name}", 3, 0, 1, 4096, 4096, 0, None
        )
        self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
        received = []

        def run():
            kernel32.ConnectNamedPipe(wintypes.HANDLE(handle), None)
            buffer = ctypes.create_string_buffer(4096)
            count = wintypes.DWORD()
            kernel32.ReadFile(
                wintypes.HANDLE(handle), buffer, 4096, ctypes.byref(count), None
            )
            received.append(buffer.raw[: count.value])
            if reply is not None:
                kernel32.WriteFile(
                    wintypes.HANDLE(handle),
                    reply,
                    len(reply),
                    ctypes.byref(count),
                    None,
                )
            # Hold the connection open like a stuck app would.
            time.sleep(1)
            kernel32.CloseHandle(wintypes.HANDLE(handle))

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        return name, received

    def test_acknowledged_event_is_delivered(self):
        name, received = self.serve(b"OK\n")

        self.assertTrue(codex_client.send_pet_event(EVENT, name))
        self.assertIn(b'"prompt"', received[0])

    def test_silent_server_times_out_instead_of_blocking(self):
        name, received = self.serve(None)

        started = time.monotonic()
        with patch.object(codex_client, "RESPONSE_TIMEOUT_MS", 200):
            self.assertFalse(codex_client.send_pet_event(EVENT, name))
        self.assertLess(time.monotonic() - started, 0.9)
        self.assertTrue(received)


if __name__ == "__main__":
    unittest.main()
