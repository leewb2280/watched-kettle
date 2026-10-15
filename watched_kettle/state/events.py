"""Normalize agent hook payloads into pet state decisions.

This module is a Python adaptation of the event normalization design from
yangbuyiya/desktop-pet. See THIRD_PARTY_NOTICES.md for attribution.
"""

from dataclasses import dataclass, replace

from watched_kettle.state.agent_scope import normalize_agent_scope
from watched_kettle.state.event_names import (  # noqa: F401 - re-exported API
    AGENT_SOURCES,
    EVENT_ALIASES,
    SOURCE_ALIASES,
    SOURCE_LABELS,
    URGENCY_ALIASES,
    approval_actor,
    normalize_agent_source,
    normalize_event_name,
    normalize_urgency,
    source_display_label,
)


REACTION_TO_STATE = {
    "idle": "idle",
    "thinking": "review",
    "working": "running",
    "editing": "running",
    "running": "running",
    "waiting": "waiting",
    "waving": "waving",
    "success": "jumping",
    "done": "jumping",
    "error": "failed",
    "failed": "failed",
    "celebrating": "jumping",
}


@dataclass(frozen=True)
class PetDecision:
    """A normalized state change for one agent session."""

    source: str
    event: str
    session_id: str
    persistent_state: str | None = None
    visual_state: str | None = None
    duration_ms: int = 0
    message: str = ""
    terminal: bool = False
    urgency: str = "normal"
    agent_scope: str = "main"
    event_id: str = ""
    approval_actor: str = "unknown"


def build_decision(payload):
    """Return a PetDecision for a supported payload, otherwise None."""
    decision = _build_decision(payload)
    if decision is None:
        return None
    scope = normalize_agent_scope(payload.get("agent_scope", "main"))
    raw_event = str(payload.get("hook_event_name") or payload.get("event") or "")
    raw_event = (
        raw_event.lower()
        .replace("_", "")
        .replace("-", "")
        .replace(".", "")
        .replace(" ", "")
    )
    if raw_event in {"subagentstart", "subagentstop"}:
        scope = "subagent"
        parent_id = payload.get("session_id") or "default"
        child_id = payload.get("agent_id") or f"{parent_id}:subagent"
        decision = replace(
            decision,
            session_id=_pick_session_id({"session_id": child_id}, decision.source),
        )
    event_id = (
        payload.get("event_id")
        or payload.get("tool_use_id")
        or payload.get("call_id")
        or ""
    )
    decision = replace(
        decision,
        agent_scope=scope,
        event_id=str(event_id)[:160],
        approval_actor=approval_actor(payload),
    )
    # Agent tool returns and compaction are still part of an active task.
    # Keep the review sprite available to manual and ambient animations.
    if decision.source in AGENT_SOURCES and decision.persistent_state == "review":
        decision = replace(
            decision,
            persistent_state="running",
            message=_default_message(decision.source, "running"),
        )
    return decision


