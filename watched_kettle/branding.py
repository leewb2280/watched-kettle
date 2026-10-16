"""Shared application identity and packaged branding resources."""

from pathlib import Path


APPLICATION_NAME = "Watched Kettle"
APPLICATION_VERSION = "0.15.4"
APPLICATION_DESCRIPTION = "Windows desktop pet that watches your coding agents"
# Install and user-data identifiers (ADR 0005). Never change after release.
APPLICATION_ID = "WatchedKettle"
APPLICATION_SLUG = "watched-kettle"
# Private Beta builds used this name for data, startup and Qt settings.
LEGACY_APPLICATION_ID = "CodexDesktopPets"
# Inno Setup AppId (packaging/windows-installer.iss); its uninstall entry is
# HKCU\...\Uninstall\{<this>}_is1. Never change after release.
INSTALLER_APP_GUID = "74FC68D2-EB57-452A-A11F-7787F5DF8B72"
# Public GitHub repository whose Releases the update check reads
# (scripts/build_windows.ps1 writes it into Public bundles).
UPDATE_REPOSITORY = "leewb2280/watched-kettle"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_ICON_PATH = PROJECT_ROOT / "assets" / "app_icon.png"
