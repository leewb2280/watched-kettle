# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import os
import sys


project_root = Path(SPECPATH).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from watched_kettle.build_profiles import (
    PRIVATE_BETA_BUILD_PROFILE,
    collect_pet_build_sources,
    normalize_build_profile,
)

app_icon = project_root / "assets" / "app_icon.ico"
app_icon_png = project_root / "assets" / "app_icon.png"
checkmark_icon = project_root / "assets" / "ui" / "check-white.svg"
version_info = Path(
    os.environ.get("WATCHED_KETTLE_VERSION_FILE")
    or project_root / "build" / "windows_version_info.txt"
)
if not version_info.is_file():
    raise FileNotFoundError(
        "Generate Windows version metadata before running PyInstaller: "
        f"{version_info}"
    )
build_profile = normalize_build_profile(
    os.environ.get("WATCHED_KETTLE_BUILD_PROFILE")
)
edition = os.environ.get("WATCHED_KETTLE_EDITION", "pet-assistant")
if edition not in {"pet-only", "pet-assistant"}:
    raise ValueError(f"unsupported edition: {edition}")
entry_script = "main_pet_only.py" if edition == "pet-only" else "main.py"
pet_datas = []
for source in collect_pet_build_sources(project_root, build_profile):
    pet_datas.extend([
        (str(source.manifest_path), source.destination),
        (str(source.spritesheet_path), source.destination),
    ])
    pet_datas.extend((str(path), folder) for path, folder in source.frame_images)

font_root = project_root / "assets" / "fonts" / "Pretendard"
font_datas = [
    (str(font_root / filename), "assets/fonts/Pretendard")
    for filename in (
        "Pretendard-Regular.otf",
        "Pretendard-Medium.otf",
        "Pretendard-SemiBold.otf",
        "Pretendard-Bold.otf",
        "OFL.txt",
    )
]

# The Qt Quick usage widget belongs to the assistant edition only.
widget_qml_root = project_root / "watched_kettle" / "ui" / "usage_widget" / "qml"
widget_datas = (
    [
        (str(path), "watched_kettle/ui/usage_widget/qml")
        for path in sorted(widget_qml_root.iterdir())
        if path.suffix in {".qml", ".js"}
    ]
    if edition == "pet-assistant"
    else []
)
notice_datas = []
if build_profile == PRIVATE_BETA_BUILD_PROFILE:
    private_notice = project_root / "packaging" / "private-beta" / "NOTICE.txt"
    if not private_notice.is_file():
        raise FileNotFoundError(private_notice)
    notice_datas.append((str(private_notice), "."))

a = Analysis(
    [str(project_root / entry_script)],
    pathex=[str(project_root)],
    binaries=[],
    datas=(
        pet_datas
        + font_datas
        + widget_datas
        + [(str(app_icon_png), "assets")]
        + [(str(checkmark_icon), "assets/ui")]
        + [(str(project_root / "THIRD_PARTY_NOTICES.md"), ".")]
        + notice_datas
    ),
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=(
        ([] if edition == "pet-assistant" else [
            "watched_kettle.application.runtime",
            "watched_kettle.application.settings_ui.assistant",
            "watched_kettle.features.tasks",
            "watched_kettle.features.project_activity",
            "watched_kettle.features.notifications",
            "watched_kettle.storage",
            "watched_kettle.usage",
            "watched_kettle.state",
        ])
    ),
    noarchive=False,
    optimize=0,
)

# Importing PySide6.QtQuick makes PyInstaller collect every QML module and the Qt
# libraries behind them (WebEngine, 3D, Controls, Charts; about +300 MiB). The
# usage widget needs only QtQuick with Shapes and Window, so keep those modules
# and drop the libraries that only the other modules load.
KEPT_QML_MODULES = (
    "QtQml",
    "QtQml/Models",
    "QtQml/WorkerScript",
    "QtQuick",
    "QtQuick/Shapes",
    "QtQuick/Window",
)
DROPPED_QT_LIBRARY_PREFIXES = (
    "Qt63D", "Qt6Charts", "Qt6DataVisualization", "Qt6Graphs", "Qt6Labs",
    "Qt6Location", "Qt6Multimedia", "Qt6OpenGLWidgets", "Qt6PdfQuick",
    "Qt6Positioning", "Qt6QmlLocalStorage", "Qt6QmlNetwork", "Qt6QmlXmlListModel",
    "Qt6Quick3D", "Qt6QuickControls2", "Qt6QuickDialogs2", "Qt6QuickEffects",
    "Qt6QuickLayouts", "Qt6QuickParticles", "Qt6QuickShapesDesignHelpers",
    "Qt6QuickTemplates2", "Qt6QuickTest", "Qt6QuickTimeline", "Qt6QuickVectorImage",
    "Qt6RemoteObjects", "Qt6Scxml", "Qt6Sensors", "Qt6ShaderTools",
    "Qt6SpatialAudio", "Qt6Sql", "Qt6StateMachine", "Qt6Test", "Qt6TextToSpeech",
    "Qt6VirtualKeyboard", "Qt6WebChannel", "Qt6WebEngine", "Qt6WebSockets",
    "Qt6WebView",
)  # fmt: skip


def keep_qt_entry(destination):
    parts = Path(destination).as_posix().split("/")
    if parts[:1] != ["PySide6"]:
        return True
    if parts[1:2] == ["qml"]:
        module = "/".join(parts[2:-1])
        # Top-level qmltypes describe the language itself.
        return module == "" or module in KEPT_QML_MODULES
    if parts[1:3] == ["plugins", "qmltooling"]:
        return False
    if parts[1:2] == ["translations"] and parts[-1].startswith("qtdeclarative_"):
        return False
    return not parts[-1].startswith(DROPPED_QT_LIBRARY_PREFIXES)


a.binaries = [entry for entry in a.binaries if keep_qt_entry(entry[0])]
a.datas = [entry for entry in a.datas if keep_qt_entry(entry[0])]

# The workspace toolchain can put Poppler's version-suffixed ICU DLLs on PATH.
# Qt for Windows imports the system ICU compatibility exports without suffixes,
# so collecting Poppler's icuuc.dll makes QtCore fail with entrypoint-not-found.
poppler_icu_names = {"icuuc.dll", "icudt78.dll"}
a.binaries = [
    entry
    for entry in a.binaries
    if not (
        Path(entry[0]).name.casefold() in poppler_icu_names
        and "poppler" in str(entry[1]).casefold()
    )
]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WatchedKettle",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(app_icon),
    version=str(version_info),
)

bridge_parts = []
if edition == "pet-assistant":
    # Codex runs the hook on every tool call (ADR 0004). Excluding inspect and
    # dataclasses also drops PyInstaller's inspect runtime hook (~20 ms per call).
    bridge = Analysis(
        [str(project_root / "main_hook_bridge.py")],
        pathex=[str(project_root)],
        binaries=[],
        datas=[],
        hiddenimports=[],
        hookspath=[],
        hooksconfig={},
        runtime_hooks=[],
        excludes=["PySide6", "shiboken6", "PIL", "inspect", "dataclasses"],
        noarchive=False,
        optimize=0,
    )
    bridge_exe = EXE(
        PYZ(bridge.pure),
        bridge.scripts,
        [],
        exclude_binaries=True,
        name="WatchedKettleHookBridge",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        icon=str(app_icon),
        version=str(version_info),
    )
    bridge_parts = [bridge_exe, bridge.binaries, bridge.datas]

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    *bridge_parts,
    strip=False,
    upx=False,
    name="WatchedKettle",
)
