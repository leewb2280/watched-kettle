"""Appearance assets and cosmetic scheduling remain separate from activity."""

from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image, ImageDraw
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSettings

from watched_kettle.config import ANIMATIONS
from watched_kettle.pet.appearance_assets import parse_appearance_set
from watched_kettle.pet.appearance_controller import AppearanceController
from watched_kettle.pet.importer import PetImporter
from watched_kettle.pet.loader import load_pet, load_appearance_frames
from watched_kettle.pet.preferences import PetPreferences
from watched_kettle.pet.window import DesktopPet
from watched_kettle.ui.menu import show_pet_context_menu
from watched_kettle.build_profiles import collect_pet_build_sources
from scripts.stage_private_pets import stage_private_pets


def manifest():
    return {
        "id": "fixture",
        "displayName": "Fixture",
        "distribution": "private-beta",
        "spriteVersionNumber": 2,
        "spritesheetPath": "spritesheet.webp",
        "appearanceSet": {
            "version": 1,
            "default": "down",
            "variants": [
                {
                    "id": "down",
                    "labels": {"ko": "내림", "en": "Down"},
                    "spritesheetPath": "spritesheet.webp",
                },
                {
                    "id": "swept",
                    "labels": {"ko": "넘김", "en": "Swept"},
                    "spritesheetPath": "swept.webp",
                },
            ],
            "transitions": [
                {
                    "from": "down",
                    "to": "swept",
                    "spritesheetPath": "up.webp",
                    "frames": 12,
                    "intervalMs": 60,
                },
                {
                    "from": "swept",
                    "to": "down",
                    "spritesheetPath": "down.webp",
                    "frames": 12,
                    "intervalMs": 60,
                },
            ],
        },
    }


def package(root):
    root.mkdir(parents=True)
    raw = manifest()
    (root / "pet.json").write_text(
        json.dumps(raw, ensure_ascii=False), encoding="utf-8"
    )
    for name, color in [("spritesheet.webp", "#ceab87"), ("swept.webp", "#85bbaa")]:
        im = Image.new("RGBA", (1536, 2288))
        draw = ImageDraw.Draw(im)
        for row in range(11):
            for col in range(8):
                draw.rectangle(
                    (col * 192 + 30, row * 208 + 20, col * 192 + 150, row * 208 + 195),
                    fill=color,
                )
        im.save(root / name, lossless=True, exact=True)
    for name in ["up.webp", "down.webp"]:
        im = Image.new("RGBA", (2304, 208))
        draw = ImageDraw.Draw(im)
        for col in range(12):
            draw.rectangle(
                (col * 192 + 30, 20, col * 192 + 150, 195),
                fill=(120 + col, 100, 130, 255),
            )
        im.save(root / name, lossless=True, exact=True)
    return raw


class AppearancePolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.safe = False
        self.events = []
        self.saved = []
        spec = parse_appearance_set(manifest())
        self.controller = AppearanceController(
            spec,
            {("down", "swept"): list(range(12)), ("swept", "down"): list(range(12))},
            mode="auto",
            current="down",
            can_start=lambda: self.safe,
            on_commit=lambda v: self.events.append(("commit", v)),
            on_change=lambda: self.events.append(("change", None)),
            on_frame=lambda: None,
            save_mode=lambda v: self.saved.append(("mode", v)),
            save_current=lambda v: self.saved.append(("current", v)),
            delay=lambda: 60_123,
        )
        self.controller.resume()

    def tearDown(self):
        self.controller.shutdown()
        self.controller.deleteLater()

    def ready(self):
        self.safe = True
        self.controller.notify_safety()
        self.controller.safe_timer.stop()
        self.controller._safe_ready()

    def finish(self):
        for _ in range(12):
            self.controller._next_frame()

    def test_auto_due_waits_for_safe_front_idle_then_commits_once(self):
        c = self.controller
        self.assertEqual(c.auto_timer.interval(), 60_123)
        c._auto_due()
        self.assertTrue(c.pending)
        self.assertFalse(c.active)
        self.ready()
        self.assertTrue(c.active)
        self.assertEqual(c.frame_timer.interval(), 60)
        self.finish()
        self.assertEqual(c.current, "swept")
        self.assertIsNone(c.target)
        self.assertEqual(self.saved, [("current", "swept")])
        self.assertTrue(c.auto_timer.isActive())

    def test_manual_disables_auto_immediately_and_last_choice_wins(self):
        c = self.controller
        c.set_mode("swept")
        self.assertFalse(c.auto_timer.isActive())
        self.assertEqual(self.saved, [("mode", "swept")])
        self.assertEqual(c.current, "down")
        c.set_mode("down")
        self.assertFalse(c.pending)
        self.ready()
        self.assertFalse(c.active)

    def test_manual_interruption_keeps_request_without_commit(self):
        c = self.controller
        c.set_mode("swept")
        self.ready()
        c._next_frame()
        self.safe = False
        c.notify_safety()
        self.assertFalse(c.active)
        self.assertEqual(c.current, "down")
        self.assertEqual(c.target, "swept")
        self.assertNotIn(("current", "swept"), self.saved)
        self.ready()
        self.finish()
        self.assertEqual(c.current, "swept")

    def test_auto_interruption_discards_due_and_rearms_full_delay(self):
        c = self.controller
        self.ready()
        c._auto_due()
        self.assertTrue(c.active)
        self.safe = False
        c.notify_safety()
        self.assertFalse(c.active)
        self.assertFalse(c.pending)
        self.assertTrue(c.auto_timer.isActive())
        self.assertEqual(c.current, "down")

    def test_hide_cancels_frames_and_timers_without_replaying_auto(self):
        c = self.controller
        self.ready()
        c._auto_due()
        c.suspend()
        self.assertFalse(c.active)
        self.assertFalse(c.pending)
        self.assertFalse(c.auto_timer.isActive())
        self.assertFalse(c.frame_timer.isActive())
        c.resume()
        self.assertTrue(c.auto_timer.isActive())
        self.assertFalse(c.pending)

    def test_return_to_auto_clears_manual_pending(self):
        c = self.controller
        c.set_mode("swept")
        c.set_mode("auto")
        self.assertFalse(c.pending)
        self.assertTrue(c.auto_timer.isActive())

    def test_invalid_mode_has_no_writes(self):
        with self.assertRaises(ValueError):
            self.controller.set_mode("missing")
        self.assertEqual(self.saved, [])


class AppearancePackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.pet = self.root / "private-pets/fixture"
        self.raw = package(self.pet)

    def tearDown(self):
        self.temp.cleanup()

    def test_legacy_loader_contract_and_complete_variants(self):
        original = load_pet(self.pet)
        self.assertEqual(len(original), 4)
        spec, variants, transitions = load_appearance_frames(self.pet, *original)
        self.assertEqual(spec.ids, ("down", "swept"))
        self.assertEqual(len(transitions[("down", "swept")]), 12)
        for frames, looks in variants.values():
            self.assertEqual(
                sum(map(len, frames.values())),
                sum(int(v["frames"]) for v in ANIMATIONS.values()),
            )
            self.assertEqual(len(looks), 16)

    def test_folder_and_zip_preserve_assets_and_identity(self):
        importer = PetImporter(self.root / "imported")
        prepared = importer.prepare(self.pet)
        identifier = prepared.pet_id
        self.assertIn("appearanceSet", prepared.extras)
        self.assertEqual(len(prepared.assets), 3)
        down = importer.preview(prepared.token, "idle", "down")[0]
        swept = importer.preview(prepared.token, "idle", "swept")[0]
        self.assertNotEqual(down, swept)
        self.assertEqual(Image.open(BytesIO(swept)).size, (1152, 208))
        archive = self.root / "pet.zip"
        with ZipFile(archive, "w") as z:
            for file in self.pet.iterdir():
                z.write(file, file.name)
        prepared = importer.prepare(archive)
        self.assertEqual(prepared.pet_id, identifier)
        imported = importer.commit(prepared.token, "Fixture")
        original = load_pet(importer.root / imported.id)
        self.assertIsNotNone(
            load_appearance_frames(importer.root / imported.id, *original)[0]
        )

    def test_build_staging_includes_all_declared_appearance_files(self):
        sources = collect_pet_build_sources(self.root, "private-beta")
        self.assertEqual(len(sources[0].appearance_images), 3)
        stage_private_pets(self.root, self.root / "staged")
        self.assertEqual(
            {p.name for p in (self.root / "staged/fixture").iterdir()},
            {"pet.json", "spritesheet.webp", "swept.webp", "up.webp", "down.webp"},
        )

    def test_paths_duplicates_reserved_ids_and_missing_transitions_rejected(self):
        for change in [
            lambda r: r["appearanceSet"]["variants"][1].update(
                spritesheetPath="../out.webp"
            ),
            lambda r: r["appearanceSet"]["variants"][1].update(id="auto"),
            lambda r: r["appearanceSet"]["transitions"].pop(),
            lambda r: r["appearanceSet"].update(default="missing"),
        ]:
            raw = manifest()
            change(raw)
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_appearance_set(raw)

    def test_invalid_extra_image_rejected_and_changes_identity(self):
        importer = PetImporter(self.root / "imported")
        first = importer.prepare(self.pet).pet_id
        im = Image.open(self.pet / "up.webp").convert("RGBA")
        im.putpixel((80, 80), (230, 10, 10, 255))
        im.save(self.pet / "up.webp", lossless=True, exact=True)
        self.assertNotEqual(importer.prepare(self.pet).pet_id, first)
        Image.new("RGBA", (192, 208)).save(self.pet / "up.webp", lossless=True)
        with self.assertRaises(ValueError):
            importer.prepare(self.pet)

    def test_runtime_manual_persistence_and_activity_isolation(self):
        settings = QSettings(
            str(self.root / "settings.ini"), QSettings.Format.IniFormat
        )
        pet = DesktopPet(self.pet, settings=settings)
        try:
            self.assertEqual(pet.appearance_snapshot().mode, "auto")
            pet.set_state("running")
            pet.set_appearance_mode("swept")
            self.assertEqual(pet.current_state, "running")
            self.assertEqual(pet.appearance_snapshot().current_id, "down")
            self.assertTrue(pet.appearance_snapshot().pending)
            self.assertEqual(
                PetPreferences("fixture", settings).load_appearance_mode(
                    ("down", "swept")
                ),
                "swept",
            )
            self.assertEqual(pet.bubble_controller.is_snoozed, False)
        finally:
            pet.close()
            pet.deleteLater()
        second = DesktopPet(self.pet, settings=settings)
        try:
            self.assertEqual(second.appearance_snapshot().current_id, "swept")
            self.assertFalse(second.appearance_snapshot().pending)
            second.set_appearance_mode("auto")
        finally:
            second.close()
            second.deleteLater()
        third = DesktopPet(self.pet, settings=settings)
        try:
            self.assertEqual(third.appearance_snapshot().current_id, "swept")
            self.assertEqual(third.appearance_snapshot().mode, "auto")
        finally:
            third.close()
            third.deleteLater()

    def test_context_menu_uses_the_same_mode_values(self):
        from watched_kettle.pet.appearance_assets import (
            AppearanceChoice,
            AppearanceStatus,
        )

        status = AppearanceStatus(
            "auto",
            "down",
            None,
            False,
            False,
            (AppearanceChoice("down", "Down"), AppearanceChoice("swept", "Swept")),
        )

        def select(menu, _):
            sub = next(
                a.menu()
                for a in menu.actions()
                if a.menu()
                and any(x.text().endswith("Swept 유지") for x in a.menu().actions())
            )
            return sub.actions()[-1]

        command = show_pet_context_menu(
            None,
            None,
            "idle",
            True,
            False,
            True,
            appearance=status,
            menu_executor=select,
        )
        self.assertEqual((command.name, command.value), ("set_pet_appearance", "swept"))

    def test_settings_command_preserves_theme_and_preview_tracks_settled_appearance(
        self,
    ):
        from watched_kettle.application.settings_ui.core import CoreSettingsAdapter
        from watched_kettle.application.settings_ui.host import SettingsWindowHost
        from watched_kettle.application.settings_ui.contracts import CommandError
        from watched_kettle.app_preferences import ApplicationPreferences
        from watched_kettle.features.pet.viewmodel import PetViewModel
        from watched_kettle.features.settings.core_viewmodel import (
            CoreSettingsViewModel,
        )
        from watched_kettle.integrations.windows_startup import (
            StartupRegistrationStatus,
        )

        settings = QSettings(str(self.root / "bridge.ini"), QSettings.Format.IniFormat)
        pet = DesktopPet(
            self.pet,
            settings=settings,
            pets_roots=(self.pet.parent,),
            user_pets_root=self.root / "imported",
        )
        vm = PetViewModel(pet)
        core = CoreSettingsAdapter(
            vm,
            CoreSettingsViewModel(
                SimpleNamespace(
                    inspect=lambda: StartupRegistrationStatus(
                        True, False, False, "", ""
                    )
                )
            ),
            ApplicationPreferences(settings),
            self.app,
        )
        host = SettingsWindowHost(core)

        def context(**values):
            return dict(
                petId=pet.pet_id,
                revision=core.revision,
                epoch=core.account_epoch,
                **values,
            )

        try:
            before = core.appearance()
            original_preview = core.pet_preview(pet.pet_id)
            self.assertEqual(original_preview["appearanceId"], "down")
            self.assertIn(
                "pet_appearance", {row["key"] for row in core.snapshot()["controls"]}
            )
            pet.set_state("running")
            result = core.execute(
                "settings.set", context(key="pet_appearance", value="swept")
            )
            self.assertTrue(result["saved"])
            self.assertTrue(result["snapshot"]["pet"]["appearance"]["pending"])
            self.assertEqual(core.appearance(), before)
            self.assertEqual(
                core.pet_preview(pet.pet_id)["image"], original_preview["image"]
            )
            with self.assertRaises(CommandError):
                core.execute(
                    "settings.set", context(key="pet_appearance", value="invalid")
                )
            prepared = core.prepare_pet_import(self.pet)
            self.assertEqual(
                [v["id"] for v in prepared["appearanceChoices"]], ["down", "swept"]
            )
            c = pet.appearance_controller
            c.current, c.target = "swept", None
            pet._apply_appearance("swept")
            vm.refresh()
            changed = core.pet_preview(pet.pet_id)
            self.assertEqual(changed["appearanceId"], "swept")
            self.assertNotEqual(changed["image"], original_preview["image"])
        finally:
            host.shutdown()
            pet.close()
            pet.deleteLater()

    def test_duplicate_import_uses_appearance_asset_limit(self):
        from unittest.mock import patch
        from watched_kettle.pet.import_package import read_local
        from watched_kettle.pet.appearance_assets import MAX_APPEARANCE_IMAGE_BYTES

        importer = PetImporter(self.root / "imported")
        prepared = importer.prepare(self.pet)
        importer.commit(prepared.token, "Fixture")
        prepared = importer.prepare(self.pet)
        with patch(
            "watched_kettle.pet.import_package.read_local", wraps=read_local
        ) as read:
            self.assertTrue(importer.commit(prepared.token, "Fixture").already_exists)
        limits = [
            call.args[2]
            for call in read.call_args_list
            if call.args[1].startswith("appearance/")
        ]
        self.assertEqual(limits, [MAX_APPEARANCE_IMAGE_BYTES] * 3)
