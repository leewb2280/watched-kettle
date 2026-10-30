"""User decoration layers: validation, old sticker conversion, canvas and painting."""

from dataclasses import replace
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from watched_kettle.pet.bubble_decor import (
    MAX_DECOR_LAYERS,
    DecorLayer,
    decor_from_list,
    decor_overflow,
    image_path,
    stickers_as_layers,
)
from watched_kettle.pet.bubble_frame import (
    package_image_path,
    package_image_reference,
    register_package_frame,
    registered_frame,
)
from watched_kettle.pet.bubble_theme import (
    DEFAULT_BUBBLE_THEME,
    bubble_theme_from_dict,
    bubble_theme_to_dict,
)
from watched_kettle.ui.bubble_elements import BubbleElementRegistry
from watched_kettle.ui.speech_bubble_frame import (
    frame_insets,
    paint_frame_backdrop,
    paint_frame_overlay,
)
from watched_kettle.ui.speech_bubble_paint import theme_brush


USER = "user:" + "a" * 32


def layer(**values):
    return DecorLayer(**{"id": "l", "name": "", "image": USER, **values})


class DecorValidationTests(unittest.TestCase):
    def test_invalid_layers_are_dropped_and_values_bounded(self):
        layers = decor_from_list(
            [
                {"id": "ok", "image": USER, "x": 9999, "width": 0, "alpha": 400},
                {"id": "path", "image": "C:/outside.png"},
                {"id": "escape", "image": "pkg:pet/../secret.png"},
                {"id": "anchor", "image": USER, "anchor": "middle"},
                {"id": "ok", "image": USER, "placement": "sideways", "tint": "nope"},
                "not a layer",
            ]
        )
        self.assertEqual([item.id for item in layers], ["ok", "layer-5"])
        first, second = layers
        self.assertEqual((first.x, first.width, first.alpha), (240.0, 1.0, 255))
        self.assertEqual((second.placement, second.tint), ("front", ""))

    def test_builtin_ornaments_are_layer_images(self):
        layers = decor_from_list(
            [
                {"id": "ear", "image": "ornament:cat-ear"},
                {"id": "none", "image": "ornament:none"},
                {"id": "dragon", "image": "ornament:dragon"},
            ]
        )
        self.assertEqual([item.image for item in layers], ["ornament:cat-ear"])

    def test_layer_count_is_capped(self):
        raw = [{"id": f"l{index}", "image": USER} for index in range(40)]
        self.assertEqual(len(decor_from_list(raw)), MAX_DECOR_LAYERS)

    def test_theme_round_trip_keeps_layers_as_plain_data(self):
        theme = replace(
            DEFAULT_BUBBLE_THEME,
            decor=(layer(rotation=30.0, repeat="x", tint="border"),),
        )
        data = bubble_theme_to_dict(theme)
        self.assertIsInstance(data["decor"], list)
        self.assertEqual(bubble_theme_from_dict(json.loads(json.dumps(data))), theme)

    def test_old_stickers_become_layers_once(self):
        old = {
            **{
                key: value
                for key, value in bubble_theme_to_dict(DEFAULT_BUBBLE_THEME).items()
                if key != "decor"
            },
            "sticker_1": USER,
            "sticker_1_x": 90,
            "sticker_1_y": 10,
            "sticker_1_size": 40,
            "sticker_2": "none",
            "sticker_3": "user:" + "b" * 32,
            "sticker_3_x": 50,
            "sticker_3_y": 90,
        }
        theme = bubble_theme_from_dict(old)
        self.assertEqual([item.id for item in theme.decor], ["sticker-1", "sticker-3"])
        right, bottom = theme.decor
        self.assertEqual(right.anchor, "top-right")
        # 90% of the 240px reference body, centered: 216 - 240 - 20.
        self.assertEqual((right.x, right.y, right.width), (-44.0, -12.8, 40.0))
        self.assertEqual(bottom.anchor, "bottom-center")
        # A saved theme with "decor" never converts stickers again.
        self.assertEqual(bubble_theme_from_dict({**old, "decor": []}).decor, ())
        self.assertEqual(stickers_as_layers({"sticker_1": "C:/x.png"}), ())


