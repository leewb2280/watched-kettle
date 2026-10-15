"""A registered package frame for layout tests that need outer decorations."""

from pathlib import Path

from watched_kettle.pet.bubble_frame import register_package_frame
from watched_kettle.pet.bubble_theme import (
    PUBLIC_BUBBLE_PRESETS,
    bubble_theme_from_dict,
    bubble_theme_from_manifest,
)


FRAME_FIXTURE_MANIFEST = {
    "id": "frame-fixture",
    "bubbleTheme": {
        "tail": "none",
        "header": "capsule",
        "border": {"color": "#716bc9", "width": 1.8, "style": "double"},
        "effects": {"shadow": "#c8c5f3", "shadowAlpha": 0},
        "radius": 18,
        "layout": {
            "minimumWidth": 96,
            "horizontalPadding": 34,
            "stackAlignment": "left",
        },
        "textBold": True,
        "frame": {
            "insets": [22, 26, 38, 16],
            "contentPadding": [15, 14, 20],
            "innerBorder": {"color": "#ddd6b8", "alpha": 220},
            "halo": {"color": "shadow", "alpha": 92, "width": 4.5, "offsetY": 2.5},
            "overlay": [
                {"circle": {"radius": 6, "color": "shadow"}, "anchor": "arc-top-left"},
                {"circle": {"radius": 2, "color": "#f4d96b"}, "anchor": "top-right"},
            ],
        },
    },
}


def frame_fixture_theme():
    """Register the fixture frame and return the theme that uses it."""
    register_package_frame(FRAME_FIXTURE_MANIFEST, Path("."))
    return bubble_theme_from_manifest(FRAME_FIXTURE_MANIFEST)


def layout_test_themes(default_theme):
    """The default, every public preset, and a decorated package frame."""
    return [
        default_theme,
        *[
            bubble_theme_from_dict(dict(values))
            for _label, values in PUBLIC_BUBBLE_PRESETS.values()
        ],
        frame_fixture_theme(),
    ]
