"""Discover locally available pet packages without loading their atlases."""

import json

from dataclasses import dataclass
from pathlib import Path

from watched_kettle.localization import get_translator


@dataclass(frozen=True)
class PetCatalogEntry:
    id: str
    display_name: str
    description: str
    directory: Path
    spritesheet_path: Path


def localized_description(manifest):
    """The active locale's description (exact tag, then language), else the default."""
    default = str(manifest.get("description") or "")
    variants = manifest.get("localizedDescriptions")
    if not isinstance(variants, dict):
        return default
    variants = {
        str(tag).casefold(): text
        for tag, text in variants.items()
        if isinstance(text, str) and text.strip()
    }
    locale = get_translator().locale.casefold()
    return variants.get(locale) or variants.get(locale.split("-")[0]) or default


def pet_name_sort_key(entry):
    return entry.display_name.casefold(), entry.id.casefold()


def order_pet_entries(entries, sort_mode="name", custom_order=()):
    """Order entries by display name or a stable user-defined ID list."""
    entries = list(entries)
    name_sorted = sorted(entries, key=pet_name_sort_key)
    if sort_mode != "custom":
        return name_sorted

    ranks = {
        str(pet_id): index for index, pet_id in enumerate(custom_order) if str(pet_id)
    }
    ranked = [entry for entry in name_sorted if entry.id in ranks]
    ranked.sort(key=lambda entry: ranks[entry.id])
    return ranked + [entry for entry in name_sorted if entry.id not in ranks]


def personalize_pet_catalog(
    entries,
    sort_mode="name",
    custom_order=(),
    hidden_ids=(),
    fallback_pet_id=None,
    required_visible_id=None,
):
    """Apply user ordering and visibility with a recoverable empty-list guard."""
    ordered = order_pet_entries(entries, sort_mode, custom_order)
    hidden_ids = {str(pet_id) for pet_id in hidden_ids}
    if required_visible_id:
        hidden_ids.discard(str(required_visible_id))
    visible = [entry for entry in ordered if entry.id not in hidden_ids]
    if visible or not ordered:
        return visible

    fallback = next(
        (entry for entry in ordered if entry.id == str(fallback_pet_id or "")),
        ordered[0],
    )
    return [fallback]


def discover_pets(pets_root: Path):
    """Return valid immediate child pet packages in a stable display order."""
    pets_root = Path(pets_root)
    if not pets_root.is_dir():
        return []

    entries = []
    seen_ids = set()

    for pet_directory in sorted(
        (path for path in pets_root.iterdir() if path.is_dir()),
        key=lambda path: path.name.casefold(),
    ):
        manifest_path = pet_directory / "pet.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue

        if not isinstance(manifest, dict):
            continue

        pet_id = str(manifest.get("id") or pet_directory.name).strip()
        if not pet_id or pet_id in seen_ids:
            continue

        spritesheet_name = manifest.get(
            "spritesheetPath",
            "spritesheet.webp",
        )
        if not isinstance(spritesheet_name, str) or not spritesheet_name:
            continue

        try:
            resolved_directory = pet_directory.resolve()
            spritesheet_path = (pet_directory / spritesheet_name).resolve()
            if not spritesheet_path.is_relative_to(resolved_directory):
                continue
        except OSError:
            continue

        if not spritesheet_path.is_file():
            continue

        display_name = str(
            manifest.get("displayName") or manifest.get("name") or pet_directory.name
        )
        entries.append(
            PetCatalogEntry(
                id=pet_id,
                display_name=display_name,
                description=localized_description(manifest),
                directory=pet_directory,
                spritesheet_path=spritesheet_path,
            )
        )
        seen_ids.add(pet_id)

    return sorted(
        entries,
        key=pet_name_sort_key,
    )


def discover_pets_in_roots(pets_roots):
    """Merge catalogs from several roots, keeping the first duplicate ID."""
    entries = []
    seen_ids = set()
    seen_directories = set()
    for pets_root in pets_roots:
        root = Path(pets_root)
        try:
            resolved_root = root.resolve()
        except OSError:
            resolved_root = root
        if resolved_root in seen_directories:
            continue
        seen_directories.add(resolved_root)
        for entry in discover_pets(root):
            if entry.id in seen_ids:
                continue
            entries.append(entry)
            seen_ids.add(entry.id)
    return sorted(
        entries,
        key=pet_name_sort_key,
    )


def find_pet(pets_root: Path, pet_id):
    pet_id = str(pet_id or "")
    return next(
        (entry for entry in discover_pets(pets_root) if entry.id == pet_id),
        None,
    )
