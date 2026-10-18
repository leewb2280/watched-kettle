"""Editable pack copies and translator references shared by settings and tooling."""

from __future__ import annotations

from itertools import count
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from .catalog import source_catalog
from .packs import MAX_PACKS, PACK_ID, primary_language

# Catalog contexts name the source file that shows a message. Map those files to
# a screen a user can find; unmapped files simply have no "screen" field.
# Settings pages reuse the navigation titles so the label matches the window.
_SETTINGS_PAGES = {
    "settings-ui/src/assistant/AssistantHomePage": "message.0590",
    "settings-ui/src/core/CorePetPage": "message.0591",
    "settings-ui/src/PetManagerDialog": "message.0591",
    "settings-ui/src/PetImportDialog": "message.0591",
    "watched_kettle/pet/trash": "message.0591",
    "watched_kettle/pet/importer": "message.0591",
    "watched_kettle/application/settings_ui/pet_batch": "message.0591",
    "settings-ui/src/core/CoreBubblePage": "message.0592",
    "settings-ui/src/core/BubbleEditorDialog": "message.0592",
    "settings-ui/src/core/bubbleTheme": "message.0592",
    "settings-ui/src/core/useBubbleEditor": "message.0592",
    "watched_kettle/pet/bubble_theme": "message.0592",
    "watched_kettle/ui/bubble_theme_preview": "message.0592",
    "settings-ui/src/assistant/AssistantWidgetPage": "message.0494",
    "settings-ui/src/assistant/WidgetPreview": "message.0494",
    "settings-ui/src/assistant/AssistantUsagePage": "message.0204",
    "settings-ui/src/assistant/Trends": "message.0204",
    "settings-ui/src/TrendChart": "message.0204",
    "settings-ui/src/assistant/QuotaGroups": "message.0204",
    "watched_kettle/features/usage/": "message.0204",
    **{
        "watched_kettle/usage/" + name: "message.0204"
        for name in (
            "service",
            "claude_code_service",
            "claude_code_limits",
            "conversation_catalog",
            "conversation_models",
            "history_projection",
            "models",
            "notice_policy",
            "presentation",
            "turn_log",
            "worker",
        )
    },
    "settings-ui/src/assistant/AssistantActivityPage": "message.0593",
    "watched_kettle/features/history/": "message.0593",
    "settings-ui/src/assistant/AssistantIntegrationPage": "message.0594",
    "settings-ui/src/assistant/Connections": "message.0594",
    "watched_kettle/integrations/codex_install": "message.0594",
    "watched_kettle/integrations/claude_code_install": "message.0594",
    "watched_kettle/integrations/claude_code_status_line_install": "message.0594",
    "watched_kettle/features/integrations/": "message.0594",
    "settings-ui/src/core/CoreAppPage": "message.0595",
    "settings-ui/src/core/UpdateRow": "message.0595",
    "settings-ui/src/core/CoreDialogs": "message.0595",
    "settings-ui/src/core/useCoreSettings": "message.0595",
    "watched_kettle/application/update_check": "message.0595",
    "watched_kettle/integrations/windows_startup": "message.0595",
    "language.": "message.0595",
}
_AREAS = {
    "status.": "settings_common",
    "bubble.": "pet",
    "statusline.": "statusline",
    "widget.": "widget",
    "settings-ui/": "settings_common",
    "watched_kettle/application/settings_ui/": "settings_common",
    "watched_kettle/ui/menu": "tray",
    "watched_kettle/ui/assistant_tray": "tray",
    "watched_kettle/ui/pet_tray": "tray",
    "watched_kettle/ui/pet_controls": "tray",
    "watched_kettle/usage/widget_": "widget",
    "Desktop usage widget": "widget",
    "Claude Code status line": "statusline",
    "watched_kettle/integrations/assistant_notification": "notification",
    "watched_kettle/features/notifications/": "notification",
    "watched_kettle/startup_recovery": "startup",
    "watched_kettle/ui/startup_recovery": "startup",
    "watched_kettle/integrations/single_instance": "startup",
    "watched_kettle/app": "startup",
    "watched_kettle/ui/": "pet",
    "watched_kettle/pet/": "pet",
    "watched_kettle/state/": "pet",
}


