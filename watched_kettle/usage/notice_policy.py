"""Account notification policy, independent of Qt and transport."""

from watched_kettle.localization import t

import sqlite3
from watched_kettle.usage.contracts import UsageRepository
from watched_kettle.usage.widget_presentation import _percent_text

ALERT_THRESHOLDS = (70, 90, 100)


class UsageNoticePolicy:
    def __init__(self, repository: UsageRepository, now, local_timezone, emit, failure):
        self.repository = repository
        self._now = now
        self._local_timezone = local_timezone
        self._emit_notice = emit
        self._storage_failed = failure
        self._session_markers: set[str] = set()
        self._session_summaries: set[str] = set()
        self._last_used_percent: dict[tuple[str, str], float] = {}

    def reset(self):
        self._session_markers.clear()
        self._session_summaries.clear()
        self._last_used_percent.clear()

    def check_thresholds(self, snapshot, buckets, alert=True):
        account_key = snapshot.account_hash or "session"
        if snapshot.account_hash:
            try:
                markers = set(self.repository.load_threshold_markers(account_key))
            except (OSError, sqlite3.DatabaseError) as error:
                self._storage_failed(error)
                markers = set()
        else:
            markers = set(self._session_markers)
        changed = False
        for bucket in buckets:
            for slot, window in (
                ("primary", bucket.primary),
                ("secondary", bucket.secondary),
            ):
                if window is None or window.used_percent is None:
                    continue
                usage_key = (bucket.limit_id, slot)
                reset_key = (
                    window.resets_at.isoformat() if window.resets_at else "unknown"
                )
                prefix = f"{account_key}|{bucket.limit_id}|{slot}|"
                obsolete = {
                    item
                    for item in markers
                    if item.startswith(prefix)
                    and not item.startswith(f"{prefix}{reset_key}|")
                }
                if obsolete:
                    markers.difference_update(obsolete)
                    changed = True
                previous = self._last_used_percent.get(usage_key)
                if previous is not None and window.used_percent < previous:
                    markers = {item for item in markers if not item.startswith(prefix)}
                    changed = True
                self._last_used_percent[usage_key] = window.used_percent
                for threshold in ALERT_THRESHOLDS:
                    if window.used_percent < threshold:
                        continue
                    marker = f"{account_key}|{bucket.limit_id}|{slot}|{reset_key}|{threshold}"
                    if marker in markers:
                        continue
                    markers.add(marker)
                    changed = True
                    if alert:
                        urgency = "high" if threshold >= 90 else "normal"
                        remaining = window.remaining_percent
                        text = t("message.0369", value0=_percent_text(remaining))
                        if window.resets_at is not None:
                            reset_seconds = max(
                                0,
                                int((window.resets_at - self._now()).total_seconds()),
                            )
                            reset_hours, reset_remainder = divmod(
                                reset_seconds,
                                3600,
                            )
                            reset_minutes = reset_remainder // 60
                            if reset_hours:
                                text += t(
                                    "message.0337",
                                    value0=reset_hours,
                                    value1=reset_minutes,
                                )
                            else:
                                text += t("message.0338", value0=reset_minutes)
                        self._emit_notice(text, urgency, marker, f"{prefix}{reset_key}")
        if changed:
            if snapshot.account_hash:
                try:
                    self.repository.replace_threshold_markers(account_key, markers)
                except (OSError, sqlite3.DatabaseError) as error:
                    self._storage_failed(error)
            else:
                self._session_markers = set(markers)

    def daily_summary(self, snapshot, enabled):
        if not enabled:
            return
        local_now = self._now().astimezone(self._local_timezone)
        today_key = local_now.date().isoformat()
        summary_key = f"{today_key}|{snapshot.account_hash or 'session'}"
        if snapshot.account_hash:
            try:
                already_sent = self.repository.was_daily_summary_sent(
                    snapshot.account_hash or "session", today_key
                )
            except (OSError, sqlite3.DatabaseError) as error:
                self._storage_failed(error)
                already_sent = False
        else:
            already_sent = summary_key in self._session_summaries
        if local_now.hour < 18 or already_sent:
            return
        today = next(
            (
                item
                for item in snapshot.daily_buckets
                if item.start_date == local_now.date()
            ),
            None,
        )
        if today is None or not today.tokens:
            return
        known = [
            item.tokens
            for item in snapshot.daily_buckets[-7:]
            if item.tokens is not None
        ]
        message = t("message.0367", value0=f"{today.tokens:,}")
        if known:
            average = sum(known) / len(known)
            if average:
                change = (today.tokens - average) / average * 100
                message += t(
                    "message.0368",
                    value0=f"{abs(change):.0f}",
                    value1=t("comparison.more" if change >= 0 else "comparison.less"),
                )
        if snapshot.account_hash:
            try:
                self.repository.mark_daily_summary_sent(
                    snapshot.account_hash or "session", today_key, self._now()
                )
            except (OSError, sqlite3.DatabaseError) as error:
                self._storage_failed(error)
                return
        else:
            self._session_summaries.add(summary_key)
        self._emit_notice(message, "low", f"summary:{summary_key}")
