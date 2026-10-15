"""Stage the private-beta pet packages for the invitation installer.

Only runtime files are copied: each manifest, its spritesheet, and the bubble
frame images it declares. Notes and provenance records stay in the repository.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from watched_kettle.build_profiles import (  # noqa: E402
    PRIVATE_BETA_BUILD_PROFILE,
    collect_pet_build_sources,
)


def stage_private_pets(project_root, destination):
    """Copy each private-beta package into ``destination/<folder>``."""
    destination = Path(destination)
    if destination.exists():
        raise ValueError("Use a new staging directory; it is never overwritten")
    sources = [
        source
        for source in collect_pet_build_sources(
            Path(project_root), PRIVATE_BETA_BUILD_PROFILE
        )
        if source.distribution == PRIVATE_BETA_BUILD_PROFILE
    ]
    if not sources:
        raise ValueError("No private-beta pet packages to stage")
    for source in sources:
        folder = destination / source.directory.name
        files = [source.manifest_path, source.spritesheet_path]
        files.extend(path for path, _bundle_folder in source.frame_images)
        for path in files:
            target = folder / path.relative_to(source.directory)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    return [source.pet_id for source in sources]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    staged = stage_private_pets(PROJECT_ROOT, args.destination)
    print(f"Staged {len(staged)} private pet packages: {args.destination}")


if __name__ == "__main__":
    main()
