"""Exercise the real PowerShell entry points without running their external tools."""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BOUNDARIES = {
    "watched_kettle/storage",
    "watched_kettle/usage",
    "watched_kettle/integrations/codex_log_worker.py",
    "watched_kettle/process_metrics.py",
    "watched_kettle/preferences",
    "watched_kettle/features/pet/contracts.py",
    "watched_kettle/ui/assistant_tray.py",
    "scripts/runtime_check.py",
    "watched_kettle/features/tasks",
    "watched_kettle/integrations/codex_task_client.py",
    "watched_kettle/features/project_activity",
    "watched_kettle/features/notifications",
    "watched_kettle/bubble_timing.py",
    "watched_kettle/settings_protocol.py",
    "scripts/generate_settings_protocol.py",
    "watched_kettle/application/settings_ui",
}
DRIVER = r"""
$ErrorActionPreference = "Stop"
function global:Invoke-FakeTool {
    param([string]$Tool, [object[]]$CommandArguments)
    $record = @{
        tool = $Tool
        arguments = @($CommandArguments | ForEach-Object { [string]$_ })
        edition = $env:WATCHED_KETTLE_EDITION
        coverage = $env:COVERAGE_FILE
    } | ConvertTo-Json -Compress
    [IO.File]::AppendAllText($env:CHECK_TRACE, $record + [Environment]::NewLine)
    $global:LASTEXITCODE = 0
    if ($Tool -eq $env:FAIL_TOOL -and
        ($CommandArguments -join " ") -like $env:FAIL_ARGUMENTS) {
        $global:LASTEXITCODE = 7
    }
}
function global:python { Invoke-FakeTool "python" $args }
function global:pnpm.cmd { Invoke-FakeTool "pnpm" $args }
function global:node.exe { Invoke-FakeTool "node" $args }
$options = @{}
$properties = Get-Content -Raw -LiteralPath $env:CHECK_OPTIONS | ConvertFrom-Json
foreach ($property in $properties.PSObject.Properties) {
    $options[$property.Name] = $property.Value
}
$failed = $false
try {
    & $env:CHECK_ENTRY @options
} catch {
    $failed = $true
    Write-Host $_
} finally {
    @{
        coverage = $env:COVERAGE_FILE
        coverage_exists = Test-Path Env:COVERAGE_FILE
        edition = $env:WATCHED_KETTLE_EDITION
        location = (Get-Location).Path
    } | ConvertTo-Json | Set-Content -LiteralPath $env:CHECK_FINAL -Encoding UTF8
}
if ($failed) { exit 1 }
exit 0
"""


def commands(calls: list[dict], tool: str, *prefix: str) -> list[dict]:
    return [
        call
        for call in calls
        if call["tool"] == tool and call["arguments"][: len(prefix)] == list(prefix)
    ]


