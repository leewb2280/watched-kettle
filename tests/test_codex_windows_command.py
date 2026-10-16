"""Execute generated invocations through the Windows shells, preserving stdin."""

import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from watched_kettle.integrations.codex_install import (
    MANAGED_MARKER,
    _windows_command,
    build_managed_hook,
)


def windows_shells():
    system = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    yield (
        "Windows PowerShell",
        [
            str(system / "WindowsPowerShell" / "v1.0" / "powershell.exe"),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
        ],
    )
    yield "cmd", [str(system / "cmd.exe"), "/d", "/s", "/c"]
    if pwsh := shutil.which("pwsh"):
        yield (
            "PowerShell 7",
            [pwsh, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command"],
        )


class WindowsHookCommandTests(unittest.TestCase):
    def test_encoded_invocation_quotes_paths_and_rejects_invalid_windows_paths(self):
        hook = build_managed_hook(
            executable=Path("Installed App/$cash & 한글's (%)!.exe")
        )
        command = hook["commandWindows"]
        self.assertTrue(command.startswith("powershell.exe -NoLogo -NoProfile"))
        script = base64.b64decode(command.split()[-1], validate=True).decode(
            "utf-16-le"
        )
        self.assertIn("$cash & 한글''s (%)!.exe' '--codex-hook-bridge'", script)
        self.assertIn(f"'--managed-id' '{MANAGED_MARKER}'", script)
        self.assertTrue(script.endswith("; exit $LASTEXITCODE"))
        with self.assertRaises(ValueError):
            _windows_command('invalid"path.exe')

    @unittest.skipUnless(os.name == "nt", "Windows shell integration")
    def test_native_input_arguments_and_exit_code_survive_each_outer_shell(self):
        code = (
            "import sys,json; "
            "print(json.dumps(dict(args=sys.argv[1:],stdin=sys.stdin.read())))"
        )
        arguments = ["space value", "한글", "literal-$&'()%!`", MANAGED_MARKER]
        payload = json.dumps(
            {"hook_event_name": "PreToolUse", "session_id": "isolated"}
        )
        for shell, prefix in windows_shells():
            with self.subTest(shell=shell):
                process = subprocess.run(
                    [*prefix, _windows_command(sys.executable, "-c", code, *arguments)],
                    input=payload,
                    text=True,
                    capture_output=True,
                    timeout=15,
                    check=False,
                )
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertEqual(
                    json.loads(process.stdout), dict(args=arguments, stdin=payload)
                )
                failed = subprocess.run(
                    [
                        *prefix,
                        _windows_command(sys.executable, "-c", "raise SystemExit(7)"),
                    ],
                    input="",
                    text=True,
                    capture_output=True,
                    timeout=15,
                    check=False,
                )
                # An outer PowerShell -Command maps a failing native process
                # to 1; cmd preserves its code. The encoded host itself must
                # retain the native exit code (checked below).
                self.assertEqual(
                    failed.returncode, 7 if shell == "cmd" else 1, failed.stderr
                )
        direct = subprocess.run(
            _windows_command(sys.executable, "-c", "raise SystemExit(7)").split(),
            input="",
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(direct.returncode, 7, direct.stderr)

    @unittest.skipUnless(os.name == "nt", "Windows script integration")
    def test_generated_development_hook_preserves_input_from_each_outer_shell(self):
        # A harmless wrapper observes the generated -ManagedId and stdin. No
        # real pipe, user runtime, or project hook is contacted.
        code = "import sys,json; print(json.dumps(dict(args=sys.argv[1:],stdin=sys.stdin.read())))"

        def quote(value):
            return "'" + str(value).replace("'", "''") + "'"

        payload = '{"hook_event_name":"Stop","session_id":"isolated"}'
        with TemporaryDirectory() as directory:
            root = Path(directory) / "Project 한글's $cash & (%)!` [space]"
            wrapper = root / ".codex" / "hooks" / "codex_pet_bridge.ps1"
            wrapper.parent.mkdir(parents=True)
            wrapper.write_text(
                "param([string]$ManagedId)\n& "
                + " ".join(quote(value) for value in (sys.executable, "-c", code))
                + " $ManagedId\nexit $LASTEXITCODE\n",
                encoding="utf-8-sig",
            )
            command = build_managed_hook(project_root=root)["commandWindows"]
            for shell, prefix in windows_shells():
                with self.subTest(shell=shell):
                    process = subprocess.run(
                        [*prefix, command],
                        input=payload,
                        text=True,
                        capture_output=True,
                        timeout=15,
                        check=False,
                    )
                    self.assertEqual(process.returncode, 0, process.stderr)
                    self.assertEqual(
                        json.loads(process.stdout),
                        dict(args=[MANAGED_MARKER], stdin=payload),
                    )
