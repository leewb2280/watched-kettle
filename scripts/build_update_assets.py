"""Write a release's partial update assets (docs/decisions/0007).

Inputs are the two Public bundles of this release, the folder holding their
update installers (build_installer.ps1 -UpdateInstallers), and a folder with
earlier releases' ``WatchedKettle-<v>-update.json`` and ``-files.json``
assets, fetched with ``gh release download v<old> -p "*-update.json" -p
"*-files.json"``. For each edition this writes its file list, the zip of
files changed since each of up to three earlier releases of the same
installer revision, and the release index with its ``.sha256``.

    python -m scripts.build_update_assets --bundle dist/r/public/pet-only/WatchedKettle \
        --bundle dist/r/public/pet-assistant/WatchedKettle \
        --installers dist/r/installers --bases build/update-bases --out dist/r/installers
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from watched_kettle.application.update_assets import (  # noqa: E402
    EDITIONS,
    MANIFEST_NAME,
    MAX_DELTA_BASES,
    UpdateIndexError,
    build_profile,
    changed_paths,
    delta_name,
    file_sha256,
    files_name,
    index_name,
    installer_name,
    manifest_entries,
    parse_index,
)

CHANNEL_KIND = {"official": "public", "local-test": "public-update-test"}
# Fixed zip timestamps keep the same input producing the same bytes.
ZIP_TIME = (2020, 1, 1, 0, 0, 0)


def _version_key(version):
    return tuple(int(part) for part in version.split("."))


def _asset(path):
    return {"name": path.name, "size": path.stat().st_size, "sha256": file_sha256(path)}


def read_bundle(root):
    root = Path(root)
    profile = build_profile(root)
    edition, version = profile.get("edition"), profile.get("version")
    channel = profile.get("update_channel", "none")
    if profile.get("profile") != "public" or edition not in EDITIONS:
        raise SystemExit(f"Expected a Public bundle: {root}")
    if channel not in CHANNEL_KIND:
        raise SystemExit(f"Bundle has no update channel: {root}")
    try:
        revision = int(profile.get("installer_revision", ""))
    except ValueError:
        raise SystemExit(f"Bundle has no installer revision: {root}") from None
    manifest = (root / MANIFEST_NAME).read_bytes()
    entries = manifest_entries(manifest)
    for path, (size, _digest) in entries.items():
        if (root / path).stat().st_size != size:
            raise SystemExit(f"Bundle file differs from its manifest: {path}")
    return dict(
        root=root,
        edition=edition,
        version=version,
        channel=channel,
        revision=revision,
        manifest=manifest,
        entries=entries,
    )


def earlier_releases(bases, version, channel, revision):
    """[(base version, {edition: entries})] newest first, same revision only."""
    found = []
    for path in (
        sorted(Path(bases).glob("WatchedKettle-*-update.json")) if bases else ()
    ):
        base = path.name[len("WatchedKettle-") : -len("-update.json")]
        try:
            index = parse_index(path.read_bytes(), base, channel)
        except UpdateIndexError as error:
            raise SystemExit(f"Invalid earlier index {path.name}: {error}") from None
        if _version_key(base) >= _version_key(version):
            continue
        if index.installer_revision != revision:
            print(f"Skipping {base}: installer revision {index.installer_revision}")
            continue
        editions = {}
        for edition, assets in index.editions.items():
            if assets.files is None:
                continue
            listing = Path(bases) / assets.files.name
            if not listing.is_file() or file_sha256(listing) != assets.files.sha256:
                raise SystemExit(
                    f"Missing or changed earlier file list: {listing.name}"
                )
            editions[edition] = manifest_entries(listing.read_bytes())
        found.append((base, editions))
    found.sort(key=lambda item: _version_key(item[0]), reverse=True)
    return found[:MAX_DELTA_BASES]


def update_installer(installers, version, kind, edition):
    """The edition's update installer, signed or not; one folder holds one."""
    candidates = (
        Path(installers) / installer_name(version, kind, edition, signed)
        for signed in (True, False)
    )
    found = [path for path in candidates if path.is_file()]
    if len(found) != 1:
        raise SystemExit(
            f"Expected one {edition} update installer in {installers}, found {len(found)}"
        )
    return found[0]


def write_delta(target, bundle, paths):
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in [*paths, MANIFEST_NAME]:
            info = zipfile.ZipInfo(path, ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            source = bundle["root"] / path
            with open(source, "rb") as stream, archive.open(info, "w") as out:
                shutil.copyfileobj(stream, out, 1 << 20)
    # Read it back the way the app will.
    with zipfile.ZipFile(target) as archive:
        if manifest_entries(archive.read(MANIFEST_NAME)) != bundle["entries"]:
            raise SystemExit(f"Delta manifest differs: {target.name}")
        for path in paths:
            digest = hashlib.sha256(archive.read(path)).hexdigest()
            if digest != bundle["entries"][path][1]:
                raise SystemExit(f"Delta content differs: {target.name} {path}")


def build(bundles, installers, bases, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    bundles = [read_bundle(root) for root in bundles]
    first = bundles[0]
    version, channel, revision = first["version"], first["channel"], first["revision"]
    for bundle in bundles:
        if (bundle["version"], bundle["channel"], bundle["revision"]) != (
            version,
            channel,
            revision,
        ):
            raise SystemExit("Bundles differ in version, update channel or revision.")
    if len({bundle["edition"] for bundle in bundles}) != len(bundles):
        raise SystemExit("Give each edition's bundle once.")
    kind = CHANNEL_KIND[channel]
    earlier = earlier_releases(bases, version, channel, revision)
    editions = {}
    for bundle in bundles:
        edition = bundle["edition"]
        listing = out / files_name(version, kind, edition)
        listing.write_bytes(bundle["manifest"])
        installer = update_installer(installers, version, kind, edition)
        if installer.parent.resolve() != out.resolve():
            shutil.copy2(installer, out / installer.name)
            installer = out / installer.name
        deltas = {}
        for base, base_editions in earlier:
            if edition not in base_editions:
                continue
            paths = changed_paths(base_editions[edition], bundle["entries"])
            target = out / delta_name(version, kind, edition, base)
            write_delta(target, bundle, paths)
            deltas[base] = _asset(target)
            print(
                f"{target.name}: {len(paths)} changed files, "
                f"{target.stat().st_size / 2**20:.1f} MiB"
            )
        editions[edition] = dict(
            files=_asset(listing), installer=_asset(installer), deltas=deltas
        )
    index = out / index_name(version)
    index.write_text(
        json.dumps(
            dict(
                schemaVersion=1,
                version=version,
                installerRevision=revision,
                editions=editions,
            ),
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    parse_index(index.read_bytes(), version, channel)
    (out / (index.name + ".sha256")).write_text(
        f"{file_sha256(index).upper()}  {index.name}\n", encoding="ascii"
    )
    print(f"{index.name}: {len(earlier)} earlier releases, revision {revision}")
    return index


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bundle", action="append", required=True, type=Path)
    parser.add_argument("--installers", required=True, type=Path)
    parser.add_argument("--bases", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    build(args.bundle, args.installers, args.bases, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
