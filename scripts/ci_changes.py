"""Classify the whole GitHub event diff without third-party dependencies."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import fnmatch
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess


@dataclass(frozen=True)
class ChangePlan:
    docs_only: bool
    run_quality: bool
    reason: str


def classify_paths(paths: list[str]) -> ChangePlan:
    if not paths:
        return ChangePlan(False, True, "No changed paths; run full validation")
    docs_only = True
    quality_required = False
    for name in paths:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name:
            return ChangePlan(False, True, "Unrecognized path; run full validation")
        markdown = path.suffix == ".md" and (
            len(path.parts) == 1 or path.parts[0] == "docs"
        )
        docs_only = docs_only and markdown
        quality_required = (
            quality_required
            or (len(path.parts) == 1 and fnmatch.fnmatchcase(name, "requirements*.txt"))
            or name
            in {
                "pyproject.toml",
                "pnpm-workspace.yaml",
                "settings-ui/package.json",
                "settings-ui/pnpm-lock.yaml",
                "scripts/check.ps1",
                "scripts/report_quality.ps1",
                "scripts/ci_changes.py",
                "scripts/coverage_gate.py",
                "scripts/python_version.py",
                "docs/public/quality.yml",
            }
            or name.startswith(".github/workflows/")
        )
    return ChangePlan(docs_only, quality_required, "Classified complete event diff")


def _sha(value) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", value):
        raise ValueError("Missing or invalid commit SHA")
    if set(value) == {"0"}:
        raise ValueError("No previous commit")
    return value


def plan_event(event_name: str, event: dict, root: Path) -> ChangePlan:
    if not isinstance(event, dict):
        return ChangePlan(False, True, "Invalid event; run full validation")
    if event_name == "workflow_dispatch":
        inputs = event.get("inputs", {})
        if not isinstance(inputs, dict):
            return ChangePlan(False, True, "Invalid manual inputs; run full validation")
        full = inputs.get("full", False)
        return ChangePlan(False, str(full).lower() == "true", "Manual validation")
    try:
        if event_name == "pull_request":
            pull = event["pull_request"]
            comparison = f"{_sha(pull['base']['sha'])}...{_sha(pull['head']['sha'])}"
        elif event_name == "push":
            comparison = f"{_sha(event['before'])}..{_sha(event['after'])}"
        else:
            raise ValueError("Unsupported event")
        result = subprocess.run(
            ["git", "diff", "--no-renames", "--name-only", "-z", comparison, "--"],
            cwd=root,
            capture_output=True,
            check=True,
            timeout=30,
        )
        paths = result.stdout.decode("utf-8").rstrip("\0").split("\0")
        return classify_paths([path for path in paths if path])
    except (KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError):
        return ChangePlan(False, True, "Diff unavailable; run full validation")


def main() -> int:
    try:
        event = json.loads(
            Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8")
        )
        plan = plan_event(os.environ.get("GITHUB_EVENT_NAME", ""), event, Path.cwd())
    except (KeyError, OSError, ValueError, TypeError):
        plan = ChangePlan(False, True, "Event unavailable; run full validation")
    print(json.dumps(asdict(plan)))
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        output.write(f"docs_only={str(plan.docs_only).lower()}\n")
        output.write(f"run_quality={str(plan.run_quality).lower()}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
