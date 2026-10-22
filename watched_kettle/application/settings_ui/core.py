"""Common settings adapter. Does not import assistant services or storage."""

from __future__ import annotations


from collections import OrderedDict
from typing import cast
import base64
from dataclasses import asdict
from io import BytesIO
import json

from PIL import Image
from PySide6.QtCore import (
    QBuffer,
    QByteArray,
    QIODevice,
    QObject,
    QSettings,
    Signal,
    QUrl,
    QTimer,
    Qt,
)
from PySide6.QtGui import QDesktopServices

from watched_kettle import settings_protocol as wire_types
from watched_kettle.app_preferences import DOUBLE_CLICK_ACTIONS
from watched_kettle.application.about import about_info, licenses_folder
from watched_kettle.application.click_through import PET_LOCK
from watched_kettle.application.settings_ui.contracts import (
    CommandError,
    boolean,
    choice,
    integer,
    require,
    text,
    wire,
)
from watched_kettle.application.logging import log_event
from watched_kettle.application.settings_ui.pet_batch import PetBatchController
from watched_kettle.application.settings_ui.pet_import import PetImportController
from watched_kettle.application.update_check import (
    UpdateCheckSchedule,
    _version,
    release_url_kind,
)
from watched_kettle.application.localization import packs_for
from watched_kettle.localization import t
from watched_kettle.localization.editing import copy_pack
from watched_kettle.branding import APPLICATION_VERSION, PROJECT_ROOT
from watched_kettle.config import (
    CODEX_MAX_PET_WIDTH,
    DEFAULT_PET_WIDTH,
    EXTENDED_MAX_PET_WIDTH,
    FRAME_HEIGHT,
    FRAME_WIDTH,
    LOOK_RANGE_MIN,
    LOOK_RANGE_MAX,
    PET_WIDTH_OPTIONS,
)
from watched_kettle.pet import bubble_theme as themes
from watched_kettle.pet.bubble_frame import frame_style_for, registered_frame
from watched_kettle.pet.catalog import order_pet_entries
from watched_kettle.pet.import_package import PET_IMAGE_FORMATS
from watched_kettle.pet.importer import (
    IMPORT_LIFETIME_SECONDS,
    PetImportError,
    PetImporter,
)
from watched_kettle.pet.trash import PetTrashError
from watched_kettle.preferences.hotkeys import format_hotkey
from watched_kettle.ui.bubble_elements import BubbleElementError
from watched_kettle.ui.bubble_theme_preview import BubbleThemePreview
from watched_kettle.ui.pet_controls import ACTION_TEST_STATES, size_label


THEME_UNITS = {
    "radius": "px",
    "border_width": "px",
    "ornament_scale": "%",
    "minimum_width": "px",
    "maximum_width": "px",
    "horizontal_padding": "px",
}
# The pet is placed and shown a moment after startup.
UPDATED_NOTICE_DELAY_MS = 5000
# Twice the largest CSS tile (110x120) so picker thumbnails stay sharp at 200%.
CATALOG_THUMBNAIL_SIZE = (220, 240)


def _choice_order(values):
    """Stable editor order with the neutral "none"/"standard" option first."""
    return sorted(values, key=lambda value: (value not in {"none", "standard"}, value))


def png_data(pixmap):
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    require(pixmap.save(buffer, "PNG"), t("message.0512"))
    require(data.size() <= 512 * 1024, code="response_limit")
    return "data:image/png;base64," + bytes(data.toBase64().data()).decode("ascii")


def png_bytes_data(data):
    require(len(data) <= 512 * 1024, code="response_limit")
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def control(key, label, value, kind="bool", **extras):
    return dict(key=key, label=label, value=value, kind=kind, **extras)


def hotkey_text(value):
    """A shortcut the renderer recorded: canonical text, or "" to clear it."""
    require(
        isinstance(value, str) and (value == "" or format_hotkey(value) == value),
        t("hotkey.invalid"),
    )
    return value


def hotkey_status(shortcuts, name, value):
    if shortcuts is not None:
        return shortcuts.status(name)
    return "unavailable" if value else "unassigned"


