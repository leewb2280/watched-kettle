"""Claude Code task history from local transcripts; lives in the usage worker.

The service imports turns incrementally with a per-tick time and byte budget,
keeps session titles and folder names in memory only, and answers the same
project → conversation → task queries the Codex history uses. Rate-limit
samples arrive from the status line bridge (stage 13).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
import logging
from pathlib import Path
from time import monotonic

from PySide6.QtCore import QObject, QTimer, Signal

from watched_kettle.application.logging import log_event
from watched_kettle.features.notifications.models import NoticeRequest
from watched_kettle.integrations.claude_code_transcript import claude_config_dir
from watched_kettle.storage.claude_code_repository import FileState
from watched_kettle.usage.claude_code_limits import (
    QuotaSample,
    account_hash,
    bucket,
    samples_from_payload,
    threshold_notices,
)
from watched_kettle.usage.claude_code_transcripts import (
    MAIN_PART,
    FilePass,
    read_custom_title,
    transcript_files,
)
from watched_kettle.usage.conversation_models import (
    ConversationUsage,
    ProjectUsageSummary,
    sort_projects,
)
from watched_kettle.usage.identifiers import hash_identifier
from watched_kettle.usage.models import TaskUsageRecord, UsageAvailability
from watched_kettle.usage.task_query import ORDERS, PAGE_SIZE, search_text
from watched_kettle.usage.trends import (
    AVERAGE_DAYS,
    hourly_profile,
    hours_by_day,
    remaining_series,
)

# Daily sums kept for the overview: the longest range (30 days) plus the six
# days its first moving average needs.
DAILY_DAYS = 37


ACCOUNT_KEY = "claude_code"
TICK_BUDGET_SECONDS = 0.03
TICK_BUDGET_BYTES = 1024 * 1024
BUSY_INTERVAL_MS = 50
IDLE_INTERVAL_MS = 15_000
HOOK_DELAY_MS = 1_500
# A last turn without ``end_turn`` counts as running until the file is quiet
# for the default working inactivity limit.
RUNNING_IDLE_SECONDS = 10 * 60
MAX_FILES = 4096
# Status lines run after every response; an unchanged value is stored at most
# this often so 8 days of samples stay small.
UNCHANGED_SAMPLE_SECONDS = 10 * 60
NAME_SCAN_BYTES = 256 * 1024
DEFAULT_TITLE = "Claude Code 대화"
DEFAULT_PROJECT = "Claude Code 작업"
_TASK_SORT = {
    "recent": ("completed_at", True),
    "top": ("total_tokens", True),
    "time_asc": ("completed_at", False),
    "input": ("input_tokens", True),
    "output": ("output_tokens", True),
}
_COLUMN_FIELDS = (
    "completed_at",
    "outcome",
    "data_quality",
    "total_tokens",
    "input_tokens",
    "output_tokens",
    "model",
)


@dataclass(frozen=True)
class ClaudeCodeUsageSnapshot:
    availability: UsageAvailability = field(
        default_factory=lambda: UsageAvailability(
            "starting", "기록을 준비하는 중입니다."
        )
    )
    projects: tuple = ()
    project_search: str = ""
    project_order: str = "recent"
    project_offset: int = 0
    projects_has_more: bool = False
    project_count: int = 0
    selected_project_key: str = ""
    conversations: tuple = ()
    conversation_search: str = ""
    conversation_order: str = "recent"
    conversation_offset: int = 0
    conversations_has_more: bool = False
    selected_thread_hash: str = ""
    recent_tasks: tuple = ()
    latest_tasks: tuple = ()
    task_history_search: str = ""
    task_history_order: str = "recent"
    task_history_limit: int = PAGE_SIZE
    task_history_has_more: bool = False
    import_remaining: int = 0
    history_message: str = ""
    # Status line rate limits as a Codex-shaped bucket; empty until observed.
    buckets: tuple = ()
    limits_observed_at: datetime | None = None
    # Tokens of turns finished today, by local hour; empty until one finishes.
    today_hourly_tokens: tuple = ()
    # Overview trends (usage.trends): today against recent days, each limit's
    # remaining percent today, and daily tokens of this PC.
    trend_hours: dict | None = None
    trend_quota: dict | None = None
    daily_tokens: tuple = ()
    account_hash: str = ""


def trend_values(turns, now=None):
    """Hourly profile and daily sums for the overview charts (this PC only)."""
    local_now = (now or datetime.now(timezone.utc)).astimezone()
    tz = local_now.tzinfo
    today = local_now.date()
    points = [(turn.completed_at, turn.total_tokens) for turn in turns]
    previous = [today - timedelta(days=offset) for offset in range(1, AVERAGE_DAYS + 1)]
    by_day = hours_by_day(points, [today, *previous], tz)
    profile = hourly_profile(
        by_day[today] or [0] * 24,
        [by_day[day] for day in previous],
        local_now.hour,
        day=today,
    )
    totals: dict[date, int] = {}
    for moment, tokens in points:
        day = moment.astimezone(tz).date()
        totals[day] = totals.get(day, 0) + int(tokens or 0)
    first = min(totals, default=today)
    daily = tuple(
        (day, totals.get(day, 0) if day >= first else None)
        for day in (today - timedelta(days=offset) for offset in range(DAILY_DAYS))
    )
    return profile, daily


def today_hourly_tokens(turns, now=None):
    """Sum today's finished turns by local hour; () when none finished today."""
    local_now = (now or datetime.now(timezone.utc)).astimezone()
    hours = [0] * 24
    seen = False
    for turn in turns:
        finished = turn.completed_at.astimezone(local_now.tzinfo)
        if finished.date() == local_now.date():
            hours[finished.hour] += int(turn.total_tokens or 0)
            seen = True
    return tuple(hours) if seen else ()