@unittest.skipUnless(os.name == "nt", "Windows PowerShell entry points")
class CheckCommandTests(unittest.TestCase):
    def run_check(self, *, entry="check.ps1", options=None, fail=None, coverage=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scripts = root / "scripts"
            scripts.mkdir()
            caller = root / "caller"
            caller.mkdir()
            for name in ("check.ps1", "report_quality.ps1", "python_version.py"):
                shutil.copy2(ROOT / "scripts" / name, scripts / name)
            # Even the -Full contract test cannot invoke real packaging.
            (scripts / "build_windows.ps1").write_text(
                "param([string]$Profile, [switch]$SkipTests)\n"
                'Invoke-FakeTool "package" @($Profile, [string]$SkipTests)\n',
                encoding="utf-8",
            )
            driver = root / "driver.ps1"
            driver.write_text(DRIVER, encoding="utf-8")
            option_file = root / "options.json"
            option_file.write_text(json.dumps(options or {}), encoding="utf-8")
            trace = root / "trace.jsonl"
            final = root / "final.json"
            env = {
                **os.environ,
                "CHECK_ENTRY": str(scripts / entry),
                "CHECK_OPTIONS": str(option_file),
                "CHECK_TRACE": str(trace),
                "CHECK_FINAL": str(final),
                "FAIL_TOOL": fail[0] if fail else "",
                "FAIL_ARGUMENTS": fail[1] if fail else "",
                "WATCHED_KETTLE_EDITION": "caller-edition",
            }
            if coverage is None:
                env.pop("COVERAGE_FILE", None)
            else:
                env["COVERAGE_FILE"] = coverage
            result = subprocess.run(
                [
                    shutil.which("pwsh") or "powershell.exe",
                    "-NoProfile",
                    "-File",
                    str(driver),
                ],
                cwd=caller,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            calls = (
                [
                    json.loads(line)
                    for line in trace.read_text(encoding="utf-8").splitlines()
                ]
                if trace.exists()
                else []
            )
            state = json.loads(final.read_text(encoding="utf-8-sig"))
            # CI's temp folder can be a short 8.3 name (RUNNER~1) that
            # PowerShell reports in its long form; compare the real folders.
            self.assertEqual(
                Path(state["location"]).resolve(),
                caller.resolve(),
                result.stdout + result.stderr,
            )
            self.assertEqual(state["edition"], "caller-edition")
            return result, calls, state

    def assert_common(self, calls):
        self.assertEqual(len(commands(calls, "node", "--test")), 1)
        self.assertEqual(
            commands(calls, "node", "--test")[0]["arguments"],
            [
                "--test",
                "settings-ui/scripts/appearance.test.cjs",
                "settings-ui/scripts/protocol.test.cjs",
                "settings-ui/scripts/localization.test.cjs",
                "settings-ui/scripts/localization-literals.test.cjs",
            ],
        )
        self.assertEqual(
            len(commands(calls, "python", "-m", "scripts.localization_guard", "check")),
            1,
        )
        self.assertEqual(
            len(commands(calls, "pnpm", "--dir", "settings-ui", "run", "check")), 1
        )
        builds = commands(
            calls, "pnpm", "--dir", "settings-ui", "exec", "vite", "build"
        )
        self.assertEqual(
            [call["edition"] for call in builds], ["pet-only", "pet-assistant"]
        )
        strict = [
            call
            for call in commands(calls, "python", "-m", "mypy")
            if "--follow-imports=silent" in call["arguments"]
        ]
        self.assertEqual(len(strict), 1)
        self.assertEqual(set(strict[0]["arguments"][2:-1]), BOUNDARIES)
        self.assertEqual(strict[0]["arguments"][-1], "--follow-imports=silent")

    def assert_language_qa(self, calls):
        # Each English QA run drives the settings build made just before it.
        qa = commands(calls, "node", "settings-ui/scripts/language-qa.cjs")
        self.assertEqual(
            [(call["arguments"][1:], call["edition"]) for call in qa],
            [
                (["pet-only", "en"], "pet-only"),
                (["pet-assistant", "en"], "pet-assistant"),
            ],
        )
        builds = commands(
            calls, "pnpm", "--dir", "settings-ui", "exec", "vite", "build"
        )
        self.assertEqual(
            [calls.index(call) for call in builds],
            [calls.index(call) - 1 for call in qa],
        )

    def test_normal_runs_tests_and_common_checks_once(self):
        result, calls, _ = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_common(calls)
        self.assertEqual(
            len(commands(calls, "python", "-m", "unittest", "discover")), 1
        )
        self.assertFalse(commands(calls, "python", "-m", "coverage"))
        self.assertFalse(commands(calls, "package"))
        self.assertFalse(commands(calls, "node", "settings-ui/scripts/language-qa.cjs"))

    def test_quality_substitutes_verbose_coverage_tests_and_restores_environment(self):
        result, calls, state = self.run_check(
            options={"Quality": True}, coverage="caller.coverage"
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_common(calls)
        self.assertFalse(commands(calls, "python", "-m", "unittest"))
        runs = commands(calls, "python", "-m", "coverage", "run")
        self.assertEqual(len(runs), 1)
        self.assertEqual(
            runs[0]["arguments"][4:],
            ["unittest", "discover", "-s", "tests", "-t", ".", "-v"],
        )
        self.assertNotEqual(runs[0]["coverage"], "caller.coverage")
        erase = commands(calls, "python", "-m", "coverage", "erase")
        self.assertEqual(len(erase), 1)
        self.assertLess(calls.index(erase[0]), calls.index(runs[0]))
        self.assertEqual(
            len(commands(calls, "python", "-m", "scripts.coverage_gate")), 1
        )
        self.assertEqual(len(commands(calls, "python", "-m", "pip_audit")), 1)
        self.assertEqual(state["coverage"], "caller.coverage")
        self.assertFalse(commands(calls, "package"))

    def test_docs_only_uses_lightweight_checks(self):
        result, calls, _ = self.run_check(options={"DocsOnly": True})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(commands(calls, "node"))
        self.assertFalse(commands(calls, "pnpm"))
        self.assertFalse(commands(calls, "python", "-m", "mypy"))
        tests = commands(calls, "python", "-m", "unittest")
        self.assertEqual(len(tests), 1)
        self.assertEqual(
            tests[0]["arguments"][2:], ["tests.test_bubble_architecture", "-v"]
        )

    def test_incompatible_options_fail_before_external_commands(self):
        for extra in ("Quality", "Full", "LanguageQa"):
            with self.subTest(extra=extra):
                result, calls, _ = self.run_check(
                    options={"DocsOnly": True, extra: True}
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(calls)

    def test_common_check_failures_stop_quality_tests(self):
        for fail in (
            ("python", "-m mypy *--follow-imports=silent"),
            ("pnpm", "--dir settings-ui run check"),
            ("pnpm", "--dir settings-ui exec vite build"),
        ):
            with self.subTest(fail=fail):
                result, calls, _ = self.run_check(options={"Quality": True}, fail=fail)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(commands(calls, "python", "-m", "coverage"))
                self.assertFalse(commands(calls, "package"))

    def test_normal_test_failure_is_required(self):
        result, _, _ = self.run_check(fail=("python", "-m unittest discover *"))
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("All required checks passed.", result.stdout)

    def test_quality_failures_propagate_restore_environment_and_stop_packaging(self):
        for module, suffix in (
            ("coverage", "run *"),
            ("scripts.coverage_gate", "*"),
            ("pip_audit", "*"),
        ):
            with self.subTest(module=module):
                result, calls, state = self.run_check(
                    options={"Quality": True, "Full": True},
                    fail=("python", f"-m {module} {suffix}"),
                    coverage="caller.coverage",
                )
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(state["coverage"], "caller.coverage")
                self.assertFalse(commands(calls, "package"))
                if module == "coverage":
                    self.assertFalse(
                        commands(calls, "python", "-m", "scripts.coverage_gate")
                    )
                if module != "pip_audit":
                    self.assertFalse(commands(calls, "python", "-m", "pip_audit"))

    def test_advisory_failure_does_not_weaken_other_gates(self):
        result, calls, state = self.run_check(
            options={"Quality": True}, fail=("python", "-m mypy")
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(commands(calls, "python", "-m", "pip_audit")), 1)
        self.assertFalse(state["coverage_exists"])

    def test_quality_report_is_independent(self):
        result, calls, state = self.run_check(entry="report_quality.ps1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(commands(calls, "node"))
        self.assertFalse(commands(calls, "pnpm"))
        self.assertEqual(len(commands(calls, "python", "-m", "coverage", "run")), 1)
        self.assertFalse(state["coverage_exists"])

    def test_full_retains_packaging_after_quality_checks(self):
        result, calls, _ = self.run_check(
            options={"Full": True, "Quality": True, "BuildProfile": "Public"}
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(commands(calls, "python", "-m", "coverage", "run")), 1)
        self.assertEqual(
            [call["arguments"] for call in commands(calls, "package")],
            [["Public", "True"]],
        )
        self.assert_language_qa(calls)

    def test_language_qa_runs_english_qa_without_packaging(self):
        result, calls, _ = self.run_check(options={"LanguageQa": True})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_common(calls)
        self.assert_language_qa(calls)
        self.assertFalse(commands(calls, "package"))

    def test_language_qa_failure_stops_the_check(self):
        result, calls, state = self.run_check(
            options={"LanguageQa": True},
            fail=("node", "settings-ui/scripts/language-qa.cjs pet-only*"),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(state["edition"], "caller-edition")
        self.assertFalse(commands(calls, "python", "-m", "unittest"))

    def test_quality_workflows_run_english_qa_in_every_branch(self):
        for path in (
            ROOT / ".github/workflows/quality.yml",
            ROOT / "docs/public/quality.yml",
        ):
            if not path.exists():
                continue  # Public snapshots contain only the installed workflow.
            with self.subTest(workflow=path):
                text = path.read_text(encoding="utf-8")
                self.assertIn("electron/install.js", text)
                runs = re.findall(r"\\scripts\\check\.ps1([^\n]*)", text)
                gated = [args for args in runs if "-DocsOnly" not in args]
                self.assertEqual(len(gated), 2)
                self.assertTrue(all("-LanguageQa" in args for args in gated))


def upload_enabled(condition: str, *, quality: bool, successful: bool) -> bool:
    # GitHub implicitly requires success() unless a status function overrides it.
    if "always()" not in condition and not successful:
        return False
    expression = condition.strip().removeprefix("${{").removesuffix("}}").strip()
    expression = expression.replace("always()", "True").replace("&&", " and ")
    expression = expression.replace(
        "steps.changes.outputs.run_quality", repr(str(quality).lower())
    )
    tree = ast.parse(expression, mode="eval")
    allowed = (ast.Expression, ast.BoolOp, ast.And, ast.Compare, ast.Eq, ast.Constant)
    if any(not isinstance(node, allowed) for node in ast.walk(tree)):
        raise ValueError(f"Unsupported artifact condition: {condition}")
    return eval(compile(tree, "<artifact condition>", "eval"), {"__builtins__": {}}, {})


class QualityArtifactTests(unittest.TestCase):
    def test_quality_reports_upload_on_success_and_failure_only_for_quality(self):
        paths = (
            ROOT / ".github/workflows/quality.yml",
            ROOT / "docs/public/quality.yml",
        )
        for path in paths:
            if not path.exists():
                continue  # Public snapshots contain only the installed workflow.
            with self.subTest(workflow=path):
                match = re.search(
                    r"uses: actions/upload-artifact@[^\n]+\n\s+if: ([^\n]+)",
                    path.read_text(encoding="utf-8"),
                )
                self.assertIsNotNone(match)
                for quality in (False, True):
                    for successful in (False, True):
                        self.assertEqual(
                            upload_enabled(
                                match[1], quality=quality, successful=successful
                            ),
                            quality,
                        )


if __name__ == "__main__":
    unittest.main()
