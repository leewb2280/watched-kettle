"""Fail a packaged edition if PyInstaller archived excluded feature modules."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path


PET_FORBIDDEN = (
    "watched_kettle.application.settings_ui.assistant",
    "watched_kettle.application.runtime",
    "watched_kettle.features.tasks",
    "watched_kettle.features.integrations",
    "watched_kettle.features.project_activity",
    "watched_kettle.features.notifications",
    "watched_kettle.features.settings.viewmodel",
    "watched_kettle.integrations.assistant_notification",
    "watched_kettle.integrations.codex_",
    "watched_kettle.integrations.claude_code_",
    "watched_kettle.state",
    "watched_kettle.storage",
    "watched_kettle.usage",
    # The usage widget and Qt Quick belong to the assistant edition.
    "watched_kettle.ui.usage_companion",
    "watched_kettle.ui.usage_widget",
    "PySide6.QtQuick",
    "PySide6.QtQml",
)
# Explicit user-triggered app launch is common; agent readers remain forbidden.
PET_ALLOWED = frozenset({"watched_kettle.integrations.codex_launcher"})
ALL_FORBIDDEN = ("watched_kettle.features.tasks",)
# The hook bridge starts on every Codex tool call (ADR 0004). inspect pulls in
# PyInstaller's inspect runtime hook, so the spec excludes it explicitly.
HOOK_BRIDGE_FORBIDDEN = (
    "PySide6",
    "shiboken6",
    "PIL",
    "inspect",
    "dataclasses",
    "watched_kettle.app",
    "watched_kettle.application",
    "watched_kettle.features",
    "watched_kettle.pet",
    "watched_kettle.storage",
    "watched_kettle.ui",
    "watched_kettle.usage",
)
FORBIDDEN = {
    "pet-only": PET_FORBIDDEN,
    "pet-assistant": ALL_FORBIDDEN,
    "hook-bridge": HOOK_BRIDGE_FORBIDDEN,
}


# Files under the bundle's _internal folder, as posix prefixes.
BUNDLE_FORBIDDEN = {
    "pet-only": (
        "PySide6/QtQuick.pyd",
        "PySide6/QtQml.pyd",
        "PySide6/qml/",
        "watched_kettle/ui/usage_widget/",
    ),
    # The spec keeps only the QML modules the usage widget imports.
    "pet-assistant": (
        "PySide6/Qt6WebEngine",
        "PySide6/Qt6Quick3D",
        "PySide6/Qt6QuickControls2",
        "PySide6/qml/QtQuick/Controls/",
        "PySide6/qml/QtQuick3D/",
        "PySide6/qml/QtWebEngine/",
        "PySide6/plugins/qmltooling/",
    ),
}


def check_bundle_files(internal_root, edition):
    root = Path(internal_root)
    forbidden = BUNDLE_FORBIDDEN.get(edition, ())
    return sorted(
        relative
        for path in root.rglob("*")
        if path.is_file()
        for relative in (path.relative_to(root).as_posix(),)
        if relative.startswith(forbidden)
    )


def check_edition_modules(toc_path, edition):
    archive = ast.literal_eval(Path(toc_path).read_text(encoding="utf-8"))
    modules = {row[0] for row in archive[1]}
    forbidden = FORBIDDEN[edition]
    unexpected = sorted(
        name
        for name in modules
        if not (edition == "pet-only" and name in PET_ALLOWED)
        and any(
            name == prefix
            or name.startswith(prefix + ".")
            or (prefix.endswith("_") and name.startswith(prefix))
            for prefix in forbidden
        )
    )
    return unexpected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("toc", type=Path)
    parser.add_argument("--edition", choices=tuple(FORBIDDEN), required=True)
    parser.add_argument(
        "--bundle", type=Path, help="the bundle's _internal folder to check files"
    )
    args = parser.parse_args()
    unexpected = check_edition_modules(args.toc, args.edition)
    if args.bundle is not None:
        unexpected += [
            "file " + name for name in check_bundle_files(args.bundle, args.edition)
        ]
    if unexpected:
        for module in unexpected:
            print(f"unexpected packaged module: {module}")
        return 1
    print(f"{args.edition} module boundary passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