class ClaudeCodeUsageService(QObject):
    snapshot_changed = Signal(object)
    notice_requested = Signal(object)

    def __init__(self, repository, config_dir=None, enabled=True, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.config_dir = Path(config_dir) if config_dir else claude_config_dir()
        self.enabled = bool(enabled)
        self.snapshot = ClaudeCodeUsageSnapshot()
        self.titles: dict[str, str] = {}
        self.project_names: dict[str, str] = {}
        self._queue: list = []
        self._pass: FilePass | None = None
        self._job: tuple = ()
        self._named: set[str] = set()
        self._closed = False
        self._account = ""
        self._account_stamp = None
        self._latest: dict[str, QuotaSample] = {}
        # Recent samples of every window, for the overview's remaining line.
        self._history: list[QuotaSample] = []
        self._stored: dict[str, QuotaSample] = {}
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.tick)

    # Lifecycle ---------------------------------------------------------------

    def start(self):
        if self.repository is None:
            self._publish(
                availability=UsageAvailability(
                    "offline",
                    "기록 저장소를 사용할 수 없어 Claude Code 기록을 모으지 않습니다.",
                )
            )
            return
        if not self.enabled:
            self.set_enabled(False)
            return
        self._load_limits(self._current_account())
        self._schedule(0)

    def close(self):
        self._closed = True
        self.timer.stop()

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        if not self.enabled:
            self.timer.stop()
            self._pass = None
            self._queue.clear()
            self._publish(
                availability=UsageAvailability(
                    "disabled", "사용량 비서가 꺼져 있습니다."
                )
            )
        else:
            self._schedule(0)

    def observe_agent_payload(self, payload):
        """A Claude Code hook means a transcript changed; look again soon."""
        if (
            self.enabled
            and isinstance(payload, dict)
            and payload.get("source") == "claude_code"
            and payload.get("event") == "rate_limits"
        ):
            self._observe_limits(payload)
            return
        if (
            self.enabled
            and isinstance(payload, dict)
            and payload.get("source") == "claude_code"
            and not self._queue
            and self._pass is None
        ):
            self._schedule(HOOK_DELAY_MS)

    def refresh(self):
        if not self.enabled or self._closed:
            return False
        self._schedule(0)
        return True

    # Rate limits --------------------------------------------------------------

    def _current_account(self):
        """Re-read the account only when Claude Code rewrote its account file."""
        stamps = []
        for candidate in (
            self.config_dir / ".claude.json",
            self.config_dir.parent / ".claude.json",
        ):
            try:
                stamps.append(candidate.stat().st_mtime_ns)
            except OSError:
                stamps.append(None)
        if stamps != self._account_stamp or not self._account:
            self._account_stamp = stamps
            self._account = account_hash(self.config_dir)
        return self._account

    def _load_limits(self, account):
        self._latest = {}
        self._stored = {}
        self._history = []
        if self.repository is not None:
            since = datetime.now(timezone.utc) - timedelta(days=8)
            try:
                rows = self.repository.quota_samples(account, since)
            except Exception as error:  # noqa: BLE001 - limits are optional
                log_event(
                    "usage.claude_code",
                    "limits_load_failed",
                    logging.WARNING,
                    error_code=type(error).__name__,
                )
                rows = ()
            for window, observed, percent, resets in rows:
                self._latest[window] = QuotaSample(window, observed, percent, resets)
                self._history.append(self._latest[window])
        self._stored = dict(self._latest)
        self._publish_limits()

    def _observe_limits(self, payload):
        account = self._current_account()
        if account != self.snapshot.account_hash:
            self._load_limits(account)
        samples = samples_from_payload(payload)
        for sample in samples:
            for notice in threshold_notices(self._latest.get(sample.window), sample):
                self.notice_requested.emit(
                    NoticeRequest(
                        source="system",
                        session_id="claude-code-usage",
                        urgency=notice.urgency,
                        message=notice.message,
                        deduplication_key=notice.deduplication_key,
                        replacement_key=notice.replacement_key,
                        category="usage",
                    )
                )
            self._latest[sample.window] = sample
            self._history.append(sample)
        # Two days are enough for today's line; keep memory bounded.
        cutoff = datetime.now(timezone.utc) - timedelta(days=2)
        self._history = [s for s in self._history if s.observed_at >= cutoff][-2000:]
        changed = [sample for sample in samples if self._worth_storing(sample)]
        if self.repository is not None and changed:
            try:
                self.repository.append_quota_samples(account, changed)
                self._stored.update({sample.window: sample for sample in changed})
            except Exception as error:  # noqa: BLE001 - keep the live value
                log_event(
                    "usage.claude_code",
                    "limits_save_failed",
                    logging.WARNING,
                    error_code=type(error).__name__,
                )
        self._publish_limits()

    def _worth_storing(self, sample):
        previous = self._stored.get(sample.window)
        return (
            previous is None
            or previous.used_percent != sample.used_percent
            or previous.resets_at != sample.resets_at
            or (sample.observed_at - previous.observed_at).total_seconds()
            >= UNCHANGED_SAMPLE_SECONDS
        )

    def _publish_limits(self):
        buckets = bucket(self._latest)
        observed = max((s.observed_at for s in self._latest.values()), default=None)
        quota = self._quota_trend()
        if (
            buckets != self.snapshot.buckets
            or observed != self.snapshot.limits_observed_at
            or self._account != self.snapshot.account_hash
            or quota != self.snapshot.trend_quota
        ):
            self._publish(
                buckets=buckets,
                limits_observed_at=observed,
                account_hash=self._account,
                trend_quota=quota,
            )

    def _quota_trend(self):
        now = datetime.now(timezone.utc).astimezone()
        return {
            window: remaining_series(
                [
                    (s.observed_at, s.used_percent, s.resets_at)
                    for s in self._history
                    if s.window == window
                ],
                now.date(),
                now.tzinfo,
                now,
            )
            for window in ("five_hour", "seven_day")
        }

    # Import -----------------------------------------------------------------

    def _schedule(self, delay_ms):
        if self._closed or not self.enabled or self.repository is None:
            return
        if not self.timer.isActive() or self.timer.remainingTime() > delay_ms:
            self.timer.start(int(delay_ms))

    def tick(self):
        if self._closed or not self.enabled or self.repository is None:
            return
        deadline = monotonic() + TICK_BUDGET_SECONDS
        changed = False
        try:
            if not self._queue and self._pass is None:
                self._publish_limits()
                self._queue = self._changed_files()
                if not self._queue:
                    self._refresh(ready=True)
                    self._schedule(IDLE_INTERVAL_MS)
                    return
            while monotonic() < deadline and (self._queue or self._pass):
                if self._pass is None:
                    self._begin(*self._queue.pop(0))
                    continue
                if self._pass.read(TICK_BUDGET_BYTES):
                    self._finish_pass()
                    changed = True
        except Exception as error:  # noqa: BLE001 - never stop the worker
            log_event(
                "usage.claude_code",
                "import_failed",
                logging.WARNING,
                error_code=type(error).__name__,
            )
            self._pass = None
            changed = True
        remaining = len(self._queue) + (self._pass is not None)
        if changed or remaining != self.snapshot.import_remaining:
            self._refresh(ready=not remaining, remaining=remaining)
        self._schedule(BUSY_INTERVAL_MS if remaining else IDLE_INTERVAL_MS)

    def _changed_files(self):
        cutoff = self.repository.cutoff.timestamp()
        work = []
        for count, (path, session_id, part) in enumerate(
            transcript_files(self.config_dir)
        ):
            if count >= MAX_FILES:
                break
            try:
                stat = path.stat()
            except OSError:
                continue
            if stat.st_mtime < cutoff:
                continue
            if part == MAIN_PART:
                self._remember_names(path, session_id)
            file_hash = hash_identifier(str(path))
            state = self.repository.file_state(file_hash)
            idle = datetime.now().timestamp() - stat.st_mtime >= RUNNING_IDLE_SECONDS
            if (
                state is not None
                and state.size == stat.st_size
                and state.mtime_ns == stat.st_mtime_ns
                and not (state.open_turn and idle)
            ):
                continue
            work.append((path, session_id, part, file_hash, stat, state))
        return work

    def _begin(self, path, session_id, part, file_hash, stat, state):
        rewritten = state is not None and stat.st_size < state.size
        offset = 0 if state is None or rewritten else state.resume_offset
        self._pass = FilePass(path, session_id, part, offset)
        self._job = (file_hash, stat, rewritten)

    def _finish_pass(self):
        current, self._pass = self._pass, None
        if current is None:
            return
        file_hash, stat, rewritten = self._job
        idle = datetime.now().timestamp() - stat.st_mtime >= RUNNING_IDLE_SECONDS
        parts = current.finish(idle)
        if current.part == MAIN_PART:
            session_hash = current.session_hash
            if current.title:
                self.titles[session_hash] = current.title
            if current.project_hash and current.project_label:
                self.project_names[current.project_hash] = current.project_label
            custom = read_custom_title(current.path.with_suffix(""))
            if custom:
                self.titles[session_hash] = custom
        open_turn = any(part.outcome == "running" for part in parts)
        self.repository.save_pass(
            file_hash,
            parts,
            FileState(stat.st_size, stat.st_mtime_ns, current.resume_offset, open_turn),
            rewritten=rewritten,
        )

    def _remember_names(self, path, session_id):
        """Read titles near the end and the folder near the start, once per run."""
        session_hash = hash_identifier(session_id)
        if session_hash in self._named:
            return
        self._named.add(session_hash)
        try:
            size = path.stat().st_size
            head = FilePass(path, session_id, MAIN_PART, 0)
            head.read(min(size, 64 * 1024) or 1)
            tail = FilePass(path, session_id, MAIN_PART, max(0, size - NAME_SCAN_BYTES))
            tail.read(NAME_SCAN_BYTES)
        except OSError:
            return
        title = read_custom_title(path.with_suffix("")) or tail.title or head.title
        if title:
            self.titles[session_hash] = title
        for scan in (head, tail):
            if scan.project_hash and scan.project_label:
                self.project_names[scan.project_hash] = scan.project_label

    # Queries ----------------------------------------------------------------

    def set_project_query(self, search="", order="recent", offset=0, custom=None):
        del custom
        self._publish(
            project_search=str(search)[:200],
            project_order=order if order in {"recent", "name"} else "recent",
            project_offset=max(0, int(offset)),
        )
        self._refresh()

    def select_usage_project(self, key):
        self._publish(
            selected_project_key=str(key),
            conversation_offset=0,
            selected_thread_hash="",
            recent_tasks=(),
        )
        self._refresh()

    def set_conversation_query(self, search="", order="recent", offset=0):
        self._publish(
            conversation_search=str(search)[:200],
            conversation_order=order if order in {"recent", "top"} else "recent",
            conversation_offset=max(0, int(offset)),
        )
        self._refresh()

    def select_usage_conversation(self, thread_hash):
        self._publish(
            selected_thread_hash=str(thread_hash),
            task_history_search="",
            task_history_order="recent",
            task_history_limit=PAGE_SIZE,
        )
        self._refresh()

    def set_task_query(
        self, search="", order="recent", limit=PAGE_SIZE, thread_hash=None
    ):
        self._publish(
            task_history_search=str(search)[:200],
            task_history_order=order if order in ORDERS else "recent",
            task_history_limit=max(PAGE_SIZE, int(limit)),
            selected_thread_hash=str(thread_hash or self.snapshot.selected_thread_hash),
        )
        self._refresh()

    def clear_history(self):
        if self.repository is None:
            return
        self.repository.clear()
        self._publish(
            selected_project_key="",
            selected_thread_hash="",
            history_message="Claude Code 작업 기록을 지웠습니다. 이후 작업부터 다시 기록합니다.",
        )
        self._refresh()

    def _refresh(self, ready=None, remaining=None):
        if self.repository is None:
            return
        snapshot = self.snapshot
        turns = self.repository.turns()
        projects = self._projects(turns, snapshot.project_search)
        ordered = sort_projects(projects, snapshot.project_order)
        page = ordered[snapshot.project_offset : snapshot.project_offset + PAGE_SIZE]
        selected = snapshot.selected_project_key
        if selected not in {p.project_key for p in ordered}:
            selected = page[0].project_key if page else ""
        # A project found by its own name lists all of its conversations; one
        # found through a conversation title lists only the matching ones.
        search = snapshot.conversation_search or snapshot.project_search
        if (
            not snapshot.conversation_search
            and search.casefold() in self._name(selected).casefold()
        ):
            search = ""
        conversations = self._conversations(
            [t for t in turns if (t.project_hash or "none") == selected],
            search,
            snapshot.conversation_order,
        )
        offset = snapshot.conversation_offset
        tasks = ()
        has_more = False
        if snapshot.selected_thread_hash:
            records = [
                _record(t)
                for t in turns
                if t.session_hash == snapshot.selected_thread_hash
            ]
            if snapshot.task_history_search:
                needle = snapshot.task_history_search.casefold()
                records = [r for r in records if needle in search_text(r)]
            records = _sort_tasks(records, snapshot.task_history_order)
            tasks = tuple(records[: snapshot.task_history_limit])
            has_more = len(records) > snapshot.task_history_limit
        changes = dict(
            projects=tuple(page),
            project_count=len(ordered),
            projects_has_more=len(ordered) > snapshot.project_offset + PAGE_SIZE,
            selected_project_key=selected,
            conversations=tuple(conversations[offset : offset + PAGE_SIZE]),
            conversations_has_more=len(conversations) > offset + PAGE_SIZE,
            recent_tasks=tasks,
            task_history_has_more=has_more,
            latest_tasks=tuple(_record(t) for t in turns[:20]),
            today_hourly_tokens=today_hourly_tokens(turns),
        )
        changes["trend_hours"], changes["daily_tokens"] = trend_values(turns)
        # Also on turn refreshes, so the line moves to a new day without a sample.
        changes["trend_quota"] = self._quota_trend()
        if remaining is not None:
            changes["import_remaining"] = remaining
        if ready is not None:
            changes["availability"] = (
                UsageAvailability(
                    "ready", "이 기기의 Claude Code 대화 기록에서 관측한 작업"
                )
                if ready
                else UsageAvailability(
                    "importing", "Claude Code 대화 기록을 읽는 중입니다."
                )
            )
        self._publish(**changes)

    def _projects(self, turns, search):
        groups: dict[str, dict] = {}
        for turn in turns:
            key = turn.project_hash or "none"
            group = groups.setdefault(key, {"sessions": set(), "at": turn.completed_at})
            group["sessions"].add(turn.session_hash)
            group["at"] = max(group["at"], turn.completed_at)
        needle = search.casefold()
        projects = []
        for key, group in groups.items():
            name = self._name(key)
            titles = [self.titles.get(s, DEFAULT_TITLE) for s in group["sessions"]]
            matched = sum(needle in t.casefold() for t in titles)
            if needle and needle not in name.casefold() and not matched:
                continue
            projects.append(
                ProjectUsageSummary(
                    key, name, len(group["sessions"]), matched, group["at"]
                )
            )
        return projects

    def _conversations(self, turns, search, order):
        groups: dict[str, list] = {}
        for turn in turns:
            groups.setdefault(turn.session_hash, []).append(turn)
        needle = search.casefold()
        rows = []
        for session, items in groups.items():
            title = self.titles.get(session, DEFAULT_TITLE)
            if needle and needle not in title.casefold():
                continue
            project = items[0].project_hash or "none"
            rows.append(
                ConversationUsage(
                    session,
                    title,
                    project,
                    self._name(project),
                    max(t.completed_at for t in items),
                    len(items),
                    len(items),
                    0,
                    0,
                    sum(t.total_tokens for t in items),
                )
            )
        if order == "top":
            rows.sort(key=lambda r: (-(r.total_tokens or 0), r.thread_hash))
        else:
            rows.sort(key=lambda r: (r.completed_at, r.thread_hash), reverse=True)
        return rows

    def _name(self, project_key):
        if project_key in {"", "none"}:
            return DEFAULT_PROJECT
        return self.project_names.get(project_key, DEFAULT_PROJECT)

    def _publish(self, **changes):
        self.snapshot = replace(self.snapshot, **changes)
        self.snapshot_changed.emit(self.snapshot)


def _record(turn):
    return TaskUsageRecord(
        completed_at=turn.completed_at,
        account_hash=ACCOUNT_KEY,
        thread_hash=turn.session_hash,
        outcome=turn.outcome,
        input_tokens=turn.input_tokens,
        net_new_input_tokens=turn.net_new_input_tokens,
        cached_input_tokens=turn.cached_input_tokens,
        output_tokens=turn.output_tokens,
        total_tokens=turn.total_tokens,
        model=turn.model,
        data_quality="measured",
        turn_hash=turn.turn_hash,
        quality_reason="claude_code_transcript",
    )


def _sort_tasks(records, order):
    if order.startswith("column_"):
        _, column, direction = order.split("_")
        name, descending = _COLUMN_FIELDS[int(column)], direction == "desc"
    else:
        name, descending = _TASK_SORT.get(order, _TASK_SORT["recent"])
    present = [r for r in records if getattr(r, name) is not None]
    missing = [r for r in records if getattr(r, name) is None]
    present.sort(
        key=lambda r: (getattr(r, name), r.completed_at, r.turn_hash),
        reverse=descending,
    )
    return present + missing
