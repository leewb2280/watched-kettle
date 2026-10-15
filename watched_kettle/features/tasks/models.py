"""Immutable review contracts. A candidate never carries execution authority."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import hashlib
import json


class TaskState(str, Enum):
    DRAFT = "draft"
    QUEUED = "queued"
    STARTING = "starting"
    RUNNING = "running"
    RECONCILING = "reconciling"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"
    STOPPED = "stopped"
    COMPLETE = "complete"


class CheckKind(str, Enum):
    MANUAL = "manual"
    COMMAND = "command"
    ARTIFACT = "artifact"


@dataclass(frozen=True)
class CompletionCheck:
    description: str
    kind: CheckKind = CheckKind.MANUAL
    target: str = ""


@dataclass(frozen=True)
class TaskSpec:
    title: str
    instruction: str
    project_id: str
    thread_id: str
    cwd: str
    source_version: str
    source_refs: tuple[str, ...] = ()
    scope: str = ""
    exclusions: str = ""
    prerequisites: str = ""
    checks: tuple[CompletionCheck, ...] = ()
    source_candidate: str = ""

    def validate(self, *, execution: bool = False) -> None:
        if not self.title.strip() or not self.instruction.strip():
            raise ValueError("task_text_required")
        if len(self.instruction) > 32_000 or len(self.title) > 240:
            raise ValueError("task_text_too_large")
        if execution:
            if not self.thread_id or not self.cwd or not self.source_version:
                raise ValueError("execution_target_required")
            if not self.checks:
                raise ValueError("completion_check_required")
            for check in self.checks:
                if not check.description.strip():
                    raise ValueError("completion_description_required")
                if check.kind != CheckKind.MANUAL and not check.target.strip():
                    raise ValueError("completion_target_required")

    def to_dict(self) -> dict:
        return asdict(self)

    def execution_prompt(self) -> str:
        """All reviewed boundaries are part of the exact message sent to Codex."""
        parts = [self.instruction]
        for label, value in (
            ("작업 범위", self.scope),
            ("제외 범위", self.exclusions),
            ("선행 조건", self.prerequisites),
        ):
            if value.strip():
                parts.append(f"{label}:\n{value}")
        if self.checks:
            checks = []
            for check in self.checks:
                text = check.description
                if check.target:
                    text += f" ({check.kind.value}: {check.target})"
                checks.append("- " + text)
            parts.append("완료 조건:\n" + "\n".join(checks))
        return "\n\n".join(parts)

    @classmethod
    def from_dict(cls, value: dict) -> TaskSpec:
        data = dict(value)
        data["source_refs"] = tuple(data.get("source_refs", ()))
        data["checks"] = tuple(
            CompletionCheck(
                description=c["description"],
                kind=CheckKind(c.get("kind", "manual")),
                target=c.get("target", ""),
            )
            for c in data.get("checks", ())
        )
        spec = cls(**data)
        spec.validate()
        return spec


@dataclass(frozen=True)
class Candidate:
    spec: TaskSpec
    reason: str
    evidence: str
    confirmed_plan: bool = False
    reported_complete: bool = False


@dataclass(frozen=True)
class ReviewItem:
    id: str
    state: TaskState
    revision: int
    spec: TaskSpec | None = field(repr=False)
    reason: str = ""
    batch_id: str = ""
    position: int = 0
    attempt_id: str = ""
    summary: dict = field(default_factory=dict, repr=False)


class SourceVersion:
    """Same digest for full and paginated history, without retaining the history."""

    def __init__(self):
        self.digest = hashlib.sha256()

    def add(self, value):
        data = json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        self.digest.update(str(len(data)).encode() + b":" + data)

    def turn(self, turn):
        self.add(["turn", turn.get("id"), turn.get("status")])

    def item(self, item):
        self.add(["item", item])

    def value(self):
        return "v2:" + self.digest.hexdigest()


def source_version(turns: list[dict]) -> str:
    version = SourceVersion()
    for turn in turns:
        version.turn(turn)
        for item in turn.get("items", []):
            version.item(item)
    return version.value()
