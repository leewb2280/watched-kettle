"""Bundled UI font registration with a safe system fallback."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from watched_kettle.branding import PROJECT_ROOT


PRETENDARD_FAMILY = "Pretendard"
PRETENDARD_ROOT = PROJECT_ROOT / "assets" / "fonts" / "Pretendard"
PRETENDARD_FILES = (
    "Pretendard-Regular.otf",
    "Pretendard-Medium.otf",
    "Pretendard-SemiBold.otf",
    "Pretendard-Bold.otf",
)

_registered_family = None


def register_bundled_fonts(font_root=None):
    """Register the bundled Pretendard faces and return the usable family."""
    global _registered_family
    if _registered_family is not None and font_root is None:
        return _registered_family

    root = Path(font_root) if font_root is not None else PRETENDARD_ROOT
    registered_families = set()
    for filename in PRETENDARD_FILES:
        path = root / filename
        if not path.is_file():
            continue
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id >= 0:
            registered_families.update(QFontDatabase.applicationFontFamilies(font_id))

    family = (
        PRETENDARD_FAMILY
        if PRETENDARD_FAMILY in registered_families
        else QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont).family()
    )
    if font_root is None:
        _registered_family = family
    return family


def configure_application_font(app=None):
    """Apply the bundled family while preserving the platform default size."""
    app = app or QApplication.instance()
    family = register_bundled_fonts()
    if app is not None:
        font = app.font()
        font.setFamily(family)
        app.setFont(font)
    return family
