"""Bounded discovery and validation of editable, data-only language packs."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
import re

from .catalog import (
    RESOURCE_ROOT,
    Translator,
    locale_info,
    read_json,
    source_catalog,
    validate_value,
)

PACK_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,79}\Z")
MAX_PACKS = 128
PROBLEM_CODES = frozenset(
    (
        "unknown",
        "invalid_entry",
        "invalid_revision",
        "invalid_placeholder",
        "invalid_plural",
        "unexpected_plural",
        "invalid_text",
    )
)


@dataclass
class LanguagePack:
    id: str
    name: str
    locale: str = ""
    author: str = ""
    version: str = ""
    official: bool = False
    error: str = ""
    translated: int = 0
    untranslated: int = 0
    total: int = 0
    outdated: int = 0
    issues: list[str] = field(default_factory=list)
    problems: list[dict] = field(default_factory=list)
    messages: dict = field(default_factory=dict, repr=False)
    revisions: dict = field(default_factory=dict, repr=False)
    # Missing or invalid entries use this pack's values, then the Korean catalog.
    fallback_id: str = ""
    fallback_messages: dict = field(default_factory=dict, repr=False)

    def info(self):
        return {
            "id": self.id,
            "name": self.name,
            "locale": self.locale,
            "author": self.author,
            "version": self.version,
            "official": self.official,
            "error": self.error,
            "translated": self.translated,
            "untranslated": self.untranslated,
            "total": self.total,
            "outdated": self.outdated,
            "issues": self.issues[:32],
            "problems": self.problems[:32],
            "problemCount": len(self.problems),
            "fallback": self.fallback_id,
            "fallbackCount": self.total - self.translated if self.fallback_id else 0,
            "selectable": not self.error,
        }

    def effective_messages(self):
        return {**self.fallback_messages, **self.messages}

    def translator(self):
        return Translator(self.locale, self.effective_messages(), self.id)


def primary_language(locale):
    return str(locale).split("-")[0].lower()


def load_pack(folder, *, official=False):
    folder = Path(folder)
    if folder.is_symlink() or folder.is_junction():
        raise ValueError("linked_pack")
    for name in ("manifest.json", "messages.json"):
        path = folder / name
        if path.is_symlink() or path.is_junction():
            raise ValueError("linked_pack")
    manifest = read_json(folder / "manifest.json", 16384)
    if (
        not isinstance(manifest, dict)
        or type(manifest.get("schemaVersion")) is not int
        or manifest["schemaVersion"] != 1
    ):
        raise ValueError("unsupported_format")
    required = ("id", "locale", "name", "author", "version")
    if not all(
        isinstance(manifest.get(k), str) and 0 < len(manifest[k]) <= 200
        for k in required
    ):
        raise ValueError("invalid_manifest")
    pack_id = manifest["id"]
    if not PACK_ID.fullmatch(pack_id) or (
        pack_id.startswith("official.") and not official
    ):
        raise ValueError("invalid_id")
    if type(manifest.get("catalogVersion")) is not int:
        raise ValueError("invalid_manifest")
    try:
        locale_info(manifest["locale"])
    except (ValueError, TypeError, LookupError) as error:
        raise ValueError("unsupported_locale") from error
    pack = LanguagePack(
        pack_id,
        manifest["name"],
        manifest["locale"],
        manifest["author"],
        manifest["version"],
        official,
    )
    raw = read_json(folder / "messages.json")
    if not isinstance(raw, dict):
        raise ValueError("invalid_messages")
    catalog = source_catalog()["messages"]
    pack.total = len(catalog)
    pack.untranslated = len(catalog)
    for key, translation in raw.items():
        if key not in catalog:
            pack.issues.append("unknown:" + key[:120])
            pack.problems.append({"key": key[:120], "code": "unknown"})
            continue
        entry = catalog[key]
        if (
            isinstance(translation, dict)
            and isinstance(translation.get("value"), str)
            and not translation["value"].strip()
        ):
            continue
        pack.untranslated -= 1
        try:
            if not isinstance(translation, dict):
                raise ValueError("invalid_entry")
            validate_value(translation.get("value"), entry)
            if type(translation.get("sourceRevision")) is not int:
                raise ValueError("invalid_revision")
        except (ValueError, TypeError) as error:
            pack.issues.append("invalid:" + key)
            code = str(error) if isinstance(error, ValueError) else ""
            pack.problems.append(
                {"key": key, "code": code if code in PROBLEM_CODES else "invalid_entry"}
            )
            continue
        pack.messages[key] = translation["value"]
        pack.revisions[key] = translation["sourceRevision"]
        if translation["sourceRevision"] != entry["revision"]:
            pack.outdated += 1
    pack.translated = len(pack.messages)
    return pack


class LanguagePacks:
    """App-run active language and an explicitly refreshed discovery snapshot."""

    def __init__(self, root, selected="", installer_locale="ko"):
        self.root = Path(root) if root is not None else None
        self.selected = selected
        self.packs = []
        self.refresh()
        choice = selected or (
            "official.en" if installer_locale == "en" else "official.ko"
        )
        pack = self.find(choice)
        self.active = (
            pack if pack and not pack.error else self.find("official.ko")
        ).translator()
        self.startup_issue = bool(
            (selected or installer_locale == "en") and (pack is None or pack.error)
        )

    def refresh(self):
        catalog = source_catalog()
        base = LanguagePack(
            "official.ko",
            "한국어",
            "ko",
            "Watched Kettle",
            "1",
            True,
            total=len(catalog["messages"]),
            translated=len(catalog["messages"]),
        )
        try:
            english = load_pack(RESOURCE_ROOT / "en", official=True)
        except (OSError, ValueError, UnicodeError, TypeError, KeyError):
            english = LanguagePack(
                "official.en", "English", "en-US", official=True, error="invalid_pack"
            )
        packs = [base, english]
        folders = []
        if (
            self.root is not None
            and self.root.is_dir()
            and not self.root.is_symlink()
            and not self.root.is_junction()
        ):
            try:
                folders = sorted(self.root.iterdir(), key=lambda p: p.name.casefold())[
                    :MAX_PACKS
                ]
            except OSError:
                packs.append(LanguagePack("", "language-packs", error="invalid_pack"))
            for folder in folders:
                # Dot folders are unfinished editable copies (see editing.py).
                if folder.name.startswith(".") or not folder.is_dir():
                    continue
                try:
                    packs.append(load_pack(folder))
                except (
                    OSError,
                    ValueError,
                    UnicodeError,
                    TypeError,
                    KeyError,
                ) as error:
                    safe_codes = {
                        "unsupported_format",
                        "unsupported_locale",
                        "invalid_manifest",
                        "invalid_id",
                        "invalid_messages",
                        "duplicate_key",
                        "too_large",
                        "linked_pack",
                    }
                    code = str(error)
                    packs.append(
                        LanguagePack(
                            "",
                            folder.name[:200],
                            error=code if code in safe_codes else "invalid_pack",
                        )
                    )
        for pack in packs[2:]:
            if pack.error:
                continue
            if primary_language(pack.locale) != "ko" and not english.error:
                pack.fallback_id = english.id
                pack.fallback_messages = english.messages
            else:
                pack.fallback_id = base.id
        counts = Counter(pack.id for pack in packs if pack.id)
        for pack in packs:
            if not pack.official and counts[pack.id] > 1:
                pack.error = "duplicate_id"
        self.packs = packs
        return [pack.info() for pack in packs]

    def find(self, pack_id):
        return next((pack for pack in self.packs if pack.id == pack_id), None)

    def select(self, pack_id):
        self.refresh()
        pack = self.find(pack_id)
        if pack is None or pack.error:
            raise ValueError("unavailable_pack")
        return pack

    def state(self):
        selected = self.find(self.selected or self.active.pack_id)
        changed = (
            selected is None
            or bool(selected.error)
            or selected.locale != self.active.locale
            or selected.effective_messages() != self.active.messages
        )
        return {
            "current": self.active.pack_id,
            "selected": self.selected or self.active.pack_id,
            "locale": self.active.locale,
            "restartRequired": bool(
                changed or (self.selected and self.selected != self.active.pack_id)
            ),
            "recovered": self.startup_issue,
        }
