"""Public speech-bubble API kept stable across the split UI modules."""

from watched_kettle.ui.speech_bubble_controller import (
    AssistantHistoryEntry,
    MAX_ASSISTANT_HISTORY,
    MAX_VISIBLE_BUBBLES,
    PetBubbleController,
)
from watched_kettle.ui.speech_bubble_window import (
    BUBBLE_BODY_BOTTOM_MARGIN,
    BUBBLE_BODY_TOP_MARGIN,
    BUBBLE_GAP,
    BUBBLE_HORIZONTAL_PADDING,
    BUBBLE_MAX_WIDTH,
    BUBBLE_MIN_WIDTH,
    BUBBLE_RADIUS,
    BUBBLE_SHADOW_OFFSET,
    BUBBLE_STACK_GAP,
    BUBBLE_TAIL_HALF_BASE,
    BUBBLE_TAIL_SIZE,
    MAX_BUBBLE_LINES,
    SpeechBubbleWindow,
    bubble_position,
    bubble_stack_positions,
    elide_wrapped_text,
)


__all__ = (
    "AssistantHistoryEntry",
    "BUBBLE_BODY_BOTTOM_MARGIN",
    "BUBBLE_BODY_TOP_MARGIN",
    "BUBBLE_GAP",
    "BUBBLE_HORIZONTAL_PADDING",
    "BUBBLE_MAX_WIDTH",
    "BUBBLE_MIN_WIDTH",
    "BUBBLE_RADIUS",
    "BUBBLE_SHADOW_OFFSET",
    "BUBBLE_STACK_GAP",
    "BUBBLE_TAIL_HALF_BASE",
    "BUBBLE_TAIL_SIZE",
    "MAX_ASSISTANT_HISTORY",
    "MAX_BUBBLE_LINES",
    "MAX_VISIBLE_BUBBLES",
    "PetBubbleController",
    "SpeechBubbleWindow",
    "bubble_position",
    "bubble_stack_positions",
    "elide_wrapped_text",
)
