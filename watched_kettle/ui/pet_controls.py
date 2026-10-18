"""Presentation-only labels shared by the Assistant Center and system tray."""

from __future__ import annotations

from watched_kettle.localization import t
from watched_kettle.localization.collections import (
    MessageId,
    MessageMapping,
    MessageSequence,
)

from watched_kettle.config import (
    CODEX_MAX_PET_WIDTH,
    DEFAULT_PET_WIDTH,
    EXTENDED_MAX_PET_WIDTH,
    FRAME_WIDTH,
)
from watched_kettle.ui.bubble_models import source_display_label


ACTION_TEST_STATES = MessageSequence(
    (
        (MessageId("message.0279"), "idle"),
        (MessageId("message.0280"), "running-right"),
        (MessageId("message.0281"), "running-left"),
        (MessageId("message.0282"), "waving"),
        (MessageId("message.0283"), "jumping"),
        (MessageId("message.0284"), "failed"),
        (MessageId("message.0274"), "waiting"),
        (MessageId("message.0257"), "running"),
        (MessageId("message.0273"), "review"),
    )
)

STATE_LABELS = MessageMapping(
    {
        "idle": MessageId("message.0272"),
        "running": MessageId("message.0257"),
        "review": MessageId("message.0273"),
        "waiting": MessageId("message.0274"),
        "jumping": MessageId("message.0275"),
        "failed": MessageId("message.0276"),
        "waving": MessageId("message.0277"),
        "running-left": MessageId("message.0278"),
        "running-right": MessageId("message.0278"),
    }
)


def size_label(pet_width: int) -> str:
    """Return a short display label for a supported pet width."""
    label = f"{pet_width}px"
    if pet_width == DEFAULT_PET_WIDTH:
        return t("message.0285", value0=label)
    if pet_width == FRAME_WIDTH:
        return t("message.0286", value0=label)
    if pet_width == CODEX_MAX_PET_WIDTH:
        return t("message.0287", value0=label)
    if pet_width == EXTENDED_MAX_PET_WIDTH:
        return t("message.0288", value0=label)
    if pet_width > CODEX_MAX_PET_WIDTH:
        return t("message.0289", value0=label)
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
