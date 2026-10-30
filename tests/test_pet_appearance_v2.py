"""Appearance set version 2: more looks, optional transitions and timing."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image, ImageDraw
from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication

from watched_kettle.pet.appearance_assets import (
    AppearanceAuto,
    appearance_manifest,
    normalized_appearance_assets,
    parse_appearance_set,
)
from watched_kettle.pet.appearance_controller import (
    FADE_FRAMES,
    FADE_INTERVAL_MS,
    AppearanceController,
    AppearanceTransitions,
    cross_fade,
)
from watched_kettle.pet.importer import PetImporter
from watched_kettle.pet.loader import load_appearance_frames, load_pet
from watched_kettle.pet.window import DesktopPet


COLORS = {"day": "#ceab87", "night": "#3d4a7a", "rain": "#85bbaa"}


def manifest(**appearance):
    return {
        "id": "closet",
        "displayName": "Closet",
        "distribution": "private-beta",
        "spriteVersionNumber": 2,
        "spritesheetPath": "spritesheet.webp",
        "appearanceSet": {
            "version": 2,
            "default": "day",
            "variants": [
                {"id": "day", "label": "Day", "spritesheetPath": "spritesheet.webp"},
                {
                    "id": "night",
                    "labels": {"ko": "밤", "en": "Night"},
                    "spritesheetPath": "looks/night.webp",
                },
                {"id": "rain", "label": "Rain", "spritesheetPath": "looks/rain.webp"},
            ],
            "transitions": [
                {
                    "from": "day",
                    "to": "night",
                    "spritesheetPath": "looks/day-night.webp",
                    "frames": 4,
                    "intervalMs": 70,
                }
            ],
            "auto": {"minSeconds": 20, "maxSeconds": 40, "order": "sequence"},
            **appearance,
        },
    }


def atlas(color):
    image = Image.new("RGBA", (1536, 2288))
    draw = ImageDraw.Draw(image)
    for row in range(11):
        for col in range(8):
            draw.rectangle(
                (col * 192 + 30, row * 208 + 20, col * 192 + 150, row * 208 + 195),
                fill=color,
            )
    return image


def write_package(root):
    (root / "looks").mkdir(parents=True)
    raw = manifest()
    (root / "pet.json").write_text(json.dumps(raw), encoding="utf-8")
    atlas(COLORS["day"]).save(root / "spritesheet.webp", lossless=True, exact=True)
    atlas(COLORS["night"]).save(root / "looks/night.webp", lossless=True, exact=True)
    atlas(COLORS["rain"]).save(root / "looks/rain.webp", lossless=True, exact=True)
    strip = Image.new("RGBA", (4 * 192, 208))
    draw = ImageDraw.Draw(strip)
    for col in range(4):
        draw.rectangle(
            (col * 192 + 30, 20, col * 192 + 150, 195), fill=(90 + col, 80, 120, 255)
        )
    strip.save(root / "looks/day-night.webp", lossless=True, exact=True)
    return raw


class ParseTests(unittest.TestCase):
    def test_version_two_reads_labels_partial_transitions_and_timing(self):
        spec = parse_appearance_set(manifest())
        self.assertEqual((spec.version, spec.ids), (2, ("day", "night", "rain")))
        self.assertEqual(spec.variants[0].label, "Day")
        self.assertEqual(len(spec.transitions), 1)
        self.assertEqual(spec.auto, AppearanceAuto(20, 40, "sequence"))
        # Version 2 may draw no transition at all and omit timing.
        bare = manifest(transitions=[])
        del bare["appearanceSet"]["auto"]
        self.assertEqual(parse_appearance_set(bare).auto, AppearanceAuto())

    def test_invalid_version_two_declarations_are_rejected(self):
        def variant(index):
            return {
                "id": f"look{index}",
                "label": f"Look {index}",
                "spritesheetPath": f"looks/{index}.webp",
            }

        first = manifest()["appearanceSet"]["variants"][0]
        cases = {
            "seven looks": dict(variants=[first] + [variant(i) for i in range(6)]),
            "no label": dict(
                variants=[first, {"id": "x", "spritesheetPath": "looks/x.webp"}]
            ),
            "same pair twice": dict(
                transitions=manifest()["appearanceSet"]["transitions"] * 2
            ),
            "too many frames": dict(
                transitions=[
                    {
                        **manifest()["appearanceSet"]["transitions"][0],
                        "frames": 49,
                    }
                ]
            ),
            "slow before fast": dict(auto={"minSeconds": 50, "maxSeconds": 40}),
            "unknown order": dict(auto={"order": "shuffle"}),
            "too short": dict(auto={"minSeconds": 5}),
        }
        for name, change in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                parse_appearance_set(manifest(**change))

    def test_version_one_keeps_its_stricter_rules(self):
        raw = manifest(version=1)
        with self.assertRaises(ValueError):
            parse_appearance_set(raw)

    def test_normalized_declaration_round_trips(self):
        spec = parse_appearance_set(manifest())
        paths = {path: path for path in spec.paths}
        again = parse_appearance_set(
            {**manifest(), "appearanceSet": appearance_manifest(spec, paths)}
        )
        self.assertEqual(again, spec)


class TransitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def still(self, color):
        pixmap = QPixmap(10, 10)
        pixmap.fill(QColor(color))
        return pixmap

    def test_drawn_reversed_and_faded_transitions(self):
        spec = parse_appearance_set(manifest())
        stills = {name: self.still(color) for name, color in COLORS.items()}
        calls = []

        def still(name):
            calls.append(name)
            return stills[name]

        library = AppearanceTransitions(
            spec, {("day", "night"): ["a", "b", "c", "d"]}, still
        )
        self.assertEqual(library.get("day", "night"), (["a", "b", "c", "d"], 70))
        self.assertEqual(library.get("night", "day"), (["d", "c", "b", "a"], 70))
        frames, interval = library.get("day", "rain")
        self.assertEqual((len(frames), interval), (FADE_FRAMES, FADE_INTERVAL_MS))
        # The middle frame is a half blend; the ends are not repeated.
        middle = frames[FADE_FRAMES // 2 - 1].toImage().pixelColor(5, 5)
        self.assertTrue(
            QColor(COLORS["rain"]).red() <= middle.red() <= QColor(COLORS["day"]).red()
        )
        self.assertNotEqual(
            frames[-1].toImage().pixelColor(5, 5), QColor(COLORS["rain"])
        )
        self.assertIs(library.get("day", "rain")[0], frames)
        self.assertEqual(calls, ["day", "rain"])

    def test_cross_fade_frame_count(self):
        self.assertEqual(len(cross_fade(self.still("red"), self.still("blue"), 3)), 3)


class ControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def controller(self, **values):
        spec = parse_appearance_set(manifest())
        self.safe = True
        commits = []
        controller = AppearanceController(
            spec,
            AppearanceTransitions(
                spec,
                {("day", "night"): list(range(4))},
                lambda name: QPixmap(4, 4),
            ),
            mode="auto",
            current="day",
            can_start=lambda: self.safe,
            on_commit=commits.append,
            on_change=lambda: None,
            on_frame=lambda: None,
            save_mode=lambda value: None,
            save_current=lambda value: None,
            **values,
        )
        self.addCleanup(controller.deleteLater)
        self.addCleanup(controller.shutdown)
        controller.resume()
        controller.safe_timer.stop()
        controller._safe_ready()
        return controller, commits

    def change(self, controller):
        controller._auto_due()
        while controller.active:
            controller._next_frame()

    def test_package_order_walks_looks_in_sequence_with_fades(self):
        controller, commits = self.controller()
        self.change(controller)
        self.change(controller)
        self.change(controller)
        self.assertEqual(commits, ["night", "rain", "day"])

    def test_random_order_never_picks_the_current_look(self):
        controller, _ = self.controller(order="random")
        with patch("random.choice", side_effect=lambda items: items[-1]) as choice:
            controller._auto_due()
        self.assertEqual(choice.call_args.args[0], ["night", "rain"])
        self.assertEqual(controller.target, "rain")

    def test_interval_follows_the_package_or_the_choice(self):
        controller, _ = self.controller()
        with patch("random.randint", side_effect=lambda low, high: low) as pick:
            controller._delay()
            controller.set_timing(interval="600-1800")
        self.assertEqual(
            [call.args for call in pick.call_args_list],
            [(20_000, 40_000), (600_000, 1_800_000)],
        )
        # The waiting automatic change was rescheduled with the new range.
        self.assertEqual(controller.auto_timer.interval(), 600_000)
        self.assertEqual(controller.snapshot().interval, "600-1800")
        self.assertEqual(controller.snapshot().package_auto.order, "sequence")


class PackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pet = self.root / "private-pets/closet"
        write_package(self.pet)

    def test_loader_and_import_keep_every_look(self):
        spec, variants, strips = load_appearance_frames(self.pet, *load_pet(self.pet))
        self.assertEqual(set(variants), {"day", "night", "rain"})
        self.assertEqual(list(strips), [("day", "night")])
        importer = PetImporter(self.root / "imported")
        prepared = importer.prepare(self.pet)
        declaration = prepared.extras["appearanceSet"]
        self.assertEqual(declaration["version"], 2)
        self.assertEqual(declaration["auto"]["order"], "sequence")
        self.assertEqual(declaration["variants"][0]["label"], "Day")
        self.assertEqual(len(prepared.assets), 3)
        imported = importer.commit(prepared.token, "Closet")
        folder = importer.root / imported.id
        self.assertEqual(
            load_appearance_frames(folder, *load_pet(folder))[0].ids, spec.ids
        )

    def test_normalized_assets_rename_files(self):
        raw = json.loads((self.pet / "pet.json").read_text(encoding="utf-8"))

        def read(name, limit):
            return (self.pet / name).read_bytes()

        declaration, assets = normalized_appearance_assets(raw, read)
        self.assertEqual(
            declaration["variants"][0]["spritesheetPath"], "spritesheet.webp"
        )
        self.assertTrue(all(name.startswith("appearance/") for name in assets))

    def test_runtime_timing_is_saved_per_pet(self):
        settings = QSettings(
            str(self.root / "settings.ini"), QSettings.Format.IniFormat
        )
        pet = DesktopPet(self.pet, settings=settings)
        try:
            pet.set_appearance_timing(interval="10-30", order="random")
            status = pet.appearance_snapshot()
            self.assertEqual((status.interval, status.order), ("10-30", "random"))
            self.assertEqual(len(status.choices), 3)
        finally:
            pet.close()
            pet.deleteLater()
        again = DesktopPet(self.pet, settings=settings)
        try:
            status = again.appearance_snapshot()
            self.assertEqual((status.interval, status.order), ("10-30", "random"))
        finally:
            again.close()
            again.deleteLater()

    def test_settings_expose_timing_controls(self):
        from watched_kettle.application.settings_ui.contracts import CommandError
        from watched_kettle.application.settings_ui.core import CoreSettingsAdapter
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
        try:
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

            def controls():
                return {row["key"]: row for row in core.snapshot()["controls"]}

            interval = controls()["pet_appearance_interval"]
            self.assertEqual(interval["value"], "package")
            self.assertEqual(interval["options"][0]["label"], "펫 기본값(20~40초)")
            self.assertIn("1~3분", [row["label"] for row in interval["options"]])
            self.assertFalse(interval["disabled"])
            self.assertEqual(controls()["pet_appearance_order"]["value"], "package")

            def change(key, value):
                return core.execute(
                    "settings.set",
                    dict(
                        petId=pet.pet_id,
                        revision=core.revision,
                        epoch=core.account_epoch,
                        key=key,
                        value=value,
                    ),
                )

            change("pet_appearance_interval", "180-600")
            change("pet_appearance_order", "random")
            self.assertEqual(controls()["pet_appearance_interval"]["value"], "180-600")
            self.assertEqual(controls()["pet_appearance_order"]["value"], "random")
            with self.assertRaises(CommandError):
                change("pet_appearance_interval", "1-2")
            change("pet_appearance", "night")
            self.assertTrue(controls()["pet_appearance_interval"]["disabled"])
        finally:
            pet.close()
            pet.deleteLater()


if __name__ == "__main__":
    unittest.main()
