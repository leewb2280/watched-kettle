"""Read known public pet sources without running pasted commands or CLIs."""

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler
from uuid import uuid4

from watched_kettle.localization import t
from watched_kettle.pet.import_package import (
    MAX_ARCHIVE_BYTES,
    MAX_MANIFEST_BYTES,
    PackageError,
    json_object,
    linked,
    package_reader,
    read_package,
)


class SourceError(ValueError):
    pass


def parse_command(command):
    if (
        not isinstance(command, str)
        or len(command) > 512
        or any(c in command.strip() for c in "\r\n")
    ):
        raise SourceError(t("pet.import.command_invalid"))
    match = re.fullmatch(
        r"(?:npx\s+(?:--yes\s+|-y\s+)?)?(codexpetdb|petdb|petscodex)\s+install\s+"
        r"(?:'([A-Za-z0-9._~*-]+)'|\"([A-Za-z0-9._~*-]+)\"|([A-Za-z0-9._~*-]+))",
        command.strip(),
    )
    if not match:
        raise SourceError(t("pet.import.command_invalid"))
    provider = "petscodex" if match[1] == "petscodex" else "codexpetdb"
    slug = next(value for value in match.groups()[1:] if value is not None)
    if slug in {".", ".."} or len(slug) > 100:
        raise SourceError(t("pet.import.command_invalid"))
    return provider, slug


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Fetcher:
    def __init__(self, cancel, progress):
        self.cancel, self.progress = cancel, progress
        self.deadline = time.monotonic() + 120

    def check(self):
        if self.cancel.is_set():
            raise SourceError(t("pet.import.cancelled"))
        if time.monotonic() > self.deadline:
            raise SourceError(t("pet.import.network_failed"))

    def __call__(self, url, limit, expected_type=""):
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname
            not in {
                "codexpetdb.com",
                "cdn.codexpetdb.com",
                "api.github.com",
                "raw.githubusercontent.com",
            }
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 443}
        ):
            raise SourceError(t("pet.import.network_failed"))
        self.check()
        try:
            request = Request(
                url,
                headers={
                    "User-Agent": "WatchedKettle-PetImport",
                    "Accept": expected_type or "application/json",
                },
            )
            with build_opener(NoRedirect).open(request, timeout=8) as response:
                if (
                    expected_type
                    and response.headers.get_content_type() != expected_type
                ):
                    raise SourceError(t("pet.import.integrity_failed"))
                total = int(response.headers.get("Content-Length", "0"))
                if total < 0 or total > limit:
                    raise SourceError(t("pet.import.integrity_failed"))
                data = bytearray()
                while True:
                    self.check()
                    block = response.read(min(65536, limit + 1 - len(data)))
                    if not block:
                        break
                    data.extend(block)
                    if len(data) > limit:
                        raise SourceError(t("pet.import.integrity_failed"))
                    self.progress(len(data), total)
                if total and len(data) != total:
                    raise SourceError(t("pet.import.integrity_failed"))
                return bytes(data)
        except HTTPError as error:
            key = (
                "pet.import.not_found"
                if error.code == 404
                else "pet.import.rate_limited"
                if error.code == 429
                or (
                    error.code == 403
                    and error.headers.get("X-RateLimit-Remaining") == "0"
                )
                else "pet.import.network_failed"
            )
            raise SourceError(t(key)) from error
        except (URLError, OSError, ValueError) as error:
            if isinstance(error, SourceError):
                raise
            raise SourceError(t("pet.import.network_failed")) from error


def document(data):
    """A source's JSON object; a changed format is an integrity failure."""
    try:
        value = json.loads(data)
    except ValueError as error:
        raise SourceError(t("pet.import.integrity_failed")) from error
    if not isinstance(value, dict):
        raise SourceError(t("pet.import.integrity_failed"))
    return value


def member(value, *keys):
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            raise SourceError(t("pet.import.integrity_failed"))
        value = value[key]
    return value