def _build_decision(payload):
    if not isinstance(payload, dict):
        return None

    source = _pick_source(payload)
    event = _pick_event(payload)
    session_id = _pick_session_id(payload, source)
    reaction = str(payload.get("reaction") or "").strip().lower()

    if reaction in REACTION_TO_STATE:
        state = REACTION_TO_STATE[reaction]
        return PetDecision(
            source=source,
            event=reaction,
            session_id=session_id,
            persistent_state=state,
            message=_pick_message(payload, _default_message(source, state)),
        )

    if event in {"session_start", "task_start", "prompt"}:
        return PetDecision(
            source=source,
            event=event,
            session_id=session_id,
            persistent_state="running",
            message=_pick_message(payload, _default_message(source, "running")),
        )

    if event == "thinking":
        return PetDecision(
            source=source,
            event=event,
            session_id=session_id,
            persistent_state="review",
            message=_pick_message(payload, _default_message(source, "review")),
        )

    if event == "tool_start":
        return PetDecision(
            source=source,
            event=event,
            session_id=session_id,
            persistent_state="running",
            message=_pick_message(payload, _default_message(source, "running")),
        )

    if event in {"tool_end", "review"}:
        return PetDecision(
            source=source,
            event=event,
            session_id=session_id,
            persistent_state="review",
            message=_pick_message(payload, _default_message(source, "review")),
        )

    if event in {"permission", "permission_resolved"}:
        user_wait = event == "permission" and approval_actor(payload) == "user"
        return PetDecision(
            source=source,
            event=event,
            session_id=session_id,
            persistent_state="waiting" if user_wait else "running",
            message=_default_message(source, "waiting" if user_wait else "running"),
        )

    if event in {"waiting", "question_wait"}:
        return PetDecision(
            source=source,
            event=event,
            session_id=session_id,
            persistent_state="waiting",
            message=_pick_message(payload, _default_message(source, "waiting")),
        )

    if event == "question_resolved":
        return PetDecision(
            source=source,
            event=event,
            session_id=session_id,
            persistent_state="running",
            message=_default_message(source, "running"),
        )

    if event == "notification":
        return PetDecision(
            source=source,
            event=event,
            session_id=session_id,
            visual_state="waving",
            duration_ms=2_200,
            message=_pick_message(payload, _default_message(source, "waving")),
            urgency=normalize_urgency(
                payload.get("urgency") or payload.get("priority")
            ),
        )

    if event == "done":
        return PetDecision(
            source=source,
            event=event,
            session_id=session_id,
            visual_state="jumping",
            duration_ms=2_600,
            message=_pick_message(payload, _default_message(source, "jumping")),
            terminal=True,
        )

    if event == "cancelled":
        return PetDecision(
            source=source,
            event=event,
            session_id=session_id,
            visual_state="idle",
            message=_pick_message(payload, _default_message(source, "cancelled")),
            terminal=True,
        )

    if event == "tool_failed":
        # A failed agent tool call is routine; the agent keeps working.
        if source in AGENT_SOURCES:
            return PetDecision(
                source=source,
                event=event,
                session_id=session_id,
                persistent_state="running",
                message=_default_message(source, "running"),
            )
        return PetDecision(
            source=source,
            event=event,
            session_id=session_id,
            visual_state="failed",
            duration_ms=3_200,
            message=_pick_message(payload, _default_message(source, "failed")),
            terminal=False,
        )

    if event == "failed":
        return PetDecision(
            source=source,
            event=event,
            session_id=session_id,
            visual_state="failed",
            duration_ms=3_200,
            message=_pick_message(payload, _default_message(source, "failed")),
            terminal=True,
        )

    if event == "background_wait":
        # The turn waits for background work; the pet stops showing work and
        # completes later with the turn that reads the result.
        return PetDecision(
            source=source,
            event=event,
            session_id=session_id,
            persistent_state="idle",
        )

    if event in {"session_end", "idle"}:
        return PetDecision(
            source=source,
            event=event,
            session_id=session_id,
            visual_state="idle",
            terminal=True,
        )

    return None


def _pick_source(payload):
    return normalize_agent_source(
        payload.get("source")
        or payload.get("agent")
        or payload.get("agentId")
        or payload.get("agent_id")
    )


def _pick_event(payload):
    return normalize_event_name(
        payload.get("event")
        or payload.get("type")
        or payload.get("name")
        or payload.get("hook_event_name")
        or payload.get("reaction")
        or payload.get("state")
    )


def _pick_session_id(payload, source):
    value = (
        payload.get("sessionId")
        or payload.get("session_id")
        or payload.get("conversationId")
        or payload.get("taskId")
        or payload.get("task_id")
        or "default"
    )
    return f"{source}:{str(value)[:160]}"


def _pick_message(payload, fallback):
    value = (
        payload.get("message")
        or payload.get("text")
        or payload.get("title")
        or payload.get("summary")
    )
    if isinstance(value, str) and value.strip():
        return value.strip()[:120]
    return fallback


def _default_message(source, state):
    label = source_display_label(source)
    messages = {
        "review": f"{label}가 생각하고 있어요",
        "running": f"{label}가 작업하고 있어요",
        "waiting": f"{label}가 확인을 기다리고 있어요",
        "waving": f"{label} 알림이 있어요",
        "jumping": f"{label} 작업이 끝났어요",
        "cancelled": f"{label} 작업이 중단됐어요",
        "failed": f"{label} 작업에 문제가 생겼어요",
    }
    return messages.get(state, "")
