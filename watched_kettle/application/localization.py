"""Connect immutable translation state to settings and lightweight helper processes."""

from __future__ import annotations

import json
import os
from pathlib import Path

from watched_kettle.localization import get_translator, set_translator
from watched_kettle.localization.packs import LanguagePacks
from watched_kettle.application.paths import AppPaths


def packs_for(preferences):
    packs = getattr(preferences, "language_packs", None)
    if packs is None:
        file_name = getattr(preferences.settings, "fileName", None)
        root = (
            Path(file_name()).parent / "language-packs" if callable(file_name) else None
        )
        packs = LanguagePacks(root, preferences.load_language_pack())
        packs.active = get_translator()
        preferences.language_packs = packs
    return packs


def initialize_language(preferences, paths=None):
    from watched_kettle.application.update_check import installer_language

    paths = paths or AppPaths.default()
    packs = LanguagePacks(
        paths.language_packs, preferences.load_language_pack(), installer_language()
    )
    preferences.language_packs = packs
    set_translator(packs.active)
    # A tiny display-only snapshot: the bridge does no pack discovery or Babel import.
    helper = {
        key: packs.active.text(key)
        for key in (
            "statusline.pet_off",
            "statusline.context",
            "statusline.five_hour",
            "statusline.seven_day",
        )
    }
    target = paths.data_root / "runtime" / "language-statusline.json"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(helper, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, target)
    except OSError:
        # Helper display failure cannot stop the pet or change integration state.
        pass
    return packs
