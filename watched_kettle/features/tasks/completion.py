"""Evaluate registered conditions against an identified terminal turn."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from watched_kettle.features.tasks.models import CheckKind, TaskSpec


class Verdict(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CompletionResult:
    verdict: Verdict
    reasons: tuple[str, ...]


def verify_artifacts(spec: TaskSpec) -> dict[str, bool]:
    """Only test existence of reviewed relative files within the execution root."""
    results: dict[str, bool] = {}
    try:
        root = Path(spec.cwd).resolve(strict=True)
    except OSError:
        return results
    for check in spec.checks:
        if check.kind != CheckKind.ARTIFACT:
            continue
        relative = Path(check.target)
        if relative.is_absolute() or ".." in relative.parts:
            continue
        try:
            target = (root / relative).resolve()
            if not target.is_relative_to(root):
                continue
            results[check.target] = target.is_file()
        except OSError:
            continue
    return results


def evaluate_completion(
    spec: TaskSpec,
    turn: dict,
    expected_turn_id: str,
    *,
    manual_confirmed: bool = False,
    artifact_results: dict[str, bool] | None = None,
) -> CompletionResult:
    if not expected_turn_id or turn.get("id") != expected_turn_id:
        return CompletionResult(Verdict.UNKNOWN, ("turn_identity_unknown",))
    status = turn.get("status")
    if status in {"failed", "interrupted"}:
        return CompletionResult(Verdict.FAILED, ("turn_" + status,))
    if status != "completed":
        return CompletionResult(Verdict.UNKNOWN, ("turn_not_terminal",))
    if not spec.checks:
        return CompletionResult(Verdict.UNKNOWN, ("completion_check_required",))
    failed, unknown = [], []
    items = turn.get("items", [])
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        return CompletionResult(Verdict.UNKNOWN, ("completion_evidence_invalid",))
    for check in spec.checks:
        if check.kind == CheckKind.MANUAL:
            if not manual_confirmed:
                unknown.append("manual_confirmation_required")
        elif check.kind == CheckKind.COMMAND:
            matches = [
                item
                for item in items
                if item.get("type") == "commandExecution"
                and item.get("command") == check.target
                and item.get("cwd") == spec.cwd
            ]
            if (
                not matches
                or matches[-1].get("status") != "completed"
                or type(matches[-1].get("exitCode")) is not int
            ):
                unknown.append("command_evidence_missing")
            elif matches[-1]["exitCode"] != 0:
                failed.append("command_failed")
        elif check.kind == CheckKind.ARTIFACT:
            # Only the explicit local verifier may supply this mapping, never model text.
            result = (artifact_results or {}).get(check.target)
            if result is None:
                unknown.append("artifact_evidence_missing")
            elif not result:
                failed.append("artifact_check_failed")
    if failed:
        return CompletionResult(Verdict.FAILED, tuple(failed + unknown))
    if unknown:
        return CompletionResult(Verdict.UNKNOWN, tuple(unknown))
    return CompletionResult(Verdict.PASSED, ())
