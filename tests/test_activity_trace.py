import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from watched_kettle.application.logging import _safe_event_fields
from watched_kettle.application.runtime import ApplicationRuntime
from watched_kettle.features.project_activity.service import (
    ProjectActivityService,
    trace_ref,
)
from watched_kettle.integrations.codex_ipc import PIPE_TRANSPORT, CodexHookServer


THREAD = "01a0fcd1-b1d6-7860-abfe-25ffe4f6443f"
TURN = "01a0fcd2-255a-79e1-af56-000000000001"


class Clock:
    def __init__(self):
        self.value = 1_000.0

    def __call__(self):
        return self.value


class ProjectActivityTraceTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.records = []
        self.service = ProjectActivityService(now=self.clock, wall_now=lambda: 0.0)
        self.service._collection_started_at = 0
        self.service.trace = lambda event, **fields: self.records.append(
            (event, fields)
        )

    def payload(self, event, **fields):
        return {
            "source": "codex",
            "event": event,
            "session_id": THREAD,
            "turn_id": TURN,
            "agent_scope": "main",
            **fields,
        }

    def test_accepted_and_rejected_events_are_traced_with_hashes_only(self):
        self.service.observe(self.payload("tool_end", event_id="call-1"))
        self.service.observe(self.payload("prompt"))

        (rejected_event, rejected), (accepted_event, accepted) = self.records
        self.assertEqual(rejected_event, "event_observed")
        self.assertEqual(rejected["result"], "rejected")
        self.assertEqual(rejected["reason"], "missing_start")
        self.assertEqual(accepted["result"], "accepted")
        self.assertEqual(accepted["state"], "running")
        self.assertEqual(accepted["thread_ref"], trace_ref(THREAD))
        self.assertEqual(accepted["turn_ref"], trace_ref(TURN))
        encoded = json.dumps(self.records)
        self.assertNotIn(THREAD, encoded)
        self.assertNotIn(TURN, encoded)

    def test_stale_and_expired_rows_are_traced(self):
        self.service.observe(self.payload("prompt"))
        self.clock.value += self.service.running_stale_seconds
        self.service.expire()
        self.service.observe(self.payload("done"))
        self.clock.value += self.service.duration
        self.service.expire()

        events = [event for event, _fields in self.records]
        self.assertIn("activity_stale", events)
        self.assertIn("activity_expired", events)

    def test_trace_failures_never_break_observation(self):
        def broken(event, **fields):
            raise RuntimeError("log disk full")

        self.service.trace = broken

        self.assertTrue(self.service.observe(self.payload("prompt")))
        self.assertIn(THREAD, self.service.activities)

    def test_log_event_keeps_trace_fields(self):
        fields = _safe_event_fields(
            {
                "thread_ref": "abc123",
                "turn_ref": "def456",
                "reason": "missing_start",
                "uncertain": True,
                "session_id": THREAD,
            }
        )

        self.assertEqual(
            fields,
            {
                "thread_ref": "abc123",
                "turn_ref": "def456",
                "reason": "missing_start",
                "uncertain": True,
            },
        )


class DeliveryTraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_duplicates_are_traced_as_duplicates(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            server = CodexHookServer(
                server_name=f"watched-kettle-test-{uuid4().hex}",
                spool_directory=root / "events",
                hook_config_path=root / "hooks.json",
                global_hook_config_path=root / "global-hooks.json",
                codex_config_path=root / "config.toml",
                hook_health_path=root / "hook-health.json",
                managed_spool_directory=None,
                managed_hook_health_path=None,
            )
            records = []
            server.trace = lambda event, **fields: records.append(fields)
            payload = {
                "source": "codex",
                "event": "prompt",
                "session_id": THREAD,
                "turn_id": TURN,
            }

            server._deliver_payload(payload, PIPE_TRANSPORT)
            server._deliver_payload(payload, PIPE_TRANSPORT)
            server.close()
            server.deleteLater()

        self.assertEqual(
            [record["result"] for record in records], ["accepted", "duplicate"]
        )
        self.assertEqual(records[0]["transport"], PIPE_TRANSPORT)
        self.assertNotIn(THREAD, json.dumps(records))

    def test_runtime_attaches_trace_to_both_layers(self):
        runtime = SimpleNamespace(
            projects=SimpleNamespace(trace=None),
            codex_server=SimpleNamespace(trace=None),
        )

        ApplicationRuntime._enable_activity_trace(runtime)

        self.assertIsNotNone(runtime.projects.trace)
        self.assertIsNotNone(runtime.codex_server.trace)


if __name__ == "__main__":
    unittest.main()
