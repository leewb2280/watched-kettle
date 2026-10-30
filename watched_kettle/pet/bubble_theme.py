"""Validated speech-bubble theme model shared by pet settings and UI."""

from __future__ import annotations

from watched_kettle.localization.collections import MessageId, MessageMapping

from dataclasses import asdict, dataclass, replace

from PySide6.QtGui import QColor
from watched_kettle.pet.bubble_decor import (
    ORNAMENT_KINDS,
    DecorLayer,
    decor_from_list,
    stickers_as_layers,
)
from watched_kettle.pet.bubble_frame import (
    FRAME_STYLE_PREFIX,
    frame_style_for,
    is_frame_style,
)


DEFAULT_BUBBLE_THEME_MODE = "character"
BUBBLE_THEME_MODES = frozenset({"character", "default", "custom"})
BUBBLE_SHAPES = frozenset({"rounded", "cloud", "jelly", "comic", "tech"})
BUBBLE_TAILS = frozenset({"none", "triangle", "curved", "stub", "angular", "droplet"})
BUBBLE_GRADIENTS = frozenset({"solid", "vertical", "horizontal", "angle"})
# "free" places the photo in its own box: background_x/y and width/height.
BACKGROUND_FITS = frozenset({"cover", "contain", "stretch", "tile", "free"})
BUBBLE_BORDER_STYLES = frozenset({"single", "double", "accent"})
BUBBLE_HEADER_STYLES = frozenset({"none", "capsule", "tab", "ribbon", "panel"})
# "standard" or "pet:<id>", a package frame registered by pet/bubble_frame.py.
BUBBLE_FRAME_STYLES = frozenset({"standard"})
BUBBLE_STACK_ALIGNMENTS = frozenset({"center", "left"})
BUBBLE_TEXT_ALIGNMENTS = frozenset({"center", "left"})
BUILTIN_BUBBLE_PATTERNS = frozenset({"none", "dots", "stars", "grid"})
# Tiles in assets/bubble-patterns, tinted with the border color when painted.
# The order is the editor's.
BACKGROUND_PATTERN_NAMES = (
    "dots",
    "gingham",
    "stripes",
    "hearts",
    "stars",
    "flowers",
    "waves",
    "grid",
)
BUILTIN_BACKGROUND_PREFIX = "builtin:"
BUILTIN_BACKGROUND_IMAGES = frozenset(
    {"none", *(BUILTIN_BACKGROUND_PREFIX + name for name in BACKGROUND_PATTERN_NAMES)}
)
BUILTIN_BUBBLE_ORNAMENTS = frozenset({"none", *ORNAMENT_KINDS})

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
    "gradient_angle": (0, 359),
    "pattern_tile_size": (12, 96),
    "pattern_opacity": (4, 60),
    "background_opacity": (0, 100),
    "background_focus_x": (0, 100),
    "background_focus_y": (0, 100),
    "background_zoom": (100, 300),
    "background_tile_size": (16, 256),
    "background_blur": (0, 20),
    "background_overlay": (0, 80),
    "background_x": (0.0, 100.0),
    "background_y": (0.0, 100.0),
    "background_width": (8, 960),
    "background_height": (8, 960),
    "frame_slice": (4, 64),
    "inner_border_alpha": (0, 255),
    "halo_alpha": (0, 255),
    "halo_width": (0.0, 12.0),
    "halo_offset_y": (-20.0, 20.0),
    "halo_grow": (-10.0, 20.0),
    "content_top": (0, 60),
    "content_bottom": (0, 60),
    "content_left": (0, 80),
}
# Fields a preset never changes: the user's images and decoration layers.
IMAGE_THEME_KEYS = frozenset(
    {
        "background_image",
        "background_fit",
        "background_opacity",
        "background_focus_x",
        "background_focus_y",
        "background_zoom",
        "background_tile_size",
        "background_blur",
        "background_overlay",
        "background_x",
        "background_y",
        "background_width",
        "background_height",
        "frame_image",
        "frame_slice",
        "package_layers",
        "decor",
    }
)
# Values a pet frame supplies (its inner line, halo and text spacing) that a
# user theme may set itself; each "*_custom" switch off keeps the pet's own.
FRAME_THEME_KEYS = frozenset(
    {
        "inner_border_custom",
        "inner_border_color",
        "inner_border_alpha",
        "halo_custom",
        "halo_color",
        "halo_alpha",
        "halo_width",
        "halo_offset_y",
        "halo_grow",
        "content_custom",
        "content_top",
        "content_bottom",
        "content_left",
    }
)
# A preset also leaves the pet's character frame on: it restyles the bubble,
# the frame belongs to the pet.
PRESET_KEPT_KEYS = IMAGE_THEME_KEYS | FRAME_THEME_KEYS | {"frame_style"}
_IMAGE_NUMBER_KEYS = (
    "background_opacity",
    "background_focus_x",
    "background_focus_y",
    "background_zoom",
    "background_tile_size",
    "background_blur",
    "background_overlay",
    "background_width",
    "background_height",
    "frame_slice",
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
    # Degrees for gradient "angle": 0 runs left to right, 90 top to bottom.
    gradient_angle: int = 135
    # Tile size and opacity of a user pattern image.
    pattern_tile_size: int = 28
    pattern_opacity: int = 16
    # User images: a photo under the text and a 9-slice frame image that
    # replaces the drawn border. Each is "none" or a "user:<id>" element;
    # the photo may also be a "builtin:<name>" pattern tile.
    background_image: str = "none"
    background_fit: str = "cover"
    background_opacity: int = 45
    background_focus_x: int = 50
    background_focus_y: int = 50
    background_zoom: int = 100
    background_tile_size: int = 64
    background_blur: int = 0
    # Percent of the bubble color laid over the photo to keep text readable.
    background_overlay: int = 0
    # "free" fit: the photo's center in percent of the body and its size in
    # pixels, so a longer bubble keeps the picture's shape and its side.
    background_x: float = 50.0
    background_y: float = 50.0
    background_width: int = 120
    background_height: int = 80
    frame_image: str = "none"
    frame_slice: int = 16
    # False hides the layers of the pet frame (frame_style) but keeps its
    # spacing; set when the user copied those layers into decor to edit them.
    package_layers: bool = True
    # User decoration layers (pet/bubble_decor.py), drawn after the pet frame.
    decor: tuple[DecorLayer, ...] = ()
    # The double border's inner line; off uses the pet frame's or the border.
    inner_border_custom: bool = False
    inner_border_color: str = "#8c8377"
    inner_border_alpha: int = 115
    # A rounded line around the body, behind it; off uses the pet frame's.
    # Width 0 draws none.
    halo_custom: bool = False
    halo_color: str = "#263246"
    halo_alpha: int = 90
    halo_width: float = 3.0
    halo_offset_y: float = 0.0
    halo_grow: float = 0.0
    # Text spacing inside the body (top, bottom, extra left); off uses the
    # pet frame's or the standard spacing.
    content_custom: bool = False
    content_top: int = 12
    content_bottom: int = 14
    content_left: int = 0


DEFAULT_BUBBLE_THEME = SpeechBubbleTheme(
    background="#fffdf8",
    border="#8c8377",
    text="#2d2924",
    shadow="#263246",
)


# Starting points for the editor's gallery in every build. Choosing one keeps
# the user's photo, frame image, decoration layers and the pet's character
# frame (PRESET_KEPT_KEYS).
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
        gradient_angle=_bounded_int(
            fill.get(
                "angle",
                raw_theme.get("gradient_angle", raw_theme.get("gradientAngle")),
            ),
            DEFAULT_BUBBLE_THEME.gradient_angle,
            *BUBBLE_THEME_LIMITS["gradient_angle"],
        ),
        pattern_tile_size=_bounded_int(
            raw_theme.get("pattern_tile_size"),
            DEFAULT_BUBBLE_THEME.pattern_tile_size,
            *BUBBLE_THEME_LIMITS["pattern_tile_size"],
        ),
        pattern_opacity=_bounded_int(
            raw_theme.get("pattern_opacity"),
            DEFAULT_BUBBLE_THEME.pattern_opacity,
            *BUBBLE_THEME_LIMITS["pattern_opacity"],
        ),
        **_image_fields(raw_theme),
        **_frame_fields(raw_theme),
    )


