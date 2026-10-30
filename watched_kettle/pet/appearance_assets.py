"""Validated appearance metadata and image assets, independent of Qt.

Version 1 declares exactly two looks with both transitions. Version 2 allows
two to six looks, transitions only where a package draws them (the rest are
played in reverse or cross-faded), one plain label, and automatic timing.
"""

from dataclasses import dataclass, field
from io import BytesIO
import re

from watched_kettle.config import ANIMATIONS, FRAME_HEIGHT, FRAME_WIDTH
from watched_kettle.localization import get_translator, t


MAX_APPEARANCE_IMAGE_BYTES = 20 * 1024 * 1024
MAX_APPEARANCE_VARIANTS = 6
AUTO_ORDERS = ("random", "sequence")
# Inclusive bounds of automatic change delays, in seconds.
AUTO_SECONDS = (10, 3600)
# Ranges a user can pick instead of the package's own ("package").
APPEARANCE_INTERVALS = {
    "10-30": (10, 30),
    "60-180": (60, 180),
    "180-600": (180, 600),
    "600-1800": (600, 1800),
    "1800-3600": (1800, 3600),
}
_TRANSITION_FRAMES = {1: (2, 32), 2: (2, 48)}
_ID_PATTERN = re.compile(r"[a-z][a-z0-9_-]{0,63}")


@dataclass(frozen=True)
class AppearanceVariant:
    id: str
    # Language code to name; a version 2 plain "label" is stored under "".
    labels: dict[str, str]
    path: str

    @property
    def label(self):
        locale = get_translator().locale.split("-")[0].lower()
        return (
            self.labels.get(locale)
            or self.labels.get("en")
            or next(iter(self.labels.values()))
        )


@dataclass(frozen=True)
class AppearanceTransition:
    source: str
    target: str
    path: str
    frames: int
    interval: int


@dataclass(frozen=True)
class AppearanceAuto:
    min_seconds: int = 60
    max_seconds: int = 180
    order: str = "random"


@dataclass(frozen=True)
class AppearanceSet:
    default: str
    variants: tuple[AppearanceVariant, ...]
    transitions: tuple[AppearanceTransition, ...]
    auto: AppearanceAuto = field(default_factory=AppearanceAuto)
    version: int = 1

    @property
    def ids(self):
        return tuple(variant.id for variant in self.variants)

    @property
    def paths(self):
        return tuple(
            dict.fromkeys(
                [variant.path for variant in self.variants]
                + [transition.path for transition in self.transitions]
            )
        )


@dataclass(frozen=True)
class AppearanceChoice:
    id: str
    label: str


@dataclass(frozen=True)
class AppearanceStatus:
    mode: str
    current_id: str
    target_id: str | None
    transitioning: bool
    pending: bool
    choices: tuple[AppearanceChoice, ...]
    # The user's automatic timing ("package" follows the package) and order.
    interval: str = "package"
    order: str = "package"
    package_auto: AppearanceAuto = field(default_factory=AppearanceAuto)


def invalid_appearance():
    return ValueError(t("pet.appearance.invalid_package"))


def parse_appearance_set(manifest):
    raw = manifest.get("appearanceSet")
    if raw is None:
        return None
    # Import here to reuse the package's exact path policy without a cycle.
    from watched_kettle.pet.import_package import relative_name

    if not isinstance(raw, dict) or type(raw.get("version")) is not int:
        raise invalid_appearance()
    version = raw["version"]
    if version not in _TRANSITION_FRAMES:
        raise invalid_appearance()
    rows = raw.get("variants")
    if not isinstance(rows, list):
        rows = []
    count = len(rows)
    if count < 2 or count > (2 if version == 1 else MAX_APPEARANCE_VARIANTS):
        raise invalid_appearance()
    variants = []
    for row in rows:
        if not isinstance(row, dict):
            raise invalid_appearance()
        identifier = row.get("id")
        if (
            not isinstance(identifier, str)
            or identifier == "auto"
            or _ID_PATTERN.fullmatch(identifier) is None
        ):
            raise invalid_appearance()
        variants.append(
            AppearanceVariant(
                identifier,
                _labels(row, version),
                relative_name(row.get("spritesheetPath")),
            )
        )
    ids = tuple(v.id for v in variants)
    if len(set(ids)) != len(ids) or raw.get("default") not in ids:
        raise invalid_appearance()
    default = next(v for v in variants if v.id == raw["default"])
    if default.path != relative_name(
        manifest.get("spritesheetPath", "spritesheet.webp")
    ):
        raise invalid_appearance()
    items = raw.get("transitions")
    if not isinstance(items, list) or (version == 1 and len(items) != 2):
        raise invalid_appearance()
    low, high = _TRANSITION_FRAMES[version]
    transitions = []
    for row in items:
        if not isinstance(row, dict):
            raise invalid_appearance()
        source, target, frames, interval = (
            row.get(k) for k in ("from", "to", "frames", "intervalMs")
        )
        if (
            source not in ids
            or target not in ids
            or source == target
            or type(frames) is not int
            or not low <= frames <= high
            or type(interval) is not int
            or not 16 <= interval <= 1000
        ):
            raise invalid_appearance()
        transitions.append(
            AppearanceTransition(
                source,
                target,
                relative_name(row.get("spritesheetPath")),
                frames,
                interval,
            )
        )
    if len({(v.source, v.target) for v in transitions}) != len(transitions):
        raise invalid_appearance()
    paths = [v.path for v in variants] + [v.path for v in transitions]
    if len({p.casefold() for p in paths}) != len(paths):
        raise invalid_appearance()
    auto = _auto(raw.get("auto")) if version == 2 else AppearanceAuto()
    return AppearanceSet(
        raw["default"], tuple(variants), tuple(transitions), auto, version
    )


