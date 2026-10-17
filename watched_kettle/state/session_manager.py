"""Aggregate pet states from one or more active agent sessions.

This module is a Python adaptation of the session aggregation design from
yangbuyiya/desktop-pet. See THIRD_PARTY_NOTICES.md for attribution.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import time

from watched_kettle.state.events import AGENT_SOURCES, PetDecision


STATE_PRIORITY = {
    "failed": 50,
    "waiting": 60,
    "running": 30,
    "review": 20,
    "waving": 10,
    "jumping": 10,
    "idle": 0,
}

MAX_RECENT_EVENTS = 12
DEFAULT_STALE_SESSION_AGE_MS = 12 * 60 * 60 * 1_000


@dataclass(frozen=True)
class InactivityLimit:
    """Release a source's sessions after silence; 0 disables that part."""

    work_ms: int
    waiting_ms: int


# Claude Code sends no event when a turn is interrupted, a permission request
# is denied, or the VS Code panel is closed (docs/support-claude-code.md).
CLAUDE_CODE_INACTIVITY_LIMIT = InactivityLimit(
    work_ms=10 * 60 * 1_000,
    waiting_ms=30 * 60 * 1_000,
)
DEFAULT_INACTIVITY_LIMITS = {"claude_code": CLAUDE_CODE_INACTIVITY_LIMIT}


@dataclass(frozen=True)
class AggregateState:
    state: str = "idle"
    message: str = ""
    session_id: str | None = None
    source: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class DisplayState:
    state: str
    message: str
    source: str
    session_id: str
    event: str
    duration_ms: int
    return_state: AggregateState
    urgency: str = "normal"
    announce: bool = True


@dataclass(frozen=True)
class ApplyResult:
    display: DisplayState
    aggregate: AggregateState
    sessions: tuple


@dataclass
class AgentSession:
    session_id: str
    source: str
    state: str
    message: str
    event: str
    updated_at: str
    updated_at_ms: int
    recent_events: list = field(default_factory=list)
    pending_wait_ids: frozenset[str] = frozenset()
    pending_question_ids: frozenset[str] = frozenset()
    unidentified_wait: bool = False
    turn_id: str = ""
    uncertain: bool = False
    agent_scope: str = "main"
    activity_version: int = 0
    # Tool calls started but not yet ended; a long tool reports nothing.
    open_tool_ids: frozenset[str] = frozenset()


