"""Turn agent state results into quiet, privacy-safe UI presentations."""

from __future__ import annotations

from dataclasses import dataclass
import time

from watched_kettle.state.events import source_display_label
from watched_kettle.state.session_manager import (
    AggregateState,
    ApplyResult,
    counted_session,
)
from watched_kettle.ui.bubble_models import BubbleNotice


START_EVENTS = frozenset({"session_start", "task_start", "prompt"})
TIMED_NOTICE_DURATIONS_MS = {
    "session_start": 3_200,
    "task_start": 3_200,
    "prompt": 3_200,
    "notification": 5_000,
    "done": 3_200,
    "cancelled": 3_200,
    "tool_failed": 4_500,
    "failed": 4_500,
}
REPEAT_NOTICE_WINDOW_MS = 10_000
NOTICE_PRIORITIES = {
    "start": 20,
    "cancelled": 30,
    "done": 40,
    "notification": 60,
    "waiting": 110,
    "error": 100,
    "preview": 120,
}
NOTIFICATION_URGENCY_OFFSETS = {
    "high": 10,
    "normal": 0,
    "low": -10,
}


@dataclass(frozen=True)
class PresentationUpdate:
    """A complete UI snapshot for animation, tray, and speech bubble."""

    state: str
    message: str = ""
    source: str = ""
    event: str = ""
    session_id: str = ""
    active_count: int = 0
    notice: BubbleNotice | None = None
    persistent_notice: BubbleNotice | None = None
    persistent_notices: tuple[BubbleNotice, ...] = ()
    # Agent sources with working sessions, for the caption under the pet.
    working_sources: tuple[str, ...] = ()


def working_sources(sessions):
    """Distinct sources of working sessions, most important session first."""
    sources = []
    for session in sessions:
        if not counted_session(session):
            continue
        if session.state in {"running", "review"} and session.source not in sources:
            sources.append(session.source)
    return tuple(sources)


class ActivityPresentationPolicy:
    """Show only meaningful transitions while keeping all state in the tray."""

    def __init__(self, now_ms=None, repeat_window_ms=REPEAT_NOTICE_WINDOW_MS):
        self._now_ms = now_ms or (lambda: time.monotonic_ns() // 1_000_000)
        self.repeat_window_ms = max(0, int(repeat_window_ms))
        self._recent_notices = {}

    def build(self, result: ApplyResult):
        display = result.display
        persistent_notices = self._waiting_notices(
            result.aggregate,
            result.sessions,
        )
        persistent = persistent_notices[0] if persistent_notices else None
        notice = self._event_notice(display)
        if notice is not None and self._is_repeated(notice):
            notice = None

        return PresentationUpdate(
            state=display.state,
            message=display.message,
            source=display.source,
            event=display.event,
            session_id=display.session_id,
            active_count=sum(counted_session(s) for s in result.sessions),
            notice=notice,
            persistent_notice=persistent,
            persistent_notices=persistent_notices,
            working_sources=working_sources(result.sessions),
        )

    def restore(self, aggregate: AggregateState, sessions=()):
        persistent_notices = self._waiting_notices(aggregate, sessions)
        return PresentationUpdate(
            state=aggregate.state,
            message=aggregate.message,
            source=aggregate.source or "",
            session_id=aggregate.session_id or "",
            active_count=sum(counted_session(s) for s in sessions),
            persistent_notice=(persistent_notices[0] if persistent_notices else None),
            persistent_notices=persistent_notices,
            working_sources=working_sources(sessions),
        )

    def _event_notice(self, display):
        if not display.announce:
            return None
        event = display.event
        if event == "permission" and display.state == "waiting":
            event = "waiting"
        if event == "waiting":
            duration_ms = 0
        else:
            event_duration = TIMED_NOTICE_DURATIONS_MS.get(event)
            if event_duration is None:
                return None
            duration_ms = event_duration

        message = str(display.message or "").strip()[:120]
        if not message:
            message = self._fallback_message(display.source, event)
        if not message:
            return None

        kind = self._notice_kind(event)
        return BubbleNotice(
            message=message,
            source=display.source,
            event=event,
            session_id=display.session_id,
            duration_ms=duration_ms,
            kind=kind,
            priority=self._notice_priority(kind, display.urgency),
            replace_key=self._replace_key(
                display.source,
                display.session_id,
                kind,
            ),
            member_ids=(display.session_id,),
        )

    @classmethod
    def _waiting_notices(cls, aggregate, sessions=()):
        waiting_sessions = [
            session for session in sessions if session.state == "waiting"
        ]
        if not waiting_sessions and aggregate.state == "waiting":
            waiting_sessions = [aggregate]

        notices = []
        for session in waiting_sessions:
            source = session.source or "codex"
            session_id = session.session_id or ""
            message = str(
                session.message or cls._fallback_message(source, "waiting")
            ).strip()
            if not message:
                continue
            notices.append(
                BubbleNotice(
                    message=message[:120],
                    source=source,
                    event="waiting",
                    session_id=session_id,
                    kind="waiting",
                    priority=NOTICE_PRIORITIES["waiting"],
                    replace_key=cls._replace_key(
                        source,
                        session_id,
                        "waiting",
                    ),
                    member_ids=(session_id,),
                )
            )
        return tuple(notices)

    @staticmethod
    def _notice_kind(event):
        if event in START_EVENTS:
            return "start"
        if event in {"tool_failed", "failed"}:
            return "error"
        return event

    @staticmethod
    def _notice_priority(kind, urgency="normal"):
        priority = NOTICE_PRIORITIES.get(kind, 0)
        if kind == "notification":
            priority += NOTIFICATION_URGENCY_OFFSETS.get(urgency, 0)
        return priority

    @staticmethod
    def _replace_key(source, session_id, kind):
        if kind in {"start", "done"}:
            return f"{source}:{kind}"
        return f"{source}:{session_id}:{kind}"

    def _is_repeated(self, notice):
        now = int(self._now_ms())
        category = "start" if notice.event in START_EVENTS else notice.event
        key = (notice.source, notice.session_id, category, notice.message)
        previous = self._recent_notices.get(key)
        self._recent_notices[key] = now
        self._discard_old(now)
        return previous is not None and now - previous <= self.repeat_window_ms

    def _discard_old(self, now):
        retention = max(self.repeat_window_ms * 2, 60_000)
        stale = [
            key
            for key, recorded_at in self._recent_notices.items()
            if now - recorded_at > retention
        ]
        for key in stale:
            self._recent_notices.pop(key, None)

    @staticmethod
    def _fallback_message(source, event):
        label = source_display_label(source)
        messages = {
            "session_start": f"{label} 작업을 시작했어요",
            "task_start": f"{label} 작업을 시작했어요",
            "prompt": f"{label} 작업을 시작했어요",
            "waiting": f"{label}가 확인을 기다리고 있어요",
            "notification": f"{label} 알림이 있어요",
            "done": f"{label} 작업이 끝났어요",
            "cancelled": f"{label} 작업이 중단됐어요",
            "tool_failed": f"{label} 작업에 문제가 생겼어요",
            "failed": f"{label} 작업에 문제가 생겼어요",
        }
        return messages.get(event, "")
