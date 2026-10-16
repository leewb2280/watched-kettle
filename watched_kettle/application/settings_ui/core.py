"""Common settings adapter. Does not import assistant services or storage."""

from __future__ import annotations

from collections import OrderedDict
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
from watched_kettle.application.update_check import (
    FOUND_MESSAGE,
    INSTALLING_MESSAGE,
    UpdateCheckSchedule,
    release_url_kind,
)
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
from watched_kettle.pet.importer import (
    IMPORT_LIFETIME_SECONDS,
    PetImportError,
    PetImporter,
)
from watched_kettle.pet.trash import PetTrashError
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
# Twice the largest CSS tile (110x120) so picker thumbnails stay sharp at 200%.
CATALOG_THUMBNAIL_SIZE = (220, 240)
PET_SIZE_DESCRIPTION = (
    "원본 스프라이트 셀은 192×208px입니다. 80~224px는 표준 크기, "
    "256~352px는 큰 화면용 확장 크기입니다."
)


def _choice_order(values):
    """Stable editor order with the neutral "none"/"standard" option first."""
    return sorted(values, key=lambda value: (value not in {"none", "standard"}, value))


def png_data(pixmap):
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    require(pixmap.save(buffer, "PNG"), "미리보기 이미지를 만들지 못했습니다.")
    require(data.size() <= 512 * 1024, code="response_limit")
    return "data:image/png;base64," + bytes(data.toBase64()).decode("ascii")


def png_bytes_data(data):
    require(len(data) <= 512 * 1024, code="response_limit")
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def control(key, label, value, kind="bool", **extras):
    return dict(key=key, label=label, value=value, kind=kind, **extras)