def _frame_fields(raw_theme):
    """The theme's own inner line, halo and text spacing (FRAME_THEME_KEYS)."""
    values = {
        key: _boolean(raw_theme.get(key), False)
        for key in ("inner_border_custom", "halo_custom", "content_custom")
    }
    for key in ("inner_border_color", "halo_color"):
        values[key] = _color(raw_theme.get(key), getattr(DEFAULT_BUBBLE_THEME, key))
    for key in (
        "inner_border_alpha",
        "halo_alpha",
        "content_top",
        "content_bottom",
        "content_left",
    ):
        values[key] = _bounded_int(
            raw_theme.get(key),
            getattr(DEFAULT_BUBBLE_THEME, key),
            *BUBBLE_THEME_LIMITS[key],
        )
    # Halves keep a pet halo's 2.5px offset when it is copied.
    for key in ("halo_width", "halo_offset_y", "halo_grow"):
        values[key] = (
            round(
                _bounded_float(
                    raw_theme.get(key),
                    getattr(DEFAULT_BUBBLE_THEME, key),
                    *BUBBLE_THEME_LIMITS[key],
                )
                * 2
            )
            / 2
        )
    return values


def _image_fields(raw_theme):
    """User-image fields; only "none", built-in tiles or user elements."""
    values = {
        "background_image": _element_id(
            raw_theme.get("background_image"), BUILTIN_BACKGROUND_IMAGES, "none"
        ),
        "background_fit": _choice(
            raw_theme.get("background_fit"),
            BACKGROUND_FITS,
            DEFAULT_BUBBLE_THEME.background_fit,
        ),
        "frame_image": _element_id(raw_theme.get("frame_image"), {"none"}, "none"),
        "package_layers": _boolean(
            raw_theme.get("package_layers"), DEFAULT_BUBBLE_THEME.package_layers
        ),
        # Themes saved before decoration layers kept up to three stickers.
        "decor": (
            decor_from_list(raw_theme["decor"])
            if "decor" in raw_theme
            else stickers_as_layers(raw_theme)
        ),
    }
    for key in _IMAGE_NUMBER_KEYS:
        values[key] = _bounded_int(
            raw_theme.get(key),
            getattr(DEFAULT_BUBBLE_THEME, key),
            *BUBBLE_THEME_LIMITS[key],
        )
    # Tenths of a percent keep a dragged photo where it was dropped.
    for key in ("background_x", "background_y"):
        values[key] = round(
            _bounded_float(
                raw_theme.get(key),
                getattr(DEFAULT_BUBBLE_THEME, key),
                *BUBBLE_THEME_LIMITS[key],
            ),
            1,
        )
    return values


