"""Content-free, conservative per-turn measurements from Codex rollouts."""

from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from datetime import datetime, timezone

from watched_kettle.state.agent_scope import scope_from_session_source
from watched_kettle.usage.device import nonnegative


COUNTERS = ("total_tokens", "input_tokens", "cached_input_tokens", "output_tokens")


def _timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return result.astimezone(timezone.utc) if result.tzinfo else None


def _counters(info):
    usage = info.get("total_token_usage") if isinstance(info, dict) else None
    if not isinstance(usage, dict):
        return None
    return {key: nonnegative(usage.get(key)) for key in COUNTERS}


@dataclass(frozen=True)
class TurnUsageEvidence:
    thread_id: str
    turn_id: str
    completed_at: datetime
    total_tokens: int
    input_tokens: int | None
    cached_input_tokens: int | None
    output_tokens: int | None
    model: str | None
    reasoning_effort: str | None
    partial: bool


class TurnLogParser:
    """Consume one complete rollout in order without retaining its content."""

    def __init__(self, file_session_id):
        self.file_session_id = file_session_id
        self.thread_id = ""
        self.trusted = False
        self.header_seen = False
        self.previous = None
        self.active = None
        self.failures = {}
        self.initial_zero = False
        self._file_offset = 0

    def invalidate(self, reason="log_damaged"):
        """Lose this segment's baseline, not the identity of later turns."""
        if self.active is not None:
            self.active["invalid"] = reason
        self.previous = None
        self.initial_zero = False

    def inherit(self, previous):
        self.previous = deepcopy(previous.previous)
        self.active = deepcopy(previous.active)
        self.initial_zero = previous.initial_zero

    def _failure(self, turn_id, reason):
        self.failures[turn_id] = reason
        while len(self.failures) > 1024:
            self.failures.pop(next(iter(self.failures)))

    def feed(self, record):
        if not isinstance(record, dict):
            return None
        kind = record.get("type")
        payload = record.get("payload")
        if not isinstance(payload, dict):
            return None
        if kind == "session_meta":
            if self.header_seen:
                # A second header can be copied history from another owner.
                self.invalidate("owner_mismatch")
                self.trusted = False
                return None
            self.header_seen = True
            owner = payload.get("id")
            self.trusted = (
                isinstance(owner, str)
                and bool(owner)
                and payload.get("session_id", owner) == owner
                and not payload.get("parent_thread_id")
                and payload.get("subagent_history_start_ordinal") is None
                and scope_from_session_source(payload.get("source"))
                not in {"subagent", "internal"}
            )
            if self.trusted and isinstance(owner, str):
                self.thread_id = owner
                self.initial_zero = owner == self.file_session_id and not payload.get(
                    "history_base"
                )
            return None
        if not self.trusted:
            return None
        if kind == "turn_context" and self.active is not None:
            if payload.get("turn_id") == self.active["id"]:
                model = payload.get("model")
                effort = payload.get("effort")
                if isinstance(model, str) and model:
                    self.active["models"].add(model[:160])
                if isinstance(effort, str) and effort:
                    self.active["efforts"].add(effort[:80])
            return None
        if kind != "event_msg":
            return None
        event = payload.get("type")
        if event == "task_started":
            turn_id = payload.get("turn_id")
            if not isinstance(turn_id, str) or not turn_id:
                self.active = None
                return None
            if self.active is not None and self.active["id"] == turn_id[:160]:
                return None
            self.active = {
                "id": turn_id[:160],
                "baseline": self.previous.copy()
                if self.previous is not None
                else {key: 0 if self.initial_zero else None for key in COUNTERS},
                "last": None,
                "count": 0,
                "invalid": False,
                "models": set(),
                "efforts": set(),
            }
            self.initial_zero = False
            return None
        if event == "token_count":
            current = _counters(payload.get("info"))
            if current is None or current["total_tokens"] is None:
                self.invalidate("token_baseline_missing")
                return None
            if self.previous is not None and any(
                current[key] is not None
                and self.previous[key] is not None
                and current[key] < self.previous[key]
                for key in COUNTERS
            ):
                self.invalidate("counter_regressed")
            self.previous = current
            if self.active is not None:
                self.active["last"] = current
                self.active["count"] += 1
            return None
        if event != "task_complete":
            return None
        active = self.active
        if active is None or payload.get("turn_id") != active["id"]:
            if isinstance(payload.get("turn_id"), str):
                self._failure(payload["turn_id"], "turn_boundary_missing")
            return None
        self.active = None
        if active["invalid"] or not active["count"] or active["last"] is None:
            self._failure(active["id"], active["invalid"] or "token_baseline_missing")
            return None
        completed = _timestamp(payload.get("completed_at")) or _timestamp(
            record.get("timestamp")
        )
        if completed is None:
            return None
        deltas = {}
        for key in COUNTERS:
            before, after = active["baseline"][key], active["last"][key]
            deltas[key] = (
                after - before
                if before is not None and after is not None and after >= before
                else None
            )
        if deltas["total_tokens"] is None:
            self._failure(active["id"], "token_baseline_missing")
            return None
        models, efforts = active["models"], active["efforts"]
        return TurnUsageEvidence(
            self.thread_id,
            active["id"],
            completed,
            deltas["total_tokens"],
            deltas["input_tokens"],
            deltas["cached_input_tokens"],
            deltas["output_tokens"],
            next(iter(models)) if len(models) == 1 else "복수 모델" if models else None,
            next(iter(efforts)) if len(efforts) == 1 else None,
            any(deltas[key] is None for key in COUNTERS) or len(models) != 1,
        )
