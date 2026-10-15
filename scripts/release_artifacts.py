"""Generate and verify release package file inventories."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import zipfile
from pathlib import Path


MANIFEST_NAME = "PACKAGE_MANIFEST.sha256.json"
# Per-user state lives under %LOCALAPPDATA%\WatchedKettle and must never ship.
FORBIDDEN_DIRECTORIES = frozenset(
    {
        "logs",
        "runtime",
        "bubble-elements",
        ".watched-kettle-runtime",
        ".codex-pets-runtime",
        ".codex",
        "__pycache__",
    }
)
FORBIDDEN_FILE_PATTERNS = (
    "settings.ini*",
    "*.sqlite3*",
    "usage-history-*.json",
    "hook-health.json",
    "*.electron",
    "*.pyc",
    "*.bak",
)
TEXT_SUFFIXES = frozenset(
    {".json", ".txt", ".md", ".html", ".cjs", ".js", ".yaml", ".yml", ".ini", ".cfg"}
)


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def generate_manifest(bundle_root: Path) -> Path:
    """Write a deterministic size and SHA-256 inventory beside bundle files."""
    bundle_root = Path(bundle_root).resolve()
    if not bundle_root.is_dir():
        raise FileNotFoundError(f"Bundle directory does not exist: {bundle_root}")
    target = bundle_root / MANIFEST_NAME
    entries = []
    for path in sorted(bundle_root.rglob("*")):
        if not path.is_file() or path == target:
            continue
        content = path.read_bytes()
        entries.append(
            {
                "path": path.relative_to(bundle_root).as_posix(),
                "size": len(content),
                "sha256": _sha256_bytes(content),
            }
        )
    manifest = {"schemaVersion": 1, "fileCount": len(entries), "files": entries}
    target.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def verify_archive(archive_path: Path) -> int:
    """Validate ZIP CRCs and every file described by its embedded manifest."""
    archive_path = Path(archive_path).resolve()
    with zipfile.ZipFile(archive_path) as archive:
        corrupt = archive.testzip()
        if corrupt:
            raise ValueError(f"ZIP CRC failed: {corrupt}")
        manifest_names = [
            name for name in archive.namelist() if name.endswith(f"/{MANIFEST_NAME}")
        ]
        if len(manifest_names) != 1:
            raise ValueError("ZIP must contain exactly one package manifest")
        manifest_name = manifest_names[0]
        prefix = manifest_name[: -len(MANIFEST_NAME)]
        manifest = json.loads(archive.read(manifest_name).decode("utf-8"))
        entries = manifest.get("files")
        if not isinstance(entries, list):
            raise ValueError("Package manifest files must be a list")
        expected = set()
        for entry in entries:
            relative = str(entry["path"])
            member = f"{prefix}{relative}"
            expected.add(member)
            content = archive.read(member)
            if len(content) != int(entry["size"]):
                raise ValueError(f"Package size mismatch: {relative}")
            if _sha256_bytes(content) != str(entry["sha256"]):
                raise ValueError(f"Package hash mismatch: {relative}")
        actual = {
            info.filename
            for info in archive.infolist()
            if not info.is_dir() and info.filename != manifest_name
        }
        if actual != expected:
            raise ValueError("ZIP contents differ from the package manifest")
        if int(manifest.get("fileCount", -1)) != len(entries):
            raise ValueError("Package manifest file count is inconsistent")
        return len(entries)


def _normalized(text: str) -> str:
    return text.casefold().replace("\\\\", "\\").replace("\\", "/")


def default_forbidden_roots() -> tuple[Path, ...]:
    """Build-machine locations whose paths must not appear inside a bundle."""
    roots = [Path(__file__).resolve().parents[1], Path.home()]
    for name in ("USERPROFILE", "LOCALAPPDATA", "APPDATA"):
        if os.environ.get(name):
            roots.append(Path(os.environ[name]))
    return tuple(roots)


def _code_strings(code):
    yield code.co_filename
    for constant in code.co_consts:
        if isinstance(constant, str):
            yield constant
        elif hasattr(constant, "co_consts"):
            yield from _code_strings(constant)


def _executable_strings(executable: Path):
    from PyInstaller.archive.readers import CArchiveReader

    archive = CArchiveReader(str(executable))
    for name in archive.toc:
        if not name.endswith(".pyz"):
            continue
        pyz = archive.open_embedded_archive(name)
        for module in pyz.toc:
            if module.split(".", 1)[0] != "watched_kettle":
                continue
            code = pyz.extract(module)
            if code is not None:
                yield module, _code_strings(code)


def check_bundle_state(bundle_root: Path, forbidden_roots=None) -> list[str]:
    """Return per-user state files and build-machine paths found in a bundle."""
    bundle_root = Path(bundle_root).resolve()
    if not bundle_root.is_dir():
        raise FileNotFoundError(f"Bundle directory does not exist: {bundle_root}")
    roots = [
        _normalized(str(root)).rstrip("/") + "/"
        for root in (
            default_forbidden_roots() if forbidden_roots is None else forbidden_roots
        )
    ]
    violations = []
    for path in sorted(bundle_root.rglob("*")):
        relative = path.relative_to(bundle_root)
        name = path.name.casefold()
        if path.is_dir():
            if name in FORBIDDEN_DIRECTORIES:
                violations.append(f"user state directory: {relative.as_posix()}/")
            continue
        if any(
            part.casefold() in FORBIDDEN_DIRECTORIES for part in relative.parts[:-1]
        ):
            continue  # Reported once through its directory.
        if any(fnmatch.fnmatch(name, pattern) for pattern in FORBIDDEN_FILE_PATTERNS):
            violations.append(f"user state file: {relative.as_posix()}")
            continue
        if path.suffix.casefold() in TEXT_SUFFIXES:
            text = _normalized(path.read_text(encoding="utf-8", errors="replace"))
            if any(root in text for root in roots):
                violations.append(f"build machine path in: {relative.as_posix()}")
        elif path.suffix.casefold() == ".exe" and path.parent == bundle_root:
            for module, strings in _executable_strings(path):
                if any(
                    root in _normalized(value) for value in strings for root in roots
                ):
                    violations.append(
                        f"build machine path in {relative.as_posix()}: {module}"
                    )
    return violations


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="operation", required=True)
    manifest_parser = subparsers.add_parser("manifest")
    manifest_parser.add_argument("bundle", type=Path)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("archive", type=Path)
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("bundle", type=Path)
    args = parser.parse_args()
    if args.operation == "manifest":
        print(generate_manifest(args.bundle))
    elif args.operation == "inspect":
        violations = check_bundle_state(args.bundle)
        for violation in violations:
            print(violation)
        if violations:
            return 1
        print("No per-user state or build machine paths in the bundle.")
    else:
        print(f"Verified {verify_archive(args.archive)} packaged files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
