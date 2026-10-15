import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4
from tempfile import TemporaryDirectory
import unittest

from watched_kettle.integrations.codex_install import (
    CodexHookInstaller,
    HookInstallError,
    LEGACY_MANAGED_MARKERS,
    MANAGED_HOOK_EVENTS,
    MANAGED_MARKER,
    StaleHookPlanError,
    build_managed_hook,
    default_hook_executable,
)
from scripts.check_edition_modules import check_edition_modules


OTHER_HOOK = {
    "type": "command",
    "command": "other-hook",
    "commandWindows": "other-hook.exe",
    "timeout": 5,
}


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


class CodexHookInstallerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _warm_windows_powershell()

    def setUp(self):
        self.directory = TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.hooks_path = self.root / ".codex" / "hooks.json"
        self.config_path = self.root / ".codex" / "config.toml"
        self.hooks_path.parent.mkdir()
        self.managed_hook = build_managed_hook(
            project_root=self.root / "Project With Spaces"
        )
        self.installer = CodexHookInstaller(
            hooks_path=self.hooks_path,
            config_path=self.config_path,
            managed_hook=self.managed_hook,
        )

    def tearDown(self):
        self.directory.cleanup()

    def write_existing_settings(self):
        self.hooks_path.write_text(
            json.dumps(
                {
                    "description": "Existing hooks",
                    "custom": {"keep": True},
                    "hooks": {
                        "Stop": [{"matcher": "keep", "hooks": [OTHER_HOOK]}],
                    },
                }
            ),
            encoding="utf-8",
        )
        self.config_path.write_text(
            "# keep this comment\n[features]\nexperimental = true\n",
            encoding="utf-8",
        )

    def test_preview_install_apply_and_remove_preserve_other_settings(self):
        self.write_existing_settings()
        original_hooks = self.hooks_path.read_bytes()
        original_config = self.config_path.read_bytes()

        plan = self.installer.preview_install()

        self.assertTrue(plan.can_apply)
        self.assertTrue(plan.has_changes)
        self.assertIn("hooks = true", plan.config_text)
        result = self.installer.apply(plan)

        self.assertEqual(result.status.state, "installed")
        self.assertEqual(len(result.backup_paths), 2)
        self.assertEqual(result.backup_paths[0].read_bytes(), original_config)
        self.assertEqual(result.backup_paths[1].read_bytes(), original_hooks)

        installed = json.loads(self.hooks_path.read_text(encoding="utf-8"))
        self.assertEqual(installed["description"], "Existing hooks")
        self.assertEqual(installed["custom"], {"keep": True})
        self.assertEqual(
            installed["hooks"]["Stop"][0]["hooks"][0],
            OTHER_HOOK,
        )
        self.assertEqual(
            sum(
                MANAGED_MARKER in hook.get("commandWindows", "")
                for groups in installed["hooks"].values()
                for group in groups
                for hook in group["hooks"]
            ),
            len(MANAGED_HOOK_EVENTS),
        )
        config = self.config_path.read_text(encoding="utf-8")
        self.assertIn("# keep this comment", config)
        self.assertIn("experimental = true", config)
        self.assertIn("hooks = true", config)

        repeated = self.installer.preview_install()
        self.assertTrue(repeated.can_apply)
        self.assertFalse(repeated.has_changes)

        removed = self.installer.apply(self.installer.preview_remove())
        self.assertEqual(removed.status.state, "not_installed")
        cleaned = json.loads(self.hooks_path.read_text(encoding="utf-8"))
        self.assertEqual(
            cleaned["hooks"],
            {
                "Stop": [{"matcher": "keep", "hooks": [OTHER_HOOK]}],
            },
        )
        self.assertIn(
            "hooks = true",
            self.config_path.read_text(encoding="utf-8"),
        )

    def test_missing_files_are_created_and_remove_is_idempotent(self):
        plan = self.installer.preview_install()

        self.assertTrue(plan.can_apply)
        self.assertEqual(plan.status_before.state, "not_installed")
        result = self.installer.apply(plan)

        self.assertEqual(result.status.state, "installed")
        self.assertEqual(result.backup_paths, ())
        self.assertTrue(self.hooks_path.is_file())
        self.assertTrue(self.config_path.is_file())

        self.installer.apply(self.installer.preview_remove())
        second_remove = self.installer.preview_remove()
        self.assertFalse(second_remove.has_changes)

    def test_explicit_disabled_feature_is_never_overwritten(self):
        self.hooks_path.write_text('{"hooks": {}}', encoding="utf-8")
        self.config_path.write_text(
            "[features]\nhooks = false\n",
            encoding="utf-8",
        )
        before_hooks = self.hooks_path.read_bytes()
        before_config = self.config_path.read_bytes()

        plan = self.installer.preview_install()

        self.assertFalse(plan.can_apply)
        with self.assertRaises(HookInstallError):
            self.installer.apply(plan)
        self.assertEqual(self.hooks_path.read_bytes(), before_hooks)
        self.assertEqual(self.config_path.read_bytes(), before_config)

    def test_invalid_json_and_toml_are_reported_without_changes(self):
        self.hooks_path.write_text("not-json", encoding="utf-8")
        self.config_path.write_text("[features\n", encoding="utf-8")
        before_hooks = self.hooks_path.read_bytes()
        before_config = self.config_path.read_bytes()

        plan = self.installer.preview_install()

        self.assertFalse(plan.can_apply)
        self.assertEqual(plan.status_before.state, "invalid")
        self.assertEqual(self.hooks_path.read_bytes(), before_hooks)
        self.assertEqual(self.config_path.read_bytes(), before_config)

    def test_stale_preview_is_rejected(self):
        self.write_existing_settings()
        plan = self.installer.preview_install()
        self.hooks_path.write_text('{"hooks": {}}', encoding="utf-8")

        with self.assertRaises(StaleHookPlanError):
            self.installer.apply(plan)

    def test_repair_replaces_duplicate_and_drifted_managed_entries(self):
        self.write_existing_settings()
        self.installer.apply(self.installer.preview_install())
        payload = json.loads(self.hooks_path.read_text(encoding="utf-8"))
        payload["hooks"]["PreToolUse"][-1]["hooks"][0]["timeout"] = 99
        payload["hooks"]["PreToolUse"].append(
            {
                "hooks": [self.managed_hook],
            }
        )
        self.hooks_path.write_text(json.dumps(payload), encoding="utf-8")

        self.assertIn(self.installer.inspect().state, {"partial", "drifted"})
        repaired = self.installer.apply(self.installer.preview_repair())

        self.assertEqual(repaired.status.state, "installed")

    def write_legacy_hooks(self):
        self.write_existing_settings()
        legacy_hook = {
            "type": "command",
            "command": f"old.exe --codex-hook-bridge --managed-id {LEGACY_MANAGED_MARKERS[0]}",
            "commandWindows": (
                f"old.exe --codex-hook-bridge --managed-id {LEGACY_MANAGED_MARKERS[0]}"
            ),
            "timeout": 3,
        }
        payload = json.loads(self.hooks_path.read_text(encoding="utf-8"))
        for event in MANAGED_HOOK_EVENTS:
            payload["hooks"].setdefault(event, []).append({"hooks": [legacy_hook]})
        self.hooks_path.write_text(json.dumps(payload), encoding="utf-8")
        return legacy_hook

    def test_private_beta_hooks_count_as_managed_and_migrate(self):
        self.write_legacy_hooks()
        config_before = self.config_path.read_text(encoding="utf-8")

        self.assertEqual(self.installer.inspect().state, "drifted")
        result = self.installer.apply(self.installer.preview_legacy_migration())

        self.assertEqual(result.status.state, "installed")
        hooks_text = self.hooks_path.read_text(encoding="utf-8")
        self.assertNotIn(LEGACY_MANAGED_MARKERS[0], hooks_text)
        self.assertEqual(
            json.loads(hooks_text)["hooks"]["Stop"][0]["hooks"], [OTHER_HOOK]
        )
        self.assertEqual(self.config_path.read_text(encoding="utf-8"), config_before)

    def test_legacy_migration_leaves_unrelated_or_current_hooks_alone(self):
        self.write_existing_settings()
        plan = self.installer.preview_legacy_migration()
        self.assertFalse(plan.has_changes)

        self.installer.apply(self.installer.preview_install())
        self.assertFalse(self.installer.preview_legacy_migration().has_changes)

    def test_remove_also_clears_private_beta_hooks(self):
        self.write_legacy_hooks()

        self.installer.apply(self.installer.preview_remove())

        self.assertEqual(self.installer.inspect().state, "not_installed")
        self.assertNotIn(
            LEGACY_MANAGED_MARKERS[0], self.hooks_path.read_text(encoding="utf-8")
        )

    def test_packaged_command_uses_executable_and_management_marker(self):
        hook = build_managed_hook(
            executable=self.root / "Installed App" / "Watched Kettle.exe"
        )

        self.assertIn("Watched Kettle.exe", hook["commandWindows"])
        self.assertIn("--codex-hook-bridge", hook["commandWindows"])
        self.assertIn(MANAGED_MARKER, hook["commandWindows"])

    def test_packaged_hook_prefers_the_qt_free_bridge_when_installed(self):
        app = self.root / "Installed App" / "WatchedKettle.exe"
        app.parent.mkdir(parents=True)
        app.write_bytes(b"")

        self.assertEqual(default_hook_executable(app), app.resolve())
        bridge = app.with_name("WatchedKettleHookBridge.exe")
        bridge.write_bytes(b"")
        self.assertEqual(default_hook_executable(app), bridge.resolve())

    def test_hook_bridge_archive_rejects_qt_and_application_modules(self):
        toc = self.root / "PYZ-01.toc"
        toc.write_text(
            repr(
                (
                    "PYZ-01.pyz",
                    [
                        ("watched_kettle.integrations.codex_bridge", "", "PYMODULE"),
                        ("watched_kettle.state.event_names", "", "PYMODULE"),
                        ("PySide6.QtCore", "", "PYMODULE"),
                        ("dataclasses", "", "PYMODULE"),
                        ("watched_kettle.application.runtime", "", "PYMODULE"),
                    ],
                )
            ),
            encoding="utf-8",
        )

        self.assertEqual(
            check_edition_modules(toc, "hook-bridge"),
            ["PySide6.QtCore", "dataclasses", "watched_kettle.application.runtime"],
        )

    def test_packaged_bridge_mode_queues_to_user_runtime_and_returns_json(self):
        environment = os.environ.copy()
        environment["WATCHED_KETTLE_SERVER_NAME"] = f"missing-{uuid4().hex}"
        environment["LOCALAPPDATA"] = str(self.root / "Local App Data")
        process = subprocess.run(
            [sys.executable, "-m", "watched_kettle", "--codex-hook-bridge"],
            input=json.dumps(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "packaged-test",
                }
            ),
            text=True,
            capture_output=True,
            cwd=Path(__file__).resolve().parents[1],
            env=environment,
            timeout=5,
            check=False,
        )

        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stdout.strip(), "{}")
        queued = list(
            (
                self.root / "Local App Data" / "WatchedKettle" / "runtime" / "events"
            ).glob("*.json")
        )
        self.assertEqual(len(queued), 1)

    @unittest.skipUnless(PROJECT_CODEX_HOOKS.is_dir(), "development repository hook")
    def test_project_bridge_directly_reads_original_stdin(self):
        project_root = Path(__file__).resolve().parents[1]
        environment = os.environ.copy()
        environment["LOCALAPPDATA"] = str(self.root / "Direct Local Data")
        environment["WATCHED_KETTLE_SERVER_NAME"] = f"missing-{uuid4().hex}"
        environment["WATCHED_KETTLE_DEBUG"] = "1"
        bridge = project_root / ".codex" / "hooks" / "codex_pet_bridge.py"
        payload = json.dumps(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "direct-test",
            }
        )

        process = subprocess.run(
            [sys.executable, str(bridge), "--managed-id", MANAGED_MARKER],
            input=payload,
            text=True,
            capture_output=True,
            cwd=project_root,
            env=environment,
            timeout=6,
            check=False,
        )

        runtime_root = self.root / "Direct Local Data" / "WatchedKettle" / "runtime"
        queued = list((runtime_root / "events").glob("*.json"))
        health = json.loads(
            (runtime_root / "hook-health.json").read_text(encoding="utf-8")
        )
        diagnostic = (
            f"stdout={process.stdout}\nstderr={process.stderr}\nhealth={health}"
        )
        self.assertEqual(process.returncode, 0, diagnostic)
        self.assertEqual(process.stdout.strip(), "{}")
        self.assertIn("pet-hook bridge-start managed=1", process.stderr)
        self.assertIn("pet-hook input-json=object", process.stderr)
        self.assertIn("pet-hook result event=prompt outcome=queued", process.stderr)
        self.assertIn("pet-hook bridge-exit=0", process.stderr)
        self.assertEqual(health["event"], "prompt")
        self.assertEqual(health["outcome"], "queued")
        self.assertEqual(len(queued), 1, diagnostic)

    @unittest.skipUnless(os.name == "nt", "Windows wrapper integration")
    @unittest.skipUnless(PROJECT_CODEX_HOOKS.is_dir(), "development repository hook")
    def test_managed_windows_wrapper_uses_user_runtime_queue(self):
        project_root = Path(__file__).resolve().parents[1]
        environment = os.environ.copy()
        environment["LOCALAPPDATA"] = str(self.root / "Wrapper Local Data")
        environment["WATCHED_KETTLE_SERVER_NAME"] = f"missing-{uuid4().hex}"
        environment["WATCHED_KETTLE_DEBUG"] = "1"
        wrapper = project_root / ".codex" / "hooks" / "codex_pet_bridge.ps1"

        process = subprocess.run(
            _windows_powershell_command(
                wrapper,
                "-ManagedId",
                MANAGED_MARKER,
            ),
            input=json.dumps(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "wrapper-test",
                }
            ),
            text=True,
            capture_output=True,
            cwd=project_root,
            env=environment,
            timeout=6,
            shell=False,
            check=False,
        )

        self.assertEqual(process.returncode, 0, process.stderr)
        runtime_root = self.root / "Wrapper Local Data" / "WatchedKettle" / "runtime"
        queued = list((runtime_root / "events").glob("*.json"))
        health_path = runtime_root / "hook-health.json"
        health = (
            health_path.read_text(encoding="utf-8") if health_path.is_file() else ""
        )
        diagnostic = (
            f"stdout={process.stdout}\nstderr={process.stderr}\nhealth={health}"
        )
        self.assertIn("pet-hook wrapper-start managed=1", process.stderr)
        self.assertIn("pet-hook input-json=object", process.stderr)
        self.assertIn("pet-hook result event=prompt outcome=queued", process.stderr)
        self.assertIn("pet-hook bridge-exit=0", process.stderr)
        self.assertIn("pet-hook wrapper-end", process.stderr)
        health_payload = json.loads(health)
        self.assertEqual(health_payload["event"], "prompt")
        self.assertEqual(health_payload["outcome"], "queued")
        self.assertEqual(len(queued), 1, diagnostic)


if __name__ == "__main__":
    unittest.main()