def online_pet(command, importer, fetch):
    provider, slug = parse_command(command)
    if provider == "codexpetdb":
        discovery = document(
            fetch(
                "https://codexpetdb.com/.well-known/codexpetdb.json",
                MAX_MANIFEST_BYTES,
                "application/json",
            )
        )
        if (
            discovery.get("product") != "CodexPetDB"
            or discovery.get("schemaVersion") != 1
        ):
            raise SourceError(t("pet.import.integrity_failed"))
        origin = member(discovery, "assets", "origin")
        if (
            origin != "https://cdn.codexpetdb.com"
            or member(discovery, "assets").get("delivery") != "cdn"
            or discovery.get("catalogUrl") != origin + "/catalogs/v1/pets.json"
        ):
            raise SourceError(t("pet.import.integrity_failed"))
        catalog = document(
            fetch(discovery["catalogUrl"], 10 * 1024 * 1024, "application/json")
        )
        pets = member(catalog, "pets")
        if catalog.get("schemaVersion") != 1 or not isinstance(pets, list):
            raise SourceError(t("pet.import.integrity_failed"))
        pet = next(
            (
                item
                for item in pets
                if isinstance(item, dict) and item.get("slug") == slug
            ),
            None,
        )
        if pet is None:
            raise SourceError(t("pet.import.not_found"))
        prefix = member(pet, "assets", "prefix")
        if not isinstance(prefix, str) or not re.fullmatch(
            r"revisions/[0-9a-f-]{36}/", prefix
        ):
            raise SourceError(t("pet.import.integrity_failed"))
        data = fetch(
            origin + "/" + prefix + quote(slug, safe="") + ".zip",
            MAX_ARCHIVE_BYTES,
            "application/zip",
        )
        if len(data) != member(pet, "assets", "byteSize", "package") or hashlib.sha256(
            data
        ).hexdigest() != member(pet, "assets", "sha256", "package"):
            raise SourceError(t("pet.import.integrity_failed"))
        with tempfile.TemporaryDirectory(prefix="watched-kettle-pet-") as folder:
            path = Path(folder) / "pet.zip"
            path.write_bytes(data)
            result = importer.prepare(path, "CodexPetDB: " + slug)
            # The same reader as the import, so a wrapper folder is fine too.
            manifest = package_reader(path)[0]
            if manifest.get("id") != slug:
                importer.cancel(result.token)
                raise SourceError(t("pet.import.integrity_failed"))
        result.extras["author"] = str(pet.get("author", ""))[:200]
        return result
    base = "https://api.github.com/repos/mn8821236/petscodex/commits/main"
    commit = document(fetch(base, 1024 * 1024)).get("sha")
    if not isinstance(commit, str) or not re.fullmatch("[0-9a-f]{40}", commit):
        raise SourceError(t("pet.import.integrity_failed"))
    root = (
        "https://raw.githubusercontent.com/mn8821236/petscodex/"
        + commit
        + "/"
        + quote(slug, safe="")
        + "/"
    )
    raw, image, extras, assets, warnings = read_package(
        lambda name, limit: fetch(root + quote(name, safe="/"), limit)
    )
    if raw.get("id") != slug:
        raise SourceError(t("pet.import.integrity_failed"))
    return importer.prepare_bytes(
        image,
        raw.get("displayName", slug),
        extras,
        assets,
        warnings,
        "Pets Codex: " + slug,
    )


class InstalledPets:
    """Native directory paths stay in Python; a fresh scan invalidates IDs."""

    def __init__(self):
        self.entries = {}

    def scan(self):
        self.entries.clear()
        root = (
            Path(
                os.environ.get("CODEX_HOME", "").strip() or Path.home() / ".codex"
            ).expanduser()
            / "pets"
        )
        if not root.is_dir() or linked(root):
            return []
        rows = []
        for directory in sorted(root.iterdir(), key=lambda item: item.name.casefold())[
            :1024
        ]:
            if not directory.is_dir():
                continue
            key = uuid4().hex
            row = dict(id=key, name=directory.name, description="", error="")
            try:
                from watched_kettle.pet.import_package import read_local

                manifest = json_object(
                    read_local(directory, "pet.json", MAX_MANIFEST_BYTES)
                )
                row.update(
                    name=str(manifest.get("displayName", directory.name))[:100],
                    description=str(manifest.get("description", ""))[:1000],
                )
                self.entries[key] = directory
            except (OSError, ValueError):
                row["error"] = t("pet.import.invalid_package")
            rows.append(row)
        return rows

    def path(self, key):
        path = self.entries.get(key)
        if path is None:
            raise PackageError(t("pet.import.not_found"))
        return path

    def thumbnail(self, key):
        from io import BytesIO
        from PIL import Image
        from watched_kettle.pet.import_package import read_local, relative_name

        directory = self.path(key)
        manifest = json_object(read_local(directory, "pet.json", MAX_MANIFEST_BYTES))
        data = read_local(
            directory,
            relative_name(manifest.get("spritesheetPath", "spritesheet.webp")),
            20 * 1024 * 1024,
        )
        with Image.open(BytesIO(data)) as image:
            if image.size not in {(1536, 1872), (1536, 2288)}:
                raise PackageError(t("pet.import.invalid_package"))
            cell = image.crop((0, 0, 192, 208)).convert("RGBA")
            cell.thumbnail((64, 70))
            output = BytesIO()
            cell.save(output, format="PNG")
            return output.getvalue()
