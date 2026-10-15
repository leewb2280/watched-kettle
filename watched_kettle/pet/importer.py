"""Validate downloaded atlases and publish durable, local pet packages."""

from dataclasses import dataclass
import hashlib
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from uuid import uuid4

from PIL import Image

from watched_kettle.config import ANIMATIONS, FRAME_HEIGHT, FRAME_WIDTH
from watched_kettle.pet.loader import detect_sprite_version


MAX_IMPORT_BYTES = 20 * 1024 * 1024
IMPORT_LIFETIME_SECONDS = 600


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

    def prepare(self, path):
        self.cancel()
        path = Path(path)
        try:
            with path.open("rb") as stream:
                raw = stream.read(MAX_IMPORT_BYTES + 1)
            if len(raw) > MAX_IMPORT_BYTES:
                raise PetImportError("펫 이미지는 20MiB 이하여야 합니다.")
            with Image.open(BytesIO(raw)) as source:
                if source.format not in {"PNG", "WEBP"}:
                    raise PetImportError("PNG 또는 WebP 스프라이트를 선택하세요.")
                if getattr(source, "is_animated", False):
                    raise PetImportError(
                        "움직이는 이미지 대신 정지 스프라이트를 선택하세요."
                    )
                version, _ = detect_sprite_version(source)
                atlas = source.convert("RGBA")
            self._validate_frames(atlas, version)
            digest = hashlib.sha256(
                f"{atlas.width}x{atlas.height}:RGBA:".encode() + atlas.tobytes()
            ).hexdigest()
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
            raise PetImportError(
                "펫 이미지를 읽지 못했습니다. 파일 형식과 손상 여부를 확인하세요."
            ) from error
        self.prepared = PreparedPet(
            uuid4().hex,
            "imported-" + digest,
            path.stem[:100],
            version,
            output.getvalue(),
            preview.getvalue(),
            self.clock() + IMPORT_LIFETIME_SECONDS,
        )
        return self.prepared

    @staticmethod
    def _validate_frames(atlas, version):
        alpha = atlas.getchannel("A")
        if alpha.getextrema()[0] != 0:
            raise PetImportError("투명 배경이 있는 스프라이트가 필요합니다.")
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
                        f"필수 프레임이 비어 있습니다: {row + 1}행 {column + 1}열."
                    )
                if cell.getextrema()[0] != 0:
                    raise PetImportError(
                        f"프레임 배경이 투명하지 않습니다: {row + 1}행 {column + 1}열."
                    )

    def commit(self, token, name):
        prepared = self.prepared
        if prepared is None or self.clock() >= prepared.expires:
            self.cancel()
            raise PetImportError("파일 선택이 만료됐습니다. 펫 파일을 다시 선택하세요.")
        if token != prepared.token:
            raise PetImportError(
                "선택한 파일이 바뀌었습니다. 펫 파일을 다시 선택하세요."
            )
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
            raise PetImportError("펫 이름은 1~100자로 입력하세요.")
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
                    id=prepared.pet_id,
                    displayName=name.strip(),
                    spritesheetPath="spritesheet.webp",
                    spriteVersionNumber=prepared.version,
                    distribution="private",
                )
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
            raise PetImportError(
                "펫을 저장하지 못했습니다. 저장 공간과 폴더 권한을 확인하세요."
            ) from error
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
            with Image.open(destination / "spritesheet.webp") as image:
                detect_sprite_version(image)
                image.load()
                digest = hashlib.sha256(
                    f"{image.width}x{image.height}:RGBA:".encode()
                    + image.convert("RGBA").tobytes()
                ).hexdigest()
            if "imported-" + digest != prepared.pet_id:
                raise ValueError()
            return ImportedPet(prepared.pet_id, str(manifest["displayName"]), True)
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
            raise PetImportError(
                "같은 펫의 저장 파일이 손상됐습니다. 펫 폴더를 확인하세요."
            ) from error
