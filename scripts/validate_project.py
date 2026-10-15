"""Validate repository invariants that are easy for documentation to drift from."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from watched_kettle.build_profiles import (
    PRIVATE_BETA_BUILD_PROFILE,
    PUBLIC_BUILD_PROFILE,
    BuildProfileError,
    collect_pet_build_sources,
)


MARKDOWN_LINK = re.compile(r"(?<!!)\[[^]]*]\(([^)]+)\)")
ROADMAP_STAGE = re.compile(r"^#{2,3}\s+(\d+(?:\.\d+)?)\.\s", re.MULTILINE)
VERSION_ASSIGNMENT = re.compile(
    r'^APPLICATION_VERSION\s*=\s*["\']([^"\']+)["\']', re.MULTILINE
)


def validate_markdown_links() -> list[str]:
    """Return errors for local Markdown links whose targets do not exist."""
    errors: list[str] = []
    for document in (PROJECT_ROOT / "README.md", PROJECT_ROOT / "ROADMAP.md"):
        if document.is_file():
            errors.extend(_document_link_errors(document))
    placed = _public_destinations()
    moved = {destination.resolve() for destination in placed.values()}
    for document in (PROJECT_ROOT / "docs").rglob("*.md"):
        errors.extend(
            _document_link_errors(document, placed.get(document.resolve()), moved)
        )
    return errors


def _public_destinations() -> dict[Path, Path]:
    """Documents the public snapshot moves (docs/public/README.md -> README.md).

    Their links are written for the moved location, so they are checked there,
    and the moved files count as present at their destinations.
    """
    manifest = PROJECT_ROOT / "packaging" / "public-source-files.json"
    if not manifest.is_file():
        return {}
    entries = json.loads(manifest.read_text(encoding="utf-8-sig"))["files"]
    return {
        (PROJECT_ROOT / entry["source"]).resolve(): PROJECT_ROOT / entry["destination"]
        for entry in entries
        if entry.get("destination") and entry["source"].endswith(".md")
    }


def _document_link_errors(
    document: Path, placed: Path | None = None, moved: frozenset | set = frozenset()
) -> list[str]:
    errors: list[str] = []
    base = (placed or document).parent
    text = document.read_text(encoding="utf-8")
    for raw_target in MARKDOWN_LINK.findall(text):
        target = raw_target.strip().strip("<>").split("#", 1)[0]
        if not target or "://" in target or target.startswith(("mailto:", "codex:")):
            continue
        resolved = (base / target).resolve()
        if not resolved.exists() and resolved not in moved:
            errors.append(
                f"{document.relative_to(PROJECT_ROOT)}: missing link {raw_target}"
            )
    return errors


def validate_roadmap_stages() -> list[str]:
    """Ensure active roadmap stage identifiers are unique."""
    roadmap = PROJECT_ROOT / "ROADMAP.md"
    if not roadmap.is_file():
        # The public snapshot ships without development records.
        return []
    text = roadmap.read_text(encoding="utf-8")
    stages = ROADMAP_STAGE.findall(text)
    duplicates = sorted({stage for stage in stages if stages.count(stage) > 1})
    return [f"ROADMAP.md: duplicate stage {stage}" for stage in duplicates]


def validate_version_source() -> list[str]:
    """Ensure code owns the version and current documentation mirrors that value."""
    branding = (PROJECT_ROOT / "watched_kettle" / "branding.py").read_text(
        encoding="utf-8"
    )
    match = VERSION_ASSIGNMENT.search(branding)
    if match is None:
        return ["watched_kettle/branding.py: APPLICATION_VERSION is missing"]
    version = match.group(1)
    if re.fullmatch(r"\d+\.\d+\.\d+", version) is None:
        return [f"watched_kettle/branding.py: invalid version {version!r}"]

    # These are mirrors for people reading the repository. Requiring the code-owned
    # value here keeps them useful without turning either document into a second source.
    # The public snapshot has neither the status page nor the Private Beta README.
    if not (PROJECT_ROOT / "docs" / "project-status.md").is_file():
        return []
    expected_references = {
        PROJECT_ROOT / "README.md": f"**{version} Private Beta**",
        PROJECT_ROOT / "docs" / "project-status.md": f"{version} Private Beta**",
    }
    errors: list[str] = []
    for document, expected in expected_references.items():
        if expected not in document.read_text(encoding="utf-8"):
            errors.append(
                f"{document.relative_to(PROJECT_ROOT)}: current version must be {version}"
            )
    return errors


def validate_pet_manifests() -> list[str]:
    """Validate runtime pet manifests without decoding large sprite atlases."""
    errors: list[str] = []
    for root_name in ("pets", "private-pets"):
        root = PROJECT_ROOT / root_name
        for manifest_path in root.glob("*/pet.json"):
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                errors.append(f"{manifest_path.relative_to(PROJECT_ROOT)}: {error}")
                continue
            if not isinstance(payload, dict):
                errors.append(
                    f"{manifest_path.relative_to(PROJECT_ROOT)}: root must be an object"
                )
                continue
            if not str(payload.get("id") or "").strip():
                errors.append(
                    f"{manifest_path.relative_to(PROJECT_ROOT)}: id is required"
                )
            relative_sprite = Path(
                str(payload.get("spritesheetPath") or "spritesheet.webp")
            )
            sprite_path = (manifest_path.parent / relative_sprite).resolve()
            try:
                sprite_path.relative_to(manifest_path.parent.resolve())
            except ValueError:
                errors.append(
                    f"{manifest_path.relative_to(PROJECT_ROOT)}: sprite escapes package"
                )
                continue
            if not sprite_path.is_file():
                errors.append(
                    f"{manifest_path.relative_to(PROJECT_ROOT)}: sprite is missing"
                )
    try:
        sources = collect_pet_build_sources(PROJECT_ROOT, PRIVATE_BETA_BUILD_PROFILE)
    except BuildProfileError as error:
        errors.append(f"PrivateBeta build boundary: {error}")
    else:
        allowed = {PUBLIC_BUILD_PROFILE, PRIVATE_BETA_BUILD_PROFILE}
        if any(source.distribution not in allowed for source in sources):
            errors.append("PrivateBeta build boundary: unexpected distribution")
    return errors


def validate_workspace_tracking() -> list[str]:
    """Prevent generated pet source and QA artifacts from returning to Git."""
    if not (PROJECT_ROOT / "pet-workspaces").is_dir():
        return []
    result = subprocess.run(
        ["git", "ls-files", "pet-workspaces/**"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        return ["git ls-files failed while checking pet-workspaces"]
    allowed = {"pet-workspaces/README.md"}
    tracked = {
        line.strip().replace("\\", "/")
        for line in result.stdout.splitlines()
        if line.strip()
    }
    forbidden = sorted(tracked - allowed)
    if not forbidden:
        return []
    preview = ", ".join(forbidden[:3])
    suffix = f" and {len(forbidden) - 3} more" if len(forbidden) > 3 else ""
    return [f"pet-workspaces: generated files are tracked: {preview}{suffix}"]


def main() -> int:
    """Run every repository invariant and return a process exit code."""
    errors = [
        *validate_markdown_links(),
        *validate_roadmap_stages(),
        *validate_version_source(),
        *validate_pet_manifests(),
        *validate_workspace_tracking(),
    ]
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Project structure validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
