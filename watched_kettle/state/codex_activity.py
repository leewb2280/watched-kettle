"""Content-free Codex evidence shared by collection and state owners."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CodexTurnTarget:
    thread_id: str
    turn_id: str
    version: int
    generation: int
    ended: bool = False


@dataclass(frozen=True)
class CodexTurnOutcome:
    target: CodexTurnTarget
    state: str
    reason: str = "unknown"


@dataclass(frozen=True)
class CodexActivityObservation:
    thread_id: str
    turn_id: str
    version: int
    state: str
    uncertain: bool
    last_confirmed_at: float
    scope: str
