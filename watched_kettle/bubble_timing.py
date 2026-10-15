"""Shared duration policy for transient bubbles; active work has no deadline."""

from dataclasses import dataclass, replace


DURATION_KINDS = ("result", "general", "schedule", "completion")


def normalize_duration(value: object) -> int:
    try:
        seconds = int(str(value))
    except (ValueError, TypeError):
        seconds = 8
    return min(60, max(5, seconds))


@dataclass(frozen=True)
class BubbleDurationPolicy:
    common: int = 8
    result: int | None = None
    general: int | None = None
    schedule: int | None = None
    completion: int | None = None

    def seconds(self, kind: str) -> int:
        if kind not in DURATION_KINDS:
            raise ValueError(kind)
        value = getattr(self, kind)
        if kind == "completion":
            return normalize_duration(15 if value is None else value)
        return normalize_duration(self.common if value is None else value)

    def with_override(self, kind: str, value: int | None) -> "BubbleDurationPolicy":
        if kind not in DURATION_KINDS:
            raise ValueError(kind)
        normalized = None if value is None else normalize_duration(value)
        if kind == "completion":
            return replace(self, completion=normalized)
        if kind == "result":
            return replace(self, result=normalized)
        if kind == "general":
            return replace(self, general=normalized)
        return replace(self, schedule=normalized)
