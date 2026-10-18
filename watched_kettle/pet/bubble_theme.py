"""Validated speech-bubble theme model shared by pet settings and UI."""

from __future__ import annotations

from watched_kettle.localization.collections import MessageId, MessageMapping

from dataclasses import asdict, dataclass, replace

from PySide6.QtGui import QColor
from watched_kettle.pet.bubble_frame import frame_style_for, is_frame_style


DEFAULT_BUBBLE_THEME_MODE = "character"
BUBBLE_THEME_MODES = frozenset({"character", "default", "custom"})
BUBBLE_SHAPES = frozenset({"rounded", "cloud", "jelly", "comic", "tech"})
BUBBLE_TAILS = frozenset({"none", "triangle", "curved", "stub", "angular", "droplet"})
BUBBLE_GRADIENTS = frozenset({"solid", "vertical", "horizontal"})
BUBBLE_BORDER_STYLES = frozenset({"single", "double", "accent"})
BUBBLE_HEADER_STYLES = frozenset({"none", "capsule", "tab", "ribbon", "panel"})
# "standard" or "pet:<id>", a package frame registered by pet/bubble_frame.py.
BUBBLE_FRAME_STYLES = frozenset({"standard"})
BUBBLE_STACK_ALIGNMENTS = frozenset({"center", "left"})
BUBBLE_TEXT_ALIGNMENTS = frozenset({"center", "left"})
BUILTIN_BUBBLE_PATTERNS = frozenset({"none", "dots", "stars", "grid"})
BUILTIN_BUBBLE_ORNAMENTS = frozenset(
    {
        "none",
        "cat-ear",
        "small-wing",
        "horn",
        "bat-wing",
        "star",
        "sparkle",
        "ribbon",
        "goggles",
        "magnet",
    }
)

# Inclusive numeric bounds shared by normalization and the settings editor.
BUBBLE_THEME_LIMITS = {
    "shadow_alpha": (0, 120),
    "radius": (6, 24),
    "border_width": (1.0, 4.0),
    "ornament_scale": (60, 160),
    "fill_opacity": (0, 255),
    "minimum_width": (48, 240),
    "maximum_width": (140, 480),
    "horizontal_padding": (16, 64),
    "background_opacity": (10, 100),
    "background_focus_x": (0, 100),
    "background_focus_y": (0, 100),
    "background_zoom": (100, 300),
    "frame_slice": (4, 64),
    **{f"sticker_{slot}_{axis}": (0, 100) for slot in (1, 2, 3) for axis in ("x", "y")},
    **{f"sticker_{slot}_size": (16, 96) for slot in (1, 2, 3)},
}
STICKER_SLOTS = (1, 2, 3)
IMAGE_THEME_KEYS = frozenset(
    {
        "background_image",
        "background_opacity",
        "background_focus_x",
        "background_focus_y",
        "background_zoom",
        "frame_image",
        "frame_slice",
    }
    | {
        f"sticker_{slot}{suffix}"
        for slot in STICKER_SLOTS
        for suffix in ("", "_x", "_y", "_size")
    }
)


@dataclass(frozen=True)
class SpeechBubbleTheme:
    """Safe values consumed by both the live bubble and editor preview."""

    background: str
    border: str
    text: str
    shadow: str
    shadow_alpha: int = 38
    radius: int = 11
    border_width: float = 1.35
    shape: str = "rounded"
    tail: str = "triangle"
    gradient: str = "solid"
    fill_end: str = "#fffdf8"
    border_style: str = "single"
    header_style: str = "capsule"
    pattern: str = "none"
    ornament_left: str = "none"
    ornament_right: str = "none"
    ornament_scale: int = 100
    glow: bool = False
    frame_style: str = "standard"
    fill_opacity: int = 255
    minimum_width: int = 140
    maximum_width: int = 320
    horizontal_padding: int = 32
    stack_alignment: str = "center"
    text_alignment: str = "center"
    text_bold: bool = False
    # User images (stage 14): a photo under the text, a 9-slice frame image
    # that replaces the drawn border, and up to three stickers. Each is
    # "none" or a "user:<id>" element from the user's bubble elements.
    background_image: str = "none"
    background_opacity: int = 45
    background_focus_x: int = 50
    background_focus_y: int = 50
    background_zoom: int = 100
    frame_image: str = "none"
    frame_slice: int = 16
    sticker_1: str = "none"
    sticker_1_x: int = 88
    sticker_1_y: int = 20
    sticker_1_size: int = 32
    sticker_2: str = "none"
    sticker_2_x: int = 12
    sticker_2_y: int = 80
    sticker_2_size: int = 32
    sticker_3: str = "none"
    sticker_3_x: int = 50
    sticker_3_y: int = 88
    sticker_3_size: int = 32


