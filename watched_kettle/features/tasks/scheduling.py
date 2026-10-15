"""Pure fair allocation policy; ambiguous state never grants a free slot."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess

from watched_kettle.features.tasks.models import ReviewItem, TaskState


@dataclass(frozen=True)
class ExecutionScope:
    """Fresh connection observation, supplied by a verified execution adapter."""

    reliable: bool
    active_main_tasks: int
    busy_lock_keys: frozenset[str] = frozenset()
    active_projects: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Allocation:
    task_id: str
    lock_keys: tuple[str, ...]


def resolve_lock_keys(cwd: str) -> tuple[str, ...]:
    """Resolve Windows aliases and git common dir; no guessed fallback on errors."""
    path = Path(cwd)
    if not path.is_absolute() or not path.is_dir():
        raise ValueError("execution_path_unavailable")
    real = path.resolve(strict=True)
    keys = ["path:" + os.path.normcase(str(real))]
    # A git repository can live above the chosen working directory.
    marker = next(
        (
            parent / ".git"
            for parent in (real, *real.parents)
            if (parent / ".git").exists()
        ),
        None,
    )
    if marker is not None:
        try:
            result = subprocess.run(
                [
                    "git",
                    "-C",
                    str(real),
                    "rev-parse",
                    "--path-format=absolute",
                    "--git-common-dir",
                ],
                capture_output=True,
                text=True,
                timeout=3,
                check=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            common = Path(result.stdout.strip()).resolve(strict=True)
        except (OSError, ValueError, subprocess.SubprocessError):
            raise ValueError("repository_identity_unavailable") from None
        keys.append("git:" + os.path.normcase(str(common)))
    return tuple(keys)


def allocate(
    items: tuple[ReviewItem, ...],
    enabled_batches: set[str],
    paused_projects: set[str],
    scope: ExecutionScope,
    *,
    limit: int = 2,
    last_served: dict[str, float] | None = None,
    lock_resolver=resolve_lock_keys,
) -> tuple[tuple[Allocation, ...], dict[str, str]]:
    if not 1 <= limit <= 4:
        raise ValueError("execution_limit_invalid")
    reasons = {}
    waiting = [
        i
        for i in items
        if i.state == TaskState.QUEUED and i.batch_id in enabled_batches
    ]
    if not scope.reliable:
        return (), {i.id: "execution_scope_unverified" for i in waiting}
    if scope.active_main_tasks < 0:
        raise ValueError("execution_scope_invalid")
    busy = set(scope.busy_lock_keys)
    slots = max(0, limit - scope.active_main_tasks)
    projects = set()
    result = []
    # Preserve each project's queue order, then give least recently served projects priority.
    heads: dict[str, ReviewItem] = {}
    for item in sorted(waiting, key=lambda i: i.position):
        if item.spec:
            heads.setdefault(item.spec.project_id or item.spec.cwd, item)
    for project, item in sorted(
        heads.items(), key=lambda pair: (last_served or {}).get(pair[0], 0)
    ):
        if item.spec is None:
            continue
        if project in paused_projects:
            reasons[item.id] = "project_paused"
            continue
        if project in scope.active_projects:
            reasons[item.id] = "project_busy"
            continue
        # Failed, interrupted or uncertain predecessors must not be silently skipped.
        blockers = [
            i
            for i in items
            if i.spec
            and (i.spec.project_id or i.spec.cwd) == project
            and i.id != item.id
            and i.state
            in {
                TaskState.STARTING,
                TaskState.RUNNING,
                TaskState.RECONCILING,
                TaskState.NEEDS_REVIEW,
                TaskState.FAILED,
                TaskState.STOPPED,
            }
        ]
        if blockers:
            reasons[item.id] = "previous_task_needs_attention"
            continue
        if slots <= 0:
            reasons[item.id] = "concurrency_limit"
            continue
        try:
            locks = lock_resolver(item.spec.cwd)
        except (ValueError, OSError):
            reasons[item.id] = "execution_path_unavailable"
            continue
        if busy.intersection(locks) or project in projects:
            reasons[item.id] = "repository_busy"
            continue
        result.append(Allocation(item.id, locks))
        busy.update(locks)
        projects.add(project)
        slots -= 1
    return tuple(result), reasons
