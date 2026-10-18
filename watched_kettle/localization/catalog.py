"""Immutable message formatting shared by desktop UI and pack tooling."""

from __future__ import annotations

from functools import lru_cache
import json
import math
from pathlib import Path
import re
from string import Formatter
from types import MappingProxyType
import unicodedata

RESOURCE_ROOT = Path(__file__).with_name("resources")
CATEGORIES = frozenset(("zero", "one", "two", "few", "many", "other"))
_IDENTIFIER = re.compile(r"[a-zA-Z_][a-zA-Z_0-9]*\Z")
_FORMATTER = Formatter()


def read_json(path, maximum=1024 * 1024):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_key")
            result[key] = value
        return result

    with Path(path).open("rb") as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError("too_large")
    try:
        payload = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique)
        pending = [payload]
        while pending:
            value = pending.pop()
            if isinstance(value, str):
                value.encode("utf-8")  # JSON escapes can contain unpaired surrogates.
            elif isinstance(value, dict):
                pending.extend(value)
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
        return payload
    except RecursionError as error:
        raise ValueError("invalid_json") from error


def placeholders(value):
    names = set()
    for _, name, spec, conversion in _FORMATTER.parse(value):
        if name is not None:
            if not _IDENTIFIER.fullmatch(name) or spec or conversion:
                raise ValueError("invalid_placeholder")
            names.add(name)
    return names


def validate_value(value, entry):
    forms = value if isinstance(value, dict) else {"other": value}
    if not forms or not set(forms) <= CATEGORIES or "other" not in forms:
        raise ValueError("invalid_plural")
    if isinstance(value, dict) and not entry.get("plural"):
        raise ValueError("unexpected_plural")
    expected = set(entry.get("variables", {}))
    for text in forms.values():
        if not isinstance(text, str) or not text.strip() or len(text) > 16384:
            raise ValueError("invalid_text")
        if re.search(r"</?[A-Za-z][^>]*>", text):
            raise ValueError("invalid_text")
        if any(
            unicodedata.category(char) in {"Cc", "Cs"} and char not in "\n\t"
            for char in text
        ):
            raise ValueError("invalid_text")
        if placeholders(text) != expected:
            raise ValueError("invalid_placeholder")


@lru_cache(maxsize=1)
def source_catalog():
    payload = read_json(RESOURCE_ROOT / "catalog.json", 4 * 1024 * 1024)
    if payload.get("version") != 1 or not isinstance(payload.get("messages"), dict):
        raise ValueError("invalid_catalog")
    for entry in payload["messages"].values():
        validate_value(entry["value"], entry)
    return payload


@lru_cache(maxsize=1)
def supported_locales():
    return frozenset(read_json(RESOURCE_ROOT / "locales.json", 65536)["locales"])


@lru_cache(maxsize=64)
def locale_info(locale):
    # Babel accepts ICU modifiers/root/und that Intl rejects or resolves using
    # the host language. Require the concrete BCP 47 subset both runtimes share.
    if (
        not isinstance(locale, str)
        or not re.fullmatch(
            r"[A-Za-z]{2,3}(?:-[A-Za-z]{4})?(?:-(?:[A-Za-z]{2}|[0-9]{3}))?"
            r"(?:-(?:[A-Za-z0-9]{5,8}|[0-9][A-Za-z0-9]{3}))*",
            locale,
        )
        or locale.split("-")[0].lower() == "und"
    ):
        raise ValueError("unsupported_locale")
    from babel import Locale

    from babel.core import UnknownLocaleError

    try:
        parsed = Locale.parse(locale, sep="-")
    except UnknownLocaleError as error:
        raise ValueError("unsupported_locale") from error
    if parsed.character_order != "left-to-right":
        raise ValueError("unsupported_direction")
    if str(parsed).replace("_", "-") not in supported_locales():
        raise ValueError("unsupported_locale")
    return parsed


class Translator:
    """Fixed for one app run. Pack values can never mutate the source catalog."""

    def __init__(self, locale="ko", messages=None, pack_id="official.ko"):
        self.locale = locale
        self.pack_id = pack_id
        self.messages = MappingProxyType(
            {
                key: MappingProxyType(dict(value)) if isinstance(value, dict) else value
                for key, value in (messages or {}).items()
            }
        )

    def text(self, key, **values):
        entry = source_catalog()["messages"].get(key)
        if entry is None:
            return key
        value = self.messages.get(key, entry["value"])
        if isinstance(value, (dict, MappingProxyType)):
            count = values.get(entry.get("plural", ""))
            valid = not isinstance(count, bool) and isinstance(count, (int, float))
            try:
                valid = valid and math.isfinite(count)
            except OverflowError:
                valid = False
            category = (
                str(locale_info(self.locale).plural_form(count)) if valid else "other"
            )
            value = value.get(category, value["other"])
        if not values and entry.get("variables"):
            return str(value)
        try:
            return str(value).format_map(values)
        except (KeyError, ValueError, TypeError):
            # An application formatting defect must not take down the UI.
            return str(
                entry["value"].get("other", "")
                if isinstance(entry["value"], dict)
                else entry["value"]
            )

    def bootstrap(self, edition="pet-assistant"):
        entries = {
            key: entry
            for key, entry in source_catalog()["messages"].items()
            if edition == "pet-assistant" or entry.get("domain") != "assistant"
        }
        return {
            "packId": self.pack_id,
            "locale": self.locale,
            "messages": {
                key: {
                    "value": dict(value)
                    if isinstance(
                        value := self.messages.get(key, entry["value"]),
                        (dict, MappingProxyType),
                    )
                    else value,
                    "plural": entry.get("plural", ""),
                }
                for key, entry in entries.items()
            },
        }


_active = None


def get_translator():
    global _active
    if _active is None:
        _active = Translator()
    return _active


def set_translator(translator):
    global _active
    _active = translator


def t(key, **values):
    return get_translator().text(key, **values)
