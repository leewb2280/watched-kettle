"""Render the installer wizard images from the app icon.

The images keep a transparent background so the same files work with the
installer's light and dark styles. One file per DPI scale lets Inno Setup pick
the closest size instead of stretching a single bitmap.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_ICON = PROJECT_ROOT / "assets" / "app_icon.png"
SCALES = (100, 125, 150, 175, 200, 250)
# Inno Setup's modern wizard sizes at 100% DPI.
LARGE_SIZE = (164, 314)
SMALL_SIZE = (55, 55)
# Share of the image width the icon occupies, and the icon's vertical center.
LARGE_ICON_WIDTH = 0.72
LARGE_ICON_CENTER = 0.42
SMALL_ICON_WIDTH = 0.92


def _scaled(size, scale):
    return tuple(round(value * scale / 100) for value in size)


def _place_icon(icon, size, width_ratio, center_ratio):
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    side = round(size[0] * width_ratio)
    resized = icon.resize((side, side), Image.Resampling.LANCZOS)
    left = (size[0] - side) // 2
    top = round(size[1] * center_ratio - side / 2)
    canvas.alpha_composite(resized, (left, top))
    return canvas


def render_installer_images(destination, icon_path=APP_ICON):
    """Write wizard-large-<scale>.png and wizard-small-<scale>.png files."""
    destination = Path(destination)
    if destination.exists():
        raise ValueError("Use a new image directory; it is never overwritten")
    destination.mkdir(parents=True)
    with Image.open(icon_path) as source:
        icon = source.convert("RGBA")
    written = []
    for scale in SCALES:
        large = _place_icon(
            icon, _scaled(LARGE_SIZE, scale), LARGE_ICON_WIDTH, LARGE_ICON_CENTER
        )
        small = _place_icon(icon, _scaled(SMALL_SIZE, scale), SMALL_ICON_WIDTH, 0.5)
        for name, image in (("large", large), ("small", small)):
            path = destination / f"wizard-{name}-{scale}.png"
            image.save(path, optimize=True)
            written.append(path)
    return written


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    written = render_installer_images(args.destination)
    print(f"Rendered {len(written)} installer images: {args.destination}")


if __name__ == "__main__":
    main()
