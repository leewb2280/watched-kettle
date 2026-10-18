from watched_kettle.localization import t
# pet_loader.py

import json
import logging
from pathlib import Path

from PIL import Image
from PIL.ImageQt import ImageQt

from PySide6.QtGui import QPixmap, QTransform

from watched_kettle.config import (
    FRAME_WIDTH,
    FRAME_HEIGHT,
    ATLAS_COLUMNS,
    ANIMATIONS,
)
from watched_kettle.pet.bubble_frame import register_package_frame
from watched_kettle.pet.look_direction import mirrored_right_frame_source


logger = logging.getLogger(__name__)


def load_pet(pet_directory: Path):
    json_path = pet_directory / "pet.json"

    if not json_path.exists():
        raise FileNotFoundError(t("message.0150", value0=json_path))

    if json_path.stat().st_size > 256 * 1024:
        raise ValueError("pet_metadata_too_large")
    with json_path.open("rb") as stream:
        raw = stream.read(256 * 1024 + 1)
    if len(raw) > 256 * 1024:
        raise ValueError("pet_metadata_too_large")
    manifest = json.loads(raw)

    if not isinstance(manifest, dict):
        raise ValueError(t("message.0151"))

    spritesheet_name = manifest.get(
        "spritesheetPath",
        "spritesheet.webp",
    )

    if not isinstance(spritesheet_name, str) or not spritesheet_name.strip():
        raise ValueError(t("message.0152"))

    resolved_directory = pet_directory.resolve()
    spritesheet_path = (pet_directory / spritesheet_name).resolve()
    if not spritesheet_path.is_relative_to(resolved_directory):
        raise ValueError(t("message.0153"))

    if not spritesheet_path.exists():
        raise FileNotFoundError(t("message.0154", value0=spritesheet_path))

    with Image.open(spritesheet_path) as source:
        detect_sprite_version(source)
        atlas = source.convert("RGBA")

    sprite_version, rows = detect_sprite_version(atlas)
    logger.info(
        "pet package loaded atlas=%sx%s sprite_version=%s rows=%s",
        atlas.width,
        atlas.height,
        sprite_version,
        rows,
    )

    frames = extract_frames(atlas)
    look_frames = extract_look_frames(atlas, sprite_version)

    if manifest.get("mirrorRightLookFromLeft", False):
        look_frames = mirror_right_look_from_left(look_frames)

    # Bubble themes name the frame "pet:<id>"; painting looks it up there.
    register_package_frame(manifest, pet_directory)
    return manifest, frames, look_frames, sprite_version


def detect_sprite_version(atlas: Image.Image):
    width, height = atlas.size

    expected_width = FRAME_WIDTH * ATLAS_COLUMNS

    if width != expected_width:
        raise ValueError(t("message.0155", value0=width, value1=expected_width))

    if height == FRAME_HEIGHT * 9:
        return 1, 9

    if height == FRAME_HEIGHT * 11:
        return 2, 11

    raise ValueError(t("message.0149", value0=atlas.size))


def extract_frames(atlas: Image.Image):
    frames = {}

    for state, info in ANIMATIONS.items():
        row = info["row"]
        frame_count = info["frames"]

        frames[state] = []

        for column in range(frame_count):
            left = column * FRAME_WIDTH
            top = row * FRAME_HEIGHT

            frame = atlas.crop(
                (
                    left,
                    top,
                    left + FRAME_WIDTH,
                    top + FRAME_HEIGHT,
                )
            )

            qimage = ImageQt(frame)

            pixmap = QPixmap.fromImage(qimage)

            frames[state].append(pixmap)

    return frames


def extract_look_frames(
    atlas: Image.Image,
    sprite_version: int,
):
    """Extract V2 look poses in clockwise order, starting at 12 o'clock."""
    if sprite_version < 2:
        return []

    look_frames = []

    for row in (9, 10):
        for column in range(ATLAS_COLUMNS):
            left = column * FRAME_WIDTH
            top = row * FRAME_HEIGHT

            frame = atlas.crop(
                (
                    left,
                    top,
                    left + FRAME_WIDTH,
                    top + FRAME_HEIGHT,
                )
            )

            qimage = ImageQt(frame)
            look_frames.append(QPixmap.fromImage(qimage))

    return look_frames


def mirror_right_look_from_left(look_frames):
    if len(look_frames) != 16:
        return look_frames

    horizontal_flip = QTransform.fromScale(-1, 1)
    corrected_frames = []

    for direction_index in range(16):
        source_index, should_flip = mirrored_right_frame_source(direction_index)
        source_frame = look_frames[source_index]

        if should_flip:
            source_frame = source_frame.transformed(horizontal_flip)

        corrected_frames.append(source_frame)

    return corrected_frames
