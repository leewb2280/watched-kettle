"""Validate downloaded atlases and publish durable, local pet packages."""

from watched_kettle.localization import t

from dataclasses import dataclass, field
import hashlib
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from watched_kettle.config import ANIMATIONS, FRAME_HEIGHT, FRAME_WIDTH
from watched_kettle.pet.loader import detect_sprite_version
from watched_kettle.pet.import_package import (
    PET_IMAGE_FORMATS,
    PackageError,
    package_reader,
)


MAX_IMPORT_BYTES = 20 * 1024 * 1024
IMPORT_LIFETIME_SECONDS = 600


# Leading bytes of image formats people pick by mistake (JPEG, GIF, BMP, TIFF).
OTHER_IMAGE_SIGNATURES = (b"\xff\xd8\xff", b"GIF8", b"BM", b"II*\x00", b"MM\x00*")


def _other_image(raw):
    return bytes(raw[:4]).startswith(OTHER_IMAGE_SIGNATURES)


class PetImportError(ValueError):
    """An actionable error safe to display without exposing a source path."""


@dataclass(frozen=True)
class PreparedPet:
    token: str
    pet_id: str
    name: str
    version: int
    image: bytes
    thumbnail: bytes
    expires: float
    extras: dict = field(default_factory=dict)
    assets: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    source: str = ""


@dataclass(frozen=True)
class ImportedPet:
    id: str
    name: str
    already_exists: bool


