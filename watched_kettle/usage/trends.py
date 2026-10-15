"""Trend values for the usage overview charts (stage 14).

Pure functions over already-loaded data, for both Codex and Claude Code:
today's hourly tokens against the same hours of recent days, a limit's
remaining percent through the day, and daily tokens with a moving average.
Nothing here is stored; the services compute it on their usual refreshes.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from math import isfinite

HOURS = 24
AVERAGE_DAYS = 7
# Fewer recorded days than this make an "average" misleading.
MIN_AVERAGE_DAYS = 3
MOVING_DAYS = 7
MIN_MOVING_VALUES = 4
# Same rule as usage.activity.aggregate_quota_activity: a reset time that
# moves later by more than a minute starts a new quota cycle.
RESET_SHIFT_SECONDS = 60


def _recorded(day):
    return day is not None and any(value for value in day if value)


def hourly_profile(today, previous_days, now_hour, day=None):
    """Today's hours against the average of the same hours on recorded days.

    ``today`` and each of ``previous_days`` hold 24 token counts, ``None`` for
    an hour that was not observed. A day without any tokens is no record and
    stays out of the average; unobserved hours are left out, not counted as 0.
    ``day`` is the local date the hours belong to, so a reader can tell a
    profile computed before midnight from today's (see current_hours).
    """
    today = list(today) if today else [None] * HOURS
    days = [list(day) for day in previous_days if _recorded(day)][:AVERAGE_DAYS]
    average = None
    if len(days) >= MIN_AVERAGE_DAYS:
        average = []
        for hour in range(HOURS):
            values = [day[hour] for day in days if day[hour] is not None]
            average.append(sum(values) / len(values) if values else None)
    seen = [value for value in today if value is not None]
    total = sum(seen) if seen else None
    versus = None
    if average is not None and total is not None:
        hours = range(min(HOURS, max(0, now_hour) + 1))
        usual = sum(average[hour] or 0 for hour in hours)
        so_far = sum(today[hour] or 0 for hour in hours)
        if usual > 0:
            versus = round((so_far - usual) / usual * 100)
    peak = None
    if seen and max(seen) > 0:
        peak = max(
            (hour for hour in range(HOURS) if today[hour] is not None),
            key=lambda hour: today[hour],
        )
    return {
        "date": day,
        "hours": today,
        "average": average,
        "average_days": len(days),
        "total": total,
        "versus_average": versus,
        "peak_hour": peak,
    }


def current_hours(profile, day):
    """``profile`` for ``day``; one computed on an earlier day keeps only its
    average, as nothing has been observed today until the service refreshes."""
    if not profile or profile.get("date") in (None, day):
        return profile
    return {
        **profile,
        "date": day,
        "hours": [None] * HOURS,
        "total": None,
        "versus_average": None,
        "peak_hour": None,
    }


def hours_by_day(points, days, local_timezone):
    """Sum (moment, tokens) points into 24 hours for each of ``days``.

    A day with no point is ``None`` (no record). Used for Claude Code turns,
    whose transcript history covers every day the app was not running too.
    """
    wanted: dict[date, list[int] | None] = {day: None for day in days}
    for moment, tokens in points:
        local = moment.astimezone(local_timezone)
        day = local.date()
        if day not in wanted:
            continue
        hours = wanted[day]
        if hours is None:
            hours = wanted[day] = [0] * HOURS
        hours[local.hour] += int(tokens or 0)
    return wanted


def remaining_series(samples, local_day, local_timezone, now):
    """One limit's remaining percent through ``local_day``.

    ``samples`` are (observed_at, used_percent, resets_at) for one window.
    The day starts from the last sample before midnight. A reset adds a
    vertical step back to 100%; ``spent`` sums only rises within a cycle, the
    same rule as the widget's hourly decrease.
    """
    start = datetime.combine(local_day, time(0), tzinfo=local_timezone)
    end = start + timedelta(days=1)
    ordered = sorted(
        (
            (observed, float(used), resets)
            for observed, used, resets in samples
            if observed is not None
            and observed.tzinfo is not None
            and used is not None
            and isfinite(float(used))
            and observed < end
        ),
        key=lambda item: item[0],
    )
    before = [item for item in ordered if item[0] < start]
    today = [item for item in ordered if item[0] >= start]
    points, resets, spent = [], [], 0.0
    previous = before[-1] if before else None
    if previous is not None:
        used = previous[1]
        if previous[2] is not None and previous[2] <= start:
            used = 0.0
        points.append((start, max(0.0, 100.0 - used)))
    high = None
    if previous is not None:
        high = 0.0 if previous[2] is not None and previous[2] <= start else previous[1]
    for sample in today:
        observed, used, resets_at = sample
        if previous is not None and _new_cycle(previous, sample):
            moment = (
                previous[2]
                if previous[2] and start <= previous[2] <= observed
                else observed
            )
            points.append((moment, max(0.0, 100.0 - previous[1])))
            points.append((moment, 100.0))
            resets.append(moment)
            # A cycle's first sample is its baseline, as in the widget rule.
            high = None
        if high is not None and used > high:
            spent += used - high
        high = used if high is None else max(high, used)
        points.append((observed, max(0.0, 100.0 - used)))
        previous = sample
    # A reset after the last sample still shows; the next sample confirms it.
    last = previous
    if last is not None and last[2] is not None and start <= last[2] <= min(now, end):
        if not resets or resets[-1] != last[2]:
            points.append((last[2], max(0.0, 100.0 - last[1])))
            points.append((last[2], 100.0))
            resets.append(last[2])
    current = points[-1][1] if points else None
    return {
        "points": [(moment, round(value, 1)) for moment, value in points],
        "resets": resets,
        "now_remaining": round(current, 1) if current is not None else None,
        "spent": round(spent, 1) if today else None,
        "observed": len(today),
    }


def _new_cycle(previous, sample):
    old, new = previous[2], sample[2]
    if old is not None and new is not None:
        return (new - old).total_seconds() > RESET_SHIFT_SECONDS
    return sample[1] < previous[1] - 0.5 and old is not None and old <= sample[0]


def daily_series(days, count):
    """Daily tokens for the last ``count`` days with a 7-day moving average.

    ``days`` are (date, tokens or None) in any order; days before the shown
    range feed the first averages. A window needs four known values.
    """
    ordered = sorted(
        ((day, tokens) for day, tokens in days if isinstance(day, date)),
        key=lambda item: item[0],
    )
    values = {day: tokens for day, tokens in ordered}
    if not ordered:
        return {"days": [], "total": None, "average": None, "peak_date": None}
    last = ordered[-1][0]
    shown = [last - timedelta(days=offset) for offset in range(count - 1, -1, -1)]
    rows = []
    for day in shown:
        window = [
            values.get(day - timedelta(days=offset)) for offset in range(MOVING_DAYS)
        ]
        known = [value for value in window if value is not None]
        rows.append(
            {
                "date": day,
                "tokens": values.get(day),
                "average": (
                    sum(known) / len(known) if len(known) >= MIN_MOVING_VALUES else None
                ),
            }
        )
    known = [(row["date"], row["tokens"]) for row in rows if row["tokens"] is not None]
    if not known:
        return {"days": rows, "total": None, "average": None, "peak_date": None}
    total = sum(tokens for _, tokens in known)
    peak_date, peak_tokens = max(known, key=lambda item: item[1])
    return {
        "days": rows,
        "total": total,
        "average": total / len(known),
        "peak_date": peak_date if peak_tokens else None,
    }


# Codex reports window lengths in minutes; slots are a fallback.
CODEX_WINDOWS = {300: "five_hour", 10080: "seven_day"}


def codex_quota_trend(samples, local_day, local_timezone, now, limit_id="codex"):
    """Remaining-percent lines for one Codex limit's 5-hour and 7-day windows.

    The service passes the main limit (models.main_codex_limit_id); others,
    such as a reserve, are left out of the chart.
    """
    groups: dict[str, list[tuple]] = {"five_hour": [], "seven_day": []}
    for sample in samples:
        if getattr(sample, "limit_id", None) != limit_id:
            continue
        duration = getattr(sample, "window_duration_mins", None)
        key = (CODEX_WINDOWS.get(duration) if duration is not None else None) or (
            "five_hour" if sample.window_slot == "primary" else "seven_day"
        )
        groups[key].append((sample.observed_at, sample.used_percent, sample.resets_at))
    return {
        key: remaining_series(values, local_day, local_timezone, now)
        for key, values in groups.items()
    }
