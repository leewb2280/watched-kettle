import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from watched_kettle.integrations.claude_code_install import (
    MANAGED_HOOK_EVENTS,
    ClaudeCodeHookInstaller,
    build_managed_commands,
)
from watched_kettle.integrations.codex_install import (
    MANAGED_MARKER,
    HookInstallError,
    StaleHookPlanError,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
USER_SETTINGS = {
    "modelSettings": {"claude-opus-5-5": {"effortLevel": "high"}},
    "theme": "dark",
    "permissions": {"allow": ["Bash(git status)"]},
    "hooks": {
        "PreToolUse": [
            {
                "matcher": "Bash",
                "hooks": [{"type": "command", "command": "my-own-guard.sh"}],
            }
        ],
        "Stop": [{"hooks": [{"type": "command", "command": "notify-me.sh"}]}],
    },
}


class ClaudeCodeHookInstallerTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.settings_path = self.root / ".claude" / "settings.json"
        self.settings_path.parent.mkdir()
        self.bridge = self.root / "Installed App" / "WatchedKettleHookBridge.exe"
        self.installer = self.make_installer()

    def tearDown(self):
        self.directory.cleanup()

    def make_installer(self, executable=None, **options):
        return ClaudeCodeHookInstaller(
            settings_path=self.settings_path,
            commands=build_managed_commands(executable=executable or self.bridge),
            policy_paths=options.pop("policy_paths", ()),
            **options,
        )

    def write_settings(self, payload):
        self.settings_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def read_settings(self):
        return json.loads(self.settings_path.read_text(encoding="utf-8"))

    def install(self, installer=None):
        installer = installer or self.installer
        return installer.apply(installer.preview_install())

    def test_install_adds_only_managed_entries_and_preserves_user_settings(self):
        self.write_settings(USER_SETTINGS)

        result = self.install()

        settings = self.read_settings()
        self.assertEqual(result.status.state, "installed")
        self.assertEqual(result.status.installed_events, len(MANAGED_HOOK_EVENTS))
        for key in ("modelSettings", "theme", "permissions"):
            self.assertEqual(settings[key], USER_SETTINGS[key])
        self.assertEqual(
            settings["hooks"]["PreToolUse"][0], USER_SETTINGS["hooks"]["PreToolUse"][0]
        )
        self.assertEqual(
            settings["hooks"]["Stop"][0], USER_SETTINGS["hooks"]["Stop"][0]
        )
        managed = settings["hooks"]["PreToolUse"][1]
        self.assertEqual(managed["matcher"], "*")
        command = managed["hooks"][0]["command"]
        self.assertIn("--claude-code-hook-bridge --event PreToolUse", command)
        self.assertIn(MANAGED_MARKER, command)
        self.assertTrue(command.startswith('"'))
        self.assertNotIn("\\", command)
        self.assertEqual(managed["hooks"][0]["timeout"], 5)
        self.assertNotIn("matcher", settings["hooks"]["Stop"][1])
        self.assertEqual(len(result.backup_paths), 1)
        self.assertEqual(
            json.loads(result.backup_paths[0].read_text(encoding="utf-8")),
            USER_SETTINGS,
        )

    def test_reinstall_is_idempotent(self):
        self.write_settings(USER_SETTINGS)
        self.install()
        before = self.settings_path.read_bytes()

        plan = self.installer.preview_install()
        result = self.installer.apply(plan)

        self.assertIsNone(plan.hooks_text)
        self.assertEqual(result.changed_paths, ())
        self.assertEqual(self.settings_path.read_bytes(), before)

    def test_remove_restores_the_original_settings(self):
        self.write_settings(USER_SETTINGS)
        self.install()

        result = self.installer.apply(self.installer.preview_remove())

        self.assertEqual(self.read_settings(), USER_SETTINGS)
        self.assertEqual(result.status.state, "not_installed")

    def test_install_into_missing_file_and_remove_leaves_no_hooks_key(self):
        self.install()
        self.assertEqual(self.installer.inspect().state, "installed")

        self.installer.apply(self.installer.preview_remove())

        self.assertEqual(self.read_settings(), {})

    def test_invalid_settings_are_never_overwritten(self):
        self.settings_path.write_text("{ broken", encoding="utf-8")

        status = self.installer.inspect()
        plan = self.installer.preview_install()

        self.assertEqual(status.state, "invalid")
        self.assertFalse(plan.can_apply)
        with self.assertRaises(HookInstallError):
            self.installer.apply(plan)
        self.assertEqual(self.settings_path.read_text(encoding="utf-8"), "{ broken")

    def test_invalid_settings_without_marker_do_not_block_removal(self):
        self.settings_path.write_text("{ broken", encoding="utf-8")
        self.assertTrue(self.installer.preview_remove().can_apply)

        self.settings_path.write_text(
            '{ broken "' + MANAGED_MARKER + '"', encoding="utf-8"
        )
        self.assertFalse(self.installer.preview_remove().can_apply)

    def test_disabled_hooks_and_policy_are_reported(self):
        self.write_settings({"disableAllHooks": True})
        self.assertEqual(self.installer.inspect().state, "disabled")
        self.assertTrue(self.installer.preview_install().can_apply)

        policy = self.root / "managed-settings.json"
        policy.write_text('{"allowManagedHooksOnly": true}', encoding="utf-8")
        self.write_settings({})
        installer = self.make_installer(policy_paths=(policy,))

        self.assertEqual(installer.inspect().state, "blocked_by_policy")

    def test_moved_executable_is_drifted_and_repairable(self):
        self.install()
        moved = self.make_installer(executable=self.root / "New Place" / "Bridge.exe")

        self.assertEqual(moved.inspect().state, "drifted")
        moved.apply(moved.preview_repair())

        self.assertEqual(moved.inspect().state, "installed")
        self.assertNotIn("Installed App", self.settings_path.read_text("utf-8"))

    def test_missing_event_is_partial(self):
        self.install()
        settings = self.read_settings()
        del settings["hooks"]["Notification"]
        self.write_settings(settings)

        self.assertEqual(self.installer.inspect().state, "partial")

    def test_settings_changed_after_preview_is_rejected(self):
        self.write_settings(USER_SETTINGS)
        plan = self.installer.preview_install()
        self.write_settings({**USER_SETTINGS, "theme": "light"})

        with self.assertRaises(StaleHookPlanError):
            self.installer.apply(plan)
        self.assertEqual(self.read_settings()["theme"], "light")

    def test_paths_that_bash_would_expand_are_rejected(self):
        for name in ("price$HOME", 'quote"name', "tick`name"):
            with self.assertRaises(ValueError):
                build_managed_commands(executable=self.root / name / "Bridge.exe")

    def test_unbuildable_commands_block_install_but_not_remove(self):
        installer = ClaudeCodeHookInstaller(
            settings_path=self.settings_path,
            commands={},
            policy_paths=(),
            command_error="bad path",
        )

        self.assertFalse(installer.preview_install().can_apply)
        self.assertTrue(installer.preview_remove().can_apply)

    def test_claude_config_dir_selects_the_settings_file(self):
        with patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.root / "alt")}):
            installer = ClaudeCodeHookInstaller(policy_paths=())

        self.assertEqual(installer.settings_path, self.root / "alt" / "settings.json")

    def test_source_checkout_command_runs_the_project_bridge(self):
        commands = build_managed_commands(project_root=self.root / "repo")

        self.assertIn("/repo/.venv/Scripts/python.exe", commands["Stop"])
        self.assertIn("/repo/main_hook_bridge.py", commands["Stop"])


class RemoveManagedHookCommandTests(unittest.TestCase):
    def test_helper_removes_codex_and_claude_code_hooks(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            claude = root / "claude"
            claude.mkdir()
            installer = ClaudeCodeHookInstaller(
                settings_path=claude / "settings.json",
                commands=build_managed_commands(executable=root / "Bridge.exe"),
                policy_paths=(),
            )
            installer.apply(installer.preview_install())
            environment = os.environ.copy()
            environment["CLAUDE_CONFIG_DIR"] = str(claude)
            environment["CODEX_HOME"] = str(root / "codex")

            process = subprocess.run(
                [sys.executable, "-m", "watched_kettle", "--remove-managed-hook"],
                capture_output=True,
                text=True,
                cwd=PROJECT_ROOT,
                env=environment,
                timeout=30,
                check=False,
            )

            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(
                json.loads((claude / "settings.json").read_text(encoding="utf-8")),
                {},
            )


if __name__ == "__main__":
    unittest.main()
