import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from watched_kettle.app_preferences import ApplicationPreferences
from watched_kettle.application.integration_setup import (
    parse_tool_choices,
    run_integration_setup,
)
from watched_kettle.integrations.claude_code_install import ClaudeCodeHookInstaller
from watched_kettle.integrations.codex_install import (
    CodexHookInstaller,
    build_managed_hook,
)
from tests.test_pet_preferences import FakeSettings


class SyncedSettings(FakeSettings):
    synced = False

    def sync(self):
        self.synced = True


class FakeInstaller:
    def __init__(self, can_apply=True, has_changes=True):
        self.plan = SimpleNamespace(can_apply=can_apply, has_changes=has_changes)
        self.calls = []

    def preview_install(self):
        self.calls.append("preview_install")
        return self.plan

    def preview_remove(self):
        self.calls.append("preview_remove")
        return self.plan

    def apply(self, plan):
        self.calls.append("apply")


def fully_installed(installer):
    status = installer.inspect()
    return 0 < status.installed_events == status.expected_events


class IntegrationSetupTests(unittest.TestCase):
    def setUp(self):
        self.settings = SyncedSettings()
        self.preferences = ApplicationPreferences(self.settings)

    def run_setup(self, *arguments, **installers):
        return run_integration_setup(
            ["--configure-integrations", *arguments],
            self.preferences,
            installers,
        )

    def test_choices_require_on_or_off(self):
        self.assertEqual(
            parse_tool_choices(["--codex=on", "--claude-code=off", "--other=x"]),
            {"codex": True, "claude_code": False},
        )
        with self.assertRaises(ValueError):
            parse_tool_choices(["--codex"])
        self.assertEqual(self.run_setup("--codex=yes", codex=FakeInstaller()), 2)
        self.assertEqual(self.run_setup(), 2)

    def test_each_named_tool_gets_its_hook_and_switch(self):
        codex, claude = FakeInstaller(), FakeInstaller()

        result = self.run_setup(
            "--codex=on", "--claude-code=off", codex=codex, claude_code=claude
        )

        self.assertEqual(result, 0)
        self.assertEqual(codex.calls, ["preview_install", "apply"])
        self.assertEqual(claude.calls, ["preview_remove", "apply"])
        self.assertTrue(self.settings.values["usage/enabled"])
        self.assertFalse(self.settings.values["usage/claude_code_enabled"])
        self.assertTrue(self.settings.synced)

    def test_unnamed_tool_and_unchanged_files_are_left_alone(self):
        codex = FakeInstaller(has_changes=False)
        claude = FakeInstaller()

        self.assertEqual(
            self.run_setup("--codex=on", codex=codex, claude_code=claude), 0
        )

        self.assertEqual(codex.calls, ["preview_install"])
        self.assertEqual(claude.calls, [])
        self.assertNotIn("usage/claude_code_enabled", self.settings.values)

    def test_blocked_tool_keeps_its_switch_and_reports_failure(self):
        codex, claude = FakeInstaller(can_apply=False), FakeInstaller()

        result = self.run_setup(
            "--codex=on", "--claude-code=on", codex=codex, claude_code=claude
        )

        self.assertEqual(result, 2)
        self.assertNotIn("apply", codex.calls)
        self.assertNotIn("usage/enabled", self.settings.values)
        self.assertTrue(self.settings.values["usage/claude_code_enabled"])

    def test_real_installers_add_and_remove_only_the_managed_hooks(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            hooks_path = root / ".codex" / "hooks.json"
            hooks_path.parent.mkdir()
            claude_settings = root / ".claude" / "settings.json"
            claude_settings.parent.mkdir()
            claude_settings.write_text(
                json.dumps({"theme": "dark", "hooks": {}}), encoding="utf-8"
            )
            installers = dict(
                codex=CodexHookInstaller(
                    hooks_path=hooks_path,
                    config_path=root / ".codex" / "config.toml",
                    managed_hook=build_managed_hook(project_root=root),
                ),
                claude_code=ClaudeCodeHookInstaller(
                    settings_path=claude_settings, policy_paths=()
                ),
            )

            self.assertEqual(
                self.run_setup("--codex=on", "--claude-code=on", **installers), 0
            )
            self.assertTrue(fully_installed(installers["codex"]))
            self.assertTrue(fully_installed(installers["claude_code"]))

            self.assertEqual(self.run_setup("--claude-code=off", **installers), 0)
            self.assertTrue(fully_installed(installers["codex"]))
            self.assertEqual(installers["claude_code"].inspect().installed_events, 0)
            saved = json.loads(claude_settings.read_text(encoding="utf-8"))
            self.assertEqual(saved["theme"], "dark")


if __name__ == "__main__":
    unittest.main()
