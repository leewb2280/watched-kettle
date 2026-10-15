"""Generate PyInstaller version metadata from the application version source."""

from __future__ import annotations

import argparse
from pathlib import Path

from watched_kettle.branding import APPLICATION_VERSION


def render_version_info(version: str = APPLICATION_VERSION) -> str:
    """Return PyInstaller VSVersionInfo text for one semantic version."""
    parts = tuple(int(part) for part in version.split("."))
    if len(parts) != 3:
        raise ValueError("APPLICATION_VERSION must use major.minor.patch")
    numeric = ", ".join(str(part) for part in (*parts, 0))
    file_version = f"{version}.0"
    return f'''VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({numeric}),
    prodvers=({numeric}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0),
  ),
  kids=[
    StringFileInfo([
      StringTable(
        "040904B0",
        [
          StringStruct("CompanyName", "Watched Kettle"),
          StringStruct(
            "FileDescription",
            "Watched Kettle - Windows desktop pet assistant",
          ),
          StringStruct("FileVersion", "{file_version}"),
          StringStruct("InternalName", "WatchedKettle"),
          StringStruct("LegalCopyright", "Copyright (c) 2026 leewb2280"),
          StringStruct("OriginalFilename", "WatchedKettle.exe"),
          StringStruct("ProductName", "Watched Kettle"),
          StringStruct("ProductVersion", "{version}"),
        ],
      )
    ]),
    VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
  ],
)
'''


def main() -> int:
    """Write version metadata to the build-owned output path."""
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(render_version_info(), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
