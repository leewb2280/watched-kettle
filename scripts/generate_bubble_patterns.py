"""Draw the built-in speech-bubble background patterns into assets/.

Each tile is a seamless 128px white mask; the bubble tints it with the theme's
border color, so one tile suits every palette. Run again after changing a
pattern and commit the PNGs.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

TILE = 128
# Drawn larger and scaled down for smooth edges.
SUPERSAMPLE = 4
ROOT = Path(__file__).resolve().parent.parent / "assets" / "bubble-patterns"


def _wrapped(draw_motif):
    """Draw a motif at every neighbouring tile offset so edges join up."""

    def draw(draw, *args):
        size = TILE * SUPERSAMPLE
        for dx in (-size, 0, size):
            for dy in (-size, 0, size):
                draw_motif(draw, dx, dy, *args)

    return draw


def _s(value):
    return value * SUPERSAMPLE


@_wrapped
def _circle(draw, dx, dy, x, y, radius, fill=255):
    draw.ellipse(
        (
            _s(x - radius) + dx,
            _s(y - radius) + dy,
            _s(x + radius) + dx,
            _s(y + radius) + dy,
        ),
        fill=fill,
    )


@_wrapped
def _polygon(draw, dx, dy, points, fill=255):
    draw.polygon([(_s(x) + dx, _s(y) + dy) for x, y in points], fill=fill)


def _star_points(x, y, outer, inner, count=5):
    points = []
    for index in range(count * 2):
        radius = outer if index % 2 == 0 else inner
        angle = -math.pi / 2 + index * math.pi / count
        points.append((x + radius * math.cos(angle), y + radius * math.sin(angle)))
    return points


def _heart_points(x, y, size, steps=96):
    points = []
    for index in range(steps):
        t = 2 * math.pi * index / steps
        px = 16 * math.sin(t) ** 3
        py = (
            13 * math.cos(t)
            - 5 * math.cos(2 * t)
            - 2 * math.cos(3 * t)
            - math.cos(4 * t)
        )
        points.append((x + px * size / 32, y - py * size / 32))
    return points


def dots(draw):
    _circle(draw, 32, 32, 11)
    _circle(draw, 96, 96, 11)


def gingham(draw):
    # Half-strength bands; where they cross the mask is fully opaque.
    size = _s(TILE)
    band = [115 if (value // _s(32)) % 2 == 0 else 0 for value in range(size)]
    draw.im.putdata(
        [255 if down and across else down + across for down in band for across in band]
    )


def stripes(draw):
    # Diagonal bands every 32px along x; 128 is a multiple, so they tile.
    width = 12
    for start in range(-TILE, 2 * TILE, 32):
        _polygon(
            draw,
            [
                (start, 0),
                (start + width, 0),
                (start + width + TILE, TILE),
                (start + TILE, TILE),
            ],
        )


def hearts(draw):
    _polygon(draw, _heart_points(32, 34, 26))
    _polygon(draw, _heart_points(96, 98, 26))


def stars(draw):
    _polygon(draw, _star_points(32, 34, 15, 6.5))
    _polygon(draw, _star_points(96, 98, 9, 4))
    _circle(draw, 96, 30, 2.5)
    _circle(draw, 30, 96, 2.5)


def flowers(draw):
    for cx, cy, petal in ((32, 32, 8), (96, 96, 6)):
        for index in range(5):
            angle = -math.pi / 2 + index * 2 * math.pi / 5
            _circle(
                draw,
                cx + petal * 1.15 * math.cos(angle),
                cy + petal * 1.15 * math.sin(angle),
                petal,
                170,
            )
        _circle(draw, cx, cy, petal * 0.75, 255)


def waves(draw):
    # Two sine lines per tile; one period spans the tile width.
    thickness = 3.2
    for base in (32, 96):
        top, bottom = [], []
        for step in range(0, TILE * 4 + 1):
            x = step / 4
            y = base + 7 * math.sin(2 * math.pi * x / TILE)
            top.append((x, y - thickness))
            bottom.append((x, y + thickness))
        _polygon(draw, top + bottom[::-1])


def grid(draw):
    for offset in (0, 32, 64, 96):
        strength = 230 if offset == 0 else 120
        for start in (offset - 1, offset):
            _polygon(
                draw,
                [(start, 0), (start + 1.6, 0), (start + 1.6, TILE), (start, TILE)],
                strength,
            )
            _polygon(
                draw,
                [(0, start), (TILE, start), (TILE, start + 1.6), (0, start + 1.6)],
                strength,
            )


PATTERNS = {
    "dots": dots,
    "gingham": gingham,
    "stripes": stripes,
    "hearts": hearts,
    "stars": stars,
    "flowers": flowers,
    "waves": waves,
    "grid": grid,
}


def render(paint):
    mask = Image.new("L", (_s(TILE), _s(TILE)), 0)
    paint(ImageDraw.Draw(mask))
    mask = mask.resize((TILE, TILE), Image.Resampling.LANCZOS)
    tile = Image.new("RGBA", (TILE, TILE), (255, 255, 255, 0))
    tile.putalpha(mask)
    return tile


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    for name, paint in PATTERNS.items():
        render(paint).save(ROOT / f"{name}.png", "PNG", optimize=True)
        print(f"{name}.png")


if __name__ == "__main__":
    main()
