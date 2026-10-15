"""Migrate legacy registry settings to a shared per-user settings file."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSettings

from watched_kettle.application.paths import AppPaths
from watched_kettle.branding import LEGACY_APPLICATION_ID


# Oldest builds kept settings in the registry before settings.ini existed.
LEGACY_REGISTRY_SETTINGS = (LEGACY_APPLICATION_ID, "DesktopPet")


def settings_path(paths=None):
    return (paths or AppPaths.default()).data_root / "settings.ini"


def migrate_registry_settings(target=None, legacy=None):
    target = Path(target or settings_path())
    if target.exists():
        return True
    legacy = legacy or QSettings(*LEGACY_REGISTRY_SETTINGS)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".migrating")
    if temporary.exists():
        temporary.unlink()
    candidate = QSettings(str(temporary), QSettings.Format.IniFormat)
    for key in legacy.allKeys():
        candidate.setValue(key, legacy.value(key))
    candidate.setValue("internal/settingsFormat", 1)
    candidate.sync()
    if candidate.status() != QSettings.Status.NoError or not temporary.is_file():
        temporary.unlink(missing_ok=True)
        return False
    os.replace(temporary, target)
    return True


def open_settings(paths=None):
    path = settings_path(paths)
    if not migrate_registry_settings(path):
        # Keep the old values available if migration could not be completed.
        return QSettings(*LEGACY_REGISTRY_SETTINGS)
    settings = QSettings(str(path), QSettings.Format.IniFormat)
    if settings.status() != QSettings.Status.NoError:
        return QSettings(*LEGACY_REGISTRY_SETTINGS)
    return settings