class CoreSettingsAdapter(QObject):
    changed = Signal(str)

    def __init__(self, pet_vm, settings_vm, preferences, app, parent=None):
        super().__init__(parent)
        self.pet_vm, self.settings_vm = pet_vm, settings_vm
        self.preferences, self.app = preferences, app
        self.revision = 0
        self.account_epoch = 0
        self.assistant = None
        # The runtime's global lock shortcuts (application/click_through.py).
        self.click_through = None
        self.languages = packs_for(preferences)
        self.pet_batch = PetBatchController(self)
        self._thumbnails = OrderedDict()
        self.pet_importer = PetImporter(self.pet_vm.pet.user_pets_root)
        self.pet_import = PetImportController(self)
        self.import_timer = QTimer(self)
        self.import_timer.setSingleShot(True)
        self.import_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.import_timer.timeout.connect(self.cancel_pet_import)
        self._settings_signature = self._signature(self.pet_vm.snapshot)
        self.pet_vm.snapshot_changed.connect(self._pet_changed)
        self.updates = self.settings_vm.updates
        self.updates.changed.connect(self._update_changed)
        self.updates.found.connect(self._update_found)
        self.updates.staged_ready.connect(self._update_staged)
        self.update_schedule = UpdateCheckSchedule(
            self.updates, preferences, parent=self
        )
        self.update_schedule.start()
        self._note_launched_version()

    def _note_launched_version(self):
        """After an update, tell once that the About page lists what's new."""
        recorded = self.preferences.load_last_launched_version()
        previous = _version(recorded)
        if not recorded and (
            self.preferences.load_update_last_check()
            or self.preferences.load_update_announced_version()
        ):
            # 0.15.6 and earlier kept no launch record; an update check means
            # an earlier version ran here, unlike a new install.
            previous = (0, 0, 0)
        if previous == _version(APPLICATION_VERSION):
            return
        # Saved before showing: a notice hidden by bubbles off is not replayed.
        self.preferences.save_last_launched_version(APPLICATION_VERSION)
        if previous is not None and previous < _version(APPLICATION_VERSION):
            QTimer.singleShot(UPDATED_NOTICE_DELAY_MS, self, self._announce_updated)

    def _announce_updated(self):
        shown = self.pet_vm.announce(
            t("about.updated_notice").format(version=APPLICATION_VERSION)
        )
        log_event(
            "application.update",
            "installed_announced",
            version=APPLICATION_VERSION,
            shown=shown,
        )

    def _update_changed(self):
        if self.updates.state == "installing":
            # The app is gone for the silent install, so the pet says it will
            # be back, as the settings window may be closed.
            self.pet_vm.preview_bubble(t("message.0020"))
        self.changed.emit("settings")

    def _update_found(self, version):
        """Tell about each version an automatic check finds only once."""
        if self.preferences.load_update_announced_version() == version:
            return
        self.preferences.save_update_announced_version(version)
        shown = self.pet_vm.announce(t("message.0021").format(version=version))
        log_event("application.update", "announced", version=version, shown=shown)

    def _update_staged(self, version):
        """Tell once that an automatic update waits for the next start."""
        if self.preferences.load_update_announced_version() == version:
            return
        self.preferences.save_update_announced_version(version)
        shown = self.pet_vm.announce(t("update.staged_notice", version=version))
        log_event(
            "application.update", "staged_announced", version=version, shown=shown
        )

    @staticmethod
    def _signature(snapshot):
        return {
            key: value
            for key, value in asdict(snapshot).items()
            if key
            not in {
                "visual_state",
                "active_count",
                "visible",
                "bubbles_snoozed",
                "bubble_snooze_remaining_minutes",
            }
        }

    def _pet_changed(self, snapshot):
        signature = self._signature(snapshot)
        if signature != self._settings_signature:
            self._settings_signature = signature
            self.revision += 1
        self.changed.emit("settings")

    def _sync(self):
        for settings in (
            self.preferences.settings,
            self.pet_vm.pet.preferences.settings,
        ):
            settings.sync()
            if settings.status() != QSettings.Status.NoError:
                raise CommandError(
                    "save_failed",
                    t("message.0535"),
                )

    def appearance(self):
        defaults = {
            "theme": "system",
            "material": "acrylic",
            "lightOpacity": 60,
            "darkOpacity": 36,
            "reduceMotion": False,
        }
        raw = self.preferences.settings.value("settingsUI/appearance", "")
        try:
            saved = json.loads(str(raw))
            self.validate_appearance(saved)
            return saved
        except (ValueError, TypeError, CommandError):
            return defaults

    @staticmethod
    def validate_appearance(value):
        require(
            isinstance(value, dict)
            and set(value)
            == {"theme", "material", "lightOpacity", "darkOpacity", "reduceMotion"}
        )
        choice(value["theme"], ("system", "light", "dark"))
        choice(value["material"], ("acrylic", "mica", "none"))
        integer(value["lightOpacity"], 0, 100)
        integer(value["darkOpacity"], 0, 100)
        boolean(value["reduceMotion"])

    def snapshot(self) -> wire_types.SettingsSnapshot:
        s = self.pet_vm.refresh()
        screens = [
            {"value": "current", "label": t("message.0519")},
            {"value": "primary", "label": t("message.0520")},
        ]
        screens.extend(
            {"value": "specific:" + screen.name(), "label": screen.name()}
            for screen in self.pet_vm.available_screens()
        )
        mode = self.pet_vm.pet.auto_movement_screen_mode
        name = self.pet_vm.pet.auto_movement_screen_name
        hotkey = self.preferences.load_pet_click_through_hotkey()
        controls = [
            control(
                "width",
                t("message.0521"),
                s.pet_width,
                "pet_size",
                min=0,
                max=len(PET_WIDTH_OPTIONS) - 1,
                step=1,
                options=[dict(value=v, label=size_label(v)) for v in PET_WIDTH_OPTIONS],
                presets=[
                    dict(value=DEFAULT_PET_WIDTH, label=t("message.0279")),
                    dict(value=FRAME_WIDTH, label=t("message.0554")),
                    dict(value=CODEX_MAX_PET_WIDTH, label=t("message.0555")),
                    dict(value=EXTENDED_MAX_PET_WIDTH, label=t("message.0556")),
                ],
                description=t("message.0028"),
                groupId="pet_appearance",
                group=t("message.0536"),
            ),
            control(
                "always_on_top",
                t("message.0522"),
                s.always_on_top,
                groupId="pet_appearance",
                group=t("message.0536"),
            ),
            control(
                "opacity",
                t("message.0523"),
                s.opacity_percent,
                "range",
                min=50,
                max=100,
                step=5,
                unit="%",
                groupId="pet_appearance",
                group=t("message.0536"),
            ),
            control(
                "shadow",
                t("message.0524"),
                s.shadow,
                groupId="pet_appearance",
                group=t("message.0536"),
            ),
            control(
                "fade",
                t("message.0525"),
                s.fade,
                groupId="pet_appearance",
                group=t("message.0536"),
                description=t("message.0537"),
            ),
            control(
                "activity_labels",
                t("message.0526"),
                s.activity_labels_enabled,
                groupId="pet_appearance",
                group=t("message.0536"),
            ),
            control(
                "idle",
                t("message.0527"),
                s.idle_activities_enabled,
                groupId="pet_behavior",
                group=t("message.0538"),
            ),
            control(
                "movement",
                t("message.0528"),
                s.auto_movement_enabled,
                groupId="pet_behavior",
                group=t("message.0538"),
            ),
            control(
                "screen",
                t("message.0529"),
                f"specific:{name}" if mode == "specific" else mode,
                "select",
                options=screens,
                groupId="pet_behavior",
                group=t("message.0538"),
            ),
            control(
                "look",
                t("message.0530"),
                s.look_range,
                "range",
                min=LOOK_RANGE_MIN,
                max=LOOK_RANGE_MAX,
                step=20,
                unit="px",
                groupId="pet_behavior",
                group=t("message.0538"),
            ),
            control(
                "click_through",
                t("click_through.pet"),
                s.click_through,
                groupId="pet_behavior",
                group=t("message.0538"),
                description=t("click_through.pet_description"),
            ),
            control(
                "click_through_hotkey",
                t("click_through.hotkey"),
                hotkey,
                "hotkey",
                status=hotkey_status(self.click_through, PET_LOCK, hotkey),
                groupId="pet_behavior",
                group=t("message.0538"),
                description=t("click_through.hotkey_description"),
            ),
        ]
        if self.assistant:
            controls.append(
                control(
                    "click_through_bubbles",
                    t("click_through.bubbles"),
                    s.click_through_bubbles,
                    groupId="pet_behavior",
                    group=t("message.0538"),
                    description=t("click_through.bubbles_description"),
                )
            )
        # Without a saved custom theme the "custom" mode falls back to the pet's
        # own design, so say so instead of letting the choice look ignored.
        has_custom = self.pet_vm.pet.custom_bubble_theme is not None
        bubble_controls = [
            control(
                "bubble_theme",
                t("message.0531"),
                s.bubble_theme_mode,
                "select",
                options=[
                    dict(value=v, label=label)
                    for v, label in (
                        ("character", t("message.0558")),
                        ("default", t("message.0559")),
                        (
                            "custom",
                            t("message.0562") if has_custom else t("message.0563"),
                        ),
                    )
                ],
                description=(
                    None
                    if has_custom
                    else t("message.0548")
                    + (t("message.0557") if s.bubble_theme_mode == "custom" else "")
                ),
                groupId="bubble_design",
                group=t("message.0539"),
            )
        ]
        if self.assistant:
            # Turning bubbles off hides every card, so their size and timing
            # controls are shown inactive while keeping the stored values.
            muted = not s.bubbles_enabled
            bubble_controls += [
                control(
                    "bubbles",
                    t("message.0540"),
                    s.bubbles_enabled,
                    groupId="bubble_display",
                    group=t("message.0544"),
                ),
                control(
                    "bubble_scale",
                    t("message.0541"),
                    s.bubble_scale,
                    "range",
                    min=80,
                    max=140,
                    step=10,
                    unit="%",
                    disabled=muted,
                    groupId="bubble_display",
                    group=t("message.0544"),
                ),
                control(
                    "bubble_duration",
                    t("message.0542"),
                    s.bubble_duration_seconds,
                    "range",
                    min=5,
                    max=60,
                    step=1,
                    unit=t("message.0545"),
                    disabled=muted,
                    groupId="bubble_timing",
                    group=t("message.0546"),
                ),
            ]
            for key, value in asdict(s.bubble_duration_policy).items():
                if key != "common":
                    label = {
                        "result": t("message.0549"),
                        "general": t("message.0550"),
                        "schedule": t("message.0034"),
                        "completion": t("message.0551"),
                    }[key]
                    bubble_controls.append(
                        control(
                            "duration:" + key,
                            label,
                            value,
                            "optional_number",
                            min=5,
                            max=60,
                            step=1,
                            unit=t("message.0545"),
                            effectiveValue=s.bubble_duration_policy.seconds(key),
                            fallbackLabel=(
                                t("message.0560")
                                if key == "completion"
                                else t("message.0561")
                            ),
                            disabled=muted,
                            groupId="bubble_timing",
                            group=t("message.0546"),
                        )
                    )
        startup = self.settings_vm.startup_status()
        return dict(
            language=self.languages.state(),
            version=APPLICATION_VERSION,
            revision=self.revision,
            epoch=self.account_epoch,
            edition="pet-assistant" if self.assistant else "pet-only",
            pet=wire(s),
            controls=controls,
            bubbleControls=bubble_controls,
            doubleClickAction=self.preferences.load_double_click_action(),
            appearance=self.appearance(),
            startup=dict(
                supported=startup.supported,
                enabled=startup.enabled,
                matches_current_app=startup.matches_current_app,
            ),
            animations=[
                dict(label=label, value=value) for label, value in ACTION_TEST_STATES
            ],
            update=cast(
                wire_types.UpdateState,
                dict(
                    self.updates.snapshot(),
                    auto_check=self.preferences.load_update_auto_check(),
                    auto_install=self.preferences.load_update_auto_install(),
                ),
            ),
            about=cast(
                wire_types.AboutInfo,
                about_info("pet-assistant" if self.assistant else "pet-only"),
            ),
        )

    def catalog(self) -> wire_types.PetCatalog:
        sort, order, hidden = self.pet_vm.catalog_preferences()
        entries: list[wire_types.PetCatalogEntry] = []
        duplicate_ids = self.pet_vm.packages.duplicate_ids()
        # Name order is the renderer's base order for both sort modes.
        for entry in order_pet_entries(self.pet_vm.all_pets(), "name"):
            reason = self.pet_vm.packages.deletion_reason(entry, duplicate_ids)
            entries.append(
                dict(
                    id=entry.id,
                    name=entry.display_name,
                    description=entry.description,
                    thumbnail=self._thumbnail(entry),
                    source="user"
                    if entry.directory.absolute().parent
                    == self.pet_vm.packages.user_root
                    else "bundled"
                    if entry.directory.resolve().parent
                    in {
                        (PROJECT_ROOT / "pets").resolve(),
                        (PROJECT_ROOT / "private-pets").resolve(),
                    }
                    else "external",
                    canDelete=not reason,
                    deletionReason=reason,
                )
            )
        require(len(entries) <= 256, t("message.0513"))
        return dict(
            entries=entries,
            order=list(order),
            hidden=list(hidden),
            sort=sort,
            petId=self.pet_vm.snapshot.pet_id,
            revision=self.revision,
        )

    def trash_catalog(self, offset=0) -> wire_types.PetTrashCatalog:
        service = self.pet_vm.packages
        issues = (
            list(service.issues)
            if self.pet_batch.running
            else service.recover(retry_deletes=False)
        )
        rows = service.records()
        entries: list[wire_types.PetTrashEntry] = []
        for record in rows[offset : offset + 50]:
            entry = service.entry(record)
            entries.append(
                dict(
                    trashId=record["trashId"],
                    id=record["petId"],
                    name=record["name"],
                    deletedAt=record["deletedAt"],
                    bytes=service.size(record),
                    state=record["state"],
                    thumbnail=self._thumbnail(entry) if entry else "",
                )
            )
        return dict(
            entries=entries,
            total=len(rows),
            offset=offset,
            totalBytes=sum(service.size(row) for row in rows),
            issues=list(dict.fromkeys(issues)),
            petId=self.pet_vm.snapshot.pet_id,
            revision=self.revision,
        )

    @staticmethod
    def _idle_cell(entry):
        """Return the first idle cell cropped to its content plus an 8px margin."""
        with Image.open(entry.spritesheet_path, formats=PET_IMAGE_FORMATS) as atlas:
            frame = atlas.crop((0, 0, FRAME_WIDTH, FRAME_HEIGHT)).convert("RGBA")
        alpha_bounds = frame.getchannel("A").getbbox()
        content_bounds = alpha_bounds or (0, 0, FRAME_WIDTH, FRAME_HEIGHT)
        left, top, right, bottom = content_bounds
        crop_bounds = (
            max(0, left - 8),
            max(0, top - 8),
            min(FRAME_WIDTH, right + 8),
            min(FRAME_HEIGHT, bottom + 8),
        )
        return frame.crop(crop_bounds), content_bounds, crop_bounds

    def _thumbnail(self, entry):
        """Encode a 2x picker thumbnail; a broken package keeps an empty tile."""
        try:
            path = entry.spritesheet_path
            stat = path.stat()
            key = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
            if key in self._thumbnails:
                self._thumbnails.move_to_end(key)
                return self._thumbnails[key]
            image, _, _ = self._idle_cell(entry)
        except (OSError, ValueError):
            return ""
        image.thumbnail(CATALOG_THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
        encoded = BytesIO()
        image.save(encoded, format="PNG", optimize=True)
        result = png_bytes_data(encoded.getvalue())
        self._thumbnails[key] = result
        if len(self._thumbnails) > 256:
            self._thumbnails.popitem(last=False)
        return result

    def pet_preview(self, pet_id) -> wire_types.PetPreview:
        pet_id = text(pet_id, 200)
        entry = next(
            (
                candidate
                for candidate in self.pet_vm.all_pets()
                if candidate.id == pet_id
            ),
            None,
        )
        if entry is None:
            raise CommandError("pet_missing", t("message.0532"))
        try:
            cropped, content_bounds, crop_bounds = self._idle_cell(entry)
        except (OSError, ValueError) as error:
            raise CommandError("pet_preview_failed", t("message.0543")) from error
        encoded = BytesIO()
        cropped.save(encoded, format="PNG")
        crop_left, crop_top, crop_right, crop_bottom = crop_bounds
        content_left, content_top, content_right, content_bottom = content_bounds
        return dict(
            petId=entry.id,
            revision=self.revision,
            image=png_bytes_data(encoded.getvalue()),
            sourceSize=dict(width=FRAME_WIDTH, height=FRAME_HEIGHT),
            contentBounds=dict(
                x=content_left,
                y=content_top,
                width=content_right - content_left,
                height=content_bottom - content_top,
            ),
            cropBounds=dict(
                x=crop_left,
                y=crop_top,
                width=crop_right - crop_left,
                height=crop_bottom - crop_top,
            ),
        )

    def editor(self) -> wire_types.BubbleEditor:
        state = self.pet_vm.bubble_editor_state
        # "standard" plus the frame this pet package ships, if any.
        frame_styles = ["standard"]
        for style in (
            frame_style_for(self.pet_vm.snapshot.pet_id),
            state.theme.frame_style,
        ):
            if style not in frame_styles and registered_frame(style) is not None:
                frame_styles.append(style)
        return dict(
            theme=cast(wire_types.SpeechBubbleTheme, asdict(state.theme)),
            packageTheme=cast(
                wire_types.SpeechBubbleTheme, asdict(state.package_theme)
            ),
            revision=self.revision,
            petId=self.pet_vm.snapshot.pet_id,
            elements=[
                dict(id=e.reference, name=e.name, kind=e.kind)
                for e in state.registry.elements
            ],
            presets=themes.bubble_theme_presets(),
            choices={
                "shape": _choice_order(themes.BUBBLE_SHAPES),
                "tail": _choice_order(themes.BUBBLE_TAILS),
                "gradient": _choice_order(themes.BUBBLE_GRADIENTS),
                "border_style": _choice_order(themes.BUBBLE_BORDER_STYLES),
                "header_style": _choice_order(themes.BUBBLE_HEADER_STYLES),
                "frame_style": frame_styles,
                "pattern": _choice_order(themes.BUILTIN_BUBBLE_PATTERNS),
                "ornament_left": _choice_order(themes.BUILTIN_BUBBLE_ORNAMENTS),
                "ornament_right": _choice_order(themes.BUILTIN_BUBBLE_ORNAMENTS),
                "stack_alignment": ["center", "left"],
                "text_alignment": ["center", "left"],
            },
            # The same bounds normalization applies, so the editor never shows a
            # value that differs from what preview and save will use.
            limits={
                key: dict(
                    min=minimum,
                    max=maximum,
                    step=0.05 if isinstance(minimum, float) else 1,
                    unit=THEME_UNITS.get(key, ""),
                )
                for key, (minimum, maximum) in themes.BUBBLE_THEME_LIMITS.items()
            },
            labels={
                "frame_style": {
                    style: t("message.0279")
                    if style == "standard"
                    else t("message.0552")
                    for style in frame_styles
                }
            },
        )

    def _theme(self, data):
        require(
            isinstance(data, dict)
            and set(data) == set(asdict(themes.DEFAULT_BUBBLE_THEME))
        )
        for key, value in asdict(themes.DEFAULT_BUBBLE_THEME).items():
            raw = data[key]
            if isinstance(value, bool):
                boolean(raw)
            elif isinstance(value, (float, int)):
                require(type(raw) in (float, int) and -10000 < raw < 10000)
            else:
                text(raw, 100)
        return themes.bubble_theme_from_dict(data)

    def _context(self, args):
        require(
            args.get("epoch", self.account_epoch) == self.account_epoch,
            t("message.0514"),
            "stale_context",
        )
        require(
            args.get("petId") == self.pet_vm.snapshot.pet_id,
            t("message.0515"),
            "stale_context",
        )
        require(
            args.get("revision") == self.revision,
            t("message.0516"),
            "conflict",
        )

    def execute(self, method, args):
        require(isinstance(args, dict))
        if method == "pet.trash.batch.start":
            return self.pet_batch.start(args)
        if method == "pet.trash.batch.status":
            return self.pet_batch.status(args)
        if method == "pet.trash.batch.cancel":
            return self.pet_batch.cancel(args)
        if self.pet_batch.running and method in {
            "settings.set",
            "pet.select",
            "pet.import.commit",
            "pet.catalog.save",
            "pet.action",
            "bubble.save",
            "bubble.reset",
            "element.delete",
            "pet.trash.move",
            "pet.trash.restore",
            "pet.trash.delete",
            "pet.trash.empty",
        }:
            raise CommandError(
                "batch_busy",
                t("message.0533"),
            )
        if method in {"language.list", "language.refresh"}:
            return (
                self.languages.refresh()
                if method.endswith("refresh")
                else [pack.info() for pack in self.languages.packs]
            )
        if method == "language.bootstrap":
            return self.languages.active.bootstrap(
                "pet-assistant" if self.assistant else "pet-only"
            )
        if method == "language.open_folder":
            if self.languages.root is None:
                raise CommandError("unsupported", t("language.invalid"))
            self.languages.root.mkdir(parents=True, exist_ok=True)
            return dict(
                opened=QDesktopServices.openUrl(
                    QUrl.fromLocalFile(str(self.languages.root))
                )
            )
        if method == "language.copy":
            return self._copy_language(args)
        if method == "settings.set" and args.get("key") == "languagePack":
            return self._save_language(args)
        if method == "settings.snapshot":
            return self.snapshot()
        if method == "pet.catalog":
            return self.catalog()
        if method == "pet.trash.list":
            try:
                return self.trash_catalog(integer(args.get("offset", 0), 0, 1000000))
            except (PetTrashError, OSError) as error:
                raise CommandError(
                    "pet_trash_failed",
                    str(error)
                    if isinstance(error, PetTrashError)
                    else t("message.0553"),
                ) from error
        if method == "pet.preview":
            return self.pet_preview(args.get("petId"))
        if method == "pet.import.cancel":
            self.cancel_pet_import(text(args.get("token"), 80))
            return dict(cancelled=True)
        if method == "pet.import.commit":
            return self._commit_pet_import(args)
        if method.startswith("pet.import."):
            try:
                if method in {"pet.import.start", "pet.import.installed.start"}:
                    require(not self.pet_batch.running, t("message.0518"), "batch_busy")
                if method == "pet.import.start":
                    return self.pet_import.start(command=text(args.get("command"), 512))
                if method == "pet.import.status":
                    return self.pet_import.status(text(args.get("jobId"), 80))
                if method == "pet.import.stop":
                    if text(args.get("jobId"), 80) == self.pet_import.job_id:
                        self.cancel_pet_import()
                    return dict(cancelled=True)
                if method == "pet.import.installed":
                    return self.pet_import.installed.scan()
                if method == "pet.import.installed.thumbnail":
                    return dict(
                        image=png_bytes_data(
                            self.pet_import.installed.thumbnail(
                                text(args.get("id"), 80)
                            )
                        )
                    )
                if method == "pet.import.installed.start":
                    return self.pet_import.start(
                        path=self.pet_import.installed.path(text(args.get("id"), 80))
                    )
                if method == "pet.import.preview":
                    data, count, interval = self.pet_importer.preview(
                        text(args.get("token"), 80), text(args.get("state"), 30)
                    )
                    require(len(data) < 2 * 1024 * 1024, code="response_limit")
                    return dict(
                        image="data:image/png;base64,"
                        + base64.b64encode(data).decode("ascii"),
                        frames=count,
                        interval=interval,
                    )
            except ValueError as error:
                raise CommandError("pet_import_invalid", str(error)) from error
        if method == "bubble.editor":
            return self.editor()
        if method == "bubble.render":
            return self._render_bubble(args)
        if method == "settings.set":
            self._set_setting(args)
        elif method in {
            "pet.trash.move",
            "pet.trash.restore",
            "pet.trash.delete",
            "pet.trash.empty",
        }:
            return self._change_pet_trash(method, args)
        elif method == "pet.select":
            self._select_pet(args)
        elif method == "pet.catalog.save":
            return self._save_pet_catalog(args)
        elif method == "bubble.save":
            self._context(args)
            self.pet_vm.save_custom_bubble_theme(self._theme(args.get("theme")))
        elif method == "bubble.reset":
            self._context(args)
            self.pet_vm.reset_custom_bubble_theme()
        elif method == "pet.action":
            self._pet_action(args)
        elif method == "update.check":
            self.updates.check()
            return dict(pending=True)
        elif method == "update.download":
            update = self.updates.snapshot()
            require(
                update["can_install"] and update["state"] in ("available", "error"),
                t("message.0564"),
            )
            self.updates.download()
            return dict(pending=True)
        elif method == "update.apply":
            require(self.updates.state == "staged", t("message.0564"))
            self.updates.apply_now()
            return dict(pending=True)
        elif method == "update.cancel":
            self.updates.cancel()
            return dict(pending=True)
        elif method == "update.open":
            url = self.updates.page_url
            require(release_url_kind(url) is not None, t("message.0565"))
            require(QDesktopServices.openUrl(QUrl(url)), t("message.0566"))
            return dict(opened=True)
        elif method == "about.open_licenses":
            folder = licenses_folder()
            require(folder is not None, t("about.licenses_missing"))
            require(
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))),
                t("about.licenses_open_failed"),
            )
            return dict(opened=True)
        elif method == "element.delete":
            reference = text(args.get("reference"))
            require(
                self.pet_vm.bubble_editor_state.registry.delete(reference),
                t("message.0567"),
            )
            self.pet_vm.refresh_bubble_elements()
        elif self.assistant:
            return self.assistant.execute(method, args)
        else:
            raise CommandError("unsupported", t("message.0568"))
        self.revision += 1
        self.changed.emit("settings")
        self._sync()
        return dict(saved=True, snapshot=self.snapshot())

    def _commit_pet_import(self, args):
        try:
            prepared = self.pet_importer.prepared
            ids = {entry.id for entry in self.pet_vm.all_pets()}
            require(
                len(ids) < 256 or (prepared and prepared.pet_id in ids),
                t("message.0534"),
            )
            if prepared:
                trashed = next(
                    (
                        row
                        for row in self.pet_vm.packages.records()
                        if row["petId"] == prepared.pet_id
                    ),
                    None,
                )
                if trashed:
                    return dict(
                        saved=False,
                        restoreRequired=True,
                        trashId=trashed["trashId"],
                        id=trashed["petId"],
                        name=trashed["name"],
                        snapshot=self.snapshot(),
                    )
            result = self.pet_importer.commit(
                text(args.get("token"), 80), args.get("name")
            )
        except PetImportError as error:
            raise CommandError("pet_import_invalid", str(error)) from error
        if not result.already_exists:
            self.revision += 1
            self.changed.emit("settings")
        return dict(
            id=result.id,
            name=result.name,
            alreadyExists=result.already_exists,
            saved=True,
            snapshot=self.snapshot(),
        )

    def _render_bubble(self, args):
        theme = self._theme(args.get("theme"))
        preview = BubbleThemePreview(
            self.pet_vm.bubble_editor_state.registry,
            sample=choice(args.get("sample", "notice"), ("notice", "project")),
        )
        try:
            preview.resize(600, 260)
            preview.set_theme(theme)
            return dict(image=png_data(preview.grab()), theme=asdict(theme))
        finally:
            preview.deleteLater()

    def _set_setting(self, args):
        self._context(args)
        key, value = (text(args.get("key")), args.get("value"))
        actions = {
            "always_on_top": self.pet_vm.set_always_on_top,
            "activity_labels": self.pet_vm.set_activity_labels_enabled,
            "shadow": self.pet_vm.set_shadow,
            "fade": self.pet_vm.set_fade,
            "idle": self.pet_vm.set_idle_activities_enabled,
            "movement": self.pet_vm.set_auto_movement_enabled,
            "click_through": self.pet_vm.set_click_through,
        }
        if self.assistant:
            actions["bubbles"] = self.pet_vm.set_bubbles_enabled
            actions["click_through_bubbles"] = self.pet_vm.set_click_through_bubbles
        if key in actions:
            actions[key](boolean(value))
        elif key == "opacity":
            self.pet_vm.set_opacity(integer(value, 50, 100))
        elif key == "width":
            self.pet_vm.set_width(choice(value, PET_WIDTH_OPTIONS))
        elif key == "look":
            self.pet_vm.set_look_range(integer(value, LOOK_RANGE_MIN, LOOK_RANGE_MAX))
        elif key == "screen":
            allowed = [
                row["value"]
                for row in next(
                    (c for c in self.snapshot()["controls"] if c["key"] == "screen")
                )["options"]
            ]
            choice(value, allowed)
            self.pet_vm.set_auto_movement_screen(
                "specific", value[9:]
            ) if value.startswith(
                "specific:"
            ) else self.pet_vm.set_auto_movement_screen(value)
        elif key == "bubble_theme":
            self.pet_vm.set_bubble_theme(choice(value, themes.BUBBLE_THEME_MODES))
        elif key == "bubble_scale" and self.assistant:
            self.pet_vm.set_bubble_scale(integer(value, 80, 140))
        elif key == "bubble_duration" and self.assistant:
            self.pet_vm.set_bubble_duration(integer(value, 5, 60))
        elif key.startswith("duration:") and self.assistant:
            choice(key[9:], ("result", "general", "schedule", "completion"))
            self.pet_vm.set_bubble_duration_override(
                key[9:], None if value is None else integer(value, 5, 60)
            )
        elif key == "appearance":
            self.validate_appearance(value)
            self.preferences.settings.setValue(
                "settingsUI/appearance", json.dumps(value)
            )
        elif key.startswith("appearance:"):
            field = choice(key[11:], self.appearance())
            appearance = {**self.appearance(), field: value}
            self.validate_appearance(appearance)
            self.preferences.settings.setValue(
                "settingsUI/appearance", json.dumps(appearance)
            )
        elif key == "click_through_hotkey":
            value = hotkey_text(value)
            if self.click_through is None:
                raise CommandError("unsupported", t("hotkey.unavailable"))
            require(
                not self.click_through.taken(PET_LOCK, value), t("hotkey.duplicate")
            )
            self.click_through.set_pet_hotkey(value)
        elif key == "double_click_action":
            self.preferences.save_double_click_action(
                choice(value, DOUBLE_CLICK_ACTIONS)
            )
        elif key == "update_auto_install":
            self.preferences.save_update_auto_install(boolean(value))
            self.updates.set_auto_install(boolean(value))
        elif key == "update_auto_check":
            self.preferences.save_update_auto_check(boolean(value))
            self.update_schedule.set_enabled(boolean(value))
        elif key == "startup":
            result = self.settings_vm.set_startup_enabled(boolean(value))
            require(
                result.enabled == value,
                t("message.0569"),
                "startup_failed",
            )
        else:
            raise CommandError("unsupported", t("message.0570"))

    def _change_pet_trash(self, method, args):
        self._context(args)
        require(
            args.get("epoch") == self.account_epoch,
            t("message.0514"),
            "stale_context",
        )
        service = self.pet_vm.packages
        result = {}
        try:
            if method == "pet.trash.move":
                record = self.pet_vm.trash_pet(
                    text(args.get("id"), 200),
                    text(args.get("replacementId", ""), 200),
                )
                result = dict(trashId=record["trashId"], name=record["name"])
            elif method == "pet.trash.restore":
                record = service.restore(text(args.get("trashId"), 32))
                result = dict(id=record["petId"], name=record["name"])
            elif method == "pet.trash.delete":
                service.delete(text(args.get("trashId"), 32))
            else:
                deleted, failed = (0, [])
                for record in service.records():
                    try:
                        service.delete(record["trashId"])
                        deleted += 1
                    except (PetTrashError, OSError):
                        failed.append(record["trashId"])
                result = dict(deleted=deleted, failed=failed)
        except (PetTrashError, OSError) as error:
            self.revision += 1
            self.changed.emit("settings")
            raise CommandError(
                "pet_trash_failed",
                str(error) if isinstance(error, PetTrashError) else t("message.0547"),
            ) from error
        self.revision += 1
        self.changed.emit("settings")
        self._sync()
        return dict(saved=True, snapshot=self.snapshot(), **result)

    def _save_pet_catalog(self, args):
        self._context(args)
        ids = {entry.id for entry in self.pet_vm.all_pets()}
        order, hidden = (args.get("order"), args.get("hidden"))
        require(
            isinstance(order, list)
            and isinstance(hidden, list)
            and (len(order) <= 256)
            and (len(hidden) <= 256)
        )
        require(all((isinstance(item, str) and item in ids for item in order + hidden)))
        require(
            len(set(order)) == len(order) and self.pet_vm.snapshot.pet_id not in hidden
        )
        previous = self.pet_vm.catalog_preferences()
        try:
            self.pet_vm.save_catalog_preferences(
                choice(args.get("sort"), ("name", "custom")), order, hidden
            )
            self._sync()
        except CommandError:
            self.pet_vm.save_catalog_preferences(*previous)
            try:
                self._sync()
            except CommandError:
                pass
            self.revision += 1
            self.changed.emit("settings")
            raise
        self.revision += 1
        self.changed.emit("settings")
        return dict(saved=True, snapshot=self.snapshot())

    def _pet_action(self, args):
        action = text(args.get("action"))
        actions = {
            "recenter": self.pet_vm.recenter,
            "recall": self.pet_vm.move_to_auto_movement_screen,
            "movement_test": self.pet_vm.test_movement,
            "visibility": self.pet_vm.toggle_visibility,
            "restore": self.pet_vm.restore_agent_display,
            "folder": self.pet_vm.open_pet_folder,
            "resume": self.pet_vm.resume_bubbles,
            "durations_reset": self.pet_vm.reset_bubble_durations,
        }
        if self.assistant:
            actions["duration_overrides_reset"] = (
                self.pet_vm.clear_bubble_duration_overrides
            )
        if action == "animation":
            self.pet_vm.test_animation(
                choice(args.get("state"), {value for _, value in ACTION_TEST_STATES})
            )
        elif action == "preview":
            self.pet_vm.preview_bubble(t("message.0253"))
        elif action == "snooze" and self.assistant:
            self.pet_vm.snooze_bubbles(
                choice(args.get("minutes"), (15, 30, 60)) * 60000
            )
        else:
            require(action in actions)
            actions[action]()

    def _select_pet(self, args):
        self._context(args)
        pet_id = text(args.get("id"))
        require(pet_id in {entry.id for entry in self.pet_vm.all_pets()})
        sort, order, hidden = self.pet_vm.catalog_preferences()
        if pet_id in hidden:
            self.pet_vm.save_catalog_preferences(sort, order, hidden - {pet_id})
        changed = self.pet_vm.change_pet(pet_id)
        if not changed and pet_id in hidden:
            self.pet_vm.save_catalog_preferences(sort, order, hidden)
        require(changed, t("message.0517"), "pet_failed")

    def cancel_pet_import(self, token=None):
        if token is None or (
            self.pet_importer.prepared and self.pet_importer.prepared.token == token
        ):
            self.pet_import.cancel()
        self.pet_importer.cancel(token)
        if self.pet_importer.prepared is None:
            self.import_timer.stop()

    def prepare_pet_import(self, path):
        require(not self.pet_batch.running, t("message.0518"), "batch_busy")
        self.cancel_pet_import()
        try:
            prepared = self.pet_importer.prepare(path)
        except PetImportError as error:
            raise CommandError("pet_import_invalid", str(error)) from error
        self.import_timer.start(IMPORT_LIFETIME_SECONDS * 1000)
        return dict(
            token=prepared.token,
            name=prepared.name,
            thumbnail=png_bytes_data(prepared.thumbnail),
            spriteVersion=prepared.version,
        )

    def import_element(self, path, kind):
        choice(kind, ("pattern", "ornament", "photo", "frame", "sticker"))
        try:
            element = self.pet_vm.bubble_editor_state.registry.import_image(path, kind)
        except BubbleElementError as error:
            # The registry explains size/format problems; keep that message
            # instead of the host's generic ValueError fallback.
            raise CommandError("element_invalid", str(error)) from error
        self.pet_vm.refresh_bubble_elements()
        self.revision += 1
        self.changed.emit("settings")
        return dict(id=element.reference)

    def _save_language(self, args):
        self._context(args)
        try:
            pack = self.languages.select(text(args.get("value"), 80))
        except ValueError as error:
            raise CommandError("invalid_argument", t("language.invalid")) from error
        settings = self.preferences.settings
        existed = settings.contains("app/languagePack")
        previous = self.preferences.load_language_pack()
        settings.setValue("app/languagePack", pack.id)
        try:
            self._sync()
        except CommandError:
            if existed:
                settings.setValue("app/languagePack", previous)
            else:
                settings.remove("app/languagePack")
            settings.sync()
            raise
        self.languages.selected = pack.id
        self.revision += 1
        self.changed.emit("settings")
        return dict(saved=True, snapshot=self.snapshot())

    def _copy_language(self, args):
        """Copy the selected pack into a new editable user pack and select it."""
        self._context(args)
        if self.languages.root is None:
            raise CommandError("unsupported", t("language.invalid"))
        source_id = self.languages.selected or self.languages.active.pack_id
        source = self.languages.find(source_id)
        try:
            pack_id = copy_pack(
                self.languages,
                source_id,
                name=t("language.copy_name", name=source.name if source else source_id),
                author=t("language.copy_author"),
            )
        except ValueError as error:
            raise CommandError(
                "invalid_argument",
                t(
                    "language.copy_limit"
                    if str(error) == "too_many_packs"
                    else "language.invalid"
                ),
            ) from error
        except OSError as error:
            log_event(
                "settings.language",
                "copy_failed",
                level="warning",
                error=type(error).__name__,
            )
            raise CommandError("save_failed", t("language.copy_failed")) from error
        # A failed save keeps the new folder; it stays selectable from the list.
        result = self._save_language({**args, "value": pack_id})
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.languages.root / pack_id)))
        return dict(
            result, id=pack_id, packs=[pack.info() for pack in self.languages.packs]
        )
