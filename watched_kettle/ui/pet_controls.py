"""Presentation-only labels shared by the Assistant Center and system tray."""

from __future__ import annotations

from watched_kettle.config import (
    CODEX_MAX_PET_WIDTH,
    DEFAULT_PET_WIDTH,
    EXTENDED_MAX_PET_WIDTH,
    FRAME_WIDTH,
)
from watched_kettle.ui.bubble_models import source_display_label


ACTION_TEST_STATES = (
    ("기본", "idle"),
    ("오른쪽 이동", "running-right"),
    ("왼쪽 이동", "running-left"),
    ("손 흔들기", "waving"),
    ("점프", "jumping"),
    ("실패", "failed"),
    ("확인 대기", "waiting"),
    ("작업 중", "running"),
    ("검토 중", "review"),
)

STATE_LABELS = {
    "idle": "대기 중",
    "running": "작업 중",
    "review": "검토 중",
    "waiting": "확인 대기",
    "jumping": "작업 완료",
    "failed": "작업 실패",
    "waving": "알림 표시 중",
    "running-left": "펫 이동 중",
    "running-right": "펫 이동 중",
}


def size_label(pet_width: int) -> str:
    """Return a short display label for a supported pet width."""
    label = f"{pet_width}px"
    if pet_width == DEFAULT_PET_WIDTH:
        return f"{label} · 기본"
    if pet_width == FRAME_WIDTH:
        return f"{label} · 원본 크기"
    if pet_width == CODEX_MAX_PET_WIDTH:
        return f"{label} · 표준 최대"
    if pet_width == EXTENDED_MAX_PET_WIDTH:
        return f"{label} · 확장 최대"
    if pet_width > CODEX_MAX_PET_WIDTH:
        return f"{label} · 확장 크기"
    return label


AGENT_STATES = frozenset({"running", "review", "waiting", "jumping", "failed"})


def tray_status_text(
    presentation: object | None, current_state: str | None, sources=()
) -> str:
    """Translate the effective pet state into a user-facing tray label.

    Working states name the agents with working sessions; other agent states
    name the source of the event that produced them.
    """
    state = getattr(presentation, "state", None) or current_state or "idle"
    label = STATE_LABELS.get(state, str(state))
    if state not in AGENT_STATES:
        return label
    names = tuple(sources or getattr(presentation, "working_sources", ()) or ())
    if not names or state not in {"running", "review"}:
        source = getattr(presentation, "source", "")
        names = (source,) if source in {"codex", "claude_code"} else ()
    if not names:
        return label
    return "·".join(source_display_label(name) for name in names) + " " + label