class DecorCanvasTests(unittest.TestCase):
    def test_overflow_covers_rotated_and_outside_layers_only(self):
        inside = layer(x=10, y=10, width=20, height=20)
        self.assertEqual(decor_overflow((inside,), 200, 40, 11), (0, 0, 0, 0))
        above = layer(anchor="top-right", x=-10, y=-30, width=40, height=20)
        self.assertEqual(decor_overflow((above,), 200, 40, 11), (0, 30, 30, 0))
        # A 40x10 bar turned 90 degrees stands 15px above its center.
        turned = layer(x=0, y=0, width=40, height=10, rotation=90)
        self.assertAlmostEqual(decor_overflow((turned,), 200, 40, 11)[1], 15.0)
        hidden = replace(above, hidden=True)
        self.assertEqual(decor_overflow((hidden,), 200, 40, 11), (0, 0, 0, 0))
        huge = layer(x=-500, width=320)
        self.assertEqual(decor_overflow((huge,), 200, 40, 11)[0], 120.0)

    def test_frame_insets_take_the_larger_of_frame_and_decor(self):
        theme = replace(
            DEFAULT_BUBBLE_THEME,
            decor=(layer(anchor="bottom-left", x=-12, y=-4, width=20, height=24),),
        )
        self.assertEqual(frame_insets(theme), (12.0, 0.0, 0.0, 20.0))
        self.assertEqual(frame_insets(theme, 2.0), (24.0, 0.0, 0.0, 40.0))


class DecorPaintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.registry = BubbleElementRegistry(self.root / "elements")

    def element(self, color, size=(20, 20)):
        source = self.root / "source.png"
        Image.new("RGBA", size, color).save(source)
        return self.registry.import_image(source, "sticker").reference

    def paint(self, theme, front=True):
        image = QImage(200, 120, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor(0, 0, 0, 0))
        painter = QPainter(image)
        body = QRectF(50, 40, 100, 40)
        if front:
            paint_frame_overlay(painter, body, theme, registry=self.registry)
        else:
            paint_frame_backdrop(painter, body, theme, registry=self.registry)
        painter.end()
        return image

    def test_layers_paint_outside_the_body_with_aspect_and_transforms(self):
        wide = self.element((255, 0, 0, 255), size=(40, 10))
        theme = replace(
            DEFAULT_BUBBLE_THEME,
            decor=(layer(image=wide, x=-20, y=-30, width=40, height=40),),
        )
        image = self.paint(theme)
        # The 40x10 image sits centered in its 40x40 box, above the body.
        self.assertEqual(image.pixelColor(50, 30).red(), 255)
        self.assertEqual(image.pixelColor(50, 14).alpha(), 0)
        turned = self.paint(
            replace(theme, decor=(replace(theme.decor[0], rotation=90),))
        )
        self.assertEqual(turned.pixelColor(50, 14).red(), 255)
        self.assertEqual(turned.pixelColor(36, 30).alpha(), 0)
        behind = replace(theme, decor=(replace(theme.decor[0], placement="back"),))
        self.assertEqual(self.paint(behind).pixelColor(50, 30).alpha(), 0)
        self.assertEqual(self.paint(behind, front=False).pixelColor(50, 30).red(), 255)
        self.assertEqual(self.paint(theme, front=False).pixelColor(50, 30).alpha(), 0)

    def test_tint_hidden_and_missing_images(self):
        white = self.element((255, 255, 255, 255))
        theme = replace(
            DEFAULT_BUBBLE_THEME,
            border="#00ff00",
            decor=(
                layer(image=white, x=10, y=10, width=20, height=20, tint="border"),
                layer(id="gone", image="user:" + "c" * 32, x=40, y=10),
                layer(
                    id="h", image=white, x=70, y=10, width=20, height=20, hidden=True
                ),
            ),
        )
        image = self.paint(theme)
        self.assertEqual(image.pixelColor(70, 60).green(), 255)
        self.assertEqual(image.pixelColor(70, 60).red(), 0)
        self.assertEqual(image.pixelColor(130, 60).alpha(), 0)

    def test_builtin_ornament_layers_draw_in_the_theme_colors(self):
        star = layer(image="ornament:star", x=10, y=-30, width=40, height=40)
        red = self.paint(replace(DEFAULT_BUBBLE_THEME, border="#c00000", decor=(star,)))
        center = red.pixelColor(80, 30)
        self.assertGreater(center.alpha(), 0)
        self.assertGreater(center.red(), center.blue())
        blue = self.paint(
            replace(DEFAULT_BUBBLE_THEME, border="#0000c0", decor=(star,))
        )
        self.assertGreater(
            blue.pixelColor(80, 30).blue(), blue.pixelColor(80, 30).red()
        )
        # Outside the drawing the box stays clear; a tint paints the drawing.
        self.assertEqual(red.pixelColor(62, 12).alpha(), 0)
        tinted = self.paint(
            replace(DEFAULT_BUBBLE_THEME, decor=(replace(star, tint="#00ff00"),))
        )
        self.assertEqual(tinted.pixelColor(80, 30).green(), 255)
        self.assertEqual(tinted.pixelColor(80, 30).red(), 0)

    def test_row_repeat_fills_the_body_width_with_whole_tiles(self):
        dot = self.element((0, 0, 255, 255), size=(10, 10))
        theme = replace(
            DEFAULT_BUBBLE_THEME,
            decor=(
                layer(
                    image=dot,
                    y=-12,
                    width=10,
                    height=10,
                    repeat="x",
                    repeat_gap=5,
                    repeat_inset=10,
                ),
            ),
        )
        image = self.paint(theme)
        # Whole 10px tiles every 15px from x=50 that end before 150 - 10.
        covered = [x for x in range(40, 160) if image.pixelColor(x, 33).blue() == 255]
        self.assertEqual((covered[0], covered[-1]), (50, 134))
        self.assertEqual(len(covered), 60)
        self.assertNotIn(62, covered)


