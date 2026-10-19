"""Assistant notice prioritization, lifecycle merging, and history."""

from watched_kettle.localization import t

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
import math

from PySide6.QtCore import QObject, QRect, QTimer
from PySide6.QtWidgets import QApplication

from watched_kettle.app_preferences import (
    DEFAULT_BUBBLE_DURATION_SECONDS,
    DEFAULT_BUBBLE_SCALE,
    normalize_bubble_duration_seconds,
    normalize_bubble_scale,
)
from watched_kettle.ui.bubble_models import BubbleNotice, source_display_label
from watched_kettle.ui.speech_bubble_window import (
    BUBBLE_GAP,
    BUBBLE_STACK_GAP,
    SpeechBubbleWindow,
    bubble_stack_positions,
)
from watched_kettle.pet.bubble_theme import DEFAULT_BUBBLE_THEME


MAX_VISIBLE_BUBBLES = 3
MAX_ASSISTANT_HISTORY = 20


class PetBubbleController(QObject):
    """Prioritize, merge, and position a small stack of assistant notices."""

    def __init__(
        self,
        pet,
        enabled=True,
        scale_percent=DEFAULT_BUBBLE_SCALE,
        duration_seconds=DEFAULT_BUBBLE_DURATION_SECONDS,
        theme=DEFAULT_BUBBLE_THEME,
        element_registry=None,
        max_history=MAX_ASSISTANT_HISTORY,
        now=None,
        parent=None,
    ):
        super().__init__(parent)
        self.pet = pet
        self.enabled = bool(enabled)
        self.scale_percent = normalize_bubble_scale(scale_percent)
        self.duration_seconds = normalize_bubble_duration_seconds(duration_seconds)
        self.theme = theme or DEFAULT_BUBBLE_THEME
        self.element_registry = element_registry
        self.max_history = max(1, int(max_history))
        self._now = now or datetime.now
        # Agent source dots; the runtime turns them on when both are in use.
        self.source_marks_shown = False
        self._fallback_window = SpeechBubbleWindow(
            pet,
            scale_percent=self.scale_percent,
            theme=self.theme,
            element_registry=self.element_registry,
        )
        self._window_pool = [self._fallback_window]
        self._entries = {}
        self._sequence = 0
        self._history = []
        self._history_fingerprints = {}
        self._snoozed_until = None
        self._snooze_timer = QTimer(self)
        self._snooze_timer.setSingleShot(True)
        self._snooze_timer.timeout.connect(self.resume)

    @property
    def window(self):
        entries = self._visible_entries()
        return entries[0].window if entries else self._fallback_window

    @property
    def visible_windows(self):
        """Return currently presented windows in assistant priority order."""
        return tuple(
            entry.window
            for entry in self._visible_entries()
            if entry.window.isVisible()
        )

    @property
    def current_notice(self):
        entries = self._visible_entries()
        return entries[0].notice if entries else None

    @property
    def persistent_notice(self):
        entries = [
            entry
            for entry in self._ordered_entries()
            if entry.notice.persistent and entry.notice.kind != "preview"
        ]
        return entries[0].notice if entries else None

    @property
    def assistant_summary(self):
        """Return a privacy-safe count summary for tray and diagnostics."""
        counts = {}
        for entry in self._ordered_entries():
            notice = entry.notice
            if notice.kind == "preview":
                continue
            counts[notice.kind] = counts.get(notice.kind, 0) + max(
                1,
                int(notice.count or 1),
            )
        labels = (
            ("error", t("message.0316")),
            ("waiting", t("message.0317")),
            ("notification", t("message.0318")),
            ("done", t("message.0319")),
            ("cancelled", t("message.0320")),
        )
        parts = [
            t("message.0306", value0=label, value1=counts[kind])
            for kind, label in labels
            if counts.get(kind)
        ]
        return " · ".join(parts)

    @property
    def recent_history(self):
        """Return newest-first, privacy-safe notices kept only in memory."""
        return tuple(reversed(self._history))

    def clear_history(self):
        self._history.clear()
        refresh_controls = getattr(self.pet, "refresh_controls", None)
        if callable(refresh_controls):
            refresh_controls()

    def clear_notices(self):
        """Dismiss active assistant notices without erasing recent history."""
        for key in tuple(self._entries):
            self._remove(key)
        self._render()

    @property
    def is_snoozed(self):
        return self._snoozed_until is not None and self._snoozed_until > self._now()

    @property
    def snooze_remaining_minutes(self):
        if not self.is_snoozed:
            return 0
        seconds = (self._snoozed_until - self._now()).total_seconds()
        return max(1, math.ceil(seconds / 60))

    def snooze(self, duration_ms):
        duration_ms = max(0, int(duration_ms))
        if duration_ms <= 0:
            self.resume()
            return
        self._snoozed_until = self._now() + timedelta(milliseconds=duration_ms)
        self._snooze_timer.start(duration_ms)
        self._render()

    def resume(self):
        self._snooze_timer.stop()
        self._snoozed_until = None
        self._render()

    def apply(self, presentation):
        persistent_notices = tuple(
            getattr(presentation, "persistent_notices", ()) or ()
        )
        if not persistent_notices and presentation.persistent_notice is not None:
            persistent_notices = (presentation.persistent_notice,)
        self._sync_persistent(persistent_notices)
        if presentation.notice is not None:
            self._upsert(presentation.notice)
        self._render()

    def preview(self, message, duration_ms=7_000):
        """Show an explicit UI-only preview without changing agent state."""
        self.preview_messages((message,), duration_ms=duration_ms)

    def preview_messages(self, messages, duration_ms=7_000):
        """Preview a complete assistant stack without changing agent state."""
        for key, entry in tuple(self._entries.items()):
            if entry.notice.kind == "preview":
                self._remove(key)
        values = [str(message or "").strip() for message in messages]
        values = [message for message in values if message][:MAX_VISIBLE_BUBBLES]
        for index, message in enumerate(values):
            notice = BubbleNotice(
                message=message[:120],
                source="preview",
                event="preview",
                session_id=f"settings-preview-{index}",
                duration_ms=max(1, int(duration_ms)),
                kind="preview",
                priority=120 - index,
                replace_key=f"preview:settings:{index}",
            )
            self._upsert(notice, force_visible=True)
        self._render()

    def finish_transient(self):
        preview_keys = [
            key
            for key, entry in self._entries.items()
            if entry.notice.kind == "preview"
        ]
        transient_keys = preview_keys or [
            key for key, entry in self._entries.items() if not entry.notice.persistent
        ]
        for key in transient_keys:
            self._remove(key)
        self._render()

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        if self.enabled and self.is_snoozed:
            self._snooze_timer.stop()
            self._snoozed_until = None
        self._render()

    def set_scale_percent(self, scale_percent):
        scale_percent = normalize_bubble_scale(scale_percent)
        if scale_percent == self.scale_percent:
            return
        self.scale_percent = scale_percent
        windows = {self._fallback_window}
        windows.update(self._window_pool)
        windows.update(entry.window for entry in self._entries.values())
        for window in windows:
            window.set_scale_percent(scale_percent)
        self._render()

    def set_duration_seconds(self, duration_seconds):
        duration_seconds = normalize_bubble_duration_seconds(duration_seconds)
        if duration_seconds == self.duration_seconds:
            return
        self.duration_seconds = duration_seconds

    def set_duration_policy(self, policy):
        self.set_duration_seconds(policy.common)

    def set_theme(self, theme):
        theme = theme or DEFAULT_BUBBLE_THEME
        if theme == self.theme:
            return
        self.theme = theme
        windows = {self._fallback_window}
        windows.update(self._window_pool)
        windows.update(entry.window for entry in self._entries.values())
        for window in windows:
            window.set_theme(theme)
        self._render()

    def set_source_marks_shown(self, shown):
        """Mark Codex and Claude Code with dots; only when both are in use."""
        shown = bool(shown)
        if shown == self.source_marks_shown:
            return
        self.source_marks_shown = shown
        windows = {self._fallback_window}
        windows.update(self._window_pool)
        windows.update(entry.window for entry in self._entries.values())
        for window in windows:
            window.set_source_marks_shown(shown)
        self._render()

    def refresh_element_assets(self):
        windows = {self._fallback_window}
        windows.update(self._window_pool)
        windows.update(entry.window for entry in self._entries.values())
        for window in windows:
            window.update()

    def owner_shown(self):
        self._render()

    def owner_hidden(self):
        for entry in self._entries.values():
            entry.window.hide()
        self._fallback_window.hide()

    def reposition(self):
        visible_entries = [
            entry for entry in self._visible_entries() if entry.window.isVisible()
        ]
        if not visible_entries:
            return
        screen = (
            QApplication.screenAt(self.pet.frameGeometry().center())
            or self.pet.screen()
            or QApplication.primaryScreen()
        )
        if screen is None:
            return
        avoid_rects = []
        caption_controller = getattr(
            self.pet,
            "activity_caption_controller",
            None,
        )
        if caption_controller is not None and caption_controller.window.isVisible():
            avoid_rects.append(caption_controller.window.frameGeometry())
        for entry in visible_entries:
            entry.window.set_tail_side(None)

        def calculate_positions():
            return bubble_stack_positions(
                self.pet.frameGeometry(),
                [entry.window.size() for entry in visible_entries],
                screen.availableGeometry(),
                avoid_rects=avoid_rects,
                gap=max(1, round(BUBBLE_GAP * self.scale_percent / 100)),
                stack_gap=max(
                    1,
                    round(BUBBLE_STACK_GAP * self.scale_percent / 100),
                ),
                alignment=self.theme.stack_alignment,
            )

        positions = calculate_positions()
        primary = visible_entries[0]
        pet_rect = self.pet.frameGeometry()
        primary_rect = QRect(positions[0], primary.window.size())
        tail_side = self._tail_side_for(primary_rect, pet_rect)
        primary.window.set_tail_side(tail_side)

        positions = calculate_positions()
        primary_rect = QRect(positions[0], primary.window.size())
        final_tail_side = self._tail_side_for(primary_rect, pet_rect)
        if final_tail_side != tail_side:
            primary.window.set_tail_side(final_tail_side)
            positions = calculate_positions()

        for entry, position in zip(visible_entries, positions):
            entry.window.move(position)

    @staticmethod
    def _tail_side_for(primary_rect, pet_rect):
        if primary_rect.bottom() < pet_rect.top():
            return "bottom"
        if primary_rect.top() > pet_rect.bottom():
            return "top"
        if primary_rect.right() < pet_rect.left():
            return "right"
        return "left"

    def sync_always_on_top(self, enabled):
        windows = {self._fallback_window}
        windows.update(entry.window for entry in self._entries.values())
        for window in windows:
            window.sync_always_on_top(enabled)
        self.reposition()

    def sync_click_through(self, enabled):
        windows = {self._fallback_window}
        windows.update(entry.window for entry in self._entries.values())
        windows.update(self._window_pool)
        for window in windows:
            window.sync_click_through(enabled)
        self.reposition()

    def close(self):
        self._snooze_timer.stop()
        for key in tuple(self._entries):
            self._remove(key)
        for window in set(self._window_pool + [self._fallback_window]):
            window.close()

    def _sync_persistent(self, notices):
        incoming = {self._notice_key(notice): notice for notice in notices}
        stale = [
            key
            for key, entry in self._entries.items()
            if entry.notice.persistent
            and entry.notice.kind != "preview"
            and key not in incoming
        ]
        for key in stale:
            self._remove(key)
        for notice in incoming.values():
            self._upsert(notice)

    def _upsert(self, notice, force_visible=False):
        if notice.kind in {"waiting", "error", "done", "cancelled"}:
            self._retire_start_member(notice.source, notice.session_id)
        if notice.kind in {"start", "done"}:
            members = notice.member_ids or (notice.session_id,)
            notice = replace(
                notice,
                count=len(members),
                member_ids=tuple(members),
                message=self._lifecycle_summary(
                    notice.source,
                    notice.kind,
                    len(members),
                ),
            )
        key = self._notice_key(notice)
        existing = self._entries.get(key)
        self._sequence += 1
        if existing is not None:
            notice = self._merged_notice(existing.notice, notice)
            self._record_history(key, notice)
            existing.notice = notice
            existing.sequence = self._sequence
            existing.force_visible = existing.force_visible or force_visible
            existing.window.set_message(
                notice.message,
                notice.kind,
                notice.source,
            )
            self._restart_timer(existing)
            return

        self._record_history(key, notice)
        window = self._acquire_window()
        window.set_message(notice.message, notice.kind, notice.source)
        timer = QTimer(self)
        timer.setSingleShot(True)
        entry = _BubbleEntry(
            key=key,
            notice=notice,
            window=window,
            timer=timer,
            sequence=self._sequence,
            force_visible=force_visible,
        )
        timer.timeout.connect(lambda key=key: self._expire(key))
        self._entries[key] = entry
        self._restart_timer(entry)

    def _restart_timer(self, entry):
        entry.timer.stop()
        if entry.notice.duration_ms > 0:
            entry.timer.start(self.duration_seconds * 1_000)

    def _expire(self, key):
        self._remove(key)
        self._render()

    def _remove(self, key):
        entry = self._entries.pop(key, None)
        if entry is None:
            return
        entry.timer.stop()
        entry.timer.timeout.disconnect()
        entry.timer.deleteLater()
        entry.window.hide()
        entry.window.clear_message()
        self._window_pool.append(entry.window)
        self._history_fingerprints.pop(key, None)

    def _render(self):
        visible_entries = self._visible_entries()
        visible_windows = {entry.window for entry in visible_entries}
        for entry in self._entries.values():
            if entry.window not in visible_windows:
                entry.window.hide()

        pet_visible = self.pet.isVisible()
        overflow_count = max(
            0,
            len(self._presentable_entries()) - MAX_VISIBLE_BUBBLES,
        )
        for index, entry in enumerate(visible_entries):
            entry.window.set_decorations_enabled(index == 0)
            message = entry.notice.message
            if index == MAX_VISIBLE_BUBBLES - 1 and overflow_count:
                message = t("message.0321", value0=message, value1=overflow_count)
            entry.window.set_message(
                message,
                entry.notice.kind,
                entry.notice.source,
            )
            should_show = pet_visible and (
                (self.enabled and not self.is_snoozed) or entry.force_visible
            )
            if should_show:
                entry.window.show()
            else:
                entry.window.hide()
        self.reposition()
        refresh_controls = getattr(self.pet, "refresh_controls", None)
        if callable(refresh_controls):
            refresh_controls()

    def _ordered_entries(self):
        return sorted(
            self._entries.values(),
            key=lambda entry: (
                -entry.notice.priority,
                -entry.sequence,
            ),
        )

    def _visible_entries(self):
        return self._presentable_entries()[:MAX_VISIBLE_BUBBLES]

    def _presentable_entries(self):
        entries = self._ordered_entries()
        previews = [entry for entry in entries if entry.notice.kind == "preview"]
        if previews:
            return previews
        if not self.enabled:
            entries = [entry for entry in entries if entry.force_visible]
        return entries

    def _acquire_window(self):
        if self._window_pool:
            return self._window_pool.pop()
        return SpeechBubbleWindow(
            self.pet,
            scale_percent=self.scale_percent,
            theme=self.theme,
            element_registry=self.element_registry,
            source_marks_shown=self.source_marks_shown,
        )

    @staticmethod
    def _notice_key(notice):
        return (
            notice.replace_key
            or f"{notice.source}:{notice.session_id}:{notice.kind or notice.event}"
        )

    @staticmethod
    def _merged_notice(previous, incoming):
        if incoming.kind in {"start", "done"}:
            previous_members = set(previous.member_ids or (previous.session_id,))
            incoming_members = set(incoming.member_ids or (incoming.session_id,))
            members = tuple(sorted(previous_members | incoming_members))
            return replace(
                incoming,
                count=len(members),
                member_ids=members,
                message=PetBubbleController._lifecycle_summary(
                    incoming.source,
                    incoming.kind,
                    len(members),
                ),
            )
        return incoming

    def _retire_start_member(self, source, session_id):
        key = f"{source}:start"
        entry = self._entries.get(key)
        if entry is None:
            return
        members = set(entry.notice.member_ids or (entry.notice.session_id,))
        members.discard(session_id)
        if not members:
            self._remove(key)
            return
        ordered_members = tuple(sorted(members))
        entry.notice = replace(
            entry.notice,
            session_id=ordered_members[-1],
            member_ids=ordered_members,
            count=len(ordered_members),
            message=self._lifecycle_summary(
                source,
                "start",
                len(ordered_members),
            ),
        )
        entry.window.set_message(
            entry.notice.message,
            entry.notice.kind,
            entry.notice.source,
        )

    def _record_history(self, key, notice):
        if notice.kind == "preview":
            return
        fingerprint = (
            notice.kind,
            notice.source,
            notice.event,
            notice.count,
        )
        if notice.persistent and self._history_fingerprints.get(key) == fingerprint:
            return
        self._history_fingerprints[key] = fingerprint
        self._history.append(
            AssistantHistoryEntry(
                recorded_at=self._now(),
                kind=notice.kind,
                summary=self._history_summary(notice),
                count=max(1, int(notice.count or 1)),
            )
        )
        if len(self._history) > self.max_history:
            del self._history[: -self.max_history]

    @staticmethod
    def _history_summary(notice):
        count = max(1, int(notice.count or 1))
        source_label = source_display_label(notice.source)
        if notice.source not in {"codex", "schedule"}:
            source_label = t("message.0251")
        if notice.kind == "error":
            return t("message.0307", value0=source_label, value1=count)
        if notice.kind == "waiting":
            return t("message.0308", value0=source_label, value1=count)
        if notice.kind == "notification":
            return t("message.0309", value0=source_label, value1=count)
        if notice.kind == "done":
            return t("message.0310", value0=source_label, value1=count)
        if notice.kind == "cancelled":
            return t("message.0311", value0=source_label, value1=count)
        if notice.kind == "start":
            return t("message.0312", value0=source_label, value1=count)
        return t("message.0304", value0=source_label, value1=count)

    @staticmethod
    def _lifecycle_summary(source, kind, count):
        source_label = source_display_label(source)
        if count <= 1:
            action = t("message.0314") if kind == "start" else t("message.0315")
            return t("message.0313", value0=source_label, value1=action)
        action = t("message.0314") if kind == "start" else t("message.0315")
        return t("message.0305", value0=source_label, value1=count, value2=action)


@dataclass
class _BubbleEntry:
    key: str
    notice: BubbleNotice
    window: SpeechBubbleWindow
    timer: QTimer
    sequence: int
    force_visible: bool = False


@dataclass(frozen=True)
class AssistantHistoryEntry:
    recorded_at: datetime
    kind: str
    summary: str
    count: int = 1