class AgentSessionManager:
    """Track active sessions and select the most important pet state."""

    def __init__(self, now_ms=None):
        self._now_ms = now_ms or (lambda: time.time_ns() // 1_000_000)
        self._sessions = {}

    def apply(self, decision: PetDecision):
        at_ms = int(self._now_ms())
        updated_at = (
            datetime.fromtimestamp(
                at_ms / 1_000,
                tz=timezone.utc,
            )
            .isoformat()
            .replace("+00:00", "Z")
        )

        if decision.terminal:
            self._sessions.pop(decision.session_id, None)
        elif decision.persistent_state:
            existing = self._sessions.get(decision.session_id)
            state, message, wait_ids, question_ids, unidentified = self._session_state(
                decision,
                existing,
            )
            recent_events = list(existing.recent_events) if existing else []
            recent_events.append(
                {
                    "event": decision.event,
                    "state": state,
                    "updated_at": updated_at,
                }
            )
            self._sessions[decision.session_id] = AgentSession(
                session_id=decision.session_id,
                source=decision.source,
                state=state,
                message=message,
                event=decision.event,
                updated_at=updated_at,
                updated_at_ms=at_ms,
                recent_events=recent_events[-MAX_RECENT_EVENTS:],
                pending_wait_ids=wait_ids,
                pending_question_ids=question_ids,
                unidentified_wait=unidentified,
                turn_id=decision.turn_id,
                agent_scope=decision.agent_scope,
                open_tool_ids=self._open_tools(decision, existing),
            )
        if decision.source == "claude_code" and decision.parent_session_id:
            # A parent reports nothing while its subagent works; the
            # subagent's events keep the parent from going silent.
            parent = self._sessions.get(decision.parent_session_id)
            if parent is not None:
                parent.updated_at = updated_at
                parent.updated_at_ms = at_ms

        aggregate = self.get_aggregate()
        quiet_lifecycle = (
            decision.agent_scope != "main"
            and decision.event
            in {
                "session_start",
                "task_start",
                "prompt",
                "done",
                "cancelled",
            }
        ) or decision.event == "background_wait"
        if decision.source == "codex" and decision.agent_scope == "internal":
            quiet_lifecycle = True
        quiet_tool_failure = (
            decision.source in AGENT_SOURCES and decision.event == "tool_failed"
        )
        quiet_permission = (
            decision.event in {"permission", "permission_resolved"}
            and decision.persistent_state != "waiting"
        )
        announce = not (quiet_lifecycle or quiet_tool_failure or quiet_permission)
        duration_ms = (
            max(0, min(int(decision.duration_ms or 0), 60_000))
            if announce and aggregate.state != "waiting"
            else 0
        )
        display = DisplayState(
            state=(
                decision.visual_state or aggregate.state
                if duration_ms
                else aggregate.state
            ),
            message=(
                aggregate.message
                if quiet_lifecycle
                else decision.message or aggregate.message
            ),
            source=decision.source,
            session_id=decision.session_id,
            event=decision.event,
            duration_ms=duration_ms,
            return_state=aggregate,
            urgency=decision.urgency,
            announce=announce,
        )
        return ApplyResult(
            display=display,
            aggregate=aggregate,
            sessions=self.list_sessions(),
        )

    @staticmethod
    def _session_state(decision, existing):
        """Keep waits until their own results, or legacy resume evidence."""
        wait_ids = set(existing.pending_wait_ids) if existing else set()
        question_ids = set(existing.pending_question_ids) if existing else set()
        unidentified = bool(
            existing
            and (
                existing.unidentified_wait
                or (existing.state == "waiting" and not wait_ids and not question_ids)
            )
        )
        if decision.event == "prompt":
            wait_ids.clear()
            unidentified = False
        if decision.event == "permission_resolved" or (
            decision.event == "permission" and decision.approval_actor != "unknown"
        ):
            if decision.event_id:
                wait_ids.discard(decision.event_id)
            else:
                unidentified = False
        if decision.persistent_state == "waiting":
            if decision.event == "question_wait" and decision.event_id:
                question_ids.add(decision.event_id)
            elif decision.event_id:
                wait_ids.add(decision.event_id)
            else:
                unidentified = True
        elif decision.event == "question_resolved":
            question_ids.discard(decision.event_id)
        elif decision.event in {"tool_start", "tool_end", "tool_failed"}:
            # A tool start is sufficient only for old events lacking an ID.
            unidentified = False
            if decision.event in {"tool_end", "tool_failed"}:
                wait_ids.discard(decision.event_id)

        state = decision.persistent_state
        message = decision.message
        if wait_ids or question_ids or unidentified:
            state = "waiting"
            if existing and existing.state == "waiting":
                message = existing.message
        return (
            state,
            message,
            frozenset(wait_ids),
            frozenset(question_ids),
            unidentified,
        )

    @staticmethod
    def _open_tools(decision, existing):
        tools = set(existing.open_tool_ids) if existing else set()
        if decision.event in {"prompt", "background_wait"}:
            tools.clear()
        elif decision.event == "tool_start" and decision.event_id:
            tools.add(decision.event_id)
        elif decision.event in {"tool_end", "tool_failed"}:
            tools.discard(decision.event_id)
        return frozenset(tools)

    def get_aggregate(self):
        active = [
            session
            for session in self._sessions.values()
            if session.state != "idle" and counted_session(session)
        ]
        if not active:
            return AggregateState()

        top = sorted(
            active,
            key=lambda session: (
                -STATE_PRIORITY.get(session.state, 0),
                -session.updated_at_ms,
            ),
        )[0]
        return AggregateState(
            state=top.state,
            message=top.message,
            session_id=top.session_id,
            source=top.source,
            updated_at=top.updated_at,
        )

    def list_sessions(self):
        ordered = sorted(
            self._sessions.values(),
            key=lambda session: (
                -STATE_PRIORITY.get(session.state, 0),
                -session.updated_at_ms,
            ),
        )
        return tuple(ordered)

    def expire_stale(
        self,
        max_age_ms=DEFAULT_STALE_SESSION_AGE_MS,
        preserved_states=frozenset({"waiting"}),
        inactivity_limits=None,
    ):
        """Remove inactive work states while preserving actionable waits.

        ``inactivity_limits`` maps a source to an ``InactivityLimit`` that
        replaces the general rule for that source's sessions, waits and open
        tool calls included.
        """
        max_age_ms = max(0, int(max_age_ms))
        now_ms = int(self._now_ms())
        preserved_states = frozenset(preserved_states)
        inactivity_limits = inactivity_limits or {}

        def is_stale(session):
            age_ms = now_ms - session.updated_at_ms
            limit = inactivity_limits.get(session.source)
            if limit is not None:
                # An open tool call may run long without events, like a wait.
                limit_ms = (
                    limit.waiting_ms
                    if session.state == "waiting" or session.open_tool_ids
                    else limit.work_ms
                )
                return limit_ms > 0 and age_ms >= limit_ms
            return (
                max_age_ms > 0
                and session.state not in preserved_states
                and age_ms >= max_age_ms
            )

        expired = tuple(
            session for session in self._sessions.values() if is_stale(session)
        )
        for session in expired:
            self._sessions.pop(session.session_id, None)
        return expired

    def clear(self, source=None):
        """Drop every session, or only one source's sessions."""
        if source is None:
            self._sessions.clear()
        else:
            for key, session in tuple(self._sessions.items()):
                if session.source == source:
                    del self._sessions[key]
        return self.get_aggregate()

    def project_codex_observations(self, observations):
        """Project service confidence onto existing animation sessions only."""
        by_id = {"codex:" + o.thread_id: o for o in observations}
        changed = False
        for key, session in tuple(self._sessions.items()):
            if session.source != "codex":
                continue
            observed = by_id.get(key)
            if observed is None:
                del self._sessions[key]
                changed = True
                continue
            if (
                session.turn_id
                and observed.turn_id
                and session.turn_id != observed.turn_id
            ):
                continue
            if observed.version < session.activity_version:
                continue
            state = "waiting" if observed.state == "waiting" else "running"
            stamp = int(observed.last_confirmed_at * 1000)
            values = (
                observed.turn_id,
                observed.uncertain,
                observed.scope,
                state,
                stamp,
                observed.version,
            )
            previous = (
                session.turn_id,
                session.uncertain,
                session.agent_scope,
                session.state,
                session.updated_at_ms,
                session.activity_version,
            )
            if values != previous:
                (
                    session.turn_id,
                    session.uncertain,
                    session.agent_scope,
                    session.state,
                    session.updated_at_ms,
                    session.activity_version,
                ) = values
                changed = True
        return changed


def counted_session(session):
    return session.source != "codex" or (
        not getattr(session, "uncertain", False)
        and getattr(session, "agent_scope", "main") != "internal"
        and session.state != "idle"
    )
