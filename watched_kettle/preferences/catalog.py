"""catalog preferences; existing QSettings keys are preserved."""

import json

from .models import PET_CATALOG_SORT_NAME, PET_CATALOG_SORT_MODES, normalize_pet_id_list


class CatalogPreferences:
    def __init__(self, settings, placement=None):
        self.settings = settings
        self.placement = placement

    def load_selected_pet_id(self):
        value = self.settings.value("selectedPetId", "")
        return str(value or "")

    def save_selected_pet_id(self, pet_id):
        self.settings.setValue("selectedPetId", str(pet_id))

    def load_pet_catalog_sort_mode(self):
        mode = (
            str(
                self.settings.value(
                    "petCatalog/sortMode",
                    PET_CATALOG_SORT_NAME,
                )
                or PET_CATALOG_SORT_NAME
            )
            .strip()
            .casefold()
        )
        if mode not in PET_CATALOG_SORT_MODES:
            return PET_CATALOG_SORT_NAME
        return mode

    def save_pet_catalog_sort_mode(self, mode):
        mode = str(mode or "").strip().casefold()
        if mode not in PET_CATALOG_SORT_MODES:
            mode = PET_CATALOG_SORT_NAME
        self.settings.setValue("petCatalog/sortMode", mode)
        return mode

    def load_pet_custom_order(self):
        return normalize_pet_id_list(
            self.settings.value("petCatalog/customOrder", "[]")
        )

    def save_pet_custom_order(self, pet_ids):
        pet_ids = normalize_pet_id_list(tuple(pet_ids or ()))
        self.settings.setValue(
            "petCatalog/customOrder",
            json.dumps(pet_ids, ensure_ascii=False, separators=(",", ":")),
        )
        return pet_ids

    def load_hidden_pet_ids(self):
        return frozenset(
            normalize_pet_id_list(self.settings.value("petCatalog/hiddenIds", "[]"))
        )

    def save_hidden_pet_ids(self, pet_ids):
        pet_ids = tuple(sorted(normalize_pet_id_list(tuple(pet_ids or ()))))
        self.settings.setValue(
            "petCatalog/hiddenIds",
            json.dumps(pet_ids, ensure_ascii=False, separators=(",", ":")),
        )
        return frozenset(pet_ids)