def _lookup(table, key, path):
    # Message ID prefixes ("language.") and folder/file prefixes ("ui/", "widget_")
    # match by prefix; other entries name one source file.
    for prefix, value in table.items():
        if (
            key.startswith(prefix)
            if prefix[-1] == "."
            else (path == prefix or (prefix[-1] in "/_" and path.startswith(prefix)))
        ):
            return value
    return None


def screen(key, context, translator):
    path = re.sub(r":\d+$", "", context.split(";")[0].strip()).replace("\\", "/")
    path = re.sub(r"\.(py|tsx?|cjs)$", "", path)
    if page := _lookup(_SETTINGS_PAGES, key, path):
        return translator.text("language.screen.settings", page=translator.text(page))
    if area := _lookup(_AREAS, key, path):
        return translator.text("language.screen." + area)
    return ""


def plain(value):
    return dict(value) if hasattr(value, "keys") else value


def reference(translator, english=None, current=None):
    """Per-message notes for people editing a pack; the app never loads them."""
    result = {}
    for key, entry in source_catalog()["messages"].items():
        item = {"source": entry["value"]}
        if english is not None and key in english:
            item["english"] = plain(english[key])
        if current is not None:
            item["current"] = plain(current.get(key, entry["value"]))
        if label := screen(key, entry["context"], translator):
            item["screen"] = label
        item.update(
            variables=entry["variables"],
            context=entry["context"],
            sourceRevision=entry["revision"],
            plural=entry.get("plural", ""),
        )
        result[key] = item
    return result


def write_json(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def copy_pack(packs, source_id, *, name, author):
    """Write a complete, editable copy of a pack as a new user pack; return its ID.

    Existing folders are never touched: files go to a dot folder (skipped by
    discovery) that is renamed into place only when complete.
    """
    root = packs.root
    if root is None:
        raise ValueError("unsupported")
    source = packs.select(source_id)
    root.mkdir(parents=True, exist_ok=True)
    folders = [path.name.casefold() for path in root.iterdir()]
    if sum(not folder.startswith(".") for folder in folders) >= MAX_PACKS:
        raise ValueError("too_many_packs")
    taken = set(folders) | {pack.id.casefold() for pack in packs.packs}
    prefix = "custom." + re.sub(r"[^a-z0-9-]", "", source.locale.lower())[:60]
    pack_id = next(f"{prefix}.{n}" for n in count(1) if f"{prefix}.{n}" not in taken)
    if not PACK_ID.fullmatch(pack_id):
        raise ValueError("invalid_id")
    catalog = source_catalog()["messages"]
    effective = source.effective_messages()
    # Official packs have no fallback; unreadable folders are listed with ID "".
    fallback = packs.find(source.fallback_id) if source.fallback_id else None
    # A different-language fallback stays untranslated (blank) so the copy keeps
    # the source pack's real coverage; the app keeps filling it at run time.
    inherit = fallback is None or primary_language(fallback.locale) == primary_language(
        source.locale
    )
    messages = {}
    for key, entry in catalog.items():
        if key in source.messages:
            value = source.messages[key]
            revision = source.revisions.get(key, entry["revision"])
        elif inherit:
            value = effective.get(key, entry["value"])
            revision = entry["revision"]
        else:
            value = ""
            revision = entry["revision"]
        messages[key] = {"sourceRevision": revision, "value": plain(value)}
    english = packs.find("official.en")
    staging = Path(tempfile.mkdtemp(prefix=".copy-", dir=root))
    try:
        write_json(
            staging / "manifest.json",
            {
                "schemaVersion": 1,
                "id": pack_id,
                "locale": source.locale,
                "name": name[:200],
                "author": author[:200],
                "version": "1",
                "catalogVersion": source_catalog()["version"],
            },
        )
        write_json(staging / "messages.json", messages)
        write_json(
            staging / "reference.json",
            reference(
                source.translator(),
                english.messages if english and not english.error else None,
                effective,
            ),
        )
        # rename never replaces an existing directory on Windows.
        os.rename(staging, root / pack_id)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    # The caller refreshes discovery (selecting the copy does it already).
    return pack_id