def _labels(row, version):
    def valid(value):
        return (
            isinstance(value, str)
            and value.strip()
            and len(value) <= 100
            and not any(ord(c) < 32 for c in value)
        )

    labels = row.get("labels")
    if version == 2 and labels is None:
        label = row.get("label")
        if not valid(label):
            raise invalid_appearance()
        return {"": label}
    if (
        not isinstance(labels, dict)
        or not labels
        or (version == 1 and not {"ko", "en"}.issubset(labels))
        or any(
            not isinstance(k, str) or not k or len(k) > 16 or not valid(v)
            for k, v in labels.items()
        )
    ):
        raise invalid_appearance()
    return dict(labels)


def _auto(raw):
    if raw is None:
        return AppearanceAuto()
    low, high = AUTO_SECONDS
    if not isinstance(raw, dict):
        raise invalid_appearance()
    minimum = raw.get("minSeconds", 60)
    maximum = raw.get("maxSeconds", 180)
    order = raw.get("order", "random")
    if (
        type(minimum) is not int
        or type(maximum) is not int
        or not low <= minimum <= maximum <= high
        or order not in AUTO_ORDERS
    ):
        raise invalid_appearance()
    return AppearanceAuto(minimum, maximum, order)


def appearance_manifest(spec, paths):
    """The manifest declaration of spec with spritesheets renamed by paths."""
    variants = []
    for variant in spec.variants:
        names = (
            {"label": variant.labels[""]}
            if list(variant.labels) == [""]
            else {"labels": dict(variant.labels)}
        )
        variants.append(
            {"id": variant.id, **names, "spritesheetPath": paths[variant.path]}
        )
    declaration = {
        "version": spec.version,
        "default": spec.default,
        "variants": variants,
        "transitions": [
            {
                "from": v.source,
                "to": v.target,
                "spritesheetPath": paths[v.path],
                "frames": v.frames,
                "intervalMs": v.interval,
            }
            for v in spec.transitions
        ],
    }
    if spec.version == 2:
        declaration["auto"] = {
            "minSeconds": spec.auto.min_seconds,
            "maxSeconds": spec.auto.max_seconds,
            "order": spec.auto.order,
        }
    return declaration


def validate_appearance_image(image, *, frames=None):
    if getattr(image, "is_animated", False):
        raise invalid_appearance()
    expected = (1536, 2288) if frames is None else (FRAME_WIDTH * frames, FRAME_HEIGHT)
    if image.size != expected:
        raise invalid_appearance()
    rgba = image.convert("RGBA")
    cells = (
        (
            [
                (int(a["row"]), c)
                for a in ANIMATIONS.values()
                for c in range(int(a["frames"]))
            ]
            + [(r, c) for r in (9, 10) for c in range(8)]
        )
        if frames is None
        else [(0, c) for c in range(frames)]
    )
    for row, col in cells:
        alpha = rgba.crop(
            (
                col * FRAME_WIDTH,
                row * FRAME_HEIGHT,
                (col + 1) * FRAME_WIDTH,
                (row + 1) * FRAME_HEIGHT,
            )
        ).getchannel("A")
        low, high = alpha.getextrema()
        if high == 0 or low == 255:
            raise invalid_appearance()
    return rgba


def normalized_appearance_assets(manifest, read):
    spec = parse_appearance_set(manifest)
    if spec is None:
        return {}, {}
    # Manifest-only checks run without installed image dependencies.
    from PIL import Image

    primary = manifest.get("spritesheetPath", "spritesheet.webp")
    transitions = {v.path: v for v in spec.transitions}
    assets = {}
    canonical_paths = {}
    for index, name in enumerate(spec.paths):
        raw = read(name, MAX_APPEARANCE_IMAGE_BYTES)
        with Image.open(BytesIO(raw), formats=("PNG", "WEBP")) as image:
            rgba = validate_appearance_image(
                image, frames=transitions[name].frames if name in transitions else None
            )
        if name == primary:
            canonical_paths[name] = "spritesheet.webp"
            continue
        output = BytesIO()
        rgba.save(output, format="WEBP", lossless=True, exact=True)
        target = f"appearance/{index}.webp"
        assets[target] = output.getvalue()
        canonical_paths[name] = target
    return appearance_manifest(spec, canonical_paths), assets
