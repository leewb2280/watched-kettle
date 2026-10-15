"""Recoverable pet selection and loading during application startup."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from PIL import UnidentifiedImageError

from watched_kettle.config import DEFAULT_PET_ID
from watched_kettle.pet.catalog import (
    discover_pets_in_roots,
    personalize_pet_catalog,
)


PET_STARTUP_EXCEPTIONS = (
    FileNotFoundError,
    json.JSONDecodeError,
    OSError,
    TypeError,
    UnidentifiedImageError,
    UnicodeDecodeError,
    ValueError,
)


@dataclass(frozen=True)
class FailedPetLoad:
    directory: Path
    error_type: str
    message: str


@dataclass(frozen=True)
class StartupPetResult:
    pet: object
    directory: Path
    failures: tuple[FailedPetLoad, ...] = ()


class StartupPetLoadError(RuntimeError):
    def __init__(self, search_root, failures):
        self.search_root = Path(search_root)
        self.failures = tuple(failures)
        super().__init__(self.user_message)

    @property
    def user_message(self):
        if not self.failures:
            return f"사용 가능한 펫을 찾지 못했습니다: {self.search_root}"
        last = self.failures[-1]
        return (
            f"펫 {len(self.failures)}개를 불러오지 못했습니다.\n"
            f"마지막 오류: {last.message or last.error_type}"
        )

    @property
    def details(self):
        if not self.failures:
            return f"검색 폴더: {self.search_root}"
        return "\n\n".join(
            f"{failure.directory}\n{failure.error_type}: {failure.message}"
            for failure in self.failures
        )


def startup_pet_candidates(
    pet_directory,
    preferences,
    pets_root,
    additional_pets_roots=(),
):
    """Return unique candidates in explicit, selected, default, catalog order."""
    if pet_directory is not None:
        return [Path(pet_directory)]

    all_entries = discover_pets_in_roots(
        (Path(pets_root), *(Path(root) for root in additional_pets_roots))
    )
    entries = personalize_pet_catalog(
        all_entries,
        preferences.load_pet_catalog_sort_mode(),
        preferences.load_pet_custom_order(),
        preferences.load_hidden_pet_ids(),
        fallback_pet_id=DEFAULT_PET_ID,
    )
    by_id = {entry.id: entry for entry in entries}
    installed_ids = {entry.id for entry in all_entries}
    ordered = []
    selected_pet_id = preferences.load_selected_pet_id()
    selected_is_hidden = (
        selected_pet_id in installed_ids and selected_pet_id not in by_id
    )
    priority_ids = () if selected_is_hidden else (selected_pet_id, DEFAULT_PET_ID)
    for pet_id in priority_ids:
        entry = by_id.get(str(pet_id or ""))
        if entry is not None and entry.directory not in ordered:
            ordered.append(entry.directory)
    for entry in entries:
        if entry.directory not in ordered:
            ordered.append(entry.directory)
    return ordered


def create_startup_pet(
    pet_factory,
    pet_directory,
    preferences,
    pets_root,
    settings=None,
    additional_pets_roots=(),
    pet_factory_kwargs=None,
):
    """Create the first loadable pet and retain safe diagnostics for failures."""
    candidates = startup_pet_candidates(
        pet_directory,
        preferences,
        pets_root,
        additional_pets_roots,
    )
    pet_factory_kwargs = dict(pet_factory_kwargs or {})
    failures = []
    for candidate in candidates:
        try:
            pet = pet_factory(
                Path(candidate),
                settings=settings,
                **pet_factory_kwargs,
            )
        except PET_STARTUP_EXCEPTIONS as error:
            failures.append(
                FailedPetLoad(
                    directory=Path(candidate),
                    error_type=type(error).__name__,
                    message=str(error),
                )
            )
            continue
        return StartupPetResult(
            pet=pet,
            directory=Path(candidate),
            failures=tuple(failures),
        )

    raise StartupPetLoadError(pets_root, failures)