class PetImporter:
    """Keep at most one prepared atlas; filesystem work belongs to this layer."""

    def __init__(self, root, clock=time.monotonic):
        self.root = Path(root)
        self.clock = clock
        self.prepared = None

    def cancel(self, token=None):
        if token is None or (self.prepared and token == self.prepared.token):
            self.prepared = None

    def prepare(self, path, source=""):
        self.cancel()
        path = Path(path)
        try:
            if path.is_dir() or path.suffix.lower() == ".zip":
                raw, image, extras, assets, warnings = package_reader(path)
                name = raw.get("displayName", raw.get("name", path.stem))
                if not isinstance(name, str) or not name.strip() or len(name) > 100:
                    raise PetImportError(t("message.0140"))
                prepared = self.prepare_bytes(
                    image, name, extras, assets, warnings, source
                )
                for key in ("spriteVersionNumber", "formatVersion"):
                    if key in raw and raw[key] != prepared.version:
                        self.cancel()
                        raise PackageError()
                return prepared
            with path.open("rb") as stream:
                raw = stream.read(MAX_IMPORT_BYTES + 1)
            return self.prepare_bytes(raw, path.stem[:100], source=source)
        except (OSError, ValueError) as error:
            if isinstance(error, PetImportError):
                raise
            raise PetImportError(t("pet.import.invalid_package")) from error

    def prepare_bytes(
        self, raw, name, extras=None, assets=None, warnings=None, source=""
    ):
        extras, assets, warnings = extras or {}, assets or {}, warnings or []
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise PetImportError(t("message.0140"))
        try:
            if len(raw) > MAX_IMPORT_BYTES:
                raise PetImportError(t("message.0141"))
            try:
                opened = Image.open(BytesIO(raw), formats=PET_IMAGE_FORMATS)
            except UnidentifiedImageError as error:
                # Another image format names the choice; anything else is damage.
                message = "message.0145" if _other_image(raw) else "message.0142"
                raise PetImportError(t(message)) from error
            with opened:
                if opened.format not in {"PNG", "WEBP"}:
                    raise PetImportError(t("message.0145"))
                if getattr(opened, "is_animated", False):
                    raise PetImportError(t("message.0146"))
                version, _ = detect_sprite_version(opened)
                atlas = opened.convert("RGBA")
            self._validate_frames(atlas, version)
            digest = hashlib.sha256(
                f"{atlas.width}x{atlas.height}:RGBA:".encode() + atlas.tobytes()
            ).hexdigest()
            pet_id = self.identity(digest, extras, assets)
            # exact preserves RGB even in fully transparent pixels. Do not copy
            # source EXIF/ICC/text metadata into the normalized runtime image.
            clean = Image.frombytes("RGBA", atlas.size, atlas.tobytes())
            output = BytesIO()
            clean.save(output, format="WEBP", lossless=True, exact=True)
            frame = clean.crop((0, 0, FRAME_WIDTH, FRAME_HEIGHT))
            bounds = frame.getchannel("A").getbbox()
            frame = frame.crop(bounds)
            frame.thumbnail((220, 240), Image.Resampling.LANCZOS)
            preview = BytesIO()
            frame.save(preview, format="PNG")
        except PetImportError:
            raise
        except ValueError as error:
            raise PetImportError(str(error)) from error
        except (OSError, Image.DecompressionBombError) as error:
            raise PetImportError(t("message.0142")) from error
        self.prepared = PreparedPet(
            uuid4().hex,
            pet_id,
            name,
            version,
            output.getvalue(),
            preview.getvalue(),
            self.clock() + IMPORT_LIFETIME_SECONDS,
            extras,
            assets,
            warnings,
            source,
        )
        return self.prepared

    @staticmethod
    def identity(digest, extras, assets):
        runtime = {
            k: v
            for k, v in extras.items()
            if k
            not in {
                "description",
                "localizedDescriptions",
                "author",
                "license",
                "importSource",
                "importOriginalId",
            }
        }
        if not runtime and not assets:
            return "imported-" + digest
        content = json.dumps(
            [
                digest,
                runtime,
                {
                    name: hashlib.sha256(data).hexdigest()
                    for name, data in sorted(assets.items())
                },
            ],
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
        return "importedpkg-" + hashlib.sha256(content).hexdigest()

    def preview(self, token, state):
        prepared = self.prepared
        if not prepared or token != prepared.token or self.clock() >= prepared.expires:
            raise PetImportError(t("message.0138"))
        if state in ANIMATIONS:
            animation = ANIMATIONS[state]
            row, count, interval = (
                animation["row"],
                animation["frames"],
                animation["interval"],
            )
        elif prepared.version == 2 and state in {"look-0", "look-1"}:
            row, count, interval = 9 + int(state[-1]), 8, 180
        else:
            raise PetImportError(t("pet.import.invalid_package"))
        with Image.open(BytesIO(prepared.image), formats=PET_IMAGE_FORMATS) as atlas:
            strip = atlas.crop(
                (0, row * FRAME_HEIGHT, count * FRAME_WIDTH, (row + 1) * FRAME_HEIGHT)
            )
            output = BytesIO()
            strip.save(output, format="PNG")
        return output.getvalue(), count, interval

    @staticmethod
    def _validate_frames(atlas, version):
        alpha = atlas.getchannel("A")
        if alpha.getextrema()[0] != 0:
            raise PetImportError(t("message.0137"))
        rows = [(item["row"], item["frames"]) for item in ANIMATIONS.values()]
        if version == 2:
            rows.extend([(9, 8), (10, 8)])
        for row, count in rows:
            for column in range(count):
                cell = alpha.crop(
                    (
                        column * FRAME_WIDTH,
                        row * FRAME_HEIGHT,
                        (column + 1) * FRAME_WIDTH,
                        (row + 1) * FRAME_HEIGHT,
                    )
                )
                if cell.getbbox() is None:
                    raise PetImportError(
                        t("message.0147", value0=row + 1, value1=column + 1)
                    )
                if cell.getextrema()[0] != 0:
                    raise PetImportError(
                        t("message.0148", value0=row + 1, value1=column + 1)
                    )

    def commit(self, token, name):
        prepared = self.prepared
        if prepared is None or self.clock() >= prepared.expires:
            self.cancel()
            raise PetImportError(t("message.0138"))
        if token != prepared.token:
            raise PetImportError(t("message.0139"))
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
            raise PetImportError(t("message.0140"))
        destination = self.root / prepared.pet_id
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                return self._existing(destination, prepared)
            # Stage beside the catalog on the same volume. Discovery cannot see
            # an incomplete package; Windows rename never replaces a directory.
            with TemporaryDirectory(
                prefix="pet-import-", dir=self.root.parent
            ) as folder:
                staging = Path(folder) / "package"
                staging.mkdir()
                (staging / "spritesheet.webp").write_bytes(prepared.image)
                manifest = dict(
                    **prepared.extras,
                    id=prepared.pet_id,
                    displayName=name.strip(),
                    spritesheetPath="spritesheet.webp",
                    spriteVersionNumber=prepared.version,
                    distribution="private",
                )
                if prepared.source:
                    manifest["importSource"] = prepared.source
                for asset, data in prepared.assets.items():
                    target = staging / asset
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                (staging / "pet.json").write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                try:
                    staging.rename(destination)
                except FileExistsError:
                    return self._existing(destination, prepared)
        except PetImportError:
            raise
        except OSError as error:
            raise PetImportError(t("message.0143")) from error
        # Retain the bounded preparation until cancel/expiry so retries can
        # resolve the same ID after a lost response, without duplicating pets.
        return ImportedPet(prepared.pet_id, name.strip(), False)

    @staticmethod
    def _existing(destination, prepared):
        try:
            with (destination / "pet.json").open("rb") as stream:
                raw = stream.read(256 * 1024 + 1)
            if len(raw) > 256 * 1024:
                raise ValueError()
            manifest = json.loads(raw)
            if (
                manifest.get("id") != prepared.pet_id
                or manifest.get("spritesheetPath") != "spritesheet.webp"
            ):
                raise ValueError()
            with Image.open(
                destination / "spritesheet.webp", formats=PET_IMAGE_FORMATS
            ) as image:
                detect_sprite_version(image)
                image.load()
                digest = hashlib.sha256(
                    f"{image.width}x{image.height}:RGBA:".encode()
                    + image.convert("RGBA").tobytes()
                ).hexdigest()
            extras = {
                k: v
                for k, v in manifest.items()
                if k
                not in {
                    "id",
                    "displayName",
                    "spritesheetPath",
                    "spriteVersionNumber",
                    "distribution",
                }
            }
            assets = {}
            for name in prepared.assets:
                from watched_kettle.pet.import_package import (
                    read_local,
                    MAX_DECORATION_BYTES,
                )

                assets[name] = read_local(destination, name, MAX_DECORATION_BYTES)
            if PetImporter.identity(digest, extras, assets) != prepared.pet_id:
                raise ValueError()
            return ImportedPet(prepared.pet_id, str(manifest["displayName"]), True)
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
            raise PetImportError(t("message.0144")) from error
