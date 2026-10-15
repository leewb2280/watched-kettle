"""Select pet packages for public and private-beta Windows bundles."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


PUBLIC_BUILD_PROFILE = "public"
PRIVATE_BETA_BUILD_PROFILE = "private-beta"
DEFAULT_BUILD_PROFILE = PRIVATE_BETA_BUILD_PROFILE
SUPPORTED_BUILD_PROFILES = frozenset(
    {
        PUBLIC_BUILD_PROFILE,
        PRIVATE_BETA_BUILD_PROFILE,
    }
)


class BuildProfileError(ValueError):
    """Raised when a build profile could leak or omit required pet assets."""


@dataclass(frozen=True)
class PetBuildSource:
    pet_id: str
    directory: Path
    manifest_path: Path
    spritesheet_path: Path
    destination: str
    distribution: str
    # (file, bundle folder) pairs for bubble frame images the manifest names.
    frame_images: tuple[tuple[Path, str], ...] = ()


def normalize_build_profile(profile):
    normalized = str(profile or DEFAULT_BUILD_PROFILE).strip().casefold()
    aliases = {
        "private": PRIVATE_BETA_BUILD_PROFILE,
        "privatebeta": PRIVATE_BETA_BUILD_PROFILE,
        "private_beta": PRIVATE_BETA_BUILD_PROFILE,
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in SUPPORTED_BUILD_PROFILES:
        raise BuildProfileError(f"unsupported pet build profile: {profile!r}")
    return normalized


def collect_pet_build_sources(project_root, profile=None):
    """Return validated pet packages allowed by the selected profile."""
    project_root = Path(project_root).resolve()
    profile = normalize_build_profile(profile)
    roots = [(project_root / "pets", PUBLIC_BUILD_PROFILE)]
    if profile == PRIVATE_BETA_BUILD_PROFILE:
        roots.append((project_root / "private-pets", PRIVATE_BETA_BUILD_PROFILE))

    sources = []
    seen_ids = set()
    seen_destinations = set()
    for pets_root, expected_distribution in roots:
        if not pets_root.is_dir():
            continue
        for manifest_path in sorted(pets_root.glob("*/pet.json")):
            manifest = _read_manifest(manifest_path)
            distribution = str(manifest.get("distribution") or "").strip().casefold()
            if not distribution:
                raise BuildProfileError(f"missing distribution marker: {manifest_path}")
            if distribution != expected_distribution:
                raise BuildProfileError(
                    f"{manifest_path} declares distribution={distribution!r}; "
                    f"expected {expected_distribution!r}"
                )

            pet_id = str(manifest.get("id") or manifest_path.parent.name).strip()
            if not pet_id:
                raise BuildProfileError(f"missing pet id: {manifest_path}")
            if pet_id in seen_ids:
                raise BuildProfileError(f"duplicate pet id: {pet_id}")

            spritesheet_name = manifest.get(
                "spritesheetPath",
                "spritesheet.webp",
            )
            if not isinstance(spritesheet_name, str) or not spritesheet_name:
                raise BuildProfileError(f"invalid spritesheetPath: {manifest_path}")
            pet_directory = manifest_path.parent.resolve()
            spritesheet_path = (pet_directory / spritesheet_name).resolve()
            if not spritesheet_path.is_relative_to(pet_directory):
                raise BuildProfileError(
                    f"spritesheet outside pet folder: {manifest_path}"
                )
            if not spritesheet_path.is_file():
                raise BuildProfileError(f"missing spritesheet: {spritesheet_path}")

            destination = f"pets/{manifest_path.parent.name}"
            if destination.casefold() in seen_destinations:
                raise BuildProfileError(f"duplicate bundled destination: {destination}")
            sources.append(
                PetBuildSource(
                    pet_id=pet_id,
                    directory=pet_directory,
                    manifest_path=manifest_path.resolve(),
                    spritesheet_path=spritesheet_path,
                    destination=destination,
                    distribution=distribution,
                    frame_images=_frame_images(
                        manifest, manifest_path, pet_directory, destination
                    ),
                )
            )
            seen_ids.add(pet_id)
            seen_destinations.add(destination.casefold())

    if not sources:
        if profile == PUBLIC_BUILD_PROFILE:
            raise BuildProfileError(
                "public build requires at least one rights-cleared pet in pets/"
            )
        raise BuildProfileError("private-beta build contains no pet packages")
    return tuple(sources)


def _frame_images(manifest, manifest_path, pet_directory, destination):
    """Bundle the images a package bubble frame declares, failing on bad paths."""
    theme = manifest.get("bubbleTheme")
    frame = theme.get("frame") if isinstance(theme, dict) else None
    if not isinstance(frame, dict):
        return ()
    images = []
    for section in ("backdrop", "overlay"):
        layers = frame.get(section)
        for layer in layers if isinstance(layers, list) else ():
            name = layer.get("image") if isinstance(layer, dict) else None
            if not isinstance(name, str):
                continue
            path = (pet_directory / name).resolve()
            if not path.is_relative_to(pet_directory) or not path.is_file():
                raise BuildProfileError(f"invalid bubble frame image: {manifest_path}")
            folder = path.parent.relative_to(pet_directory).as_posix()
            target = destination if folder == "." else f"{destination}/{folder}"
            if (path, target) not in images:
                images.append((path, target))
    return tuple(images)


def _read_manifest(manifest_path):
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BuildProfileError(f"invalid pet manifest: {manifest_path}") from error
    if not isinstance(manifest, dict):
        raise BuildProfileError(f"invalid pet manifest: {manifest_path}")
    return manifest
