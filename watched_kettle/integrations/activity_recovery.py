"""Content-free, incremental reconstruction of a startup lifecycle snapshot."""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from watched_kettle.integrations.log_tail import TailCursor
from watched_kettle.state.agent_scope import scope_from_session_source


@dataclass(frozen=True)
class RecoverySnapshot:
    thread_id: str
    turn_id: str
    scope: str
    started_at: float
    last_activity_at: float
    observed_at: float
    active_tools: tuple[str, ...] = ()
    parent_thread_id: str = ""
    generation: int = 0


@dataclass
class RecoveryScan:
    end: int
    identity: tuple
    cursor: TailCursor = field(default_factory=TailCursor)
    thread_id: str = ""
    scope: str = "unknown"
    parent: str = ""
    history_start: int = 0
    turn: str = ""
    started: float = 0
    last_activity: float = 0
    tools: set[str] = field(default_factory=set)

    def consume(self, record, ordinal):
        if not isinstance(record, dict):
            return
        payload = record.get("payload")
        if not isinstance(payload, dict):
            return
        kind = record.get("type")
        if ordinal == 0 and kind == "session_meta":
            self.thread_id = str(payload.get("id") or payload.get("session_id") or "")[
                :160
            ]
            source = payload.get("source")
            self.scope = scope_from_session_source(source)
            if isinstance(source, dict):
                agent = source.get("subagent")
                spawn = agent.get("thread_spawn") if isinstance(agent, dict) else None
                if isinstance(spawn, dict):
                    self.parent = str(spawn.get("parent_thread_id") or "")[:160]
            boundary = payload.get("subagent_history_start_ordinal")
            if isinstance(boundary, int) and not isinstance(boundary, bool):
                self.history_start = max(0, boundary)
            return
        if ordinal < self.history_start or kind == "session_meta":
            return
        stamp = recorded_seconds(record)
        event = payload.get("type")
        turn = str(payload.get("turn_id") or "")[:160]
        if kind == "event_msg" and event == "task_started":
            self.turn, self.started, self.last_activity = turn, stamp, stamp
            self.tools.clear()
            return
        if not self.turn or (turn and turn != self.turn):
            return
        if kind == "event_msg" and event in {"task_complete", "turn_aborted"}:
            self.turn = ""
            self.tools.clear()
            return
        if (
            kind == "response_item"
            and event
            in {
                "reasoning",
                "message",
                "function_call",
                "custom_tool_call",
                "function_call_output",
                "custom_tool_call_output",
                "compaction",
            }
        ) or (kind == "event_msg" and event in {"item_completed", "context_compacted"}):
            self.last_activity = max(self.last_activity, stamp)
            call = str(payload.get("call_id") or "")[:160]
            if call and event in {"function_call", "custom_tool_call"}:
                if len(self.tools) < 4096:
                    self.tools.add(call)
            elif call and event in {"function_call_output", "custom_tool_call_output"}:
                self.tools.discard(call)

    def snapshot(self, observed_at, now):
        if (
            not self.thread_id
            or not self.turn
            or not self.started
            or not 0 <= now - self.last_activity <= 600
        ):
            return None
        return RecoverySnapshot(
            self.thread_id,
            self.turn,
            self.scope,
            self.started,
            self.last_activity,
            observed_at,
            tuple(sorted(self.tools)),
            self.parent,
        )


def recorded_seconds(record):
    try:
        stamp = datetime.fromisoformat(
            str(record.get("timestamp", "")).replace("Z", "+00:00")
        )
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp.timestamp()
    except (ValueError, OverflowError, OSError):
        return 0.0
