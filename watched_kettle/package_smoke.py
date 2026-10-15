"""Read-only smoke check used against a packaged Windows bundle."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication

from watched_kettle.pet.catalog import discover_pets
from watched_kettle.pet.loader import load_pet
from watched_kettle.ui.fonts import (
    PRETENDARD_FAMILY,
    PRETENDARD_FILES,
    PRETENDARD_ROOT,
    register_bundled_fonts,
)


def run_package_smoke(pets_root, font_root=PRETENDARD_ROOT):
    app = QApplication.instance() or QApplication([])
    font_root = Path(font_root)
    if not (font_root / "OFL.txt").is_file() or any(
        not (font_root / filename).is_file() for filename in PRETENDARD_FILES
    ):
        return 4
    if register_bundled_fonts(font_root) != PRETENDARD_FAMILY:
        return 4
    entries = discover_pets(Path(pets_root))
    if not entries:
        return 2
    try:
        for entry in entries:
            load_pet(entry.directory)
    except (OSError, TypeError, UnicodeDecodeError, ValueError):
        return 3
    finally:
        if QApplication.instance() is app:
            app.processEvents()
    return 0
