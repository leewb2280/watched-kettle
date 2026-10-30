"""Joining installed pets into one pet with several looks."""

from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image, ImageDraw
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from watched_kettle.pet.appearance_assets import parse_appearance_set
from watched_kettle.pet.linker import (
    LinkError,
    LinkLook,
    link_package,
    look_problem,
    transition_strip,
)
from watched_kettle.pet.loader import load_appearance_frames, load_pet
from watched_kettle.pet.window import DesktopPet


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


def write_pet(root, pet_id, color, bubble=False, size=(1536, 2288)):
    root.mkdir(parents=True)
    manifest = {
        "id": pet_id,
        "displayName": pet_id.title(),
        "spriteVersionNumber": 2,
        "spritesheetPath": "spritesheet.webp",
        "defaultWidth": 140,
    }
    if bubble:
        (root / "bubble").mkdir()
        Image.new("RGBA", (12, 12), "pink").save(root / "bubble/dot.png")
        manifest["bubbleTheme"] = {
            "fill": {"start": "#fff0f5"},
            "frame": {
                "overlay": [
                    {"image": "bubble/dot.png", "anchor": "top-left", "width": 12}
                ]
            },
        }
    (root / "pet.json").write_text(json.dumps(manifest), encoding="utf-8")
    image = atlas(color) if size == (1536, 2288) else Image.new("RGBA", size, color)
    image.save(root / "spritesheet.webp", lossless=True, exact=True)
    return root


def frame(color, size=(192, 208)):
    image = Image.new("RGBA", size)
    ImageDraw.Draw(image).ellipse((10, 10, size[0] - 10, size[1] - 10), fill=color)
    return image


class TransitionStripTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_side_by_side_strip_keeps_cells(self):
        strip = Image.new("RGBA", (192 * 3, 208))
        for index in range(3):
            strip.paste(frame((200, 40 * index, 90, 255)), (192 * index, 0))
        strip.save(self.root / "strip.png")
        result = transition_strip([self.root / "strip.png"])
        self.assertEqual(
            (result.frames, result.interval, result.resized), (3, 60, False)
        )
        with Image.open(BytesIO(result.image)) as image:
            self.assertEqual(image.size, (576, 208))

    def test_animation_and_numbered_stills_fit_into_cells(self):
        frames = [frame((40 * index, 90, 160, 255), (100, 100)) for index in range(4)]
        frames[0].save(
            self.root / "turn.webp",
            save_all=True,
            append_images=frames[1:],
            duration=80,
            lossless=True,
        )
        animated = transition_strip([self.root / "turn.webp"])
        self.assertEqual((animated.frames, animated.interval), (4, 80))
        self.assertTrue(animated.resized)
        with Image.open(BytesIO(animated.image)) as image:
            cell = image.convert("RGBA").crop((0, 0, 192, 208))
        # A square frame stands on the bottom of the taller cell.
        self.assertEqual(cell.getpixel((96, 2))[3], 0)
        self.assertGreater(cell.getpixel((96, 150))[3], 0)
        for index, image in enumerate(frames[:3]):
            image.save(self.root / f"step-{2 - index}.png")
        stills = transition_strip(sorted(self.root.glob("step-*.png")))
        self.assertEqual(stills.frames, 3)

    def test_unusable_images_explain_why(self):
        Image.new("RGBA", (300, 300), "red").save(self.root / "photo.png")
        opaque = Image.new("RGBA", (384, 208), "red")
        opaque.save(self.root / "opaque.png")
        (self.root / "note.txt").write_text("x")
        for paths in (
            [self.root / "photo.png"],
            [self.root / "opaque.png"],
            [self.root / "note.txt"],
            [],
        ):
            with self.subTest(paths=paths), self.assertRaises(LinkError):
                transition_strip(paths)


class LinkPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pets = self.root / "pets"
        self.day = write_pet(self.pets / "day", "day", "#ceab87")
        self.night = write_pet(self.pets / "night", "night", "#3d4a7a", bubble=True)
        self.rain = write_pet(self.pets / "rain", "rain", "#85bbaa")
        self.old = write_pet(self.pets / "old", "old", "#999999", size=(1536, 1872))

    def strip(self):
        strip = Image.new("RGBA", (192 * 4, 208))
        for index in range(4):
            strip.paste(frame((90, 80, 40 * index, 255)), (192 * index, 0))
        strip.save(self.root / "day-night.png")
        return transition_strip([self.root / "day-night.png"])

    def test_package_declares_looks_transitions_bubble_and_timing(self):
        image, extras, assets = link_package(
            [
                LinkLook("Day", self.day),
                LinkLook("Night", self.night),
                LinkLook("Rain", self.rain),
            ],
            {(0, 1): self.strip()},
            default=0,
            bubble=1,
            auto={"minSeconds": 30, "maxSeconds": 90, "order": "sequence"},
        )
        spec = parse_appearance_set({**extras, "spritesheetPath": "spritesheet.webp"})
        self.assertEqual(spec.ids, ("look-1", "look-2", "look-3"))
        self.assertEqual([v.label for v in spec.variants], ["Day", "Night", "Rain"])
        self.assertEqual(spec.transitions[0].frames, 4)
        self.assertEqual((spec.auto.min_seconds, spec.auto.order), (30, "sequence"))
        self.assertEqual(extras["defaultWidth"], 140)
        self.assertIn("frame", extras["bubbleTheme"])
        self.assertEqual(
            set(assets) - {name for name in assets if name.startswith("bubble/")},
            {
                "appearance/look-2.webp",
                "appearance/look-3.webp",
                "appearance/look-1-look-2.webp",
            },
        )
        self.assertGreater(len(image), 0)

    def test_requirements_for_looks(self):
        self.assertTrue(look_problem(self.old / "spritesheet.webp"))
        self.assertEqual(look_problem(self.day / "spritesheet.webp"), "")
        with self.assertRaises(LinkError):
            link_package([LinkLook("Day", self.day)], {})
        with self.assertRaises(LinkError):
            link_package([LinkLook("Day", self.day), LinkLook("Old", self.old)], {})

    def test_settings_session_previews_and_creates_a_loadable_pet(self):
        from watched_kettle.application.settings_ui.contracts import CommandError
        from watched_kettle.application.settings_ui.core import CoreSettingsAdapter
        from watched_kettle.application.settings_ui.host import SettingsWindowHost
        from watched_kettle.app_preferences import ApplicationPreferences
        from watched_kettle.features.pet.viewmodel import PetViewModel
        from watched_kettle.features.settings.core_viewmodel import (
            CoreSettingsViewModel,
        )
        from watched_kettle.integrations.windows_startup import (
            StartupRegistrationStatus,
        )

        settings = QSettings(str(self.root / "bridge.ini"), QSettings.Format.IniFormat)
        user_root = self.root / "user-pets"
        pet = DesktopPet(
            self.day,
            settings=settings,
            pets_roots=(self.pets, user_root),
            user_pets_root=user_root,
        )
        core = CoreSettingsAdapter(
            PetViewModel(pet),
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
        try:
            sources = core.execute("pet.link.sources", {})
            rows = {row["id"]: row for row in sources["entries"]}
            self.assertEqual(rows["old"]["problem"], rows["old"]["problem"].strip())
            self.assertTrue(rows["old"]["problem"])
            self.assertEqual(rows["day"]["problem"], "")
            self.assertTrue(rows["night"]["hasBubble"])
            self.assertEqual(sources["maxLooks"], 6)
            self.strip()
            added = host._execute(
                "file.link.transition",
                dict(
                    paths=[str(self.root / "day-night.png")],
                    fromPetId="day",
                    toPetId="night",
                ),
            )
            self.assertEqual(added["frames"], 4)
            pair = dict(fromPetId="night", toPetId="day")
            self.assertEqual(core.execute("pet.link.preview", pair)["kind"], "reversed")
            faded = core.execute(
                "pet.link.preview", dict(fromPetId="day", toPetId="rain")
            )
            self.assertEqual((faded["kind"], len(faded["frames"])), ("fade", 8))
            self.assertTrue(faded["start"].startswith("data:image/png;base64,"))
            request = dict(
                looks=[
                    dict(petId="day", label="Day"),
                    dict(petId="night", label="Night"),
                    dict(petId="rain", label="Rain"),
                ],
                defaultPetId="day",
                name="Weather",
                bubblePetId="night",
                intervals=[dict(fromPetId="day", toPetId="night", intervalMs=90)],
                auto=dict(minSeconds=60, maxSeconds=120, order="random"),
            )
            with self.assertRaises(CommandError):
                core.execute(
                    "pet.link.create",
                    {**request, "looks": request["looks"][:1]},
                )
            with self.assertRaises(CommandError):
                core.execute(
                    "pet.link.create",
                    {**request, "looks": [*request["looks"][:2], request["looks"][0]]},
                )
            created = core.execute("pet.link.create", request)
            self.assertTrue(created["saved"])
            self.assertEqual(core.pet_link.strips, {})
            folder = user_root / created["id"]
            manifest = json.loads((folder / "pet.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["importSource"], "link")
            self.assertEqual(
                manifest["appearanceSet"]["transitions"][0]["intervalMs"], 90
            )
            spec, variants, strips = load_appearance_frames(folder, *load_pet(folder))
            self.assertEqual(len(variants), 3)
            self.assertEqual(list(strips), [("look-1", "look-2")])
            # Editing: the joined pet opens with its looks and drawn transition,
            # and saving replaces it, keeping its settings and catalog place.
            joined = created["id"]
            rows = {
                row["id"]: row
                for row in core.execute("pet.link.sources", {})["entries"]
            }
            self.assertTrue(rows[joined]["joined"])
            self.assertFalse(rows["day"]["joined"])
            pet.app_preferences.save_pet_custom_order(["night", joined, "day"])
            settings.setValue(f"pets/{joined}/width", 222)
            settings.setValue(f"pets/{joined}/appearanceMode", "look-3")
            draft = core.execute("pet.link.load", dict(petId=joined))
            self.assertEqual(
                [look["petId"] for look in draft["looks"]],
                [f"{joined}#look-1", f"{joined}#look-2", f"{joined}#look-3"],
            )
            self.assertEqual(draft["bubblePetId"], f"{joined}#look-1")
            self.assertEqual(draft["transitions"][0]["intervalMs"], 90)
            self.assertTrue(draft["sources"][0]["thumbnail"].startswith("data:image"))
            again = core.execute(
                "pet.link.preview",
                dict(fromPetId=f"{joined}#look-2", toPetId=f"{joined}#look-1"),
            )
            self.assertEqual(again["kind"], "reversed")
            edited = core.execute(
                "pet.link.create",
                dict(
                    looks=[
                        dict(petId=f"{joined}#look-1", label="Morning"),
                        dict(petId=f"{joined}#look-2", label="Night"),
                    ],
                    defaultPetId=f"{joined}#look-1",
                    name="Weather",
                    bubblePetId=f"{joined}#look-1",
                    intervals=[],
                    auto=dict(minSeconds=60, maxSeconds=120, order="random"),
                    replacePetId=joined,
                ),
            )
            self.assertTrue(edited["saved"])
            self.assertNotEqual(edited["id"], joined)
            ids = {entry.id for entry in pet.all_pets()}
            self.assertNotIn(joined, ids)
            self.assertIn(edited["id"], ids)
            self.assertEqual(
                [row["petId"] for row in core.pet_vm.packages.records()], [joined]
            )
            self.assertEqual(
                list(pet.app_preferences.load_pet_custom_order()[:2]),
                ["night", edited["id"]],
            )
            self.assertEqual(int(settings.value(f"pets/{edited['id']}/width")), 222)
            self.assertIsNone(settings.value(f"pets/{edited['id']}/appearanceMode"))
            folder = user_root / edited["id"]
            spec = load_appearance_frames(folder, *load_pet(folder))[0]
            self.assertEqual([v.label for v in spec.variants], ["Morning", "Night"])
            self.assertEqual(len(spec.transitions), 1)
        finally:
            host.shutdown()
            pet.close()
            pet.deleteLater()


if __name__ == "__main__":
    unittest.main()
