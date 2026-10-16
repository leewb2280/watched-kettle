"""Project cards derived from turn-aware events; never persisted."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field, replace
import ntpath
import time
import math
from typing import Literal
import unicodedata

from PySide6.QtCore import QObject, Signal

from watched_kettle.activity_diagnostics import (
    DiagnosticRecorder,
    diagnostic_guard,
    diagnostic_ref,
    diagnostic_thread_ref,
)

from watched_kettle.state.events import approval_actor, build_decision
from watched_kettle.state.session_manager import DEFAULT_INACTIVITY_LIMITS


PRIORITY = {
    "permission": 2,
    "waiting": 4,
    "failed": 3,
    "running": 2,
    "review": 2,
    "done": 1,
    "cancelled": 1,
    "background": 1,
}
# Presentation order must not change parent/child activity aggregation.
ROW_PRIORITY = {
    "permission": 1,
    "done": 4,
    "waiting": 3,
    "failed": 3,
    "cancelled": 2,
    "running": 1,
    "review": 1,
    "background": 2,
}
RUNNING_STALE_SECONDS = 60
TOOL_STALE_SECONDS = 180
COMPACTION_GRACE_SECONDS = 600
COMPLETION_RETENTION_SECONDS = 300
MAX_UNCONFIRMED_COMPLETIONS = 4096
# Claude Code sessions share this service with Codex threads. The prefix keeps
# their keys apart and tells navigation that no Codex deep link exists.
CLAUDE_CODE_THREAD_PREFIX = "claude_code:"
DEFAULT_TITLES = {"codex": "Codex 대화", "claude_code": "Claude Code 대화"}
DEFAULT_PROJECT_LABELS = {"codex": "Codex 작업", "claude_code": "Claude Code 작업"}
LABELS = {
    "permission": "권한 처리 중",
    "waiting": "확인 필요",
    "failed": "실패",
    "running": "작업 중",
    "review": "검토 중",
    "done": "완료",
    "cancelled": "중단",
    "background": "백그라운드 대기",
}


def safe_label(value, fallback):
    text = " ".join(str(value or "").split())
    return text[:64] if text and not any(c in text for c in ("/", "\\")) else fallback


def thread_source(thread_id):
    """Return the agent source that owns a conversation key."""
    return (
        "claude_code"
        if str(thread_id or "").startswith(CLAUDE_CODE_THREAD_PREFIX)
        else "codex"
    )


def conversation_title(value):
    if not isinstance(value, str):
        return "Codex 대화"
    text = " ".join(
        "".join(
            " " if unicodedata.category(c).startswith("C") else c for c in value
        ).split()
    )
    return text or "Codex 대화"


@dataclass(frozen=True)
class ThreadMetadata:
    thread_id: str
    project_id: str | None = None
    project_label: str = ""
    cwd: str = ""
    title: str = "Codex 대화"
    parent_thread_id: str = ""
    source: str = "codex"

    @property
    def project_key(self):
        if self.project_id is None:
            return "thread:" + self.thread_id
        # Codex keys stay unchanged; other sources never share a Codex card.
        prefix = "" if self.source == "codex" else self.source + ":"
        if self.project_id:
            return "project:" + prefix + self.project_id
        return "unassigned:" + self.source

    @property
    def card_kind(self) -> Literal["project", "unassigned", "unknown"]:
        if self.project_id is None:
            return "unknown"
        return "project" if self.project_id else "unassigned"

    @property
    def label(self):
        if self.project_id == "":
            return "프로젝트 없는 대화"
        folder = ntpath.basename(ntpath.normpath(self.cwd)) if self.cwd else ""
        return safe_label(
            self.project_label or folder,
            DEFAULT_PROJECT_LABELS.get(self.source, "Codex 작업"),
        )


@dataclass
class Activity:
    thread_id: str
    turn_id: str = ""
    state: str = "running"
    order: int = 0
    expires: float = 0
    waits: set[str] = field(default_factory=set)
    question_waits: set[str] = field(default_factory=set)
    permissions: set[str] = field(default_factory=set)
    permission_actors: dict[str, str] = field(default_factory=dict)
    active_tools: set[str] = field(default_factory=set)
    last_seen_at: float = 0
    scope: str = "main"
    started_at: float = 0
    state_changed_at: float = 0
    uncertain: bool = False
    started_wall_at: float = 0
    compaction_since: float | None = None
    compaction_turn_id: str = ""
    compaction_last_stamp: float = 0
    source: str = "codex"
    # Claude Code background tasks the turn waits for (state "background").
    background_count: int = 0


@dataclass(frozen=True)
class ConversationRow:
    thread_id: str
    title: str
    state: str
    order: int
    sort_at: float = 0
    completion_id: str = ""
    highlighted: bool = False
    highlight_until: float = 0
    uncertain: bool = False
    compacting: bool = False
    source: str = "codex"
    background_count: int = 0


@dataclass(frozen=True)
class ProjectCard:
    key: str
    label: str
    rows: tuple[ConversationRow, ...]
    order: int
    kind: Literal["project", "unassigned", "unknown"] = "project"
    source: str = "codex"

    @property
    def running(self):
        return sum(
            row.state in {"running", "review"} and not row.uncertain
            for row in self.rows
        )

    @property
    def uncertain(self):
        return sum(row.uncertain for row in self.rows)

    @property
    def waiting(self):
        return sum(row.state == "waiting" for row in self.rows)

    @property
    def done(self):
        return sum(row.state == "done" for row in self.rows)

    @property
    def summary(self):
        return " · ".join(
            f"{label} {count}개"
            for label, count in (
                ("완료", self.done),
                ("확인 필요", self.waiting),
                (
                    "권한 처리 중",
                    sum(
                        row.state == "permission" and not row.uncertain
                        for row in self.rows
                    ),
                ),
                ("작업 중", self.running),
                (
                    "백그라운드 대기",
                    sum(row.state == "background" for row in self.rows),
                ),
                ("상태 확인 중", self.uncertain),
            )
            if count > 0
        )


@dataclass(frozen=True)
class ActivityRecord:
    thread_id: str
    state: str
    occurred_at: float


@dataclass(frozen=True)
class CompletionRecord:
    record_id: str
    thread_id: str
    turn_id: str
    occurred_at: float
    highlight_until: float
    expires_at: float
    dismissed: bool = False
    completed_at: float = 0


def trace_ref(value):
    """Short one-way reference so traces never carry raw identifiers."""
    return diagnostic_ref(value)


class ProjectActivityService(QObject):
    changed = Signal()
    metadata_requested = Signal(str)
    # Optional ``trace(event, **fields)`` set by the composition root when
    # WATCHED_KETTLE_TRACE_ACTIVITY is on. Fields are hashes and enums only.
    trace = None

    def __init__(
        self,
        parent=None,
        now=None,
        duration=8,
        running_stale_seconds=RUNNING_STALE_SECONDS,
        tool_stale_seconds=TOOL_STALE_SECONDS,
        wall_now=None,
    ):
        super().__init__(parent)
        self.now = now or time.monotonic
        self.wall_now = wall_now or time.time
        self.duration = duration
        self.completion_duration = 15
        self.completions: tuple[CompletionRecord, ...] = ()
        self.pending_completions: dict[str, CompletionRecord] = {}
        self._unconfirmed_completions: OrderedDict[str, CompletionRecord] = (
            OrderedDict()
        )
        self._completion_sequence = 0
        self._completion_phase: tuple[tuple[str, bool], ...] = ()
        self.running_stale_seconds = max(1, float(running_stale_seconds))
        self.tool_stale_seconds = max(
            self.running_stale_seconds, float(tool_stale_seconds)
        )
        self.generation = 0
        self.activity_diagnostics = DiagnosticRecorder()
        self.activities: dict[str, Activity] = {}
        self.metadata: dict[str, ThreadMetadata] = {}
        self.recent: tuple[ActivityRecord, ...] = ()
        self._seen: OrderedDict[tuple, float] = OrderedDict()
        self._retired: OrderedDict[tuple, None] = OrderedDict()
        self._sequence = 0
        self._project_order: dict[str, int] = {}
        self.stale_expired_count = 0
        self.uncertain_recovered_count = 0
        self._first_display: dict[str, float] = {}
        self._confirmed_scopes: dict[str, str] = {}
        self._collection_started_at = self.wall_now()
        self._closed_threads: OrderedDict[str, float] = OrderedDict()
        self._tool_turns: OrderedDict[tuple[str, str], str] = OrderedDict()
        self.rejected_events: dict[str, int] = {}
        self.latency: OrderedDict[str, dict] = OrderedDict()
        self._recovery_deadlines: dict[str, float] = {}
        # Sources without a heartbeat release rows after the same silence as
        # the pet instead of showing "상태 확인 중" (InactivityLimit, ms).
        self.inactivity_limits = dict(DEFAULT_INACTIVITY_LIMITS)
        # Claude Code session titles read from transcripts; memory only.
        self._claude_code_titles: OrderedDict[str, str] = OrderedDict()
        # Where each Claude Code session runs (vscode-panel, vscode-terminal,
        # terminal); decides how its row opens. Memory only.
        self._claude_code_clients: OrderedDict[str, str] = OrderedDict()

    def set_claude_code_title(self, session_id, title):
        """Show a Claude Code session's title; never logged or persisted."""
        thread = CLAUDE_CODE_THREAD_PREFIX + str(session_id or "")
        title = conversation_title(title) if title else DEFAULT_TITLES["claude_code"]
        self._claude_code_titles[thread] = title
        self._claude_code_titles.move_to_end(thread)
        while len(self._claude_code_titles) > 512:
            self._claude_code_titles.popitem(last=False)
        old = self.metadata.get(thread)
        if old is not None and old.source == "claude_code" and old.title != title:
            self.metadata[thread] = replace(old, title=title)
            self._diagnose_current(thread, "title_updated")
            self.changed.emit()

    def claude_code_client(self, thread_id):
        """Where a Claude Code session runs, or "" when no hook said so."""
        return self._claude_code_clients.get(str(thread_id or ""), "")

    def set_inactivity_limit(self, source, limit):
        """Replace one source's silence limit; None restores stale marking."""
        if limit is None:
            self.inactivity_limits.pop(source, None)
        else:
            self.inactivity_limits[source] = limit

    def mark_latency(self, thread, stage, at=None):
        now = self.now()
        for key, previous in tuple(self.latency.items()):
            if now - previous["detected"] >= 600:
                del self.latency[key]
        trace = self.latency.get(thread)
        if stage == "detected":
            trace = {"detected": now}
            self.latency[thread] = trace
            self.latency.move_to_end(thread)
        if trace is not None:
            trace.setdefault(stage, now if at is None else at)
        while len(self.latency) > 512:
            self.latency.popitem(last=False)

    def restore_activity(self, snapshot):
        """Restore evidence without replaying lifecycle effects or history."""
        thread = snapshot.thread_id
        if (
            thread in self.activities
            or thread in self._closed_threads
            or (thread, snapshot.turn_id) in self._retired
            or snapshot.observed_at < self._collection_started_at
            or not 0 <= self.wall_now() - snapshot.last_activity_at <= 600
        ):
            return
        self._sequence += 1
        at = self.now()
        self.activities[thread] = Activity(
            thread,
            snapshot.turn_id,
            order=self._sequence,
            active_tools=set(snapshot.active_tools),
            last_seen_at=at,
            scope=snapshot.scope,
            started_at=at,
            state_changed_at=at,
            uncertain=True,
            started_wall_at=snapshot.started_at,
        )
        self.metadata.setdefault(
            thread, ThreadMetadata(thread, parent_thread_id=snapshot.parent_thread_id)
        )
        self._recovery_deadlines[thread] = at + 60
        self._trace(
            "activity_restored",
            thread_ref=trace_ref(thread),
            turn_ref=trace_ref(snapshot.turn_id),
            parent_ref=trace_ref(snapshot.parent_thread_id),
            scope=snapshot.scope,
        )
        for call in snapshot.active_tools:
            self._tool_turns[(thread, call)] = snapshot.turn_id
        self.mark_latency(thread, "detected")
        self.mark_latency(thread, "restored")
        self._diagnose_current(thread, "restore")
        self.changed.emit()

    def reset(self, source="codex"):
        """Forget one agent's work: a Codex account change, or a tool switched off.

        Claude Code sessions are not tied to the Codex account, and the Codex
        account generation moves only when Codex state is forgotten.
        """

        def kept(thread):
            return thread_source(thread) != source

        for thread in set(self.activities) | set(self.pending_completions):
            if not kept(thread):
                self._diagnose_reset(thread)

        def keep_keys(mapping, key=lambda item: item):
            for item in tuple(mapping):
                if not kept(key(item)):
                    del mapping[item]

        keep_keys(self.latency)
        if source == "codex":
            # Log recovery belongs to Codex sessions only.
            self._recovery_deadlines.clear()
            self._collection_started_at = self.wall_now()
        keep_keys(self._closed_threads)
        keep_keys(self._tool_turns, lambda item: item[0])
        keep_keys(self._first_display)
        keep_keys(self._confirmed_scopes)
        if source == "codex":
            self.generation += 1
        keep_keys(self.activities)
        keep_keys(self.metadata)
        self.recent = tuple(r for r in self.recent if kept(r.thread_id))
        self.completions = tuple(r for r in self.completions if kept(r.thread_id))
        keep_keys(self.pending_completions)
        keep_keys(self._unconfirmed_completions)
        self._completion_phase = ()
        keep_keys(self._seen, lambda item: item[0])
        keep_keys(self._retired, lambda item: item[0])
        claude_prefixes = ("project:claude_code:", "unassigned:claude_code")
        for key in tuple(self._project_order):
            if key.startswith(claude_prefixes) == (source == "claude_code"):
                del self._project_order[key]
        self.changed.emit()

    @diagnostic_guard
    def _diagnose_reset(self, thread):
        self.activity_diagnostics.emit(
            "activity_reset",
            **self.diagnostic_summary(thread),
            reason="account_reset",
        )
        self.activity_diagnostics.forget("activity_changed", trace_ref(thread))

    @diagnostic_guard
    def _diagnose_completion_removed(self, thread, record, reason):
        self.activity_diagnostics.emit(
            "completion_removed",
            thread_ref=trace_ref(thread),
            turn_ref=trace_ref(record.turn_id),
            source=thread_source(thread),
            reason=reason,
            generation=self.generation,
        )

    def set_metadata(self, metadata, generation):
        if generation != self.generation:
            return
        old = self.metadata.get(metadata.thread_id)
        if old:
            metadata = replace(
                metadata,
                title=old.title if metadata.title == "Codex 대화" else metadata.title,
                project_id=old.project_id
                if metadata.project_id is None
                else metadata.project_id,
                project_label=metadata.project_label or old.project_label,
                cwd=metadata.cwd or old.cwd,
            )
        if old and not metadata.parent_thread_id:
            metadata = replace(metadata, parent_thread_id=old.parent_thread_id)
        self.metadata[metadata.thread_id] = metadata
        if metadata.project_id is not None and metadata.title != "Codex 대화":
            self.mark_latency(metadata.thread_id, "named")
        if metadata.parent_thread_id:
            self._unconfirmed_completions.pop(metadata.thread_id, None)
        activity = self.activities.get(metadata.thread_id)
        scope_changed = bool(activity and activity.scope == "unknown")
        if scope_changed and activity is not None:
            activity.scope = "subagent" if metadata.parent_thread_id else "main"
            self._confirmed_scopes[metadata.thread_id] = activity.scope
        if metadata.parent_thread_id and metadata.parent_thread_id not in self.metadata:
            self.metadata_requested.emit(metadata.parent_thread_id)
        if old != metadata or scope_changed:
            self._trace(
                "metadata_applied",
                thread_ref=trace_ref(metadata.thread_id),
                parent_ref=trace_ref(metadata.parent_thread_id),
                state=metadata.card_kind,
                result="named" if metadata.title != "Codex 대화" else "unnamed",
                scope=activity.scope if activity is not None else "",
            )
            self._diagnose_current(metadata.thread_id, "metadata_applied")
            self.changed.emit()

    def set_project_relation(self, thread_id, project_id, label, generation):
        if generation != self.generation or project_id is None:
            return
        old = self.metadata.get(thread_id, ThreadMetadata(thread_id))
        updated = replace(
            old, project_id=project_id, project_label=label or old.project_label
        )
        if updated != old:
            self.metadata[thread_id] = updated
            if updated.project_id is not None and updated.title != "Codex 대화":
                self.mark_latency(thread_id, "named")
            self._diagnose_current(thread_id, "project_relation")
            self.changed.emit()

    def observe(self, payload):
        accepted = self._observe_traced(payload)
        self._diagnose_payload(payload)
        # Claude Code has a single hook channel whose pet states are verified
        # on their own. Its card never decides whether the pet sees an event.
        if isinstance(payload, dict) and payload.get("source") == "claude_code":
            return True
        return accepted

    @diagnostic_guard
    def _diagnose_payload(self, payload):
        if isinstance(payload, dict):
            keyed = self._source_payload(payload)
            thread = str(keyed.get("thread_id") or keyed.get("session_id") or "")
            self._diagnose_current(thread, str(payload.get("event") or ""), payload)

    def _observe_traced(self, payload):
        if self.trace is None or not isinstance(payload, dict):
            return self._observe(payload)
        rejected = dict(self.rejected_events)
        accepted = self._observe(payload)
        self._diagnose_observed(payload, accepted, rejected)
        return accepted

    @diagnostic_guard
    def _diagnose_observed(self, payload, accepted, rejected):
        reason = next(
            (
                key
                for key, count in self.rejected_events.items()
                if count != rejected.get(key, 0)
            ),
            "",
        )
        keyed = self._source_payload(payload)
        thread = str(keyed.get("thread_id") or keyed.get("session_id") or "")
        activity = self.activities.get(thread)
        self._trace(
            "event_observed",
            source=str(payload.get("source") or ""),
            operation=str(payload.get("event") or ""),
            scope=str(payload.get("agent_scope") or ""),
            actor=str(payload.get("approval_actor") or ""),
            thread_ref=trace_ref(thread),
            turn_ref=trace_ref(payload.get("turn_id")),
            call_ref=trace_ref(payload.get("event_id")),
            parent_ref=diagnostic_thread_ref(
                payload.get("source"),
                payload.get("parent_thread_id") or payload.get("parent_session_id"),
            ),
            result="rejected" if reason else "accepted" if accepted else "ignored",
            reason=reason,
            state=activity.state if activity is not None else "none",
            uncertain=bool(activity and activity.uncertain),
        )

    @diagnostic_guard
    def _trace(self, event, **fields):
        if event != "event_observed":
            if event in {"activity_expired", "activity_inactive", "recovery_dropped"}:
                self.activity_diagnostics.forget(
                    "activity_changed", fields.get("thread_ref", "")
                )
            self.activity_diagnostics.emit(
                event,
                generation=self.generation,
                **fields,
            )
        if self.trace is not None:
            try:
                self.trace(event, **fields)
            except Exception:
                pass

    def diagnostic_summary(self, thread):
        """Read-only content-free snapshot, also used after failed navigation."""
        item = self.activities.get(thread)
        metadata = self.metadata.get(thread)
        completion = self.pending_completions.get(thread)
        return dict(
            thread_ref=trace_ref(thread),
            source=thread_source(thread),
            turn_ref=trace_ref(
                item.turn_id if item else completion.turn_id if completion else ""
            ),
            state=item.state if item else "none",
            scope=item.scope if item else "unknown",
            parent_ref=trace_ref(metadata.parent_thread_id) if metadata else "",
            project_ref=trace_ref(metadata.project_key) if metadata else "",
            project_known=bool(metadata and metadata.project_id is not None),
            title_present=bool(
                metadata and metadata.title != DEFAULT_TITLES.get(metadata.source)
            ),
            uncertain=bool(item and item.uncertain),
            compacting=bool(item and item.compaction_since is not None),
            active=bool(item and not item.expires),
            completed=bool(completion),
            generation=self.generation,
        )

    @diagnostic_guard
    def _diagnose_current(self, thread, operation, payload=None):
        recorder = self.activity_diagnostics
        if recorder.callback is None:
            return
        key = trace_ref(thread)
        if thread not in self.activities and thread not in self.metadata:
            if ("activity_changed", key) not in recorder.states:
                return
        fields = self.diagnostic_summary(thread)
        recorder.record(
            "activity_changed",
            key,
            compare=tuple(fields),
            operation=operation,
            call_ref=trace_ref((payload or {}).get("event_id")),
            **fields,
        )

    @staticmethod
    def _source_payload(payload):
        """Give Claude Code sessions keys that cannot collide with Codex."""
        if payload.get("source") != "claude_code":
            return payload
        payload = dict(payload)
        for key in ("session_id", "parent_session_id"):
            if payload.get(key):
                payload[key] = CLAUDE_CODE_THREAD_PREFIX + str(payload[key])
        return payload

    def _observe(self, payload):
        if not isinstance(payload, dict):
            return True
        payload = self._source_payload(payload)
        if (
            payload.get("source") in {"codex", "claude_code"}
            and payload.get("event") == "review"
            and payload.get("compaction_phase") in ("start", "end")
        ):
            return self._observe_compaction(payload)
        if payload.get("source") == "codex" and payload.get("event") == "heartbeat":
            return self._observe_heartbeat(payload)
        decision = build_decision(payload)
        if decision is None or decision.source not in {"codex", "claude_code"}:
            return True
        thread = str(payload.get("thread_id") or payload.get("session_id") or "default")
        turn = str(payload.get("turn_id") or "")
        event = decision.event
        current = self.activities.get(thread)
        stamp = self._valid_stamp(payload.get("collected_at"))
        starts = event in {"prompt", "task_start"}
        active = current is not None and not current.expires
        if thread == "default" or not thread:
            return self._reject_event("missing_identity")
        if event in {"question_wait", "question_resolved"} and not decision.event_id:
            return self._reject_event("missing_question_id")
        if stamp and stamp < self._collection_started_at:
            return self._reject_event("old_collection")
        unconfirmed = self._unconfirmed_completions.get(thread)
        if (
            unconfirmed is not None
            and turn
            and unconfirmed.turn_id == turn
            and decision.terminal
            and (decision.agent_scope != "unknown" or event != "done")
        ):
            self._unconfirmed_completions.pop(thread)
            parent = payload.get("parent_thread_id") or payload.get("parent_session_id")
            metadata = self.metadata.get(thread, ThreadMetadata(thread))
            if (
                event == "done"
                and decision.agent_scope == "main"
                and not active
                and not parent
                and not metadata.parent_thread_id
                and unconfirmed.expires_at > self.now()
            ):
                self._publish_completion(unconfirmed)
                self.recent = (
                    *self.recent,
                    ActivityRecord(thread, "done", unconfirmed.occurred_at),
                )[-20:]
                self.changed.emit()
            # This enriches an ended turn's card only. Do not replay its pet
            # animation or pass a terminal event to a newer animation session.
            return False
        if not active:
            if starts:
                if (
                    not turn
                    and thread in self._closed_threads
                    and (not stamp or stamp <= self._closed_threads[thread])
                ):
                    return self._reject_event("closed_turn")
            elif event == "tool_start":
                if (
                    thread == "default"
                    or not thread
                    or not decision.event_id
                    or not stamp
                ):
                    return self._reject_event("missing_start")
                if thread in self._closed_threads and (
                    not turn or stamp <= self._closed_threads[thread]
                ):
                    return self._reject_event("closed_turn")
            else:
                return self._reject_event("missing_start")
        if current is not None and active and stamp and stamp < current.started_wall_at:
            return self._reject_event("old_turn_time")
        if (
            current is not None
            and active
            and current.turn_id
            and turn
            and current.turn_id != turn
            and not starts
            and decision.source == "claude_code"
            and decision.agent_scope == "main"
            and (thread, turn) not in self._retired
        ):
            # Claude Code reads a background task's result in a turn it starts
            # by itself, with a new prompt ID and no prompt hook. Its tools and
            # Stop belong to the open turn. A replaced turn is retired, so its
            # late events are still rejected below (BA-02).
            turn = current.turn_id
        if event in {"tool_end", "tool_failed", "permission_resolved"}:
            call = decision.event_id or "legacy"
            if (
                current is None
                or not active
                or self._tool_turns.get((thread, call)) != current.turn_id
            ):
                return self._reject_event("unmatched_tool")
            if turn and turn != current.turn_id:
                return self._reject_event("closed_turn")
        if event == "question_resolved" and (
            current is None
            or not active
            or decision.event_id not in current.question_waits
            or (turn and turn != current.turn_id)
        ):
            return self._reject_event("unmatched_question")
        if starts and not active:
            current = None
        if turn and (thread, turn) in self._retired:
            return self._reject_event("closed_turn")
        if current and current.turn_id and turn and current.turn_id != turn:
            if not starts and not (event == "tool_start" and not active):
                return False
            self._retire(thread, current.turn_id)
            current = None
        # ID-less legacy hooks cannot end a newer, identified turn. JSONL supplies
        # the correlated terminal event; do not guess from arrival order.
        # Claude Code has no second channel, and SessionEnd or a transcript
        # cancellation carries no prompt ID, so its own session may end here.
        if (
            current
            and current.turn_id
            and not turn
            and decision.terminal
            and decision.source == "codex"
        ):
            return False
        if starts and active and current is not None:
            # A hook start followed by its identified log confirmation is one run.
            if not current.turn_id and turn:
                current.turn_id = turn
                for key in tuple(self._tool_turns):
                    if key[0] == thread and self._tool_turns[key] == "":
                        self._tool_turns[key] = turn
                return False
            if current.turn_id and (not turn or turn == current.turn_id):
                return False
        identity = (
            thread,
            turn or (current.turn_id if current else ""),
            event,
            decision.event_id,
            approval_actor(payload) if event == "permission" else "",
        )
        at = self.now()
        self._first_display.setdefault(thread, at)
        previous = self._seen.get(identity)
        stable_event = (
            bool(decision.event_id)
            or decision.terminal
            or event in {"prompt", "task_start", "session_start"}
        )
        actor_changed = (
            event == "permission"
            and current is not None
            and decision.approval_actor != "unknown"
            and (decision.event_id or "legacy") in current.permission_actors
            and current.permission_actors.get(decision.event_id or "legacy")
            != decision.approval_actor
        )
        if (
            stable_event
            and not actor_changed
            and previous is not None
            and (turn or at - previous < 2)
        ):
            return False
        self._seen[identity] = at
        while len(self._seen) > 4096:
            self._seen.popitem(last=False)
        parent = str(
            payload.get("parent_thread_id") or payload.get("parent_session_id") or ""
        )
        if thread not in self.metadata or parent:
            old = self.metadata.get(thread, ThreadMetadata(thread))
            self.metadata[thread] = replace(
                old, parent_thread_id=parent or old.parent_thread_id
            )
        if decision.source == "claude_code":
            # A subagent's card is its parent's; the parent may not have
            # reported yet when the app starts mid-session.
            for key in filter(None, (thread, parent)):
                self._remember_claude_code_project(key, payload)
                if payload.get("client"):
                    self._claude_code_clients[key] = str(payload["client"])
                    self._claude_code_clients.move_to_end(key)
            while len(self._claude_code_clients) > 512:
                self._claude_code_clients.popitem(last=False)
        else:
            self.metadata_requested.emit(thread)
        if decision.terminal and event in {"idle", "session_end"}:
            self._remember_closed(thread)
            self.activities.pop(thread, None)
            self.changed.emit()
            return True
        if not decision.terminal and not decision.persistent_state:
            return True
        new_activity = current is None or bool(current.expires)
        if new_activity:
            self.mark_latency(thread, "detected")
        self._recovery_deadlines.pop(thread, None)
        if current is None:
            self._sequence += 1
            current = Activity(
                thread, order=self._sequence, last_seen_at=at, source=decision.source
            )
            self.activities[thread] = current
        old_state = current.state
        if new_activity:
            self._clear_tool_turns(thread)
            current.started_at = at
            stamp = payload.get("collected_at")
            current.started_wall_at = self._valid_stamp(stamp) or self.wall_now()
            current.state_changed_at = at
        current.last_seen_at = at
        if decision.agent_scope != "unknown":
            current.scope = decision.agent_scope
            self._confirmed_scopes[thread] = current.scope
        elif new_activity:
            current.scope = self._confirmed_scopes.get(thread, "unknown")
        resumes = (
            event
            in {
                "prompt",
                "task_start",
                "session_start",
                "tool_start",
                "tool_end",
                "tool_failed",
                "waiting",
                "question_wait",
                "question_resolved",
                "permission",
                "permission_resolved",
            }
            or decision.terminal
        )
        if resumes:
            current.compaction_since = None
            current.compaction_turn_id = ""
        if current.uncertain and (resumes or current.compaction_since is None):
            self.uncertain_recovered_count += 1
            current.uncertain = False
        current.turn_id = turn or current.turn_id
        if event == "prompt":
            current.waits.clear()
            current.permissions.clear()
            current.permission_actors.clear()
            current.active_tools.clear()
        if new_activity or event in {"prompt", "task_start", "session_start"}:
            previous_completion = self.pending_completions.get(thread)
            if previous_completion is not None:
                self._diagnose_completion_removed(
                    thread, previous_completion, "new_activity"
                )
            self.pending_completions.pop(thread, None)
            self._unconfirmed_completions.pop(thread, None)
            self.completions = tuple(
                replace(record, dismissed=True)
                if record.thread_id == thread
                else record
                for record in self.completions
            )
        if event == "permission":
            call = decision.event_id or "legacy"
            current.waits.discard(call)
            current.permissions.discard(call)
            actor = approval_actor(payload)
            if actor == "unknown":
                actor = current.permission_actors.get(call, actor)
            current.permission_actors[call] = actor
            if actor == "user":
                current.waits.add(call)
            elif actor == "unknown":
                current.permissions.add(call)
        elif event == "permission_resolved":
            current.permission_actors.pop(decision.event_id or "legacy", None)
            current.waits.discard(decision.event_id or "legacy")
            current.permissions.discard(decision.event_id or "legacy")
        elif event == "waiting":
            current.waits.add(decision.event_id or "legacy")
        elif event == "question_wait":
            current.question_waits.add(decision.event_id)
        elif event == "question_resolved":
            self._tool_turns.pop((thread, decision.event_id), None)
            current.question_waits.discard(decision.event_id)
        elif event == "tool_start":
            current.active_tools.add(decision.event_id or "legacy")
            current.waits.discard("legacy")
        elif event in {"tool_end", "tool_failed"}:
            if decision.event_id not in current.question_waits:
                self._tool_turns.pop((thread, decision.event_id or "legacy"), None)
            current.waits.discard("legacy")
            current.waits.discard(decision.event_id)
            current.permissions.discard(decision.event_id or "legacy")
            current.active_tools.discard("legacy")
            current.permission_actors.pop(decision.event_id or "legacy", None)
            if decision.event_id:
                current.active_tools.discard(decision.event_id)
        if decision.terminal:
            self._remember_closed(thread)
            current.state = (
                "failed"
                if event == "failed"
                else "cancelled"
                if event == "cancelled"
                else "done"
            )
            current.waits.clear()
            current.question_waits.clear()
            current.permissions.clear()
            current.permission_actors.clear()
            current.active_tools.clear()
            current.expires = at + self.duration
            if current.turn_id:
                self._retire(thread, current.turn_id)
            if (
                event == "done"
                and decision.agent_scope in {"main", "unknown"}
                and current.scope not in {"subagent", "internal"}
                and not parent
                and not self.metadata[thread].parent_thread_id
                and (decision.agent_scope == "main" or current.turn_id)
            ):
                self._completion_sequence += 1
                record = CompletionRecord(
                    f"completion:{self.generation}:{self._completion_sequence}",
                    thread,
                    current.turn_id,
                    time.time(),
                    at + self.completion_duration,
                    at + COMPLETION_RETENTION_SECONDS,
                    completed_at=at,
                )
                if decision.agent_scope == "main":
                    self._publish_completion(record)
                else:
                    self._unconfirmed_completions[thread] = record
                    while (
                        len(self._unconfirmed_completions) > MAX_UNCONFIRMED_COMPLETIONS
                    ):
                        self._unconfirmed_completions.popitem(last=False)
        else:
            current.state = (
                "waiting"
                if current.waits or current.question_waits
                else "permission"
                if current.permissions
                else "review"
                if event == "review"
                else "background"
                if event == "background_wait"
                else decision.persistent_state or "running"
            )
            current.background_count = (
                int(payload.get("background_count") or 1)
                if current.state == "background"
                else 0
            )
            current.expires = 0
        if event in {"tool_start", "waiting", "question_wait", "permission"}:
            self._tool_turns[(thread, decision.event_id or "legacy")] = current.turn_id
            while len(self._tool_turns) > 4096:
                self._tool_turns.popitem(last=False)
        if current.state != old_state:
            current.state_changed_at = at
        if decision.agent_scope == "main" and (
            current.state != old_state or new_activity
        ):
            self.recent = (
                *self.recent,
                ActivityRecord(thread, current.state, time.time()),
            )[-20:]
        self.changed.emit()
        return True

    def _remember_claude_code_project(self, thread, payload):
        """Fix the card on the session's first folder; never request metadata."""
        old = self.metadata.get(thread, ThreadMetadata(thread))
        if old.source == "claude_code" and old.project_id:
            return
        reference = str(payload.get("project_ref") or "")
        self.metadata[thread] = replace(
            old,
            source="claude_code",
            project_id=reference,
            project_label=str(payload.get("project_label") or "") if reference else "",
            title=self._claude_code_titles.get(thread, DEFAULT_TITLES["claude_code"]),
        )

    def _publish_completion(self, record):
        self.pending_completions[record.thread_id] = record
        self.completions = (*self.completions, record)[-100:]

    def _reject_event(self, reason):
        self.rejected_events[reason] = self.rejected_events.get(reason, 0) + 1
        return False

    def _remember_closed(self, thread):
        self._clear_tool_turns(thread)
        self._closed_threads[thread] = self.wall_now()
        self._closed_threads.move_to_end(thread)
        while len(self._closed_threads) > 4096:
            self._closed_threads.popitem(last=False)

    def _clear_tool_turns(self, thread):
        for key in tuple(self._tool_turns):
            if key[0] == thread:
                del self._tool_turns[key]

    @staticmethod
    def _valid_stamp(value):
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            and value > 0
        ):
            return float(value)
        return 0.0

    def _observe_compaction(self, payload):
        thread = str(payload.get("thread_id") or payload.get("session_id") or "")
        current = self.activities.get(thread)
        if current is None or current.expires:
            return False
        turn = str(payload.get("turn_id") or "")
        stamp = self._valid_stamp(payload.get("collected_at"))
        if turn and turn != current.turn_id:
            return False
        if not turn and not stamp:
            return False
        if stamp and (
            stamp < current.started_wall_at or stamp < current.compaction_last_stamp
        ):
            return False
        phase = payload["compaction_phase"]
        event_id = str(payload.get("event_id") or "")
        identity = (
            thread,
            current.turn_id,
            "compaction:" + phase,
            event_id or str(stamp),
        )
        if (event_id or stamp) and identity in self._seen:
            return False
        self._seen[identity] = self.now()
        while len(self._seen) > 4096:
            self._seen.popitem(last=False)
        if phase == "start":
            if current.state == "waiting" or current.compaction_since is not None:
                return False
            age = max(0, self.wall_now() - stamp) if stamp else 0
            current.compaction_since = self.now() - age
            current.compaction_turn_id = current.turn_id
            current.uncertain = age >= COMPACTION_GRACE_SECONDS
        else:
            current.compaction_since = None
            current.compaction_turn_id = ""
            current.uncertain = False
        current.compaction_last_stamp = stamp or self.wall_now()
        self._recovery_deadlines.pop(thread, None)
        current.last_seen_at = self.now()
        self.changed.emit()
        return True

    def _observe_heartbeat(self, payload):
        thread = str(payload.get("thread_id") or payload.get("session_id") or "")
        current = self.activities.get(thread)
        if current is None or current.expires:
            return True
        turn = str(payload.get("turn_id") or "")
        if current.turn_id and turn and current.turn_id != turn:
            return False
        self._recovery_deadlines.pop(thread, None)
        current.last_seen_at = self.now()
        if current.uncertain and current.compaction_since is None:
            current.uncertain = False
            self.uncertain_recovered_count += 1
            self.changed.emit()
        return True

    @property
    def visible_completions(self):
        at = self.now()
        return tuple(
            record
            for record in sorted(
                self.pending_completions.values(),
                key=lambda r: (-r.completed_at, r.thread_id),
            )
            if not record.dismissed and record.expires_at > at
        )

    def dismiss_completions(self, record_ids):
        identifiers = set(record_ids)
        for thread, record in self.pending_completions.items():
            if record.record_id in identifiers:
                self._diagnose_completion_removed(thread, record, "dismissed")
        pending = {
            key: r
            for key, r in self.pending_completions.items()
            if r.record_id not in identifiers
        }
        pending_changed = pending != self.pending_completions
        self.pending_completions = pending
        updated = tuple(
            replace(record, dismissed=True)
            if record.record_id in identifiers
            else record
            for record in self.completions
        )
        if updated != self.completions or pending_changed:
            self.completions = updated
            self.changed.emit()

    def _retire(self, thread, turn):
        self._retired[(thread, turn)] = None
        while len(self._retired) > 4096:
            self._retired.popitem(last=False)

    def expire(self):
        now = self.now()
        for thread, deadline in tuple(self._recovery_deadlines.items()):
            if deadline <= now:
                self._recovery_deadlines.pop(thread)
                self._trace(
                    "recovery_dropped",
                    thread_ref=trace_ref(thread),
                    source=thread_source(thread),
                    reason="recovery_expired",
                )
                self.activities.pop(thread, None)
                self._clear_tool_turns(thread)
                self.changed.emit()
        expired = [
            key
            for key, item in self.activities.items()
            if item.expires and item.expires <= now
        ]
        silent = [
            key
            for key, item in self.activities.items()
            if not item.expires and self._inactive(item, now)
        ]
        for key in silent:
            # Not a completion or failure: the source stopped reporting.
            self._trace(
                "activity_inactive",
                thread_ref=trace_ref(key),
                source=thread_source(key),
                turn_ref=trace_ref(self.activities[key].turn_id),
                reason="inactivity",
                state=self.activities[key].state,
            )
            self._remember_closed(key)
            del self.activities[key]
        stale = [
            key
            for key, item in self.activities.items()
            if not item.expires
            and item.source not in self.inactivity_limits
            and not item.uncertain
            and item.state != "waiting"
            and item.last_seen_at
            and now
            - (
                item.compaction_since
                if item.compaction_since is not None
                else item.last_seen_at
            )
            >= (
                COMPACTION_GRACE_SECONDS
                if item.compaction_since is not None
                else self.tool_stale_seconds
                if item.active_tools
                else self.running_stale_seconds
            )
        ]
        for key in stale:
            item = self.activities[key]
            if not item.uncertain:
                item.uncertain = True
                self.stale_expired_count += 1
                self._trace(
                    "activity_stale",
                    thread_ref=trace_ref(key),
                    turn_ref=trace_ref(item.turn_id),
                    state=item.state,
                    scope=item.scope,
                )
        for key in expired:
            self._trace(
                "activity_expired",
                thread_ref=trace_ref(key),
                source=thread_source(key),
                turn_ref=trace_ref(self.activities[key].turn_id),
                reason="result_expired",
                state=self.activities[key].state,
            )
            del self.activities[key]
        for thread, record in self.pending_completions.items():
            if record.expires_at <= now:
                self._diagnose_completion_removed(thread, record, "completion_expired")
        self.pending_completions = {
            key: r for key, r in self.pending_completions.items() if r.expires_at > now
        }
        self._unconfirmed_completions = OrderedDict(
            (key, record)
            for key, record in self._unconfirmed_completions.items()
            if record.expires_at > now
        )
        retained = (
            set(self.activities)
            | {r.thread_id for r in self.recent}
            | {r.thread_id for r in self.completions}
            | set(self.pending_completions)
            | set(self._unconfirmed_completions)
        )
        retained |= {
            self.metadata[k].parent_thread_id for k in retained if k in self.metadata
        }
        for key in set(self.metadata) - retained:
            del self.metadata[key]
        for key in set(self._first_display) - retained:
            del self._first_display[key]
            self._confirmed_scopes.pop(key, None)
        active_keys = {card.key for card in self.cards}
        self._project_order = {
            k: v for k, v in self._project_order.items() if k in active_keys
        }
        phase = tuple(
            (r.record_id, r.highlight_until > now) for r in self.visible_completions
        )
        phase_changed = phase != self._completion_phase
        self._completion_phase = phase
        if expired or silent or stale or phase_changed:
            self.changed.emit()

    def _inactive(self, item, now):
        limit = self.inactivity_limits.get(item.source)
        if limit is None or not item.last_seen_at:
            return False
        # Background work may run long; it waits like a confirmation does.
        limit_ms = (
            limit.waiting_ms
            if item.state in {"waiting", "background"}
            else limit.work_ms
        )
        return limit_ms > 0 and (now - item.last_seen_at) * 1000 >= limit_ms

    def diagnostics(self):
        self.mark_latency("", "prune")
        return {
            "stale_expired_count": self.stale_expired_count,
            "uncertain_recovered_count": self.uncertain_recovered_count,
            "rejected_events": dict(self.rejected_events),
            "latency": {key: dict(value) for key, value in self.latency.items()},
        }

    @diagnostic_guard
    def _diagnose_aggregation(self, thread, members, selected, metadata):
        if len(members) == 1 and selected.thread_id == thread:
            self.activity_diagnostics.forget("activity_aggregated", trace_ref(thread))
            return
        self.activity_diagnostics.record(
            "activity_aggregated",
            trace_ref(thread),
            thread_ref=trace_ref(thread),
            source=thread_source(thread),
            selected_ref=trace_ref(selected.thread_id),
            member_count=len(members),
            state=selected.state,
            uncertain=selected.uncertain,
            project_ref=trace_ref(metadata.project_key),
            generation=self.generation,
        )

    @property
    def cards(self):
        roots: dict[str, list[Activity]] = {}
        for item in self.activities.values():
            if item.state == "done":
                continue
            metadata = self.metadata.get(item.thread_id, ThreadMetadata(item.thread_id))
            root = metadata.parent_thread_id or item.thread_id
            if item.scope != "main" and not metadata.parent_thread_id:
                continue
            visited = {item.thread_id}
            while (
                root in self.metadata
                and self.metadata[root].parent_thread_id
                and root not in visited
            ):
                visited.add(root)
                root = self.metadata[root].parent_thread_id
            roots.setdefault(root, []).append(item)
        grouped: dict[str, list[ConversationRow]] = {}
        labels = {}
        kinds = {}
        sources = {}
        for thread, members in roots.items():
            metadata = self.metadata.get(thread, ThreadMetadata(thread))
            active = [m for m in members if not m.expires]
            waiting = [m for m in active if m.state == "waiting"]
            fresh = [m for m in active if not m.uncertain]
            selected = max(
                waiting or fresh or active or members,
                key=lambda m: (PRIORITY.get(m.state, 0), m.state_changed_at),
            )
            self._diagnose_aggregation(thread, members, selected, metadata)
            state = selected.state
            order = min(m.order for m in members)
            key = metadata.project_key
            grouped.setdefault(key, []).append(
                ConversationRow(
                    thread,
                    conversation_title(metadata.title),
                    state,
                    order,
                    self.activities.get(thread, selected).started_at
                    if state in {"running", "review"}
                    else selected.state_changed_at,
                    uncertain=selected.uncertain,
                    background_count=selected.background_count
                    if state == "background"
                    else 0,
                    compacting=bool(
                        thread in self.activities
                        and self.activities[thread].compaction_since is not None
                        and not self.activities[thread].uncertain
                        and state in {"running", "review"}
                    ),
                    source=metadata.source,
                )
            )
            labels[key] = metadata.label
            kinds[key] = metadata.card_kind
            sources[key] = metadata.source
            self._project_order.setdefault(key, order)
        for record in self.visible_completions:
            # A current parent/child activity takes precedence over an old result.
            if record.thread_id in roots:
                continue
            metadata = self.metadata.get(
                record.thread_id, ThreadMetadata(record.thread_id)
            )
            key = metadata.project_key
            order = self._sequence
            grouped.setdefault(key, []).append(
                ConversationRow(
                    record.thread_id,
                    conversation_title(metadata.title),
                    "done",
                    order,
                    record.completed_at,
                    record.record_id,
                    record.highlight_until > self.now(),
                    record.highlight_until,
                    source=metadata.source,
                )
            )
            labels[key] = metadata.label
            kinds[key] = metadata.card_kind
            sources[key] = metadata.source
            self._project_order.setdefault(key, order)
        cards = [
            ProjectCard(
                key,
                labels[key],
                tuple(
                    sorted(
                        rows,
                        key=lambda r: (
                            -ROW_PRIORITY.get(r.state, 0),
                            -r.sort_at,
                            r.thread_id,
                        ),
                    )
                ),
                self._project_order[key],
                kinds[key],
                sources[key],
            )
            for key, rows in grouped.items()
        ]
        return tuple(
            sorted(
                cards,
                key=lambda c: (-max(PRIORITY.get(r.state, 0) for r in c.rows), c.order),
            )
        )

    @property
    def bubble_cards(self):
        """Group unresolved conversations without delaying their first frame."""
        cards = []
        unknown: list[ConversationRow] = []
        order = self._sequence
        for card in self.cards:
            if card.kind != "unknown":
                cards.append(card)
                continue
            rows = tuple(
                r
                for r in card.rows
                if self.now() >= self._first_display.get(r.thread_id, 0)
            )
            unknown.extend(rows)
            if rows:
                order = min(order, card.order)
        if unknown:
            rows = tuple(
                sorted(
                    unknown,
                    key=lambda r: (
                        -ROW_PRIORITY.get(r.state, 0),
                        -r.sort_at,
                        r.thread_id,
                    ),
                )
            )
            cards.append(
                ProjectCard(
                    "unknown:pending", "프로젝트 확인 중", rows, order, "unknown"
                )
            )
        return tuple(
            sorted(
                cards,
                key=lambda c: (-max(PRIORITY.get(r.state, 0) for r in c.rows), c.order),
            )
        )
