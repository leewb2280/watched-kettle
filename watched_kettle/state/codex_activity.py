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
    usage_resumes_at: float = 0


@dataclass(frozen=True)
class CodexActivityObservation:
    thread_id: str
    turn_id: str
    version: int
    state: str
    uncertain: bool
    last_confirmed_at: float
    scope: str


@dataclass(frozen=True)
class CodexLiveToolStart:
    """Internal proof from a new call in the collector's current live turn."""

    thread_id: str
    turn_id: str
    call_id: str
    recorded_at: float