def bubble_theme_to_dict(theme):
    """Return stable JSON-compatible data for per-pet preferences and the wire."""
    normalized = theme if isinstance(theme, SpeechBubbleTheme) else DEFAULT_BUBBLE_THEME
    data = asdict(normalized)
    data["decor"] = [dict(layer) for layer in data["decor"]]
    return data


def resolve_bubble_theme(
    manifest,
    mode=DEFAULT_BUBBLE_THEME_MODE,
    custom_theme=None,
):
    """Resolve the user's mode against package and per-pet custom themes."""
    mode = normalize_bubble_theme_mode(mode)
    if mode == "custom" and custom_theme is not None:
        return with_own_frame(custom_theme, manifest)
    if mode in {"character", "custom"}:
        return bubble_theme_from_manifest(manifest) or DEFAULT_BUBBLE_THEME
    return DEFAULT_BUBBLE_THEME


def with_own_frame(theme, manifest):
    """The theme with another pet's frame swapped for this pet's own.

    A design saved on one pet names that pet's frame ("pet:<id>"). On another
    pet it means "the character frame", so it takes that pet's frame, or the
    standard one when the pet ships none.
    """
    if not theme.frame_style.startswith(FRAME_STYLE_PREFIX):
        return theme
    package = bubble_theme_from_manifest(manifest)
    own = package.frame_style if package is not None else "standard"
    return theme if theme.frame_style == own else replace(theme, frame_style=own)


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
    except TypeError, ValueError:
        number = fallback
    return min(max(number, minimum), maximum)


def _bounded_float(value, fallback, minimum, maximum):
    try:
        number = float(value)
    except TypeError, ValueError:
        number = fallback
    return min(max(number, minimum), maximum)


def bubble_theme_presets():
    """Gallery entries for the editor.

    Values leave out PRESET_KEPT_KEYS so a preset never removes user images
    or the pet's character frame.
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
                if key not in PRESET_KEPT_KEYS
            },
        )
        for preset_id, label, theme in entries
    ]
