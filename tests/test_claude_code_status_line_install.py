"""Claude Code status line install keeps and restores the user's line."""

import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from watched_kettle import hook_bridge_entrypoint
from watched_kettle.integrations import claude_code_status_line
from watched_kettle.integrations.claude_code_status_line import (
    DEFAULT_STATUS_LINE_LAYOUT,
    detected_ide,
    normalize_layout,
    read_layout,
    status_text,
    write_layout,
)
from watched_kettle.integrations.claude_code_install import shell_neutral_command
from watched_kettle.integrations.claude_code_status_line_install import (
    STATUS_LINE_FLAG,
    ClaudeCodeStatusLineInstaller,
    build_status_line_command,
    is_managed_status_line,
)
from watched_kettle.integrations.codex_install import StaleHookPlanError


COMMAND = '"C:/App/WatchedKettleHookBridge.exe" --claude-code-status-line --managed-id watched-kettle-managed-v1'
MINE = {"type": "command", "command": "~/.claude/my-line.sh", "padding": 2}


class StatusLineInstallTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        root = Path(self.directory.name)
        self.settings = root / ".claude" / "settings.json"
        self.settings.parent.mkdir()
        self.sidecar = root / "runtime" / "claude-code-status-line.json"
        self.installer = ClaudeCodeStatusLineInstaller(
            self.settings, self.sidecar, COMMAND
        )

    def tearDown(self):
        self.directory.cleanup()

    def write(self, payload):
        self.settings.write_text(json.dumps(payload), encoding="utf-8")

    def read(self):
        return json.loads(self.settings.read_text(encoding="utf-8"))

    def apply(self, operation):
        preview = getattr(self.installer, f"preview_{operation}")()
        self.assertTrue(preview.can_apply, preview.warnings)
        return self.installer.apply(preview)

    def test_install_and_remove_without_a_previous_line(self):
        self.write({"theme": "dark", "hooks": {}})
        self.assertEqual(self.installer.inspect().state, "not_installed")

        self.apply("install")
        self.assertEqual(self.read()["statusLine"]["command"], COMMAND)
        self.assertEqual(self.installer.inspect().state, "installed")
        self.assertFalse(self.sidecar.exists())

        self.apply("remove")
        self.assertEqual(self.read(), {"theme": "dark", "hooks": {}})

    def test_previous_line_is_kept_and_restored(self):
        self.write({"statusLine": MINE, "theme": "dark"})

        self.apply("install")
        installed = self.read()["statusLine"]
        self.assertEqual(installed["command"], COMMAND)
        self.assertEqual(installed["padding"], 2)
        self.assertEqual(
            json.loads(self.sidecar.read_text(encoding="utf-8"))["original"], MINE
        )
        self.assertTrue(self.installer.inspect().has_original)

        self.apply("remove")
        self.assertEqual(self.read(), {"statusLine": MINE, "theme": "dark"})
        self.assertFalse(self.sidecar.exists())

    def test_old_bridge_path_is_repaired_without_losing_the_original(self):
        self.write({"statusLine": MINE})
        self.apply("install")
        settings = self.read()
        settings["statusLine"]["command"] = '"old.exe" --claude-code-status-line'
        self.write(settings)
        self.assertEqual(self.installer.inspect().state, "drifted")

        self.apply("repair")

        self.assertEqual(self.read()["statusLine"]["command"], COMMAND)
        self.assertEqual(
            json.loads(self.sidecar.read_text(encoding="utf-8"))["original"], MINE
        )

    def test_a_line_changed_after_install_is_not_overwritten(self):
        self.write({"statusLine": MINE})
        self.apply("install")
        changed = {"type": "command", "command": "other-tool"}
        self.write({"statusLine": changed})

        self.apply("remove")

        self.assertEqual(self.read(), {"statusLine": changed})
        self.assertFalse(self.sidecar.exists())

    def test_settings_changed_after_preview_are_not_overwritten(self):
        self.write({})
        plan = self.installer.preview_install()
        self.write({"theme": "light"})

        with self.assertRaises(StaleHookPlanError):
            self.installer.apply(plan)
        self.assertEqual(self.read(), {"theme": "light"})

    def test_invalid_or_disabled_settings(self):
        self.settings.write_text("{broken", encoding="utf-8")
        self.assertFalse(self.installer.preview_install().can_apply)
        self.write({"disableAllHooks": True})
        self.assertEqual(self.installer.inspect().state, "disabled")