class PackageImageTests(unittest.TestCase):
    def test_package_references_resolve_inside_registered_packages(self):
        with TemporaryDirectory() as folder:
            package = Path(folder) / "pet"
            (package / "bubble").mkdir(parents=True)
            Image.new("RGBA", (8, 8), "red").save(package / "bubble" / "dot.png")
            manifest = {
                "id": "decor-test-pet",
                "bubbleTheme": {
                    "frame": {
                        "overlay": [
                            {
                                "image": "bubble/dot.png",
                                "anchor": "top-left",
                                "rotation": 45,
                                "flipY": True,
                                "repeatX": {"gap": 2},
                            }
                        ]
                    }
                },
            }
            style = register_package_frame(manifest, package)
            frame = registered_frame(style)
            overlay = frame.overlay[0]
            self.assertEqual((overlay.rotation, overlay.flip_y), (45.0, True))
            self.assertEqual(overlay.repeat_x.gap, 2.0)
            reference = package_image_reference(style, overlay.image)
            self.assertEqual(reference, "pkg:decor-test-pet/bubble/dot.png")
            self.assertEqual(package_image_path(reference), overlay.image)
            self.assertEqual(image_path(reference), overlay.image)
            self.assertIsNone(package_image_path("pkg:decor-test-pet/../x.png"))
            self.assertIsNone(package_image_path("pkg:unknown-pet/bubble/dot.png"))

    def test_package_layers_can_be_hidden_while_spacing_stays(self):
        with TemporaryDirectory() as folder:
            package = Path(folder) / "pet"
            package.mkdir()
            manifest = {
                "id": "decor-hidden-pet",
                "bubbleTheme": {
                    "frame": {
                        "insets": [5, 6, 7, 8],
                        "overlay": [
                            {
                                "circle": {"radius": 4, "color": "#ff0000"},
                                "anchor": "top-left",
                            }
                        ],
                    }
                },
            }
            style = register_package_frame(manifest, package)
            theme = replace(DEFAULT_BUBBLE_THEME, frame_style=style)
            self.assertEqual(frame_insets(theme), (5.0, 6.0, 7.0, 8.0))
            for shown, alpha in ((True, 255), (False, 0)):
                image = QImage(40, 40, QImage.Format.Format_ARGB32_Premultiplied)
                image.fill(QColor(0, 0, 0, 0))
                painter = QPainter(image)
                paint_frame_overlay(
                    painter,
                    QRectF(10, 10, 20, 20),
                    replace(theme, package_layers=shown),
                )
                painter.end()
                self.assertEqual(image.pixelColor(10, 10).alpha(), alpha)


