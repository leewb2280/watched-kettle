from watched_kettle.localization import t
# pet_loader.py

import json
import logging
from pathlib import Path

from PIL import Image, ImageOps

from watched_kettle.config import (
    FRAME_WIDTH,
    FRAME_HEIGHT,
    ATLAS_COLUMNS,
    ANIMATIONS,
)
from watched_kettle.pet.bubble_frame import register_package_frame
from watched_kettle.pet.import_package import PET_IMAGE_FORMATS
from watched_kettle.pet.look_direction import mirrored_right_frame_source
from watched_kettle.pet.packed_frames import FrameDecodeCache, PackedFrames


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

    with Image.open(spritesheet_path, formats=PET_IMAGE_FORMATS) as source:
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

    # One decode cache for every frame of this pet, look variants included.
    cache = FrameDecodeCache()
    frames = extract_frames(atlas, cache)
    look_frames = extract_look_frames(
        atlas,
        sprite_version,
        cache,
        mirror_right=manifest.get("mirrorRightLookFromLeft", False),
    )

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


def load_appearance_frames(directory, manifest, frames, look_frames, version):
    from io import BytesIO
    from watched_kettle.pet.appearance_assets import (
        MAX_APPEARANCE_IMAGE_BYTES,
        parse_appearance_set,
        validate_appearance_image,
        invalid_appearance,
    )
    from watched_kettle.pet.import_package import read_local

    spec = parse_appearance_set(manifest)
    if spec is None:
        return None, {}, {}
    if version != 2:
        raise invalid_appearance()
    variants, transitions = {}, {}
    cache = getattr(look_frames, "cache", None)
    for variant in spec.variants:
        raw = read_local(directory, variant.path, MAX_APPEARANCE_IMAGE_BYTES)
        with Image.open(BytesIO(raw), formats=PET_IMAGE_FORMATS) as image:
            atlas = validate_appearance_image(image)
        if variant.id == spec.default:
            variants[variant.id] = (frames, look_frames)
        else:
            looks = extract_look_frames(
                atlas,
                2,
                cache,
                mirror_right=manifest.get("mirrorRightLookFromLeft", False),
            )
            variants[variant.id] = (extract_frames(atlas, cache), looks)
    for transition in spec.transitions:
        raw = read_local(directory, transition.path, MAX_APPEARANCE_IMAGE_BYTES)
        with Image.open(BytesIO(raw), formats=PET_IMAGE_FORMATS) as image:
            strip = validate_appearance_image(image, frames=transition.frames)
        transitions[(transition.source, transition.target)] = PackedFrames.from_images(
            (
                strip.crop((c * FRAME_WIDTH, 0, (c + 1) * FRAME_WIDTH, FRAME_HEIGHT))
                for c in range(transition.frames)
            ),
            cache,
        )
    return spec, variants, transitions


def _cell(atlas: Image.Image, row, column):
    left, top = column * FRAME_WIDTH, row * FRAME_HEIGHT
    return atlas.crop((left, top, left + FRAME_WIDTH, top + FRAME_HEIGHT))


def extract_frames(atlas: Image.Image, cache=None):
    """Each state's frames, kept compressed; indexing yields a QPixmap."""
    cache = cache if cache is not None else FrameDecodeCache()
    return {
        state: PackedFrames.from_images(
            (_cell(atlas, info["row"], column) for column in range(info["frames"])),
            cache,
        )
        for state, info in ANIMATIONS.items()
    }


def extract_look_frames(
    atlas: Image.Image,
    sprite_version: int,
    cache=None,
    *,
    mirror_right=False,
):
    """V2 look poses in clockwise order, starting at 12 o'clock.

    With ``mirror_right`` the right-side poses are the left ones flipped, as a
    package that draws only one side asks.
    """
    cache = cache if cache is not None else FrameDecodeCache()
    if sprite_version < 2:
        return PackedFrames((), cache)
    cells = [
        _cell(atlas, row, column) for row in (9, 10) for column in range(ATLAS_COLUMNS)
    ]
    if mirror_right and len(cells) == 16:
        corrected = []
        for direction_index in range(16):
            source_index, should_flip = mirrored_right_frame_source(direction_index)
            cell = cells[source_index]
            corrected.append(ImageOps.mirror(cell) if should_flip else cell)
        cells = corrected
    return PackedFrames.from_images(cells, cache)
