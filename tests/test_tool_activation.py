"""One "use this tool" switch per agent (features/integrations/activation.py)."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from watched_kettle.app_preferences import ApplicationPreferences
from watched_kettle.features.integrations.activation import (
    ACTIVATION_MIGRATION_KEY,
    ToolActivation,
    migrate_tool_activation,
)
from watched_kettle.integrations.codex_hooks import normalize_codex_hook
from watched_kettle.integrations.codex_install import StaleHookPlanError
from watched_kettle.integrations.codex_ipc import (
    CodexHookServer,
    JSONL_TRANSPORT,
    PIPE_TRANSPORT,
    QUEUE_TRANSPORT,
)
from tests.test_pet_preferences import FakeSettings


class Installer:
    def __init__(self, state="not_installed", can_apply=True, error=None, events=0):
        self.state, self.events = state, events
        self.plan = SimpleNamespace(
            can_apply=can_apply,
            has_changes=True,
            changes=("관리 hook 설치",),
            warnings=(),
        )
        self.error = error
        self.calls = []

    def inspect(self):
        return SimpleNamespace(state=self.state, installed_events=self.events)

    def preview_install(self):
        self.calls.append("preview_install")
        return self.plan

    def preview_remove(self):
        self.calls.append("preview_remove")
        return self.plan

    def apply(self, plan):
        self.calls.append("apply")
        if self.error is not None:
            raise self.error


class MigrationTests(unittest.TestCase):
    def preferences(self, **values):
        return ApplicationPreferences(FakeSettings(values))

    def test_claude_code_follows_this_apps_files_once_and_codex_is_kept(self):
        cases = (
            (Installer(), Installer(), False),
            (Installer("installed", events=6), Installer(), True),
            # Claude Code turned every hook off, but ours are still there.
            (Installer("disabled", events=6), Installer(), True),
            (Installer(), Installer("installed"), True),
            (Installer("blocked_by_policy"), Installer("not_installed"), False),
        )
        for hooks, status_line, expected in cases:
            with self.subTest(hooks=hooks.state, status_line=status_line.state):
                preferences = self.preferences(
                    **{"usage/enabled": False, "usage/claude_code_enabled": True}
                )
                self.assertEqual(
                    migrate_tool_activation(preferences, hooks, status_line), expected
                )
                self.assertEqual(preferences.load_claude_code_usage_enabled(), expected)
                self.assertFalse(preferences.load_usage_enabled())
                self.assertEqual(
                    preferences.settings.values[ACTIVATION_MIGRATION_KEY], 1
                )

    def test_second_run_changes_nothing(self):
        preferences = self.preferences(**{ACTIVATION_MIGRATION_KEY: 1})
        preferences.save_claude_code_usage_enabled(True)
        self.assertIsNone(
            migrate_tool_activation(preferences, Installer(), Installer())
        )
        self.assertTrue(preferences.load_claude_code_usage_enabled())

    def test_unreadable_install_state_counts_as_absent(self):
        class Broken(Installer):
            def inspect(self):
                raise OSError("locked")

        preferences = self.preferences()
        self.assertFalse(migrate_tool_activation(preferences, Broken(), Broken()))

    def test_missing_switch_is_off_rather_than_inherited(self):
        preferences = self.preferences(**{"usage/enabled": True})
        self.assertFalse(preferences.load_claude_code_usage_enabled())


class ToolActivationTests(unittest.TestCase):
    def setUp(self):
        self.preferences = ApplicationPreferences(FakeSettings())
        self.codex = Installer()
        self.claude = Installer()
        self.status_line = Installer()
        self.activation = ToolActivation(
            self.preferences,
            {
                "codex": self.codex,
                "claude_code": self.claude,
                "claude_code_status_line": self.status_line,
            },
        )

    def test_blocked_hook_still_turns_the_tool_on_with_a_warning(self):
        self.codex.plan.can_apply = False
        plan = self.activation.preview("codex", True)
        self.assertTrue(plan.can_apply)
        self.assertIn("Codex 사용을 켭니다", plan.changes)
        self.assertTrue(any("활동 표시가 제한" in line for line in plan.warnings))

        result = self.activation.apply(plan)

        self.assertFalse(result.complete)
        self.assertNotIn("apply", self.codex.calls)
        self.assertTrue(self.preferences.load_usage_enabled())

    def test_turning_off_always_saves_the_switch(self):
        self.preferences.save_claude_code_usage_enabled(True)
        self.claude.error = OSError("locked")
        plan = self.activation.preview("claude_code", False)
        self.assertEqual(
            [step.provider for step in plan.steps],
            ["claude_code", "claude_code_status_line"],
        )

        result = self.activation.apply(plan)

        self.assertFalse(result.complete)
        self.assertEqual(self.status_line.calls, ["preview_remove", "apply"])
        self.assertFalse(self.preferences.load_claude_code_usage_enabled())

    def test_turning_claude_code_on_also_brings_the_limits(self):
        plan = self.activation.preview("claude_code", True)
        self.assertEqual(
            [step.provider for step in plan.steps],
            ["claude_code", "claude_code_status_line"],
        )

        result = self.activation.apply(plan)

        self.assertTrue(result.complete)
        # The hooks step wrote settings.json, so the status line plans again.
        self.assertEqual(
            self.status_line.calls, ["preview_install", "preview_install", "apply"]
        )
        self.assertTrue(self.preferences.load_claude_code_usage_enabled())

    def test_blocked_status_line_still_turns_claude_code_on(self):
        self.status_line.plan.can_apply = False
        plan = self.activation.preview("claude_code", True)
        self.assertTrue(
            any("한도를 받을 수 없습니다" in line for line in plan.warnings)
        )

        result = self.activation.apply(plan)

        self.assertFalse(result.complete)
        self.assertNotIn("apply", self.status_line.calls)
        self.assertEqual(self.claude.calls, ["preview_install", "apply"])
        self.assertTrue(self.preferences.load_claude_code_usage_enabled())

    def test_file_changed_after_review_keeps_the_switch(self):
        self.codex.error = StaleHookPlanError("changed")
        with self.assertRaises(StaleHookPlanError):
            self.activation.apply(self.activation.preview("codex", False))
        self.assertTrue(self.preferences.load_usage_enabled())

    def test_preview_failure_becomes_a_warning(self):
        class Failing(Installer):
            def preview_install(self):
                raise OSError("unreadable")

        activation = ToolActivation(self.preferences, {"codex": Failing()})
        plan = activation.preview("codex", True)
        self.assertTrue(plan.warnings)
        self.assertFalse(activation.apply(plan).complete)
        self.assertTrue(self.preferences.load_usage_enabled())


class DisabledSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.server = CodexHookServer(
            f"activation-test-{uuid4().hex}",
            spool_directory=root / "queue",
            hook_config_path=root / "hooks.json",
            global_hook_config_path=root / "global-hooks.json",
            codex_config_path=root / "config.toml",
            hook_health_path=root / "hook-health.json",
            managed_spool_directory=None,
            managed_hook_health_path=None,
        )
        self.addCleanup(self.server.close)
        self.received = []
        self.server.payload_received.connect(self.received.append)

    @staticmethod
    def codex_event():
        return normalize_codex_hook(
            {"hook_event_name": "UserPromptSubmit", "session_id": uuid4().hex}
        )

    def test_switched_off_source_is_dropped_from_every_transport(self):
        observed = []
        self.server.transcript_monitor = SimpleNamespace(observe=observed.append)
        self.addCleanup(setattr, self.server, "transcript_monitor", None)
        claude = {
            "source": "claude_code",
            "event": "UserPromptSubmit",
            "session_id": uuid4().hex,
        }
        self.server.set_source_enabled("codex", False)
        self.server.set_source_enabled("claude_code", False)
        for transport in (PIPE_TRANSPORT, QUEUE_TRANSPORT, JSONL_TRANSPORT):
            self.assertFalse(
                self.server._deliver_payload(self.codex_event(), transport)
            )
        self.assertFalse(self.server._deliver_payload(claude, PIPE_TRANSPORT))
        self.assertEqual(self.received, [])
        # A dropped Claude Code turn is never looked up on disk.
        self.assertEqual(observed, [])
        self.assertEqual(self.server.disabled_source_drop_count, 4)

        self.server.set_source_enabled("codex", True)
        self.assertTrue(
            self.server._deliver_payload(self.codex_event(), PIPE_TRANSPORT)
        )
        self.assertEqual(len(self.received), 1)

    def test_diagnostics_do_not_read_codex_files_while_it_is_off(self):
        self.server.set_source_enabled("codex", False)
        with (
            patch.object(
                CodexHookServer, "hook_config_status", side_effect=AssertionError
            ),
            patch.object(
                CodexHookServer, "hooks_feature_status", side_effect=AssertionError
            ),
            patch.object(
                CodexHookServer, "hook_trust_status", side_effect=AssertionError
            ),
        ):
            diagnostics = self.server.diagnostics()
        self.assertFalse(diagnostics["codex_enabled"])
        self.assertEqual(diagnostics["hook_config"]["event_count"], 0)


if __name__ == "__main__":
    unittest.main()