DEFAULT_BUBBLE_THEME = SpeechBubbleTheme(
    background="#fffdf8",
    border="#8c8377",
    text="#2d2924",
    shadow="#263246",
)


# Starting points for the editor's gallery in every build. Choosing one keeps
# the user's photo, frame image and stickers (IMAGE_THEME_KEYS).
PUBLIC_BUBBLE_PRESETS = MessageMapping(
    {
        "cream": (MessageId("message.0131"), {}),
        "sage": (
            MessageId("message.0132"),
            {"background": "#f4f8f3", "border": "#4f7a5c", "text": "#263230"},
        ),
        "graphite": (
            MessageId("message.0133"),
            {
                "background": "#1f2723",
                "fill_end": "#26302b",
                "gradient": "vertical",
                "border": "#9bbfa3",
                "text": "#edf2ec",
                "shadow": "#000000",
                "shadow_alpha": 60,
            },
        ),
        "sky": (
            MessageId("message.0134"),
            {
                "background": "#f1f7fd",
                "border": "#3a6d96",
                "text": "#1f3447",
                "shape": "cloud",
                "tail": "curved",
            },
        ),
        "paper": (
            MessageId("message.0135"),
            {
                "background": "#fffef7",
                "border": "#b9a98a",
                "text": "#3a332a",
                "pattern": "grid",
                "radius": 6,
                "tail": "stub",
            },
        ),
        "pop": (
            MessageId("message.0136"),
            {
                "background": "#fff6e8",
                "border": "#a14f3a",
                "text": "#3a1f17",
                "shape": "comic",
                "border_style": "double",
                "tail": "angular",
            },
        ),
    }
)


def normalize_bubble_theme_mode(value):
    mode = str(value or "").strip().lower()
    return mode if mode in BUBBLE_THEME_MODES else DEFAULT_BUBBLE_THEME_MODE


def bubble_theme_from_manifest(manifest):
    """Return a validated package theme, or None when none was supplied."""
    if not isinstance(manifest, dict):
        return None
    raw_theme = manifest.get("bubbleTheme")
    if not isinstance(raw_theme, dict):
        return None
    theme = bubble_theme_from_dict(raw_theme)
    explicit = "frame_style" in raw_theme or "frameStyle" in raw_theme
    if isinstance(raw_theme.get("frame"), dict) and not explicit:
        style = frame_style_for(manifest.get("id") or "")
        if is_frame_style(style):
            theme = replace(theme, frame_style=style)
    return theme


