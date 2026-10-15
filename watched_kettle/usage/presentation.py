"""Pure presentation of immutable usage state; never performs worker I/O."""

from watched_kettle.usage.models import UsageSnapshot


def format_tray_summary(snapshot: UsageSnapshot) -> str:
    """Summarize the tighter Codex window, keeping reserve buckets separate."""
    codex = tuple(bucket for bucket in snapshot.buckets if bucket.limit_id == "codex")
    remaining = [
        window.remaining_percent
        for bucket in codex or snapshot.buckets
        for window in (bucket.primary, bucket.secondary)
        if window is not None and window.remaining_percent is not None
    ]
    return f"잔여 {min(remaining):.0f}%" if remaining else "확인 불가"
