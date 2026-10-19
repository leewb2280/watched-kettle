"""Shared application identity and packaged branding resources."""

from pathlib import Path


APPLICATION_NAME = "Watched Kettle"
APPLICATION_VERSION = "0.15.7"
APPLICATION_DESCRIPTION = "Windows desktop pet that watches your coding agents"
# Install and user-data identifiers (ADR 0005). Never change after release.
APPLICATION_ID = "WatchedKettle"
APPLICATION_SLUG = "watched-kettle"
# Private Beta builds used this name for data, startup and Qt settings.
LEGACY_APPLICATION_ID = "CodexDesktopPets"
# Inno Setup AppId (packaging/windows-installer.iss); its uninstall entry is
# HKCU\...\Uninstall\{<this>}_is1. Never change after release.
INSTALLER_APP_GUID = "74FC68D2-EB57-452A-A11F-7787F5DF8B72"
# Public GitHub repositories (ADR 0008), written into Public bundles by
# scripts/build_windows.ps1. People download the installer from the release
# repository, whose tag page "변경 사항 보기" opens. The update check reads the
# update repository, which carries the update files. 0.15.3 and 0.15.4
# installs still read the release repository.
RELEASE_REPOSITORY = "leewb2280/watched-kettle"
UPDATE_REPOSITORY = "leewb2280/watched-kettle-updates"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_ICON_PATH = PROJECT_ROOT / "assets" / "app_icon.png"
