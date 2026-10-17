"""Event-wide CI routing, including conservative failure behavior."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.ci_changes import classify_paths, main, plan_event
from scripts.python_version import runtime_errors


class ChangeClassificationTests(unittest.TestCase):
    def test_only_root_and_documentation_markdown_use_light_checks(self):
        plan = classify_paths(["README.md", "ROADMAP.md", "docs/a/note.md"])
        self.assertTrue(plan.docs_only)
        self.assertFalse(plan.run_quality)
        for name in (
            "tests/README.md",
            "docs/public/quality.yml",
            "docs/example.py",
            "docs/picture.svg",
            "watched_kettle/app.py",
        ):
            with self.subTest(name=name):
                self.assertFalse(classify_paths(["README.md", name]).docs_only)

    def test_dependencies_request_quality_reports(self):
        for name in (
            "requirements.txt",
            "requirements-dev.txt",
            "requirements-build.txt",
            "pyproject.toml",
            "settings-ui/package.json",
            "settings-ui/pnpm-lock.yaml",
            "pnpm-workspace.yaml",
        ):
            with self.subTest(name=name):
                plan = classify_paths([name])
                self.assertFalse(plan.docs_only)
                self.assertTrue(plan.run_quality)
        self.assertFalse(classify_paths(["watched_kettle/app.py"]).run_quality)

    def test_check_logic_changes_request_quality_validation(self):
        for name in (
            "scripts/check.ps1",
            "scripts/report_quality.ps1",
            "scripts/ci_changes.py",
            "scripts/coverage_gate.py",
            "scripts/python_version.py",
            ".github/workflows/quality.yml",
            ".github/workflows/package.yml",
            "docs/public/quality.yml",
        ):
            with self.subTest(name=name):
                plan = classify_paths([name])
                self.assertFalse(plan.docs_only)
                self.assertTrue(plan.run_quality)

    def test_missing_or_unrecognized_paths_request_full_validation(self):
        for paths in ([], ["../README.md"], ["/README.md"], ["docs\\README.md"]):
            with self.subTest(paths=paths):
                plan = classify_paths(paths)
                self.assertFalse(plan.docs_only)
                self.assertTrue(plan.run_quality)

    def test_manual_full_input_and_default(self):
        for full in (True, "true"):
            self.assertTrue(
                plan_event(
                    "workflow_dispatch", {"inputs": {"full": full}}, Path(".")
                ).run_quality
            )
        for event in ({}, {"inputs": {"full": False}}, {"inputs": {"full": "false"}}):
            plan = plan_event("workflow_dispatch", event, Path("."))
            self.assertFalse(plan.docs_only)
            self.assertFalse(plan.run_quality)

    def test_unavailable_base_and_malformed_event_do_not_skip_checks(self):
        events = [
            ("push", {"before": "0" * 40, "after": "a" * 40}),
            ("push", {"before": "--help", "after": "a" * 40}),
            ("pull_request", {}),
            ("pull_request", {"pull_request": None}),
            ("workflow_dispatch", {"inputs": []}),
            ("push", []),
            ("unknown", {}),
        ]
        for name, event in events:
            with self.subTest(event=event):
                plan = plan_event(name, event, Path("."))
                self.assertFalse(plan.docs_only)
                self.assertTrue(plan.run_quality)
        with patch(
            "scripts.ci_changes.subprocess.run",
            side_effect=subprocess.TimeoutExpired("git", 30),
        ):
            self.assertTrue(
                plan_event(
                    "push", {"before": "a" * 40, "after": "b" * 40}, Path(".")
                ).run_quality
            )

    def test_event_outputs_use_github_boolean_strings_and_append(self):
        with TemporaryDirectory() as directory:
            event = Path(directory) / "event.json"
            output = Path(directory) / "output"
            event.write_text(json.dumps({"inputs": {"full": True}}), encoding="utf-8")
            output.write_text("existing=value\n", encoding="utf-8")
            with patch.dict(
                os.environ,
                GITHUB_EVENT_PATH=str(event),
                GITHUB_OUTPUT=str(output),
                GITHUB_EVENT_NAME="workflow_dispatch",
            ):
                self.assertEqual(main(), 0)
            self.assertEqual(
                output.read_text(encoding="utf-8"),
                "existing=value\ndocs_only=false\nrun_quality=true\n",
            )


class GitEventDiffTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.git("init", "-b", "main")
        self.git("config", "user.name", "CI routing test")
        self.git("config", "user.email", "ci@example.invalid")
        self.write("README.md")
        self.write("watched_kettle/app.py")
        self.commit()
        self.base = self.git("rev-parse", "HEAD").strip()

    def git(self, *args):
        return subprocess.run(
            ["git", *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        ).stdout

    def write(self, name):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("test\n", encoding="utf-8")

    def commit(self):
        self.git("add", ".")
        self.git("commit", "-m", "test change")
        return self.git("rev-parse", "HEAD").strip()

    def push_plan(self, head):
        return plan_event("push", {"before": self.base, "after": head}, self.root)

    def test_push_checks_all_commits_not_just_last_commit(self):
        self.write("watched_kettle/other.py")
        self.commit()
        self.write("ROADMAP.md")
        self.assertFalse(self.push_plan(self.commit()).docs_only)

    def test_pull_request_uses_whole_branch_diff(self):
        self.git("switch", "-c", "feature")
        self.write("requirements-new.txt")
        self.commit()
        self.write("ROADMAP.md")
        head = self.commit()
        plan = plan_event(
            "pull_request",
            {"pull_request": {"base": {"sha": self.base}, "head": {"sha": head}}},
            self.root,
        )
        self.assertTrue(plan.run_quality)
        self.assertFalse(plan.docs_only)

    def test_deletion_and_rename_keep_old_code_path_in_diff(self):
        (self.root / "docs").mkdir()
        self.git("mv", "watched_kettle/app.py", "docs/app.md")
        self.assertFalse(self.push_plan(self.commit()).docs_only)
        self.base = self.git("rev-parse", "HEAD").strip()
        self.git("rm", "docs/app.md")
        self.assertTrue(self.push_plan(self.commit()).docs_only)

    def test_deleted_code_and_unavailable_git_object(self):
        self.git("rm", "watched_kettle/app.py")
        self.assertFalse(self.push_plan(self.commit()).docs_only)
        plan = plan_event("push", {"before": "f" * 40, "after": self.base}, self.root)
        self.assertFalse(plan.docs_only)
        self.assertTrue(plan.run_quality)


class PythonRuntimeTests(unittest.TestCase):
    def test_only_standard_cpython_314_x64_is_accepted(self):
        self.assertEqual(runtime_errors((3, 14, 8), "CPython", 64, False), [])
        for version, implementation, bits, threaded in (
            ((3, 12, 0), "CPython", 64, False),
            ((3, 13, 0), "CPython", 64, False),
            ((3, 15, 0), "CPython", 64, False),
            ((3, 14, 8), "PyPy", 64, False),
            ((3, 14, 8), "CPython", 32, False),
            ((3, 14, 8), "CPython", 64, True),
        ):
            with self.subTest(
                version=version,
                implementation=implementation,
                bits=bits,
                threaded=threaded,
            ):
                self.assertTrue(runtime_errors(version, implementation, bits, threaded))


class DocumentationCommandTests(unittest.TestCase):
    def run_docs_check(self, validator="print('structure checked')", *options):
        if os.name != "nt":
            self.skipTest("Windows PowerShell entrypoint")
        with TemporaryDirectory() as directory:
            root = Path(directory)
            scripts = root / "scripts"
            scripts.mkdir()
            source = Path(__file__).resolve().parents[1] / "scripts"
            for name in ("check.ps1", "python_version.py"):
                shutil.copyfile(source / name, scripts / name)
            (scripts / "__init__.py").touch()
            (scripts / "validate_project.py").write_text(validator, encoding="utf-8")
            tests = root / "tests"
            tests.mkdir()
            (tests / "__init__.py").touch()
            (tests / "test_bubble_architecture.py").write_text(
                "import unittest\nclass Boundary(unittest.TestCase):\n"
                "    def test_boundary(self): self.assertTrue(True)\n",
                encoding="utf-8",
            )
            env = dict(os.environ)
            env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env["PATH"]
            return subprocess.run(
                [
                    shutil.which("pwsh") or "powershell.exe",
                    "-NoProfile",
                    "-File",
                    str(scripts / "check.ps1"),
                    "-DocsOnly",
                    *options,
                ],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )

    def test_docs_mode_skips_external_tools_and_accepts_valid_structure(self):
        result = self.run_docs_check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Documentation and structure checks passed.", result.stdout)
        self.assertNotIn("Ruff", result.stdout)
        self.assertNotIn("Settings UI", result.stdout)

    def test_docs_mode_propagates_validation_failure(self):
        result = self.run_docs_check("raise SystemExit(7)")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Documentation and structure checks passed.", result.stdout)

    def test_docs_and_package_modes_cannot_be_combined(self):
        result = self.run_docs_check("print('must not run')", "-Full")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("must not run", result.stdout)

    def test_docs_and_quality_modes_cannot_be_combined(self):
        result = self.run_docs_check("print('must not run')", "-Quality")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("must not run", result.stdout)
