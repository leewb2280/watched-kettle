"""Saved bubble designs, theme files and pet package export."""

from dataclasses import replace
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
import warnings
from zipfile import ZipFile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtWidgets import QApplication

from watched_kettle.application.settings_ui.bubble_themes import (
    BubbleThemeLibrary,
    ThemeFileError,
    export_package_theme,
    export_theme_file,
    import_theme_file,
)
from watched_kettle.pet.bubble_decor import DecorLayer
from watched_kettle.pet.bubble_frame import parse_frame, register_package_frame
from watched_kettle.pet.bubble_theme import DEFAULT_BUBBLE_THEME, bubble_theme_from_dict
from watched_kettle.ui.bubble_elements import BubbleElementRegistry


def layer(image, **values):
    return DecorLayer(**{"id": "ribbon", "name": "Ribbon", "image": image, **values})


class ThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.registry = BubbleElementRegistry(self.root / "elements")
        source = self.root / "wide.png"
        Image.new("RGBA", (40, 20), (200, 40, 90, 255)).save(source)
        self.image = self.registry.import_image(source, "sticker").reference
        photo = self.root / "photo.png"
        Image.new("RGB", (30, 30), "blue").save(photo)
        self.photo = self.registry.import_image(photo, "photo").reference

    def package(self):
        package = self.root / "pet"
        (package / "bubble").mkdir(parents=True)
        Image.new("RGBA", (10, 10), "gold").save(package / "bubble" / "star.png")
        manifest = {
            "id": "theme-test-pet",
            "bubbleTheme": {
                "frame": {
                    "insets": [2, 4, 2, 2],
                    "overlay": [
                        {"image": "bubble/star.png", "anchor": "top-left", "x": 1}
                    ],
                }
            },
        }
        (package / "pet.json").write_text(json.dumps(manifest), encoding="utf-8")
        return register_package_frame(manifest, package)

    def test_library_saves_portable_designs(self):
        style = self.package()
        library = BubbleThemeLibrary(self.root / "themes", self.registry)
        theme = replace(
            DEFAULT_BUBBLE_THEME,
            radius=20,
            decor=(layer("pkg:theme-test-pet/bubble/star.png"),),
            frame_style=style,
        )
        before = len(self.registry.elements)
        theme_id = library.save("  Gold  star ", theme)
        # The package image became a library image the theme now names.
        self.assertEqual(len(self.registry.elements), before + 1)
        saved = library.load(theme_id)
        self.assertTrue(saved.decor[0].image.startswith("user:"))
        self.assertEqual(saved.radius, 20)
        # Saving it again reuses that library image instead of a second copy.
        library.delete(library.save("Again", theme))
        self.assertEqual(len(self.registry.elements), before + 1)
        entries = library.entries()
        self.assertEqual([row["name"] for row in entries], ["Gold star"])
        library.delete(theme_id)
        self.assertEqual(library.entries(), [])
        with self.assertRaises(ThemeFileError):
            library.save(" ", theme)
        with self.assertRaises(ThemeFileError):
            library.load("../x")

    def test_loading_a_design_on_another_pet_uses_that_pets_frame(self):
        from watched_kettle.application.settings_ui.core import CoreSettingsAdapter

        library = BubbleThemeLibrary(self.root / "themes", self.registry)
        theme_id = library.save(
            "Framed", replace(DEFAULT_BUBBLE_THEME, frame_style="pet:someone-else")
        )
        adapter = SimpleNamespace(
            bubble_themes=library,
            pet_vm=SimpleNamespace(pet=SimpleNamespace(manifest={"id": "plain"})),
        )
        loaded = CoreSettingsAdapter._theme_command(
            adapter, "bubble.theme.load", {"id": theme_id}
        )
        self.assertEqual(loaded["theme"]["frame_style"], "standard")

    def test_library_names_designs_that_use_an_image(self):
        library = BubbleThemeLibrary(self.root / "themes", self.registry)
        library.save(
            "Layered", replace(DEFAULT_BUBBLE_THEME, decor=(layer(self.image),))
        )
        library.save(
            "Photo", replace(DEFAULT_BUBBLE_THEME, background_image=self.photo)
        )
        library.save("Plain", DEFAULT_BUBBLE_THEME)
        self.assertEqual(library.names_using(self.image), ["Layered"])
        self.assertEqual(library.names_using(self.photo), ["Photo"])
        self.assertEqual(library.names_using("user:" + "0" * 32), [])

    def test_theme_file_round_trip_brings_images_along(self):
        theme = replace(
            DEFAULT_BUBBLE_THEME,
            background_image=self.photo,
            decor=(
                layer(self.image, rotation=20),
                layer("ornament:ribbon", id="bow"),
            ),
            frame_style="pet:someone-else",
        )
        archive = self.root / "share.zip"
        export_theme_file(archive, "Shared", theme, self.registry)
        with ZipFile(archive) as files:
            names = set(files.namelist())
            data = json.loads(files.read("theme.json"))
        self.assertEqual(names, {"theme.json", "images/1.png", "images/2.png"})
        self.assertNotIn(str(self.root), json.dumps(data))
        self.assertEqual(data["theme"]["frame_style"], "standard")
        other = BubbleElementRegistry(self.root / "other-elements")
        name, imported = import_theme_file(archive, other)
        self.assertEqual(name, "Shared")
        self.assertEqual(len(other.elements), 2)
        self.assertTrue(imported.background_image.startswith("user:"))
        self.assertEqual(imported.decor[0].rotation, 20.0)
        self.assertIsNotNone(other.get(imported.decor[0].image))
        # A built-in ornament needs no image file and arrives as it left.
        self.assertEqual(imported.decor[1].image, "ornament:ribbon")

    def test_broken_theme_files_are_rejected(self):
        bad = self.root / "bad.zip"
        with ZipFile(bad, "w") as files:
            files.writestr("theme.json", json.dumps({"format": "other"}))
        not_zip = self.root / "note.zip"
        not_zip.write_text("plain")
        # A repeated member name would hide its other copies from the limits.
        repeated = self.root / "repeated.zip"
        valid = json.dumps(
            {"format": "watched-kettle-bubble-theme", "version": 1, "theme": {}}
        )
        with ZipFile(repeated, "w") as files:
            files.writestr("theme.json", valid)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                for _ in range(3):
                    files.writestr("images/1.png", b"x" * 1024)
        for path in (bad, not_zip, repeated):
            with self.subTest(path=path.name), self.assertRaises(ThemeFileError):
                import_theme_file(path, self.registry)

    def test_package_export_loads_back_as_a_pet_frame(self):
        style = self.package()
        theme = replace(
            DEFAULT_BUBBLE_THEME,
            frame_style=style,
            background_image=self.photo,
            decor=(
                layer(
                    self.image,
                    anchor="top-right",
                    x=-20,
                    y=-30,
                    width=40,
                    height=40,
                    repeat="none",
                    tint="border",
                ),
                layer(self.image, id="back", placement="back", hidden=True),
                layer("ornament:star", id="star"),
            ),
        )
        folder = self.root / "export"
        omitted = export_package_theme(folder, theme, self.registry)
        # A package frame takes image files; drawn ornaments are named instead.
        self.assertEqual(omitted, ["background_image", "decor_ornaments"])
        data = json.loads((folder / "bubble-theme.json").read_text(encoding="utf-8"))
        bubble = data["bubbleTheme"]
        self.assertEqual(bubble["background_image"], "none")
        self.assertNotIn("decor", bubble)
        overlay = bubble["frame"]["overlay"]
        # The pet's own star, then the decoration fitted to its 40x20 image.
        self.assertEqual(len(overlay), 2)
        self.assertEqual((overlay[1]["width"], overlay[1]["height"]), (40.0, 20.0))
        self.assertEqual(overlay[1]["y"], -20.0)
        self.assertEqual(overlay[1]["tint"], "border")
        self.assertNotIn("backdrop", bubble["frame"])
        self.assertEqual(bubble["frame"]["insets"][1], 20.0)
        frame = parse_frame(bubble["frame"], folder)
        self.assertEqual(len(frame.overlay), 2)
        self.assertTrue(all(Path(item.image).is_file() for item in frame.overlay))
        restored = bubble_theme_from_dict(bubble)
        self.assertEqual(restored.radius, theme.radius)


if __name__ == "__main__":
    unittest.main()
