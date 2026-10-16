"""Partial update assets: names, the release index, and staging a runtime.

A release publishes, beside the full installers, one index per version and
for each edition its file list, an update installer and zips of the files
that changed since up to three earlier releases (docs/decisions/0007). The
app picks the zip for its own version, builds the new runtime next to the
current one from that zip plus hard links to unchanged files, and the
launcher swaps the folders. Qt-free, so scripts/build_update_assets.py uses
the same rules to write what the app reads.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import zipfile

INDEX_SCHEMA = 1
EDITIONS = ("pet-only", "pet-assistant")
# Deltas from this many earlier releases; older installs take a full installer.
MAX_DELTA_BASES = 3
MAX_INDEX_BYTES = 256 * 1024
MANIFEST_NAME = "PACKAGE_MANIFEST.sha256.json"
# Written last into runtime\<edition>.next; the launcher swaps only then.
READY_MARKER = ".ready"
# Written by the launcher into runtime\ after a swap attempt.
RESULT_FILE = "update-result.txt"
STAGED_SUFFIX = ".next"
OLD_SUFFIX = ".old"
# Asset kinds per update channel (update_check.release_url_kind).
CHANNEL_KINDS = {
    "official": ("public",),
    "local-test": ("public", "public-update-test"),
}
_VERSION = r"\d+\.\d+\.\d+"
_CHUNK = 1 << 20


class UpdateIndexError(ValueError):
    """The release index is missing a field or names an unexpected file."""


class StagingError(RuntimeError):
    """The new runtime could not be prepared; ``reason`` is log-safe."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Asset:
    name: str
    size: int
    sha256: str


@dataclass(frozen=True)
class EditionAssets:
    files: Asset | None
    installer: Asset | None
    deltas: dict


@dataclass(frozen=True)
class UpdateIndex:
    version: str
    installer_revision: int
    editions: dict


def index_name(version):
    return f"WatchedKettle-{version}-update.json"


def files_name(version, kind, edition):
    return f"WatchedKettle-{version}-{kind}-{edition}-files.json"


def delta_name(version, kind, edition, base):
    return f"WatchedKettle-{version}-{kind}-{edition}-from-{base}.zip"


def installer_name(version, kind, edition):
    return f"WatchedKettle-{version}-{kind}-{edition}-update-unsigned-setup.exe"


def _kinds(channel):
    return "|".join(re.escape(kind) for kind in CHANNEL_KINDS.get(channel, ()))


def asset_name_allowed(name, version, channel, role, edition, base=""):
    """Whether an index entry names the file this channel may use for ``role``."""
    kinds = _kinds(channel)
    if not kinds or edition not in EDITIONS:
        return False
    v, e = re.escape(version), re.escape(edition)
    patterns = {
        "files": rf"WatchedKettle-{v}-(?:{kinds})-{e}-files\.json",
        "installer": rf"WatchedKettle-{v}-(?:{kinds})-{e}-update(?:-unsigned)?-setup\.exe",
        "delta": rf"WatchedKettle-{v}-(?:{kinds})-{e}-from-{re.escape(base)}\.zip",
    }
    return re.fullmatch(patterns[role], name or "") is not None