class CoreSettingsAdapter(QObject):
    changed = Signal(str)

    def __init__(self, pet_vm, settings_vm, preferences, app, parent=None):
        super().__init__(parent)
        self.pet_vm, self.settings_vm = pet_vm, settings_vm
        self.preferences, self.app = preferences, app
        self.revision = 0
        self.account_epoch = 0
        self.assistant = None
        self.pet_batch = PetBatchController(self)
        self._thumbnails = OrderedDict()
        self.pet_importer = PetImporter(self.pet_vm.pet.user_pets_root)
        self.import_timer = QTimer(self)
        self.import_timer.setSingleShot(True)
        self.import_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.import_timer.timeout.connect(self.cancel_pet_import)
        self._settings_signature = self._signature(self.pet_vm.snapshot)
        self.pet_vm.snapshot_changed.connect(self._pet_changed)
        self.updates = self.settings_vm.updates
        self.updates.changed.connect(self._update_changed)
        self.updates.found.connect(self._update_found)
        self.update_schedule = UpdateCheckSchedule(
            self.updates, preferences, parent=self
        )
        self.update_schedule.start()

    def _update_changed(self):
        if self.updates.state == "installing":
            # The app is gone for the silent install, so the pet says it will
            # be back, as the settings window may be closed.
            self.pet_vm.preview_bubble(INSTALLING_MESSAGE)
        self.changed.emit("settings")

    def _update_found(self, version):
        """Tell about each version an automatic check finds only once."""
        if self.preferences.load_update_announced_version() == version:
            return
        self.preferences.save_update_announced_version(version)
        shown = self.pet_vm.announce(FOUND_MESSAGE.format(version=version))
        log_event("application.update", "announced", version=version, shown=shown)

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
                    "화면에 적용했지만 저장하지 못했습니다. 권한과 디스크 상태를 확인한 뒤 다시 시도하세요.",
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

    def snapshot(self):
        s = self.pet_vm.refresh()
        screens = [
            {"value": "current", "label": "펫이 있는 화면"},
            {"value": "primary", "label": "주 화면"},
        ]
        screens.extend(
            {"value": "specific:" + screen.name(), "label": screen.name()}
            for screen in self.pet_vm.available_screens()
        )
        mode = self.pet_vm.pet.auto_movement_screen_mode
        name = self.pet_vm.pet.auto_movement_screen_name
        controls = [
            control(
                "width",
                "펫 크기",
                s.pet_width,
                "pet_size",
                min=0,
                max=len(PET_WIDTH_OPTIONS) - 1,
                step=1,
                options=[dict(value=v, label=size_label(v)) for v in PET_WIDTH_OPTIONS],
                presets=[
                    dict(value=DEFAULT_PET_WIDTH, label="기본"),
                    dict(value=FRAME_WIDTH, label="원본"),
                    dict(value=CODEX_MAX_PET_WIDTH, label="표준 최대"),
                    dict(value=EXTENDED_MAX_PET_WIDTH, label="확장 최대"),
                ],
                description=PET_SIZE_DESCRIPTION,
                group="외형·표시",
            ),
            control(
                "always_on_top",
                "항상 다른 창 위에 표시",
                s.always_on_top,
                group="외형·표시",
            ),
            control(
                "opacity",
                "펫 불투명도",
                s.opacity_percent,
                "range",
                min=50,
                max=100,
                step=5,
                unit="%",
                group="외형·표시",
            ),
            control("shadow", "발밑 그림자", s.shadow, group="외형·표시"),
            control(
                "fade",
                "나타나고 사라질 때 부드럽게",
                s.fade,
                group="외형·표시",
                description="움직임 줄이기를 켜면 바로 나타나고 사라집니다.",
            ),
            control(
                "activity_labels",
                "펫 아래 현재 활동 표시",
                s.activity_labels_enabled,
                group="외형·표시",
            ),
            control(
                "idle",
                "일정 시간 후 혼자 행동하기",
                s.idle_activities_enabled,
                group="동작·화면",
            ),
            control(
                "movement",
                "가끔 화면 안에서 걷기",
                s.auto_movement_enabled,
                group="동작·화면",
            ),
            control(
                "screen",
                "이동 디스플레이",
                f"specific:{name}" if mode == "specific" else mode,
                "select",
                options=screens,
                group="동작·화면",
            ),
            control(
                "look",
                "마우스 반응 거리",
                s.look_range,
                "range",
                min=LOOK_RANGE_MIN,
                max=LOOK_RANGE_MAX,
                step=20,
                unit="px",
                group="동작·화면",
            ),
        ]
        # Without a saved custom theme the "custom" mode falls back to the pet's
        # own design, so say so instead of letting the choice look ignored.
        has_custom = self.pet_vm.pet.custom_bubble_theme is not None
        bubble_controls = [
            control(
                "bubble_theme",
                "테마 선택",
                s.bubble_theme_mode,
                "select",
                options=[
                    dict(value=v, label=label)
                    for v, label in (
                        ("character", "펫 기본 디자인"),
                        ("default", "공통 기본 디자인"),
                        (
                            "custom",
                            "내가 꾸민 디자인"
                            if has_custom
                            else "내가 꾸민 디자인 (아직 없음)",
                        ),
                    )
                ],
                description=(
                    None
                    if has_custom
                    else "말풍선 꾸미기에서 적용하면 내가 꾸민 디자인이 만들어져요."
                    + (
                        " 지금은 펫 기본 디자인으로 표시됩니다."
                        if s.bubble_theme_mode == "custom"
                        else ""
                    )
                ),
                group="디자인",
            )
        ]
        if self.assistant:
            # Turning bubbles off hides every card, so their size and timing
            # controls are shown inactive while keeping the stored values.
            muted = not s.bubbles_enabled
            bubble_controls += [
                control(
                    "bubbles", "말풍선 알림 표시", s.bubbles_enabled, group="알림 표시"
                ),
                control(
                    "bubble_scale",
                    "말풍선 배율",
                    s.bubble_scale,
                    "range",
                    min=80,
                    max=140,
                    step=10,
                    unit="%",
                    disabled=muted,
                    group="알림 표시",
                ),
                control(
                    "bubble_duration",
                    "공통 표시 시간",
                    s.bubble_duration_seconds,
                    "range",
                    min=5,
                    max=60,
                    step=1,
                    unit="초",
                    disabled=muted,
                    group="표시 시간",
                ),
            ]
            for key, value in asdict(s.bubble_duration_policy).items():
                if key != "common":
                    label = {
                        "result": "실패·중단",
                        "general": "일반 알림",
                        "schedule": "일정 알림",
                        "completion": "완료 강조",
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
                            unit="초",
                            effectiveValue=s.bubble_duration_policy.seconds(key),
                            fallbackLabel=(
                                "완료 기본값" if key == "completion" else "공통 시간"
                            ),
                            disabled=muted,
                            group="표시 시간",
                        )
                    )
        startup = self.settings_vm.startup_status()
        return dict(
            version=APPLICATION_VERSION,
            revision=self.revision,
            epoch=self.account_epoch,
            edition="pet-assistant" if self.assistant else "pet-only",
            pet=wire(s),
            controls=controls,
            bubbleControls=bubble_controls,
            appearance=self.appearance(),
            startup=dict(
                supported=startup.supported,
                enabled=startup.enabled,
                matches_current_app=startup.matches_current_app,
            ),
            animations=[
                dict(label=label, value=value) for label, value in ACTION_TEST_STATES
            ],
            update=dict(
                self.updates.snapshot(),
                auto_check=self.preferences.load_update_auto_check(),
            ),
        )

    def catalog(self):
        sort, order, hidden = self.pet_vm.catalog_preferences()
        entries = []
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
        require(len(entries) <= 256, "펫 목록이 너무 큽니다.")
        return dict(
            entries=entries,
            order=list(order),
            hidden=list(hidden),
            sort=sort,
            petId=self.pet_vm.snapshot.pet_id,
            revision=self.revision,
        )

    def trash_catalog(self, offset=0):
        service = self.pet_vm.packages
        issues = (
            list(service.issues)
            if self.pet_batch.running
            else service.recover(retry_deletes=False)
        )
        rows = service.records()
        entries = []
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
        with Image.open(entry.spritesheet_path) as atlas:
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

    def pet_preview(self, pet_id):
        pet_id = text(pet_id, 200)
        entry = next(
            (
                candidate
                for candidate in self.pet_vm.all_pets()
                if candidate.id == pet_id
            ),
            None,
        )
        require(entry is not None, "펫을 찾을 수 없습니다.", "pet_missing")
        try:
            cropped, content_bounds, crop_bounds = self._idle_cell(entry)
        except (OSError, ValueError) as error:
            raise CommandError(
                "pet_preview_failed", "펫 미리보기 이미지를 읽지 못했습니다."
            ) from error
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

    def editor(self):
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
            theme=asdict(state.theme),
            packageTheme=asdict(state.package_theme),
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
                    style: "기본" if style == "standard" else "캐릭터 장식"
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
            "계정이 변경됐습니다. 다시 불러오세요.",
            "stale_context",
        )
        require(
            args.get("petId") == self.pet_vm.snapshot.pet_id,
            "펫이 변경됐습니다. 다시 불러오세요.",
            "stale_context",
        )
        require(
            args.get("revision") == self.revision,
            "다른 곳에서 설정이 변경됐습니다. 다시 불러오세요.",
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
        if self.pet_batch.running and (
            method
            in {
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
            }
        ):
            raise CommandError(
                "batch_busy",
                "일괄 작업이 진행 중입니다. 완료하거나 남은 작업을 중단하세요.",
            )
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
                    else "휴지통을 읽지 못했습니다. 다시 시도하세요.",
                ) from error
        if method == "pet.preview":
            return self.pet_preview(args.get("petId"))
        if method == "pet.import.cancel":
            self.cancel_pet_import(text(args.get("token"), 80))
            return dict(cancelled=True)
        if method == "pet.import.commit":
            try:
                prepared = self.pet_importer.prepared
                ids = {entry.id for entry in self.pet_vm.all_pets()}
                require(
                    len(ids) < 256 or (prepared and prepared.pet_id in ids),
                    "펫은 최대 256개까지 등록할 수 있습니다.",
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
        if method == "bubble.editor":
            return self.editor()
        if method == "bubble.render":
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
        if method == "settings.set":
            self._context(args)
            key, value = text(args.get("key")), args.get("value")
            actions = {
                "always_on_top": self.pet_vm.set_always_on_top,
                "activity_labels": self.pet_vm.set_activity_labels_enabled,
                "shadow": self.pet_vm.set_shadow,
                "fade": self.pet_vm.set_fade,
                "idle": self.pet_vm.set_idle_activities_enabled,
                "movement": self.pet_vm.set_auto_movement_enabled,
            }
            if self.assistant:
                actions["bubbles"] = self.pet_vm.set_bubbles_enabled
            if key in actions:
                actions[key](boolean(value))
            elif key == "opacity":
                self.pet_vm.set_opacity(integer(value, 50, 100))
            elif key == "width":
                self.pet_vm.set_width(choice(value, PET_WIDTH_OPTIONS))
            elif key == "look":
                self.pet_vm.set_look_range(
                    integer(value, LOOK_RANGE_MIN, LOOK_RANGE_MAX)
                )
            elif key == "screen":
                allowed = [
                    row["value"]
                    for row in next(
                        c for c in self.snapshot()["controls"] if c["key"] == "screen"
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
            elif key == "update_auto_check":
                self.preferences.save_update_auto_check(boolean(value))
                self.update_schedule.set_enabled(boolean(value))
            elif key == "startup":
                result = self.settings_vm.set_startup_enabled(boolean(value))
                require(
                    result.enabled == value,
                    "자동 시작 등록을 변경하지 못했습니다.",
                    "startup_failed",
                )
            else:
                raise CommandError(
                    "unsupported", "이 구성에서 제공하지 않는 설정입니다."
                )
        elif method in {
            "pet.trash.move",
            "pet.trash.restore",
            "pet.trash.delete",
            "pet.trash.empty",
        }:
            self._context(args)
            require(
                args.get("epoch") == self.account_epoch,
                "계정이 변경됐습니다. 다시 불러오세요.",
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
                    deleted, failed = 0, []
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
                    str(error)
                    if isinstance(error, PetTrashError)
                    else "펫 파일에 접근하지 못했습니다. 저장 공간과 폴더 권한을 확인한 후 다시 시도하세요.",
                ) from error
            self.revision += 1
            self.changed.emit("settings")
            self._sync()
            return dict(saved=True, snapshot=self.snapshot(), **result)
        elif method == "pet.select":
            self._context(args)
            pet_id = text(args.get("id"))
            require(pet_id in {entry.id for entry in self.pet_vm.all_pets()})
            sort, order, hidden = self.pet_vm.catalog_preferences()
            if pet_id in hidden:
                self.pet_vm.save_catalog_preferences(sort, order, hidden - {pet_id})
            changed = self.pet_vm.change_pet(pet_id)
            if not changed and pet_id in hidden:
                self.pet_vm.save_catalog_preferences(sort, order, hidden)
            require(
                changed,
                "펫을 불러오지 못했습니다.",
                "pet_failed",
            )
        elif method == "pet.catalog.save":
            self._context(args)
            ids = {entry.id for entry in self.pet_vm.all_pets()}
            order, hidden = args.get("order"), args.get("hidden")
            require(
                isinstance(order, list)
                and isinstance(hidden, list)
                and len(order) <= 256
                and len(hidden) <= 256
            )
            require(
                all(isinstance(item, str) and item in ids for item in order + hidden)
            )
            require(
                len(set(order)) == len(order)
                and self.pet_vm.snapshot.pet_id not in hidden
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
        elif method == "bubble.save":
            self._context(args)
            self.pet_vm.save_custom_bubble_theme(self._theme(args.get("theme")))
        elif method == "bubble.reset":
            self._context(args)
            self.pet_vm.reset_custom_bubble_theme()
        elif method == "pet.action":
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
                    choice(
                        args.get("state"), {value for _, value in ACTION_TEST_STATES}
                    )
                )
            elif action == "preview":
                self.pet_vm.preview_bubble("새로운 말풍선 디자인을 미리 확인해 보세요")
            elif action == "snooze" and self.assistant:
                self.pet_vm.snooze_bubbles(
                    choice(args.get("minutes"), (15, 30, 60)) * 60000
                )
            else:
                require(action in actions)
                actions[action]()
        elif method == "update.check":
            self.updates.check()
            return dict(pending=True)
        elif method == "update.download":
            update = self.updates.snapshot()
            require(
                update["can_install"] and update["state"] in ("available", "error"),
                "지금은 업데이트를 내려받을 수 없습니다.",
            )
            self.updates.download()
            return dict(pending=True)
        elif method == "update.cancel":
            self.updates.cancel()
            return dict(pending=True)
        elif method == "update.open":
            url = self.updates.page_url
            require(release_url_kind(url) is not None, "공식 배포 페이지가 없습니다.")
            require(
                QDesktopServices.openUrl(QUrl(url)), "배포 페이지를 열지 못했습니다."
            )
            return dict(opened=True)
        elif method == "element.delete":
            reference = text(args.get("reference"))
            require(
                self.pet_vm.bubble_editor_state.registry.delete(reference),
                "이미지를 삭제하지 못했습니다.",
            )
            self.pet_vm.refresh_bubble_elements()
        elif self.assistant:
            return self.assistant.execute(method, args)
        else:
            raise CommandError("unsupported", "이 구성에서 제공하지 않는 명령입니다.")
        self.revision += 1
        self.changed.emit("settings")
        self._sync()
        return dict(saved=True, snapshot=self.snapshot())

    def cancel_pet_import(self, token=None):
        self.pet_importer.cancel(token)
        if self.pet_importer.prepared is None:
            self.import_timer.stop()

    def prepare_pet_import(self, path):
        require(not self.pet_batch.running, "일괄 작업이 진행 중입니다.", "batch_busy")
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