def bubble_theme_from_dict(raw_theme):
    """Normalize old flat themes and the expanded declarative schema."""
    if not isinstance(raw_theme, dict):
        return DEFAULT_BUBBLE_THEME

    fill = raw_theme.get("fill")
    fill = fill if isinstance(fill, dict) else {}
    border = raw_theme.get("border")
    border = border if isinstance(border, dict) else {}
    effects = raw_theme.get("effects")
    effects = effects if isinstance(effects, dict) else {}
    ornaments = raw_theme.get("ornaments")
    ornaments = ornaments if isinstance(ornaments, (list, tuple)) else ()
    layout = raw_theme.get("layout")
    layout = layout if isinstance(layout, dict) else {}

    background = _color(
        fill.get("start", raw_theme.get("background")),
        DEFAULT_BUBBLE_THEME.background,
    )
    minimum_width = _bounded_int(
        layout.get(
            "minimumWidth",
            raw_theme.get("minimum_width", raw_theme.get("minimumWidth")),
        ),
        DEFAULT_BUBBLE_THEME.minimum_width,
        *BUBBLE_THEME_LIMITS["minimum_width"],
    )
    maximum_width = _bounded_int(
        layout.get(
            "maximumWidth",
            raw_theme.get("maximum_width", raw_theme.get("maximumWidth")),
        ),
        DEFAULT_BUBBLE_THEME.maximum_width,
        *BUBBLE_THEME_LIMITS["maximum_width"],
    )
    maximum_width = max(minimum_width, maximum_width)
    return SpeechBubbleTheme(
        background=background,
        border=_color(
            border.get("color", raw_theme.get("border")),
            DEFAULT_BUBBLE_THEME.border,
        ),
        text=_color(raw_theme.get("text"), DEFAULT_BUBBLE_THEME.text),
        shadow=_color(
            effects.get("shadow", raw_theme.get("shadow")),
            DEFAULT_BUBBLE_THEME.shadow,
        ),
        shadow_alpha=_bounded_int(
            effects.get(
                "shadowAlpha",
                raw_theme.get("shadow_alpha", raw_theme.get("shadowAlpha")),
            ),
            DEFAULT_BUBBLE_THEME.shadow_alpha,
            *BUBBLE_THEME_LIMITS["shadow_alpha"],
        ),
        radius=_bounded_int(
            raw_theme.get("radius"),
            DEFAULT_BUBBLE_THEME.radius,
            *BUBBLE_THEME_LIMITS["radius"],
        ),
        border_width=_bounded_float(
            border.get(
                "width",
                raw_theme.get("border_width", raw_theme.get("borderWidth")),
            ),
            DEFAULT_BUBBLE_THEME.border_width,
            *BUBBLE_THEME_LIMITS["border_width"],
        ),
        shape=_choice(
            raw_theme.get("shape"),
            BUBBLE_SHAPES,
            DEFAULT_BUBBLE_THEME.shape,
        ),
        tail=_choice(
            raw_theme.get("tail"),
            BUBBLE_TAILS,
            DEFAULT_BUBBLE_THEME.tail,
        ),
        gradient=_choice(
            fill.get("type", raw_theme.get("gradient")),
            BUBBLE_GRADIENTS,
            DEFAULT_BUBBLE_THEME.gradient,
        ),
        fill_end=_color(
            fill.get(
                "end",
                raw_theme.get("fill_end", raw_theme.get("fillEnd")),
            ),
            background,
        ),
        border_style=_choice(
            border.get(
                "style",
                raw_theme.get("border_style", raw_theme.get("borderStyle")),
            ),
            BUBBLE_BORDER_STYLES,
            DEFAULT_BUBBLE_THEME.border_style,
        ),
        header_style=_choice(
            raw_theme.get("header_style", raw_theme.get("header")),
            BUBBLE_HEADER_STYLES,
            DEFAULT_BUBBLE_THEME.header_style,
        ),
        pattern=_element_id(
            effects.get("pattern", raw_theme.get("pattern")),
            BUILTIN_BUBBLE_PATTERNS,
            DEFAULT_BUBBLE_THEME.pattern,
        ),
        ornament_left=_element_id(
            raw_theme.get(
                "ornamentLeft",
                raw_theme.get(
                    "ornament_left",
                    ornaments[0] if ornaments else None,
                ),
            ),
            BUILTIN_BUBBLE_ORNAMENTS,
            DEFAULT_BUBBLE_THEME.ornament_left,
        ),
        ornament_right=_element_id(
            raw_theme.get(
                "ornamentRight",
                raw_theme.get(
                    "ornament_right",
                    ornaments[1] if len(ornaments) > 1 else None,
                ),
            ),
            BUILTIN_BUBBLE_ORNAMENTS,
            DEFAULT_BUBBLE_THEME.ornament_right,
        ),
        ornament_scale=_bounded_int(
            raw_theme.get("ornament_scale", raw_theme.get("ornamentScale")),
            DEFAULT_BUBBLE_THEME.ornament_scale,
            *BUBBLE_THEME_LIMITS["ornament_scale"],
        ),
        glow=_boolean(
            effects.get("glow", raw_theme.get("glow")),
            DEFAULT_BUBBLE_THEME.glow,
        ),
        frame_style=_frame_style(
            raw_theme.get("frame_style", raw_theme.get("frameStyle"))
        ),
        fill_opacity=_bounded_int(
            fill.get(
                "opacity",
                raw_theme.get("fill_opacity", raw_theme.get("fillOpacity")),
            ),
            DEFAULT_BUBBLE_THEME.fill_opacity,
            *BUBBLE_THEME_LIMITS["fill_opacity"],
        ),
        minimum_width=minimum_width,
        maximum_width=maximum_width,
        horizontal_padding=_bounded_int(
            layout.get(
                "horizontalPadding",
                raw_theme.get(
                    "horizontal_padding",
                    raw_theme.get("horizontalPadding"),
                ),
            ),
            DEFAULT_BUBBLE_THEME.horizontal_padding,
            *BUBBLE_THEME_LIMITS["horizontal_padding"],
        ),
        stack_alignment=_choice(
            layout.get(
                "stackAlignment",
                raw_theme.get(
                    "stack_alignment",
                    raw_theme.get("stackAlignment"),
                ),
            ),
            BUBBLE_STACK_ALIGNMENTS,
            DEFAULT_BUBBLE_THEME.stack_alignment,
        ),
        text_alignment=_choice(
            layout.get(
                "textAlignment",
                raw_theme.get(
                    "text_alignment",
                    raw_theme.get("textAlignment"),
                ),
            ),
            BUBBLE_TEXT_ALIGNMENTS,
            DEFAULT_BUBBLE_THEME.text_alignment,
        ),
        text_bold=_boolean(
            raw_theme.get("text_bold", raw_theme.get("textBold")),
            DEFAULT_BUBBLE_THEME.text_bold,
        ),
        **_image_fields(raw_theme),
    )


