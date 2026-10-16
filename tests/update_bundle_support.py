"""Small fake Public bundles and their partial update assets for tests."""

from pathlib import Path

from scripts import build_update_assets
from scripts.release_artifacts import generate_manifest
from watched_kettle.application.update_assets import installer_name

# The channel a -UpdateTestPort build carries, and its asset kind.
CHANNEL = "local-test"
KIND = "public-update-test"


def make_bundle(root, edition, version, files, revision=1, channel=CHANNEL):
    """Write ``files`` ({path: bytes}) as a bundle with its profile and manifest."""
    bundle = Path(root)
    for path, content in files.items():
        target = bundle / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    (bundle / "BUILD_PROFILE.txt").write_text(
        "\n".join(
            (
                f"version={version}",
                "profile=public",
                f"edition={edition}",
                f"update_channel={channel}",
                f"installer_revision={revision}",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    generate_manifest(bundle)
    return bundle


def release_files(version):
    """Two editions sharing a large unchanged file and a version-specific one."""
    shared = bytes(range(256)) * 4096
    return {
        "WatchedKettle.exe": f"app {version}".encode(),
        "_internal/shared.dll": shared,
        "settings-ui/resources/app/index.js": f"ui {version}".encode(),
    }


def build_release(root, version, bases=None, revision=1, files=None):
    """Build both editions of ``version`` and their assets; return the out folder."""
    root = Path(root)
    out = root / f"release-{version}"
    out.mkdir(parents=True, exist_ok=True)
    bundles = []
    for edition in ("pet-only", "pet-assistant"):
        content = dict(files or release_files(version))
        content[f"{edition}.txt"] = edition.encode()
        bundles.append(
            make_bundle(
                root / f"bundle-{version}-{edition}",
                edition,
                version,
                content,
                revision,
            )
        )
        (out / installer_name(version, KIND, edition)).write_bytes(
            f"setup {version} {edition}".encode() * 1000
        )
    build_update_assets.build(bundles, out, bases, out)
    return out
