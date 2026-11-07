"""When a usage limit resets, as time left or as the local clock time; no Qt.

The widget and the limit notices share this wording. ``display`` is the
user's choice: ``remaining`` (time left, "in 4h 12m") or ``clock`` (the
12-hour local time, "12:39 PM", with the date when the reset is not today).
"""

from __future__ import annotations

from watched_kettle.localization import t

REMAINING = "remaining"
CLOCK = "clock"
RESET_DISPLAYS = (REMAINING, CLOCK)
WEEKDAYS = (
    "time.weekday_0",
    "time.weekday_1",
    "time.weekday_2",
    "time.weekday_3",
    "time.weekday_4",
    "time.weekday_5",
    "time.weekday_6",
)


def normalize_reset_display(value):
    return value if value in RESET_DISPLAYS else REMAINING


def clock_text(moment):
    """12-hour clock time of an aware datetime, such as 12:39 PM."""
    hour = moment.hour % 12 or 12
    key = "time.clock_pm" if moment.hour >= 12 else "time.clock_am"
    return t(key, hour=str(hour), minute=f"{moment.minute:02d}")


def date_text(moment):
    """Month, day and weekday of an aware datetime, such as Thu 11/6."""
    return t(
        "time.month_day_weekday",
        month=str(moment.month),
        day=str(moment.day),
        weekday=t(WEEKDAYS[moment.weekday()]),
    )


def _local(resets_at, now, tz):
    moment = resets_at.astimezone(tz)
    today = now.astimezone(tz).date()
    return moment, moment.date() == today


def remaining_parts(resets_at, now):
    seconds = max(0, int((resets_at - now).total_seconds()))
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    return days, hours, remainder // 60


def widget_reset_text(resets_at, now, display=REMAINING, tz=None):
    """The widget's reset line; "" when the reset time is unknown."""
    if resets_at is None:
        return ""
    if normalize_reset_display(display) == CLOCK:
        moment, today = _local(resets_at, now, tz)
        if today:
            return t("widget.reset_at_today", time=clock_text(moment))
        return t("widget.reset_at_day", date=date_text(moment), time=clock_text(moment))
    days, hours, minutes = remaining_parts(resets_at, now)
    if days:
        return t("widget.reset_days", value0=days, value1=hours)
    if hours:
        return t("widget.reset_hours", value0=hours, value1=minutes)
    return t("widget.reset_minutes", value0=minutes)


def notice_reset_text(resets_at, now, display=REMAINING, tz=None):
    """The " · …" suffix a limit notice adds; "" when the reset is unknown."""
    if resets_at is None:
        return ""
    if normalize_reset_display(display) == CLOCK:
        moment, today = _local(resets_at, now, tz)
        if today:
            return t("usage.notice_reset_at_today", time=clock_text(moment))
        return t(
            "usage.notice_reset_at_day",
            date=date_text(moment),
            time=clock_text(moment),
        )
    seconds = max(0, int((resets_at - now).total_seconds()))
    hours, rest = divmod(seconds, 3600)
    if hours:
        return t("message.0337", value0=hours, value1=rest // 60)
    return t("message.0338", value0=rest // 60)
