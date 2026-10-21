"""What the settings window's About page shows; no Qt or UI imports."""

from __future__ import annotations

from pathlib import Path
import sys

from watched_kettle.branding import APPLICATION_VERSION, RELEASE_REPOSITORY
from watched_kettle.localization import t

# scripts.validate_project fails when this lags APPLICATION_VERSION, so a
# version bump also rewrites what's new (docs/releasing.md).
WHATS_NEW_VERSION = "0.15.10"
REPOSITORY_URL = f"https://github.com/{RELEASE_REPOSITORY}"
# Bundled components named in THIRD_PARTY_NOTICES.md, as (name, license).
THIRD_PARTY = (
    ("Electron · Chromium · Node.js", "MIT · BSD-3-Clause"),
    ("React · React DOM", "MIT"),
    ("Lucide React", "ISC"),
    ("Python", "PSF-2.0"),
    ("PySide6 · Shiboken6 · Qt", "LGPL-3.0"),
    ("Pillow", "MIT-CMU"),
    ("Babel", "BSD-3-Clause"),
    ("PyInstaller bootloader", "GPL-2.0+ with bootloader exception"),
    ("Pretendard", "OFL-1.1"),
    ("yangbuyiya/desktop-pet", "MIT"),
)


def whats_new():
    """This version's highlights, in the active language."""
    return [t("whats_new.01510.bubble_repeat")]


def links(version=APPLICATION_VERSION):
    # The public repository holds only allowlisted files, without CHANGELOG.md,
    # so the version history points at its Releases.
    return dict(
        repository=REPOSITORY_URL,
        releaseNotes=f"{REPOSITORY_URL}/releases/tag/v{version}",
        changelog=f"{REPOSITORY_URL}/releases",
        issues=f"{REPOSITORY_URL}/issues",
        license=f"{REPOSITORY_URL}/blob/main/LICENSE",
    )


def licenses_folder(executable=None):
    """The bundle's licenses folder (scripts/build_windows.ps1), or None."""
    if executable is None:
        if not getattr(sys, "frozen", False):
            return None
        executable = sys.executable
    folder = Path(executable).resolve().parent / "licenses"
    return folder if folder.is_dir() else None


def about_info(edition):
    return dict(
        version=APPLICATION_VERSION,
        edition=edition,
        whatsNewVersion=WHATS_NEW_VERSION,
        whatsNew=whats_new(),
        links=links(),
        thirdParty=[dict(name=name, license=value) for name, value in THIRD_PARTY],
        licensesAvailable=licenses_folder() is not None,
    )
