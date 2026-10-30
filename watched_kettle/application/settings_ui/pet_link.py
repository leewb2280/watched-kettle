"""Settings session for joining installed pets into one pet with several looks.

Transition images the user picks wait here until the pet is made; the result
goes through the importer's prepare and commit, like any imported package.
"""

from __future__ import annotations

import base64
import json
from dataclasses import replace
from io import BytesIO

from PIL import Image

from watched_kettle import settings_protocol as wire
from watched_kettle.config import FRAME_HEIGHT, FRAME_WIDTH
from watched_kettle.application.settings_ui.contracts import (
    CommandError,
    require,
    text,
)
from watched_kettle.localization import t
from watched_kettle.pet.appearance_assets import (
    MAX_APPEARANCE_IMAGE_BYTES,
    MAX_APPEARANCE_VARIANTS,
    parse_appearance_set,
)
from watched_kettle.pet.catalog import order_pet_entries
from watched_kettle.pet.import_package import read_local
from watched_kettle.pet.importer import PetImportError
from watched_kettle.pet.linker import (
    LinkError,
    LinkLook,
    TransitionStrip,
    has_bubble_design,
    is_joined,
    link_package,
    look_problem,
    transition_strip,
)
from watched_kettle.pet.trash import PetTrashError

FADE_PREVIEW_FRAMES = 8
FADE_PREVIEW_INTERVAL = 50
PREVIEW_SIZE = (FRAME_WIDTH // 2, FRAME_HEIGHT // 2)


class PetLinkSession:
    def __init__(self, adapter):
        self.adapter = adapter
        # (from look id, to look id) -> TransitionStrip. A look id is an
        # installed pet id, or "<joined pet id>#<look id>" for a loaded pet.
        self.strips = {}
        # Looks of the joined pet being edited: look id -> (folder, image).
        self.loaded = {}

    def reset(self):
        self.strips.clear()
        self.loaded.clear()

    def sources(self) -> wire.PetLinkSources:
        rows: list[wire.PetLinkSource] = []
        for entry in order_pet_entries(self.adapter.pet_vm.all_pets(), "name"):
            rows.append(
                dict(
                    id=entry.id,
                    name=entry.display_name,
                    thumbnail=self.adapter._thumbnail(entry),
                    problem=look_problem(entry.spritesheet_path),
                    hasBubble=has_bubble_design(entry.directory),
                    joined=is_joined(entry.directory),
                )
            )
        return dict(
            entries=rows,
            maxLooks=MAX_APPEARANCE_VARIANTS,
            transitions=self.transitions(),
        )

    def transitions(self) -> list[wire.PetLinkTransition]:
        return [
            dict(
                fromPetId=source,
                toPetId=target,
                frames=strip.frames,
                intervalMs=strip.interval,
                resized=strip.resized,
            )
            for (source, target), strip in self.strips.items()
        ]

    def add_transition(self, args, paths) -> wire.PetLinkTransition:
        source, target = self._pair(args)
        require(isinstance(paths, list) and paths, t("pet.link.transition_format"))
        try:
            strip = transition_strip([text(path, 32768) for path in paths])
        except LinkError as error:
            raise CommandError("pet_link_invalid", str(error)) from error
        self.strips[(source, target)] = strip
        return dict(
            fromPetId=source,
            toPetId=target,
            frames=strip.frames,
            intervalMs=strip.interval,
            resized=strip.resized,
        )

    def clear(self, args) -> wire.PetLinkTransitions:
        self.strips.pop(self._pair(args), None)
        return dict(transitions=self.transitions())

    def preview(self, args) -> wire.PetLinkPreview:
        source, target = self._pair(args)
        start, end = self._still(source), self._still(target)
        result: wire.PetLinkPreview = dict(
            start=_data(start), end=_data(end), frames=[], intervalMs=0, kind="fade"
        )
        if (source, target) in self.strips:
            strip = self.strips[(source, target)]
            frames = self._cells(strip)
            result["intervalMs"], result["kind"] = strip.interval, "drawn"
        elif (target, source) in self.strips:
            strip = self.strips[(target, source)]
            frames = self._cells(strip)[::-1]
            result["intervalMs"], result["kind"] = strip.interval, "reversed"
        else:
            frames = [
                Image.blend(start, end, index / (FADE_PREVIEW_FRAMES + 1))
                for index in range(1, FADE_PREVIEW_FRAMES + 1)
            ]
            result["intervalMs"] = FADE_PREVIEW_INTERVAL
        result["frames"] = [_data(frame) for frame in frames]
        return result

    def load(self, args) -> wire.PetLinkDraft:
        """Open a joined pet: its looks, drawn transitions and settings."""
        pet_id = text(args.get("petId"), 200)
        entry = next(
            (e for e in self.adapter.pet_vm.all_pets() if e.id == pet_id), None
        )
        if entry is None or not is_joined(entry.directory):
            raise CommandError("invalid_argument", t("message.0589"))
        manifest = json.loads((entry.directory / "pet.json").read_text("utf-8"))
        spec = parse_appearance_set(manifest)
        self.reset()
        sources: list[wire.PetLinkSource] = []
        looks: list[wire.PetLinkLook] = []
        bubble = has_bubble_design(entry.directory)
        for variant in spec.variants:
            look_id = f"{pet_id}#{variant.id}"
            self.loaded[look_id] = (entry.directory, variant.path)
            looks.append(dict(petId=look_id, label=variant.label))
            sources.append(
                dict(
                    id=look_id,
                    name=variant.label,
                    thumbnail=_data(self._still(look_id)),
                    problem="",
                    hasBubble=bubble,
                    joined=False,
                )
            )
        for transition in spec.transitions:
            data = read_local(
                entry.directory, transition.path, MAX_APPEARANCE_IMAGE_BYTES
            )
            self.strips[
                (f"{pet_id}#{transition.source}", f"{pet_id}#{transition.target}")
            ] = TransitionStrip(data, transition.frames, transition.interval, False)
        first = f"{pet_id}#{spec.default}"
        return dict(
            looks=looks,
            sources=sources,
            defaultPetId=first,
            name=entry.display_name,
            bubblePetId=first if bubble else "",
            transitions=self.transitions(),
            auto=dict(
                minSeconds=spec.auto.min_seconds,
                maxSeconds=spec.auto.max_seconds,
                order="sequence" if spec.auto.order == "sequence" else "random",
            ),
        )

    def create(self, args) -> wire.PetRegistration:
        entries = {entry.id: entry for entry in self.adapter.pet_vm.all_pets()}
        rows = args.get("looks")
        require(
            isinstance(rows, list) and 2 <= len(rows) <= MAX_APPEARANCE_VARIANTS,
            t("pet.link.look_count", max=MAX_APPEARANCE_VARIANTS),
        )
        ids, looks = [], []
        for row in rows:
            require(isinstance(row, dict))
            pet_id = text(row.get("petId"), 200)
            label = text(row.get("label"), 100).strip()
            require(
                (pet_id in entries or pet_id in self.loaded) and pet_id not in ids,
                t("pet.link.duplicate"),
            )
            require(label, t("pet.link.label_required"))
            ids.append(pet_id)
            if pet_id in self.loaded:
                folder, image = self.loaded[pet_id]
                looks.append(LinkLook(label, folder, image))
            else:
                looks.append(LinkLook(label, entries[pet_id].directory))
        replace_id = text(args.get("replacePetId", ""), 200)
        require(
            replace_id == ""
            or (replace_id in entries and is_joined(entries[replace_id].directory))
        )
        name = text(args.get("name"), 100).strip()
        require(name, t("message.0140"))
        default_id = text(args.get("defaultPetId"), 200)
        require(default_id in ids)
        bubble_id = text(args.get("bubblePetId", ""), 200)
        require(bubble_id == "" or bubble_id in ids)
        intervals = {}
        for row in args.get("intervals") or []:
            require(isinstance(row, dict))
            interval = row.get("intervalMs")
            require(type(interval) is int and 16 <= interval <= 1000)
            intervals[self._pair(row)] = interval
        transitions = {
            (ids.index(source), ids.index(target)): replace(
                strip, interval=intervals.get((source, target), strip.interval)
            )
            for (source, target), strip in self.strips.items()
            if source in ids and target in ids
        }
        auto = args.get("auto") if isinstance(args.get("auto"), dict) else {}
        try:
            image, extras, assets = link_package(
                looks,
                transitions,
                default=ids.index(default_id),
                bubble=ids.index(bubble_id) if bubble_id else None,
                auto={
                    key: auto[key]
                    for key in ("minSeconds", "maxSeconds", "order")
                    if type(auto.get(key)) in (int, str)
                },
            )
            prepared = self.adapter.pet_importer.prepare_bytes(
                image, name, extras, assets, source="link"
            )
        except (LinkError, PetImportError) as error:
            raise CommandError("pet_link_invalid", str(error)) from error
        result = self.adapter._commit_pet_import(dict(token=prepared.token, name=name))
        if result.get("saved") and replace_id and result["id"] != replace_id:
            self._replace(replace_id, result["id"])
            result["snapshot"] = self.adapter.snapshot()
        if result.get("saved"):
            self.reset()
        return result

    def _replace(self, old, new):
        """The edited pet takes the old one's settings and place; old goes to trash."""
        vm = self.adapter.pet_vm
        settings = vm.pet.preferences.settings
        prefix = f"pets/{old}/"
        for key in settings.allKeys():
            # Look ids follow positions, so the saved look may name another one.
            if key.startswith(prefix) and key.rsplit("/", 1)[-1] not in {
                "appearanceMode",
                "appearanceId",
            }:
                settings.setValue(
                    f"pets/{new}/" + key[len(prefix) :], settings.value(key)
                )
        preferences = vm.pet.app_preferences
        order = [
            new if pet_id == old else pet_id
            for pet_id in preferences.load_pet_custom_order()
        ]
        preferences.save_pet_custom_order(list(dict.fromkeys(order)))
        try:
            vm.trash_pet(old, new if vm.pet.pet_id == old else None)
        except (PetTrashError, OSError) as error:
            raise CommandError(
                "pet_trash_failed",
                str(error) if isinstance(error, PetTrashError) else t("message.0553"),
            ) from error
        self.adapter.revision += 1
        self.adapter.changed.emit("settings")

    def _pair(self, args):
        require(isinstance(args, dict))
        source = text(args.get("fromPetId"), 200)
        target = text(args.get("toPetId"), 200)
        known = {entry.id for entry in self.adapter.pet_vm.all_pets()} | set(
            self.loaded
        )
        require(source in known and target in known and source != target)
        return source, target

    def _still(self, pet_id):
        if pet_id in self.loaded:
            folder, image = self.loaded[pet_id]
            path = folder / image
        else:
            path = next(
                e for e in self.adapter.pet_vm.all_pets() if e.id == pet_id
            ).spritesheet_path
        try:
            with Image.open(path, formats=("PNG", "WEBP")) as atlas:
                cell = atlas.convert("RGBA").crop((0, 0, FRAME_WIDTH, FRAME_HEIGHT))
        except OSError as error:
            raise CommandError("pet_link_invalid", t("pet.link.not_v2")) from error
        return cell

    @staticmethod
    def _cells(strip):
        with Image.open(BytesIO(strip.image), formats=("PNG", "WEBP")) as image:
            atlas = image.convert("RGBA")
        return [
            atlas.crop(
                (index * FRAME_WIDTH, 0, (index + 1) * FRAME_WIDTH, FRAME_HEIGHT)
            )
            for index in range(strip.frames)
        ]


def _data(image):
    small = image.resize(PREVIEW_SIZE, Image.Resampling.LANCZOS)
    output = BytesIO()
    small.save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode(
        "ascii"
    )
