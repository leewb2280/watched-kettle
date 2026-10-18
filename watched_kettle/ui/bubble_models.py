"""Display-only bubble values shared by the pet and optional assistant."""

from watched_kettle.localization import t

from dataclasses import dataclass

from watched_kettle.ui import design_tokens

# Agent sources shown as a colored dot when both are in use (stage 14).
SOURCE_MARK_TOKENS = {"codex": "source-codex", "claude_code": "source-claude-code"}


@dataclass(frozen=True)
class BubbleNotice:
    message: str
    source: str
    event: str
    session_id: str
    duration_ms: int = 0
    kind: str = ""
    priority: int = 0
    replace_key: str = ""
    count: int = 1
    member_ids: tuple[str, ...] = ()

    @property
    def persistent(self):
        return self.duration_ms <= 0


def source_display_label(value):
    source = str(value or "manual").strip().lower()
    source = {
        "codex-cli": "codex",
        "openai-codex": "codex",
        "claude": "claude_code",
        "claude-code": "claude_code",
        "calendar": "schedule",
        "reminder": "schedule",
    }.get(source, source or "manual")
    return {
        "codex": "Codex",
        "claude_code": "Claude Code",
        "schedule": t("message.0205"),
        "system": t("message.0251"),
    }.get(source, source)


def source_mark_color(source):
    """The dot color for an agent source, or "" for any other source.

    Header chips keep a light background in every theme, so the light tokens
    stay readable on them.
    """
    token = SOURCE_MARK_TOKENS.get(source)
    return design_tokens.LIGHT_THEME[token] if token else ""


def source_marked_text(text, source):
    """Hover and screen reader text for a heading marked with a source dot."""
    if source not in SOURCE_MARK_TOKENS or not text:
        return text
    return f"{source_display_label(source)} · {text}"