def _asset(value, version, channel, role, edition, base=""):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise UpdateIndexError("asset")
    name, size, digest = value.get("name"), value.get("size"), value.get("sha256")
    if (
        not isinstance(name, str)
        or not asset_name_allowed(name, version, channel, role, edition, base)
        or not isinstance(size, int)
        or size <= 0
        or not isinstance(digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
    ):
        raise UpdateIndexError(role)
    return Asset(name, size, digest)


def parse_index(payload, version, channel):
    """Validate an index for ``version`` read over ``channel``."""
    try:
        row = json.loads(payload)
    except (ValueError, UnicodeError) as error:
        raise UpdateIndexError("json") from error
    if not isinstance(row, dict) or row.get("schemaVersion") != INDEX_SCHEMA:
        raise UpdateIndexError("schema")
    revision = row.get("installerRevision")
    if row.get("version") != version or not isinstance(revision, int) or revision < 1:
        raise UpdateIndexError("version")
    editions = row.get("editions")
    if not isinstance(editions, dict):
        raise UpdateIndexError("editions")
    parsed = {}
    for edition, value in editions.items():
        if edition not in EDITIONS or not isinstance(value, dict):
            raise UpdateIndexError("edition")
        deltas = value.get("deltas") or {}
        if not isinstance(deltas, dict):
            raise UpdateIndexError("deltas")
        parsed[edition] = EditionAssets(
            files=_asset(value.get("files"), version, channel, "files", edition),
            installer=_asset(
                value.get("installer"), version, channel, "installer", edition
            ),
            deltas={
                base: _asset(asset, version, channel, "delta", edition, base)
                for base, asset in deltas.items()
                if isinstance(base, str) and re.fullmatch(_VERSION, base)
            },
        )
    return UpdateIndex(version, revision, parsed)


def safe_relative_path(value):
    """A bundle-relative POSIX path that stays inside the bundle."""
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        return False
    # Split the text itself: PurePosixPath would fold "./a" and "a//b".
    return all(part not in ("", ".", "..") for part in value.split("/"))


def manifest_entries(payload):
    """{path: (size, sha256)} from a PACKAGE_MANIFEST document."""
    try:
        row = json.loads(payload)
        files = row["files"]
        if row.get("schemaVersion") != 1 or not isinstance(files, list):
            raise ValueError("schema")
        entries, folded = {}, set()
        for item in files:
            path, size, digest = item["path"], item["size"], item["sha256"]
            # Windows paths ignore case, so two entries must not share a file.
            if (
                not safe_relative_path(path)
                or path == MANIFEST_NAME
                or not isinstance(size, int)
                or size < 0
                or re.fullmatch(r"[0-9a-f]{64}", str(digest)) is None
                or path.casefold() in folded
            ):
                raise ValueError("entry")
            entries[path] = (size, digest)
            folded.add(path.casefold())
    except (ValueError, KeyError, TypeError, UnicodeError) as error:
        raise UpdateIndexError("manifest") from error
    if row.get("fileCount") != len(entries):
        raise UpdateIndexError("manifest")
    return entries


def changed_paths(base, target):
    """Target paths whose content is not already in ``base``."""
    return sorted(path for path, entry in target.items() if base.get(path) != entry)


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _link_or_copy(source, target, size, digest):
    """Hard link (or copy) an unchanged file; True when it was linked."""
    try:
        if source.stat().st_size != size:
            raise StagingError("base_mismatch")
    except OSError as error:
        raise StagingError("base_missing") from error
    linked = False
    try:
        os.link(source, target)
        linked = True
    except OSError:
        try:
            shutil.copyfile(source, target)
        except OSError as error:
            raise StagingError("write") from error
    # The current runtime is checked too: a damaged base must not carry over.
    if file_sha256(target) != digest:
        raise StagingError("base_mismatch")
    return linked


def stage_runtime(current, staged, delta_zip, version):
    """Build ``staged`` from ``delta_zip`` and ``current``; return counts.

    Raises StagingError, leaving ``staged`` for the caller to remove.
    """
    current, staged = Path(current), Path(staged)
    counts = {"linked": 0, "copied": 0, "extracted": 0}
    try:
        archive = zipfile.ZipFile(delta_zip)
    except (OSError, zipfile.BadZipFile) as error:
        raise StagingError("archive") from error
    with archive:
        try:
            entries = manifest_entries(archive.read(MANIFEST_NAME))
        except KeyError as error:
            raise StagingError("archive") from error
        except UpdateIndexError as error:
            raise StagingError("manifest") from error
        members = {}
        for info in archive.infolist():
            if info.is_dir():
                continue
            if info.filename != MANIFEST_NAME and info.filename not in entries:
                raise StagingError("unexpected_file")
            members[info.filename] = info
        if staged.exists():
            shutil.rmtree(staged)
        staged.mkdir(parents=True)
        for path, (size, digest) in entries.items():
            target = staged.joinpath(*PurePosixPath(path).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            info = members.get(path)
            if info is None:
                source = current.joinpath(*PurePosixPath(path).parts)
                linked = _link_or_copy(source, target, size, digest)
                counts["linked" if linked else "copied"] += 1
                continue
            if info.file_size != size:
                raise StagingError("delta_mismatch")
            hasher = hashlib.sha256()
            try:
                with archive.open(info) as stream, open(target, "wb") as out:
                    for chunk in iter(lambda: stream.read(_CHUNK), b""):
                        hasher.update(chunk)
                        out.write(chunk)
            except (OSError, zipfile.BadZipFile) as error:
                raise StagingError("write") from error
            if hasher.hexdigest() != digest:
                raise StagingError("delta_mismatch")
            counts["extracted"] += 1
        (staged / MANIFEST_NAME).write_bytes(archive.read(MANIFEST_NAME))
    (staged / READY_MARKER).write_text(version + "\n", encoding="ascii")
    return counts


def read_result(runtime_root):
    """The launcher's last swap result as a dict, or None."""
    try:
        text = (Path(runtime_root) / RESULT_FILE).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    result = {}
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if separator and key in ("state", "version", "reason"):
            result[key] = value.strip()
    return result if result.get("state") else None


def build_profile(bundle_root):
    """{key: value} from a bundle's BUILD_PROFILE.txt (empty when absent)."""
    try:
        text = (Path(bundle_root) / "BUILD_PROFILE.txt").read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return {}
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
