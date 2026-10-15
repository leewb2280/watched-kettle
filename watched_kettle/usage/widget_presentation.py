"""Pure token/quota/freshness text; reusable by preview and desktop widgets."""

from datetime import datetime


def compact_limit_label(option):
    if option is None:
        return "한도 없음"
    return option.name or option.limit_id or "한도"


def compact_limit_duration(option):
    if option is None:
        return ""
    minutes = option.window.window_duration_mins
    if minutes is None:
        return ""
    if minutes % 1440 == 0:
        return f"{minutes // 1440}일 한도"
    if minutes % 60 == 0:
        return f"{minutes // 60}시간 한도"
    return f"{minutes}분 한도"


def widget_quota_change_text(snapshot):
    if snapshot.observed_today_percent_points is None:
        return _quota_change_text(snapshot)
    return f"오늘 관측 {quota_decrease_text(snapshot.observed_today_percent_points)}"


def _percent_text(percent):
    if percent is None:
        return "확인 불가"
    return f"{float(percent):.1f}".rstrip("0").rstrip(".") + "%"


def quota_decrease_text(value):
    """Present a positive observed consumption as a remaining-quota decrease."""
    if value is None:
        return "관찰 대기"
    value = max(0.0, float(value))
    if value == 0:
        return "0%p"
    text = f"{value:.1f}".rstrip("0").rstrip(".")
    return "−<0.1%p" if text == "0" else f"−{text}%p"


def compact_token_text(value):
    if value is None:
        return "관찰 대기"
    value = max(0, int(value))
    if value < 1_000:
        return f"{value:,}"
    # Round integer tenths half up, avoiding float errors at unit boundaries.
    for power, suffix in enumerate(("K", "M", "B", "T"), start=1):
        divisor = 1000**power
        tenths = (value * 10 + divisor // 2) // divisor
        if tenths >= 10_000 and suffix != "T":
            continue
        whole, fraction = divmod(tenths, 10)
        text = f"{whole:,}" if suffix == "T" else str(whole)
        return f"{text}.{fraction}{suffix}" if fraction else f"{text}{suffix}"
    raise AssertionError("token unit missing")


def _reset_label(resets_at):
    if resets_at is None:
        return "초기화 시각 없음"
    local = resets_at.astimezone()
    now = datetime.now(resets_at.tzinfo)
    seconds = max(0, int((resets_at - now).total_seconds()))
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    relative = f"{hours}시간 {minutes}분 후" if hours else f"{minutes}분 후"
    return f"{local:%m/%d %H:%M} · {relative}"


def _quota_change_text(snapshot):
    count = max(0, int(snapshot.selected_quota_observation_count or 0))
    value = snapshot.observed_today_percent_points
    if value is None:
        return "오늘 관찰 대기" if count == 0 else "기준 수집 중"
    return f"오늘 {quota_decrease_text(value)}"


def _latest_observation(snapshot):
    candidates = tuple(
        value
        for value in (
            snapshot.quota_last_sample_at,
            snapshot.last_sample_at,
            snapshot.last_updated_at,
        )
        if value is not None
    )
    return max(candidates) if candidates else None


def _freshness_text(observed_at):
    if observed_at is None:
        return "갱신 대기", True
    now = datetime.now(observed_at.tzinfo) if observed_at.tzinfo else datetime.now()
    minutes = max(0, int((now - observed_at).total_seconds() // 60))
    if minutes < 2:
        return "방금 갱신", False
    return f"{minutes}분 전 갱신", minutes >= 15


def _hour_bucket_value(buckets, hour, attribute):
    if not 0 <= hour < len(buckets or ()):
        return None
    return getattr(buckets[hour], attribute, None)