class BackgroundTests(unittest.TestCase):
    def test_angle_gradient_runs_along_the_angle(self):
        theme = replace(
            DEFAULT_BUBBLE_THEME,
            background="#000000",
            fill_end="#ffffff",
            gradient="angle",
            gradient_angle=90,
        )
        gradient = theme_brush(QRectF(0, 0, 100, 40), theme).gradient()
        self.assertAlmostEqual(gradient.start().y(), 0.0)
        self.assertAlmostEqual(gradient.finalStop().y(), 40.0)
        self.assertAlmostEqual(gradient.start().x(), gradient.finalStop().x())


if __name__ == "__main__":
    unittest.main()


class EditorPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_real_size_preview_reports_body_and_layer_boxes(self):
        from watched_kettle.ui.bubble_theme_preview import (
            PREVIEW_PIXEL_RATIO,
            render_bubble_preview,
        )

        theme = replace(
            DEFAULT_BUBBLE_THEME,
            decor=(layer(anchor="top-right", x=-10, y=-20, width=30, height=30),),
        )
        plain, plain_geometry = render_bubble_preview(DEFAULT_BUBBLE_THEME, None)
        image, geometry = render_bubble_preview(theme, None)
        self.assertEqual(image.width(), geometry["width"] * PREVIEW_PIXEL_RATIO)
        body = geometry["body"]
        # The layer reaches 20px above and right of the body; the canvas grows.
        self.assertAlmostEqual(body["y"] - plain_geometry["body"]["y"], 20.0)
        self.assertEqual(geometry["height"] - plain_geometry["height"], 20)
        box = geometry["layers"][0]
        self.assertAlmostEqual(box["anchorX"], body["x"] + body["width"])
        self.assertAlmostEqual(box["x"], box["anchorX"] - 10)
        self.assertAlmostEqual(box["y"], body["y"] - 20)
        long_image, long_geometry = render_bubble_preview(theme, None, "long")
        # A long message widens the bubble up to its maximum width.
        self.assertGreaterEqual(long_geometry["width"], geometry["width"])
        self.assertLessEqual(long_geometry["body"]["width"], theme.maximum_width)
        project, project_geometry = render_bubble_preview(theme, None, "project")
        self.assertEqual(project_geometry["body"]["width"], theme.maximum_width)
        del plain, long_image, project

    def test_pet_frame_copies_into_decor_unless_it_has_dots(self):
        from watched_kettle.application.settings_ui import bubble_assets

        with TemporaryDirectory() as folder:
            package = Path(folder) / "pet"
            (package / "bubble").mkdir(parents=True)
            Image.new("RGBA", (20, 10), "red").save(package / "bubble" / "wing.png")
            image = {"image": "bubble/wing.png", "anchor": "center-right"}
            manifest = {
                "id": "decor-copy-pet",
                "bubbleTheme": {
                    "frame": {
                        "backdrop": [{**image, "x": -2, "tint": "border"}],
                        "overlay": [
                            {
                                **image,
                                "anchor": "top-left",
                                "repeatY": {"gap": 3, "bottomInset": 4},
                            }
                        ],
                    }
                },
            }
            register_package_frame(manifest, package)
            copied = bubble_assets.package_decor("decor-copy-pet")
            self.assertEqual(
                [(item["placement"], item["image"]) for item in copied],
                [
                    ("back", "pkg:decor-copy-pet/bubble/wing.png"),
                    ("front", "pkg:decor-copy-pet/bubble/wing.png"),
                ],
            )
            self.assertEqual(copied[0]["tint"], "border")
            self.assertEqual(
                (
                    copied[1]["repeat"],
                    copied[1]["repeat_gap"],
                    copied[1]["repeat_inset"],
                ),
                ("y", 3.0, 4.0),
            )
            # The copies are valid decor and draw from the same package image.
            layers = decor_from_list(copied)
            self.assertEqual(len(layers), 2)
            self.assertEqual(
                image_path(layers[0].image),
                str((package / "bubble" / "wing.png").resolve()),
            )
            entries = bubble_assets.package_entries("decor-copy-pet")
            self.assertEqual([entry["name"] for entry in entries], ["wing"])
            self.assertEqual((entries[0]["width"], entries[0]["height"]), (20, 10))
            self.assertTrue(
                entries[0]["thumbnail"].startswith("data:image/png;base64,")
            )
            manifest["bubbleTheme"]["frame"]["overlay"].append(
                {"circle": {"radius": 2, "color": "#000000"}, "anchor": "top-left"}
            )
            register_package_frame(manifest, package)
            self.assertEqual(bubble_assets.package_decor("decor-copy-pet"), [])
            self.assertEqual(bubble_assets.package_decor("no-such-pet"), [])


class LibraryImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.registry = BubbleElementRegistry(self.root / "elements")

    def test_trim_and_edge_white_removal(self):
        from PIL import ImageDraw

        # A red dot with a white highlight, on a white page with wide margins.
        source = Image.new("RGB", (100, 80), "white")
        draw = ImageDraw.Draw(source)
        draw.ellipse((30, 20, 70, 60), fill="red")
        draw.ellipse((45, 30, 52, 37), fill="white")
        source.save(self.root / "dot.png")
        plain = self.registry.import_image(self.root / "dot.png", "sticker")
        with Image.open(plain.image_path) as image:
            self.assertEqual(image.size, (100, 80))
        cleaned = self.registry.import_image(
            self.root / "dot.png", "sticker", trim=True, clear_white=True
        )
        with Image.open(cleaned.image_path) as image:
            image = image.convert("RGBA")
            # Margins are cut to the dot plus a pixel; the outside is clear.
            self.assertEqual(image.size, (43, 43))
            self.assertEqual(image.getpixel((0, 0))[3], 0)
            # White inside the drawing stays.
            self.assertEqual(image.getpixel((19, 13)), (255, 255, 255, 255))

    def test_usage_names_pets_and_saved_designs_using_an_image(self):
        from watched_kettle.application.settings_ui.core import CoreSettingsAdapter

        settings = SimpleNamespace(
            allKeys=lambda: [
                "pets/a/bubbleCustomTheme",
                "pets/b/bubbleCustomTheme",
                "pets/c/width",
                "app/other",
            ],
            value=lambda key: {
                "pets/a/bubbleCustomTheme": json.dumps({"decor": [{"image": USER}]}),
                "pets/b/bubbleCustomTheme": json.dumps({"background_image": "none"}),
            }.get(key),
        )
        adapter = SimpleNamespace(
            preferences=SimpleNamespace(settings=settings),
            pet_vm=SimpleNamespace(
                all_pets=lambda: [
                    SimpleNamespace(id="a", display_name="Alpha"),
                    SimpleNamespace(id="b", display_name="Beta"),
                ]
            ),
            bubble_themes=SimpleNamespace(
                names_using=lambda reference: (
                    ["Zeta", "beta"] if reference == USER else []
                )
            ),
        )
        usage = CoreSettingsAdapter.element_usage(adapter, USER)
        self.assertEqual(usage, {"pets": ["Alpha"], "designs": ["beta", "Zeta"]})

    def merge_adapter(self, root, replace_images=None):
        from watched_kettle.application.settings_ui.bubble_themes import (
            BubbleThemeLibrary,
        )

        copy = "user:" + "b" * 32
        values = {
            "pets/other/bubbleCustomTheme": json.dumps({"decor": [{"image": copy}]}),
            "pets/plain/bubbleCustomTheme": json.dumps({"background_image": "none"}),
        }
        settings = SimpleNamespace(
            allKeys=lambda: [*values, "app/other"],
            value=values.get,
            setValue=values.__setitem__,
        )
        library = BubbleThemeLibrary(root / "themes", registry=None)
        library.root.mkdir()
        design = dict(
            id="c" * 32,
            name="Saved",
            savedAt="2026-10-29T00:00:00+00:00",
            theme={"background_image": copy, "decor": [{"image": copy}, "bad"]},
        )
        (library.root / f"{'c' * 32}.json").write_text(json.dumps(design), "utf-8")
        if replace_images is not None:
            library.replace_images = replace_images
        deleted, saved = [], []
        theme = replace(
            DEFAULT_BUBBLE_THEME,
            background_image=copy,
            decor=(layer(image=copy),),
        )
        pet = SimpleNamespace(
            preferences=SimpleNamespace(prefix="pets/current"),
            custom_bubble_theme=theme,
        )
        registry = SimpleNamespace(
            duplicates=lambda: [("a" * 32, ["b" * 32])],
            delete=deleted.append,
        )
        adapter = SimpleNamespace(
            preferences=SimpleNamespace(settings=settings),
            pet_vm=SimpleNamespace(
                pet=pet,
                bubble_editor_state=SimpleNamespace(registry=registry),
                replace_custom_bubble_theme=saved.append,
            ),
            bubble_themes=library,
            _sync=lambda: None,
        )
        return adapter, values, library, deleted, saved

    def test_duplicate_images_fold_into_the_kept_copy(self):
        from watched_kettle.application.settings_ui.core import CoreSettingsAdapter

        with TemporaryDirectory() as directory:
            adapter, values, library, deleted, saved = self.merge_adapter(
                Path(directory)
            )
            CoreSettingsAdapter._merge_duplicate_images(adapter)

            self.assertEqual(
                json.loads(values["pets/other/bubbleCustomTheme"]),
                {"decor": [{"image": USER}]},
            )
            self.assertEqual(
                json.loads(values["pets/plain/bubbleCustomTheme"]),
                {"background_image": "none"},
            )
            stored = json.loads((library.root / f"{'c' * 32}.json").read_text("utf-8"))[
                "theme"
            ]
            self.assertEqual(stored["background_image"], USER)
            self.assertEqual(stored["decor"], [{"image": USER}, "bad"])
            self.assertEqual(saved[0].background_image, USER)
            self.assertEqual(saved[0].decor[0].image, USER)
            self.assertEqual(deleted, ["user:" + "b" * 32])

    def test_rewriting_the_stored_theme_keeps_the_chosen_mode(self):
        from watched_kettle.pet.window import DesktopPet

        for mode in ("character", "default", "custom"):
            with self.subTest(mode=mode):
                stored, chosen = [], []
                pet = SimpleNamespace(
                    bubble_theme_mode=mode,
                    custom_bubble_theme=None,
                    preferences=SimpleNamespace(save_custom_bubble_theme=stored.append),
                )
                pet.set_custom_bubble_theme = lambda theme: chosen.append(theme)
                theme = replace(DEFAULT_BUBBLE_THEME, background_image=USER)

                DesktopPet.replace_custom_bubble_theme(pet, theme)

                self.assertEqual(pet.bubble_theme_mode, mode)
                if mode == "custom":
                    self.assertEqual(chosen, [theme])
                else:
                    self.assertEqual((stored, chosen), ([theme], []))
                    self.assertIs(pet.custom_bubble_theme, theme)

    def test_a_failed_rewrite_keeps_the_copy(self):
        from watched_kettle.application.settings_ui.core import CoreSettingsAdapter

        def fail(replacements):
            raise OSError("disk full")

        with TemporaryDirectory() as directory:
            adapter, _values, _library, deleted, _saved = self.merge_adapter(
                Path(directory), replace_images=fail
            )
            CoreSettingsAdapter._merge_duplicate_images(adapter)
            self.assertEqual(deleted, [])

    def test_imported_packages_drop_decor_layers(self):
        from watched_kettle.pet.import_package import normalize_manifest

        extras, _assets, warnings = normalize_manifest(
            {"bubbleTheme": {"decor": [{"id": "a", "image": USER}]}},
            lambda name, limit: b"",
        )
        self.assertEqual(extras["bubbleTheme"]["decor"], [])
        self.assertIn("bubbleTheme.decor", warnings)
