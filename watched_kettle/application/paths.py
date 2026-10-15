"""Centralized filesystem locations used by the desktop application."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from watched_kettle.branding import APPLICATION_ID, LEGACY_APPLICATION_ID


# Hook events here expire within a minute, and the hook bridge may create this
# folder under the new root before the first start migrates the old data.
# Rebuilt or re-downloaded on demand; update_check.py keeps installers in updates.
DISPOSABLE_DATA_ENTRIES = frozenset({"runtime", "updates"})


def local_app_data():
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")


def _has_user_data(root):
    try:
        return any(
            entry.name not in DISPOSABLE_DATA_ENTRIES for entry in Path(root).iterdir()
        )
    except OSError:
        return False


def resolve_data_root(local=None):
    """Return the data root, keeping Private Beta data until it is migrated."""
    local = Path(local or local_app_data())
    current = local / APPLICATION_ID
    legacy = local / LEGACY_APPLICATION_ID
    if not _has_user_data(current) and _has_user_data(legacy):
        return legacy
    return current


def migrate_legacy_data_root(local=None):
    """Rename the Private Beta data folder once (ADR 0005).

    Returns ``"migrated"``, ``"kept_legacy"`` when another process holds the old
    folder (the next start retries), ``"skipped_link"`` for a linked folder, or
    ``"none"`` when nothing needs to move.
    """
    local = Path(local or local_app_data())
    current = local / APPLICATION_ID
    legacy = local / LEGACY_APPLICATION_ID
    if _has_user_data(current) or not _has_user_data(legacy):
        return "none"
    if legacy.is_symlink() or legacy.is_junction():
        return "skipped_link"
    try:
        if current.exists():
            shutil.rmtree(current)
        os.rename(legacy, current)
    except OSError:
        return "kept_legacy"
    return "migrated"


@dataclass(frozen=True)
class AppPaths:
    data_root: Path

    @classmethod
    def default(cls):
        return cls(resolve_data_root())

    @property
    def database(self):
        return self.data_root / "assistant-v1.sqlite3"

    @property
    def legacy_usage_history(self):
        return self.data_root / "usage-history-v1.json"

    @property
    def user_pets(self):
        return self.data_root / "pets"

    @property
    def logs(self):
        """Directory containing bounded, privacy-filtered application logs."""
        return self.data_root / "logs"