# Writes stdin back after UTF-8 text with colour codes, as the bridge prints.
ECHO_SCRIPT = """import json, sys
data = sys.stdin.buffer.read().decode("utf-8")
line = "\\x1b[32m한도 42%\\x1b[0m " + json.dumps([sys.argv[1:], data], ensure_ascii=False)
sys.stdout.buffer.write(line.encode("utf-8"))
"""


def status_line_shells():
    """Claude Code runs status lines in Git Bash, or PowerShell without it."""
    root = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    bash = root / "Git" / "bin" / "bash.exe"
    if bash.is_file():
        yield "Git Bash", [str(bash), "-c"]
    system = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    powershell = system / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    yield "Windows PowerShell", [str(powershell), "-NoProfile", "-Command"]
    if pwsh := shutil.which("pwsh"):
        yield "PowerShell 7", [pwsh, "-NoProfile", "-Command"]


class StatusLineCommandTests(unittest.TestCase):
    def test_plain_path_is_left_unquoted_for_both_shells(self):
        command = build_status_line_command(
            executable=Path("C:/App/WatchedKettleHookBridge.exe")
        )

        self.assertEqual(command, COMMAND.replace('"', ""))
        self.assertTrue(is_managed_status_line({"command": command}))

    def test_other_paths_fall_back_to_an_encoded_powershell_call(self):
        command = build_status_line_command(
            executable=Path("C:/Installed App/$cash & 한글's (%)!.exe")
        )

        self.assertTrue(command.startswith("powershell.exe -NoLogo -NoProfile"))
        self.assertNotIn(STATUS_LINE_FLAG, command)
        self.assertTrue(is_managed_status_line({"command": command}))
        self.assertFalse(
            is_managed_status_line({"command": "powershell.exe -EncodedCommand e30="})
        )

    def test_encoded_line_is_repaired_when_the_bridge_moves(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings = root / "settings.json"
            settings.write_text(json.dumps({"statusLine": MINE}), encoding="utf-8")
            old, new = (
                ClaudeCodeStatusLineInstaller(
                    settings,
                    root / "sidecar.json",
                    build_status_line_command(executable=root / name / "Bridge.exe"),
                )
                for name in ("Old (1)", "New (2)")
            )
            old.apply(old.preview_install())
            self.assertEqual(new.inspect().state, "drifted")

            new.apply(new.preview_repair())

            self.assertEqual(new.inspect().state, "installed")
            new.apply(new.preview_remove())
            self.assertEqual(
                json.loads(settings.read_text(encoding="utf-8")), {"statusLine": MINE}
            )

    @unittest.skipUnless(os.name == "nt", "Windows shell integration")
    def test_both_forms_keep_stdin_and_output_bytes_in_each_shell(self):
        payload = json.dumps({"model": {"display_name": "한글"}}).encode("utf-8")
        with TemporaryDirectory() as directory:
            for folder in ("plain_dir", "spaced $dir (한글's)"):
                script = Path(directory) / folder / "echo.py"
                script.parent.mkdir()
                script.write_text(ECHO_SCRIPT, encoding="utf-8")
                command = shell_neutral_command(
                    sys.executable, script, STATUS_LINE_FLAG
                )
                for shell, prefix in status_line_shells():
                    with self.subTest(folder=folder, shell=shell):
                        process = subprocess.run(
                            [*prefix, command],
                            input=payload,
                            capture_output=True,
                            timeout=60,
                            check=False,
                        )
                        self.assertEqual(process.returncode, 0, process.stderr)
                        prefix_bytes, _, echoed = process.stdout.partition(b" ")
                        self.assertEqual(prefix_bytes, "[32m한도".encode())
                        self.assertEqual(
                            json.loads(echoed.decode("utf-8").split(" ", 1)[-1]),
                            [[STATUS_LINE_FLAG], payload.decode("utf-8")],
                        )


LIMITS = {
    "five_hour": {"used_percentage": 41, "resets_at": 1900000000},
    "seven_day": {"used_percentage": 55.4, "resets_at": 1900000000},
}


def plain(text):
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


class StatusTextTests(unittest.TestCase):
    """The line shown to users who had no status line of their own."""

    def run_bridge(self, payload, sent=True, columns=""):
        stdout = io.BytesIO()
        with (
            patch.dict(
                os.environ,
                {
                    "WATCHED_KETTLE_STATUS_LINE_CONFIG": "missing.json",
                    "COLUMNS": columns,
                },
            ),
            patch(
                "watched_kettle.integrations.codex_client.send_pet_event",
                return_value=sent,
            ),
            patch.object(
                claude_code_status_line, "detected_ide", return_value="VS Code"
            ),
        ):
            hook_bridge_entrypoint.run_status_line(
                io.BytesIO(json.dumps(payload).encode("utf-8")), stdout
            )
        return stdout.getvalue().decode("utf-8")

    def test_full_line_without_a_previous_line(self):
        clock = time.strftime("%H:%M", time.localtime(1900000000))
        payload = {
            "model": {"display_name": "Opus 5.5"},
            "effort": {"level": "high"},
            "session_name": "샘플 작업",
            "context_window": {
                "context_window_size": 1000000,
                "used_percentage": 10.4,
                "current_usage": {
                    "input_tokens": 3000,
                    "cache_creation_input_tokens": 800,
                    "cache_read_input_tokens": 100000,
                    "output_tokens": 500,
                },
            },
            "rate_limits": LIMITS,
        }

        line = self.run_bridge(payload)

        # Connections first, usage second; the session name is already on
        # Claude Code's prompt border.
        self.assertEqual(
            plain(line),
            "VS Code · Opus 5.5 high\n"
            f"컨텍스트 10% (104k/1M) · 5시간 41% ({clock}) · 7일 55%\n",
        )
        self.assertIn("\x1b[32m컨텍스트", line)
        self.assertNotIn("샘플 작업", line)

    def test_pet_shows_only_when_the_send_fails(self):
        self.assertNotIn("펫", self.run_bridge({"rate_limits": LIMITS}))
        self.assertTrue(
            plain(self.run_bridge({"rate_limits": LIMITS}, sent=False)).startswith(
                "펫 꺼짐 · "
            )
        )
        # Before the first response there are no limits, so nothing was sent.
        self.assertNotIn("펫", self.run_bridge({}, sent=False))

    def test_context_colour_and_fallback_token_count(self):
        def context(percent):
            return status_text(
                {
                    "context_window": {
                        "context_window_size": 200000,
                        "used_percentage": percent,
                        "current_usage": None,
                    }
                },
                None,
            )

        self.assertIn("\x1b[33m컨텍스트 50% (100k/200k)", context(50))
        self.assertIn("\x1b[31m컨텍스트 85%", context(85))
        self.assertEqual(
            status_text({"context_window": {"used_percentage": None}}, None), ""
        )

    def test_out_of_range_reset_time_keeps_the_line(self):
        event = {"five_hour_percent": 41.0, "five_hour_resets_at": 10**18}

        self.assertEqual(status_text({}, event), "5시간 41%\n")

    def test_narrow_terminal_drops_low_priority_parts_per_line(self):
        payload = {
            "model": {"display_name": "Opus 5.5"},
            "context_window": {"used_percentage": 10},
            "rate_limits": LIMITS,
        }

        lines = plain(self.run_bridge(payload, sent=False, columns="16"))

        self.assertEqual(lines.splitlines(), ["펫 꺼짐", "컨텍스트 10%"])

    def test_empty_line_is_not_printed(self):
        self.assertEqual(status_text({}, {"seven_day_percent": 55.0}), "7일 55%\n")
        self.assertEqual(
            status_text({"model": {"display_name": "Opus 5.5"}}, None), "Opus 5.5\n"
        )

    def test_model_name_cannot_inject_control_sequences(self):
        line = status_text({"model": {"display_name": "a\x1b[2Jb\nc" + "x" * 40}}, None)

        self.assertNotIn("\x1b[2J", line)
        self.assertNotIn("\n", line.rstrip("\n"))
        self.assertIn("…", line)


class StatusLineLayoutTests(unittest.TestCase):
    payload = {
        "model": {"display_name": "Opus 5.5"},
        "context_window": {"used_percentage": 12},
    }
    event = {
        "five_hour_percent": 41.0,
        "five_hour_resets_at": 1_800_000_000,
        "seven_day_percent": 55.0,
    }

    def test_layout_moves_hides_and_uncolors_items(self):
        layout = {
            "lines": [["seven_day", "five_hour"], ["model"]],
            "color": False,
            "reset_times": False,
        }
        text = status_text(self.payload, self.event, layout=layout)
        self.assertEqual(text, "7일 55% · 5시간 41%\nOpus 5.5\n")
        colored = status_text(self.payload, self.event, layout={"lines": [["context"]]})
        self.assertIn("\x1b[32m", colored)

    def test_damaged_layouts_fall_back_to_the_default(self):
        default = status_text(self.payload, self.event)
        for broken in (None, [], {"lines": "x"}, {"lines": [["model"]], "color": 1}):
            with self.subTest(layout=broken):
                self.assertEqual(normalize_layout(broken), DEFAULT_STATUS_LINE_LAYOUT)
        self.assertEqual(
            normalize_layout({"lines": [["model", "model", "nope"], [], ["ide"]]}),
            {"lines": [["model"], []], "color": True, "reset_times": True},
        )
        self.assertEqual(
            status_text(self.payload, self.event, layout=DEFAULT_STATUS_LINE_LAYOUT),
            default,
        )

    def test_layout_file_round_trips_and_ignores_bad_files(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "runtime" / "layout.json"
            self.assertEqual(read_layout(path), DEFAULT_STATUS_LINE_LAYOUT)
            saved = write_layout(path, {"lines": [["ide"]], "color": False})
            self.assertEqual(read_layout(path), saved)
            path.write_text("{", encoding="utf-8")
            self.assertEqual(read_layout(path), DEFAULT_STATUS_LINE_LAYOUT)
            path.write_bytes(b" " * 5000)
            self.assertEqual(read_layout(path), DEFAULT_STATUS_LINE_LAYOUT)


class DetectedIdeTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.config = Path(self.directory.name)
        (self.config / "ide").mkdir()
        self.project = str(self.config / "project")

    def tearDown(self):
        self.directory.cleanup()

    def lock(self, name, **value):
        (self.config / "ide" / name).write_text(json.dumps(value), encoding="utf-8")

    def test_running_ide_for_this_folder(self):
        self.lock(
            "1.lock",
            pid=os.getpid(),
            ideName="Visual Studio Code",
            workspaceFolders=[self.project],
        )

        self.assertEqual(
            detected_ide(os.path.join(self.project, "src"), self.config), "VS Code"
        )
        self.assertIsNone(detected_ide(str(self.config / "elsewhere"), self.config))
        self.assertIsNone(detected_ide(self.project + "-other", self.config))

    def test_stale_or_broken_locks_are_ignored(self):
        self.lock("1.lock", pid=0, workspaceFolders=[self.project])
        (self.config / "ide" / "2.lock").write_text("{bad", encoding="utf-8")

        self.assertIsNone(detected_ide(self.project, self.config))
        self.assertIsNone(detected_ide(None, self.config))
        self.assertIsNone(detected_ide(self.project, self.config / "missing"))


if __name__ == "__main__":
    unittest.main()
