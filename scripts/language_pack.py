"""Create, validate and update external JSON language packs without replacing originals."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from watched_kettle.localization.catalog import (
    RESOURCE_ROOT,
    Translator,
    source_catalog,
    read_json,
    locale_info,
    validate_value,
)
from watched_kettle.localization.editing import reference, write_json
from watched_kettle.localization.packs import load_pack, PACK_ID, primary_language


def _needs_review(translation, entry):
    if not isinstance(translation, dict):
        return True
    revision = translation.get("sourceRevision")
    if type(revision) is not int or revision != entry["revision"]:
        return True
    value = translation.get("value")
    # Blank template entries are untranslated, not malformed translations.
    if isinstance(value, str) and not value.strip():
        return False
    try:
        validate_value(value, entry)
    except (ValueError, TypeError):
        return True
    return False


def template(target, pack_id, locale, previous=None):
    target = Path(target)
    if target.exists():
        raise ValueError("Output directory must be new")
    catalog = source_catalog()
    if not PACK_ID.fullmatch(pack_id) or pack_id.startswith("official."):
        raise ValueError("Invalid community pack ID")
    locale_info(locale)
    old_manifest = {}
    old = {}
    if previous is not None:
        old_manifest = read_json(Path(previous) / "manifest.json", 16384)
        old = read_json(Path(previous) / "messages.json")
        if not isinstance(old_manifest, dict) or not isinstance(old, dict):
            raise ValueError("Invalid previous pack")
    messages = {
        key: old.get(key, {"sourceRevision": entry["revision"], "value": ""})
        for key, entry in catalog["messages"].items()
    }
    english = load_pack(RESOURCE_ROOT / "en", official=True)
    # Screen names follow the official pack a translator most likely reads.
    guide = Translator() if primary_language(locale) == "ko" else english.translator()
    target.mkdir(parents=True)
    write_json(
        target / "manifest.json",
        {
            "schemaVersion": 1,
            "id": pack_id,
            "locale": locale,
            "name": old_manifest.get("name", pack_id),
            "author": old_manifest.get("author", "Translator"),
            "version": old_manifest.get("version", "1"),
            "catalogVersion": catalog["version"],
        },
    )
    write_json(target / "messages.json", messages)
    write_json(target / "reference.json", reference(guide, english.messages))
    return {
        "new": sorted(set(messages) - set(old)),
        "removed": sorted(set(old) - set(messages)),
        "review": [
            key
            for key in sorted(set(old) & set(messages))
            if _needs_review(old[key], catalog["messages"][key])
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("template", "update"):
        command = sub.add_parser(name)
        command.add_argument("--output", required=True, type=Path)
        command.add_argument("--id", required=True)
        command.add_argument("--locale", required=True)
        if name == "update":
            command.add_argument("previous", type=Path)
    check = sub.add_parser("check")
    check.add_argument("folder", type=Path)
    check.add_argument("--official", action="store_true")
    args = parser.parse_args()
    if args.command == "check":
        pack = load_pack(args.folder, official=args.official)
        print(json.dumps(pack.info(), ensure_ascii=False, indent=2))
        return 1 if pack.issues or pack.outdated or pack.translated != pack.total else 0
    print(
        json.dumps(
            template(
                args.output, args.id, args.locale, getattr(args, "previous", None)
            ),
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