def _image_fields(raw_theme):
    """User-image fields; only "none" or user elements are accepted."""
    values = {
        "background_image": _element_id(
            raw_theme.get("background_image"), {"none"}, "none"
        ),
        "frame_image": _element_id(raw_theme.get("frame_image"), {"none"}, "none"),
    }
    for key in (
        "background_opacity",
        "background_focus_x",
        "background_focus_y",
        "background_zoom",
        "frame_slice",
    ):
        values[key] = _bounded_int(
            raw_theme.get(key),
            getattr(DEFAULT_BUBBLE_THEME, key),
            *BUBBLE_THEME_LIMITS[key],
        )
    for slot in STICKER_SLOTS:
        name = f"sticker_{slot}"
        values[name] = _element_id(raw_theme.get(name), {"none"}, "none")
        for suffix in ("x", "y", "size"):
            key = f"{name}_{suffix}"
            values[key] = _bounded_int(
                raw_theme.get(key),
                getattr(DEFAULT_BUBBLE_THEME, key),
                *BUBBLE_THEME_LIMITS[key],
            )
    return values


def bubble_theme_to_dict(theme):
    """Return stable JSON-compatible data for per-pet preferences."""
    normalized = theme if isinstance(theme, SpeechBubbleTheme) else DEFAULT_BUBBLE_THEME
    return asdict(normalized)


def resolve_bubble_theme(
    manifest,
    mode=DEFAULT_BUBBLE_THEME_MODE,
    custom_theme=None,
):
    """Resolve the user's mode against package and per-pet custom themes."""
    mode = normalize_bubble_theme_mode(mode)
    if mode == "custom" and custom_theme is not None:
        return custom_theme
    if mode in {"character", "custom"}:
        return bubble_theme_from_manifest(manifest) or DEFAULT_BUBBLE_THEME
    return DEFAULT_BUBBLE_THEME


def _color(value, fallback):
    color = QColor(str(value or ""))
    if not color.isValid():
        return fallback
    return color.name(QColor.NameFormat.HexRgb)


def _frame_style(value):
    value = str(value or "").strip()
    return value if is_frame_style(value) else DEFAULT_BUBBLE_THEME.frame_style


def _choice(value, choices, fallback):
    value = str(value or "").strip().lower()
    return value if value in choices else fallback


def _element_id(value, builtins, fallback):
    value = str(value or "").strip()
    if value in builtins or value.startswith("user:"):
        return value
    return fallback


def _boolean(value, fallback):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    return fallback


def _bounded_int(value, fallback, minimum, maximum):
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = fallback
    return min(max(number, minimum), maximum)


def _bounded_float(value, fallback, minimum, maximum):
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = fallback
    return min(max(number, minimum), maximum)


def bubble_theme_presets():
    """Gallery entries for the editor.

    Values leave out IMAGE_THEME_KEYS so a preset never removes user images.
    """
    entries = [
        (preset_id, label, bubble_theme_from_dict(dict(values)))
        for preset_id, (label, values) in PUBLIC_BUBBLE_PRESETS.items()
    ]
    return [
        dict(
            id=preset_id,
            label=label,
            values={
                key: value
                for key, value in asdict(theme).items()
                if key not in IMAGE_THEME_KEYS
            },
        )
        for preset_id, label, theme in entries
    ]
