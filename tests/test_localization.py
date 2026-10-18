"""Language-pack behavior, process boundaries and real display regressions."""

import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from watched_kettle.localization import Translator, get_translator, set_translator
from watched_kettle.localization.catalog import RESOURCE_ROOT
from watched_kettle.localization.packs import LanguagePacks, load_pack
from scripts.language_pack import template


class LocalizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        original = get_translator()
        self.addCleanup(set_translator, original)
        set_translator(Translator())

    def pack(self, entries, **manifest):
        folder = self.root / str(len(list(self.root.iterdir())))
        folder.mkdir()
        (folder / "manifest.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "id": "community.en",
                    "locale": "en-US",
                    "name": "Community English",
                    "author": "Translator",
                    "version": "1",
                    "catalogVersion": 1,
                    **manifest,
                }
            ),
            encoding="utf-8",
        )
        (folder / "messages.json").write_text(json.dumps(entries), encoding="utf-8")
        return folder

    def test_widget_shape_labels_match_settings_and_menu_in_both_languages(self):
        from PySide6.QtCore import QPoint
        from tests.test_settings_bridge import SettingsBridgeTests
        from watched_kettle.ui.menu import PetMenuCommand, show_pet_context_menu

        for translator, labels in (
            (Translator(), ["링", "막대", "간단형"]),
            (
                load_pack(RESOURCE_ROOT / "en", official=True).translator(),
                ["Rings", "Bars", "Compact"],
            ),
        ):
            set_translator(translator)
            fixture = SettingsBridgeTests()
            fixture.setUp()
            try:
                adapter = fixture.assistant()
                controls = adapter.execute("usage.snapshot", {})["controls"]
                shape = next(c for c in controls if c["key"] == "widget_shape")
                self.assertEqual(
                    shape["options"],
                    [
                        dict(value=value, label=label)
                        for value, label in zip(("rings", "bars", "chips"), labels)
                    ],
                )
                for value, label in zip(("rings", "bars", "chips"), labels):

                    def choose(menu, _position):
                        submenu = next(
                            a.menu()
                            for a in menu.actions()
                            if a.text() == translator.text("message.0262")
                        )
                        actions = [a for a in submenu.actions() if a.text() in labels]
                        self.assertEqual([a.text() for a in actions], labels)
                        return next(a for a in actions if a.text() == label)

                    command = show_pet_context_menu(
                        None,
                        QPoint(),
                        "idle",
                        True,
                        False,
                        True,
                        usage_widget_available=True,
                        menu_executor=choose,
                    )
                    self.assertEqual(
                        command, PetMenuCommand("set_usage_widget_shape", value)
                    )
                    adapter.execute(
                        "usage.set",
                        dict(
                            epoch=adapter.account_epoch, key="widget_shape", value=value
                        ),
                    )
                    self.assertEqual(fixture.runtime.usage_vm.widget_shape, value)
            finally:
                fixture.tearDown()

    def test_old_widget_names_remain_usable_but_need_translation_review(self):
        entries = {
            "message.0270": {"sourceRevision": 1, "value": "Two bars"},
            "message.0271": {"sourceRevision": 1, "value": "Small chips"},
        }
        previous = self.pack(entries)
        pack = load_pack(previous)
        self.assertEqual(pack.outdated, 2)
        self.assertEqual(pack.translator().text("message.0270"), "Two bars")
        target = self.root / "updated-widget"
        report = template(target, "community.en", "en-US", previous)
        self.assertTrue(set(entries) <= set(report["review"]))
        updated = json.loads((target / "messages.json").read_text(encoding="utf-8"))
        for key, entry in entries.items():
            self.assertEqual(updated[key], entry)

    def test_deeply_nested_json_is_reported_without_breaking_startup(self):
        folder = self.pack({})
        (folder / "messages.json").write_text("[" * 2000 + "0" + "]" * 2000)
        packs = LanguagePacks(self.root, "community.en")
        self.assertEqual(packs.active.pack_id, "official.ko")
        self.assertTrue(packs.state()["recovered"])
        self.assertTrue(any(pack.error for pack in packs.packs if not pack.official))

    def test_locales_incompatible_with_electron_are_rejected(self):
        for locale in ("root", "und", "und-Latn", "en@posix", "en-US@foo", "aa"):
            with self.subTest(locale=locale):
                folder = self.pack({}, locale=locale)
                with self.assertRaisesRegex(ValueError, "unsupported_locale"):
                    load_pack(folder)

    def test_plural_compatibility_list_matches_babel_and_pinned_electron(self):
        from scripts.generate_language_locales import payload

        recorded = json.loads(
            (RESOURCE_ROOT / "locales.json").read_text(encoding="utf-8")
        )
        self.assertEqual(recorded, payload())
        self.assertTrue({"en-US", "ko", "fr-FR", "ru"} <= set(recorded["locales"]))
        self.assertTrue({"kok", "pt-AO"} <= set(recorded["excludedPluralLocales"]))
        self.assertFalse(
            set(recorded["locales"]) & set(recorded["excludedPluralLocales"])
        )

    def test_incompatible_plural_pack_recovers_instead_of_changing_grammar_by_screen(
        self,
    ):
        for locale in ("kok", "pt-AO"):
            with self.subTest(locale=locale):
                folder = self.pack(
                    {
                        "message.1258": {
                            "sourceRevision": 2,
                            "value": {"one": "{value0} ONE", "other": "{value0} OTHER"},
                        }
                    },
                    locale=locale,
                )
                with self.assertRaisesRegex(ValueError, "unsupported_locale"):
                    load_pack(folder)
                packs = LanguagePacks(self.root, "community.en")
                self.assertEqual(packs.active.pack_id, "official.ko")
                self.assertTrue(packs.state()["recovered"])

    def test_all_retired_fragments_from_followup_remain_reserved(self):
        from watched_kettle.localization.catalog import source_catalog

        retired = set(source_catalog()["retiredIds"])
        required = {
            "message.0813",
            "message.0814",
            "message.0824",
            "message.0957",
            "message.0999",
            "message.1187",
            "widget.remaining",
            "widget.reset",
            "widget.sample",
        }
        self.assertTrue(required <= retired)
        self.assertEqual(len(retired), len(source_catalog()["retiredIds"]))

    def test_unpaired_unicode_in_metadata_or_message_cannot_break_startup(self):
        for entries, metadata in (
            ({}, {"name": "\ud800"}),
            ({"language.title": {"sourceRevision": 1, "value": "\udfff"}}, {}),
        ):
            self.pack(entries, **metadata)
            packs = LanguagePacks(self.root, "community.en")
            self.assertEqual(packs.active.pack_id, "official.ko")
            self.assertTrue(packs.state()["recovered"])
            self.assertTrue(
                any(pack.error for pack in packs.packs if not pack.official)
            )

    def test_c1_controls_fall_back_but_literal_braces_render_once(self):
        pack = load_pack(
            self.pack(
                {
                    "language.title": {
                        "sourceRevision": 1,
                        "value": "Language {{pack}}",
                    },
                    "language.selection": {
                        "sourceRevision": 1,
                        "value": "Invalid\u009b",
                    },
                }
            )
        )
        self.assertEqual(pack.translator().text("language.title"), "Language {pack}")
        self.assertEqual(pack.translator().text("language.selection"), "사용할 언어팩")
        self.assertIn("invalid:language.selection", pack.issues)

    def test_template_update_preserves_author_name_version_and_invalid_entries(self):
        old = self.pack(
            {"language.title": False}, name="Handmade", author="Alice", version="2.4"
        )
        target = self.root / "updated"
        report = template(target, "community.en", "en-US", old)
        manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(
            [manifest[k] for k in ("name", "author", "version")],
            ["Handmade", "Alice", "2.4"],
        )
        self.assertIn("language.title", report["review"])
        self.assertIs(
            json.loads((target / "messages.json").read_text(encoding="utf-8"))[
                "language.title"
            ],
            False,
        )

    def test_update_reports_invalid_current_revision_translations_without_losing_them(
        self,
    ):
        cases = (
            (
                "language.title",
                {"sourceRevision": 1, "value": "Invalid {unexpected}"},
                True,
            ),
            ("language.title", {"sourceRevision": 1, "value": "Broken {"}, True),
            ("language.title", {"sourceRevision": 1, "value": "Control\u009b"}, True),
            ("language.title", {"sourceRevision": 1, "value": 123}, True),
            ("language.title", {"sourceRevision": True, "value": "Language"}, True),
            ("language.title", {"sourceRevision": 1.0, "value": "Language"}, True),
            (
                "message.1258",
                {"sourceRevision": 2, "value": {"one": "{value0} token"}},
                True,
            ),
            (
                "message.1258",
                {
                    "sourceRevision": 2,
                    "value": {"one": "{wrong} token", "other": "{value0} tokens"},
                },
                True,
            ),
            ("language.title", {"sourceRevision": 1, "value": "  "}, False),
            ("language.title", {"sourceRevision": 1, "value": "Language"}, False),
        )
        for index, (key, translation, needs_review) in enumerate(cases):
            with self.subTest(translation=translation):
                old = self.pack({key: translation})
                target = self.root / f"updated-{index}"
                report = template(target, "community.en", "en-US", old)
                self.assertEqual(key in report["review"], needs_review)
                updated = json.loads(
                    (target / "messages.json").read_text(encoding="utf-8")
                )
                self.assertEqual(updated[key], translation)

    def test_invalid_template_locale_does_not_create_output(self):
        target = self.root / "invalid"
        with self.assertRaises(ValueError):
            template(target, "community.en", "en@posix")
        self.assertFalse(target.exists())

    def test_project_relation_names_only_actual_titles_even_when_equal_to_default(self):
        from watched_kettle.features.project_activity.service import (
            ProjectActivityService,
            ThreadMetadata,
        )

        translator = load_pack(RESOURCE_ROOT / "en", official=True).translator()
        set_translator(translator)
        service = ProjectActivityService()
        for thread, title in (("empty", ""), ("real", translator.text("message.0467"))):
            service.mark_latency(thread, "detected")
            service.set_metadata(
                ThreadMetadata(thread, title=title), service.generation
            )
            service.set_project_relation(
                thread, "project", "Project", service.generation
            )
            self.assertEqual("named" in service.latency[thread], bool(title))

    def test_schema_version_requires_an_integer(self):
        for version in (True, 1.0, "1"):
            with self.subTest(version=version):
                with self.assertRaisesRegex(ValueError, "unsupported_format"):
                    load_pack(self.pack({}, schemaVersion=version))

    def test_missing_and_blank_translations_are_distinct_from_invalid_entries(self):
        from watched_kettle.localization.catalog import source_catalog

        folder = self.pack(
            {
                "language.title": {"sourceRevision": 1, "value": ""},
                "language.selection": {"sourceRevision": 1, "value": "  "},
                "language.folder": {"sourceRevision": 1, "value": "Restart"},
                "language.coverage": {
                    "sourceRevision": 1,
                    "value": "Wrong {unexpected}",
                },
            }
        )
        pack = load_pack(folder)
        self.assertEqual(pack.translated, 1)
        self.assertEqual(pack.untranslated, len(source_catalog()["messages"]) - 2)
        self.assertEqual(pack.issues, ["invalid:language.coverage"])
        self.assertEqual(pack.info()["untranslated"], pack.untranslated)
        self.assertEqual(pack.translator().text("language.title"), "언어")

    def test_empty_template_is_untranslated_without_invalid_issues(self):
        folder = self.root / "template"
        template(folder, "community.empty", "en-US")
        pack = load_pack(folder)
        self.assertEqual(pack.translated, 0)
        self.assertEqual(pack.untranslated, pack.total)
        self.assertEqual(pack.issues, [])

    def test_raw_count_and_display_string_are_independent_for_all_plural_categories(
        self,
    ):
        cases = {
            "fr-FR": [(1234, "other"), (1, "one"), (0, "one")],
            "ru": [
                (1, "one"),
                (2, "few"),
                (5, "many"),
                (1234, "few"),
                (1.0001, "other"),
                (0.000001, "other"),
                (1.5, "other"),
            ],
        }
        for locale, counts in cases.items():
            pack = load_pack(
                self.pack(
                    {
                        "message.1258": {
                            "sourceRevision": 2,
                            "value": {
                                form: "{value0} " + form
                                for form in ("one", "few", "many", "other")
                            },
                        }
                    },
                    locale=locale,
                )
            )
            translator = pack.translator()
            for count, category in counts:
                with self.subTest(locale=locale, count=count):
                    self.assertEqual(
                        translator.text("message.1258", count=count, value0="1 234"),
                        "1 234 " + category,
                    )
            for count in ("1,234", "1", True, False, None, float("nan"), float("inf")):
                self.assertEqual(
                    translator.text("message.1258", count=count, value0="shown"),
                    "shown other",
                )
            self.assertEqual(
                translator.text("message.1258", value0="shown"), "shown other"
            )

    def test_official_count_messages_select_singular_and_keep_real_newlines(self):
        translator = load_pack(RESOURCE_ROOT / "en", official=True).translator()
        for count in (0, 1, 2):
            self.assertEqual(
                translator.text("message.1258", count=count, value0=str(count)),
                str(count) + (" token" if count == 1 else " tokens"),
            )
            self.assertEqual(
                translator.text("message.0031", value0=count, value1="details"),
                f"Could not load {count} "
                + ("pet." if count == 1 else "pets.")
                + "\nLast error: details",
            )
            self.assertEqual(
                translator.text("message.0933", value0=count),
                str(count) + (" time" if count == 1 else " times"),
            )

    def test_catalog_has_no_retired_or_unreferenced_messages(self):
        from watched_kettle.localization.catalog import source_catalog

        source = source_catalog()
        self.assertFalse(set(source.get("retiredIds", ())) & set(source["messages"]))
        root = Path(__file__).resolve().parents[1]
        paths = [
            p
            for folder in ("watched_kettle", "settings-ui/src", "settings-ui/electron")
            for p in (root / folder).rglob("*")
            if p.suffix in {".py", ".ts", ".tsx", ".js", ".cjs", ".qml"}
            and "localization" not in p.parts
        ]
        text = "\n".join(p.read_text(encoding="utf-8-sig") for p in paths)
        dynamic = (
            "language.error.",
            "language.problem.",
            "language.screen.",
            "widget.",
            "status.",
        )
        missing = [
            key
            for key in source["messages"]
            if key not in text and not key.startswith(dynamic)
        ]
        self.assertEqual(missing, [])

    def test_official_english_has_every_message_and_current_revision(self):
        pack = load_pack(RESOURCE_ROOT / "en", official=True)
        self.assertEqual(pack.translated, pack.total)
        self.assertFalse(pack.issues)
        self.assertEqual(pack.outdated, 0)
        self.assertTrue(
            all(
                not any("\uac00" <= c <= "\ud7a3" for c in str(text))
                for text in pack.messages.values()
            )
        )

    def test_partial_pack_formats_values_and_falls_back_per_message(self):
        folder = self.pack(
            {
                "language.coverage": {
                    "sourceRevision": 1,
                    "value": "Done {done}/{total}; review {review}",
                },
            }
        )
        # A pack checked on its own (translator tooling) knows only the source.
        translator = load_pack(folder).translator()
        self.assertEqual(
            translator.text("language.coverage", done=2, total=4, review=0),
            "Done 2/4; review 0",
        )
        self.assertEqual(translator.text("language.title"), "언어")

    def test_installed_packs_fill_gaps_from_the_same_language_then_english(self):
        entries = {
            "language.title": {"sourceRevision": 1, "value": "Tongue"},
            "language.selection": {"sourceRevision": 1, "value": "Bad {oops}"},
        }
        cases = (
            ("community.gb", "en-GB", "Language pack", "official.en"),
            ("community.fr", "fr", "Language pack", "official.en"),
            ("community.ko", "ko-KR", "사용할 언어팩", "official.ko"),
        )
        for pack_id, locale, _, _ in cases:
            self.pack(entries, id=pack_id, locale=locale)
        packs = LanguagePacks(self.root)
        for pack_id, locale, expected, fallback in cases:
            with self.subTest(locale=locale):
                pack = packs.find(pack_id)
                translator = pack.translator()
                self.assertEqual(translator.text("language.title"), "Tongue")
                self.assertEqual(translator.text("language.selection"), expected)
                info = pack.info()
                self.assertEqual(info["fallback"], fallback)
                self.assertEqual(info["fallbackCount"], pack.total - 1)
                self.assertEqual(info["problemCount"], 1)
                self.assertEqual(
                    info["problems"],
                    [{"key": "language.selection", "code": "invalid_placeholder"}],
                )

    def test_broken_official_english_leaves_korean_as_the_last_fallback(self):
        from unittest.mock import patch

        self.pack({}, id="community.fr", locale="fr")
        real = load_pack

        def without_english(folder, *, official=False):
            if official:
                raise OSError("missing")
            return real(folder, official=official)

        with patch(
            "watched_kettle.localization.packs.load_pack", side_effect=without_english
        ):
            packs = LanguagePacks(self.root)
        pack = packs.find("community.fr")
        self.assertEqual(pack.info()["fallback"], "official.ko")
        self.assertEqual(pack.translator().text("language.title"), "언어")

    def test_selected_partial_pack_is_current_after_refresh(self):
        self.pack(
            {"language.title": {"sourceRevision": 1, "value": "Tongue"}},
            id="community.gb",
            locale="en-GB",
        )
        packs = LanguagePacks(self.root, "community.gb")
        self.assertEqual(packs.active.text("language.selection"), "Language pack")
        packs.refresh()
        self.assertFalse(packs.state()["restartRequired"])

    def test_problem_codes_name_each_kind_of_invalid_entry(self):
        pack = load_pack(
            self.pack(
                {
                    "not.a.key": {"sourceRevision": 1, "value": "x"},
                    "language.title": "Language",
                    "language.selection": {"sourceRevision": "1", "value": "x"},
                    "language.restart": {"sourceRevision": 1, "value": "<b>x</b>"},
                    "language.folder": {
                        "sourceRevision": 1,
                        "value": {"other": "x"},
                    },
                    "bubble.more_items": {"sourceRevision": 1, "value": {"one": "x"}},
                }
            )
        )
        self.assertEqual(
            {problem["key"]: problem["code"] for problem in pack.info()["problems"]},
            {
                "not.a.key": "unknown",
                "language.title": "invalid_entry",
                "language.selection": "invalid_revision",
                "language.restart": "invalid_text",
                "language.folder": "unexpected_plural",
                "bubble.more_items": "invalid_plural",
            },
        )

    def test_copy_writes_a_complete_new_pack_and_keeps_the_original(self):
        from watched_kettle.localization.catalog import source_catalog
        from watched_kettle.localization.editing import copy_pack

        catalog = source_catalog()["messages"]
        original = self.pack(
            {
                "language.title": {"sourceRevision": 0, "value": "Tongue"},
                "language.selection": {"sourceRevision": 1, "value": "Bad {oops}"},
            },
            id="community.gb",
            locale="en-GB",
        )
        before = {path.name: path.read_bytes() for path in original.iterdir()}
        packs = LanguagePacks(self.root)
        pack_id = copy_pack(packs, "community.gb", name="Copy", author="Me")
        self.assertEqual(pack_id, "custom.en-gb.1")
        self.assertEqual(
            before, {path.name: path.read_bytes() for path in original.iterdir()}
        )
        folder = self.root / pack_id
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(
            [manifest[k] for k in ("id", "locale", "name", "author")],
            [pack_id, "en-GB", "Copy", "Me"],
        )
        messages = json.loads((folder / "messages.json").read_text(encoding="utf-8"))
        self.assertEqual(list(messages), list(catalog))
        # Own entries keep their revision so "review needed" survives the copy.
        self.assertEqual(
            messages["language.title"], {"sourceRevision": 0, "value": "Tongue"}
        )
        self.assertEqual(messages["language.selection"]["value"], "Language pack")
        reference = json.loads((folder / "reference.json").read_text(encoding="utf-8"))
        self.assertEqual(list(reference), list(catalog))
        self.assertEqual(
            {
                k: reference["language.title"][k]
                for k in ("source", "english", "current", "screen")
            },
            {
                "source": "언어",
                "english": "Language",
                "current": "Tongue",
                "screen": "Settings › App settings",
            },
        )
        packs.refresh()
        copy = packs.find(pack_id)
        self.assertEqual(copy.translated, copy.total)
        self.assertEqual(copy.outdated, 1)
        self.assertEqual(copy.problems, [])
        self.assertEqual(
            copy_pack(packs, "community.gb", name="Copy", author="Me"),
            "custom.en-gb.2",
        )
        self.assertFalse([p for p in self.root.iterdir() if p.name.startswith(".")])

    def test_copy_of_another_language_keeps_english_gaps_untranslated(self):
        from watched_kettle.localization.editing import copy_pack

        self.pack(
            {"language.title": {"sourceRevision": 1, "value": "Langue"}},
            id="community.fr",
            locale="fr",
        )
        packs = LanguagePacks(self.root)
        pack_id = copy_pack(packs, "community.fr", name="Copie", author="Moi")
        messages = json.loads(
            (self.root / pack_id / "messages.json").read_text(encoding="utf-8")
        )
        self.assertEqual(messages["language.title"]["value"], "Langue")
        self.assertEqual(messages["language.selection"]["value"], "")
        packs.refresh()
        copy = packs.find(pack_id)
        self.assertEqual(copy.translated, 1)
        self.assertEqual(copy.translator().text("language.selection"), "Language pack")

    def test_copies_of_official_packs_are_complete_and_current(self):
        from watched_kettle.localization.editing import copy_pack

        # An unreadable folder is listed with an empty ID; it is nobody's fallback.
        (self.root / "broken").mkdir()
        packs = LanguagePacks(self.root)
        for source, locale, title in (
            ("official.ko", "ko", "언어"),
            ("official.en", "en-US", "Language"),
        ):
            with self.subTest(source=source):
                pack_id = copy_pack(packs, source, name="Copy", author="Me")
                packs.refresh()
                copy = packs.find(pack_id)
                self.assertEqual(copy.locale, locale)
                self.assertEqual(copy.translated, copy.total)
                self.assertEqual((copy.outdated, copy.problems), (0, []))
                self.assertEqual(copy.translator().text("language.title"), title)

    def test_copy_failures_leave_no_partial_pack(self):
        from unittest.mock import patch
        from watched_kettle.localization import editing

        (self.root / ".copy-interrupted").mkdir()
        packs = LanguagePacks(self.root)
        self.assertEqual(
            [pack.id for pack in packs.packs], ["official.ko", "official.en"]
        )
        with patch.object(editing, "write_json", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                editing.copy_pack(packs, "official.en", name="Copy", author="Me")
        self.pack({})
        with patch.object(editing, "MAX_PACKS", 1):
            with self.assertRaisesRegex(ValueError, "too_many_packs"):
                editing.copy_pack(packs, "official.en", name="Copy", author="Me")
        self.assertEqual(
            sorted(path.name for path in self.root.iterdir()),
            [".copy-interrupted", "1"],
        )

    def test_template_reference_has_english_and_screen_hints(self):
        folder = self.root / "template"
        template(folder, "community.example", "de")
        reference = json.loads((folder / "reference.json").read_text(encoding="utf-8"))
        self.assertEqual(reference["language.title"]["english"], "Language")
        self.assertEqual(
            reference["language.title"]["screen"], "Settings › App settings"
        )
        self.assertNotIn("current", reference["language.title"])

    def test_invalid_variables_are_ignored_without_losing_valid_translations(self):
        pack = load_pack(
            self.pack(
                {
                    "language.coverage": {
                        "sourceRevision": 1,
                        "value": "Done {secret}",
                    },
                    "language.title": {"sourceRevision": 1, "value": "Language"},
                    "unknown.key": {"sourceRevision": 1, "value": "Unknown"},
                }
            )
        )
        self.assertEqual(pack.translated, 1)
        self.assertEqual(len(pack.issues), 2)
        self.assertEqual(pack.translator().text("language.title"), "Language")

    def test_outdated_but_valid_translation_is_retained(self):
        pack = load_pack(
            self.pack(
                {
                    "language.title": {"sourceRevision": 0, "value": "Language"},
                }
            )
        )
        self.assertEqual(pack.outdated, 1)
        self.assertEqual(pack.translator().text("language.title"), "Language")

    def test_plain_text_and_formatter_attributes_cannot_be_injected(self):
        for value in (
            "<img src='file:///private'>",
            "{count.__class__}",
            "{count!r}",
            "{count:1000000}",
            "\x1b[31mBad",
        ):
            pack = load_pack(
                self.pack(
                    {
                        "bubble.more_projects": {"sourceRevision": 1, "value": value},
                    },
                    id="community.bad" + str(len(list(self.root.iterdir()))),
                )
            )
            self.assertEqual(pack.translated, 0)

    def test_plural_rules_use_the_pack_locale_and_other_fallback(self):
        pack = load_pack(
            self.pack(
                {
                    "bubble.more_projects": {
                        "sourceRevision": 1,
                        "value": {
                            "one": "{count} project",
                            "other": "{count} projects",
                        },
                    },
                }
            )
        )
        self.assertEqual(
            pack.translator().text("bubble.more_projects", count=1), "1 project"
        )
        self.assertEqual(
            pack.translator().text("bubble.more_projects", count=2), "2 projects"
        )

    def test_multiform_locale_is_supported(self):
        pack = load_pack(
            self.pack(
                {
                    "bubble.more_projects": {
                        "sourceRevision": 1,
                        "value": {
                            "one": "{count} one",
                            "few": "{count} few",
                            "many": "{count} many",
                            "other": "{count} other",
                        },
                    },
                },
                id="community.pl",
                locale="pl",
            )
        )
        self.assertEqual(
            pack.translator().text("bubble.more_projects", count=2), "2 few"
        )
        self.assertEqual(
            pack.translator().text("bubble.more_projects", count=5), "5 many"
        )

    def test_duplicate_ids_disable_both_external_packs(self):
        self.pack({})
        self.pack({})
        packs = LanguagePacks(self.root)
        matches = [pack for pack in packs.packs if pack.id == "community.en"]
        self.assertEqual(len(matches), 2)
        self.assertTrue(all(pack.error == "duplicate_id" for pack in matches))

    def test_reserved_ids_cannot_override_official_packs(self):
        self.pack({}, id="official.en")
        packs = LanguagePacks(self.root, installer_locale="en")
        self.assertEqual(packs.active.pack_id, "official.en")
        self.assertEqual(
            len([pack for pack in packs.packs if pack.id == "official.en"]), 1
        )

    def test_invalid_manifest_is_listed_without_exposing_parser_details(self):
        folder = self.pack({})
        (folder / "manifest.json").write_text("{", encoding="utf-8")
        packs = LanguagePacks(self.root)
        invalid = [pack for pack in packs.packs if not pack.official]
        self.assertEqual(len(invalid), 1)
        self.assertTrue(invalid[0].error)
        self.assertNotIn(str(folder), str(invalid[0].info()))

    def test_duplicate_json_keys_are_rejected(self):
        folder = self.pack({})
        (folder / "messages.json").write_text('{"x": 1, "x": 2}', encoding="utf-8")
        with self.assertRaises(ValueError):
            load_pack(folder)

    def test_unknown_format_and_rtl_are_rejected(self):
        for manifest in (
            {"schemaVersion": 2},
            {"locale": "ar"},
            {"locale": "invalid-locale"},
        ):
            with self.assertRaises(ValueError):
                load_pack(self.pack({}, **manifest))

    def test_missing_selected_pack_recovers_to_korean_without_losing_selection(self):
        packs = LanguagePacks(self.root, "community.missing", "en")
        self.assertEqual(packs.active.pack_id, "official.ko")
        self.assertEqual(packs.state()["selected"], "community.missing")
        self.assertTrue(packs.state()["recovered"])

    def test_selection_changes_only_after_a_new_app_run(self):
        packs = LanguagePacks(self.root)
        selected = packs.select("official.en")
        packs.selected = selected.id
        self.assertEqual(packs.active.locale, "ko")
        self.assertTrue(packs.state()["restartRequired"])
        restarted = LanguagePacks(self.root, packs.selected)
        self.assertEqual(restarted.active.locale, "en-US")
        self.assertFalse(restarted.state()["restartRequired"])

    def test_refresh_does_not_mutate_the_active_dictionary(self):
        folder = self.pack({"language.title": {"sourceRevision": 1, "value": "Before"}})
        packs = LanguagePacks(self.root, "community.en")
        (folder / "messages.json").write_text(
            json.dumps(
                {
                    "language.title": {"sourceRevision": 1, "value": "After"},
                }
            ),
            encoding="utf-8",
        )
        packs.refresh()
        self.assertEqual(packs.active.text("language.title"), "Before")
        self.assertTrue(packs.state()["restartRequired"])
        self.assertEqual(
            packs.find("community.en").translator().text("language.title"), "After"
        )

    def test_installer_default_and_explicit_override(self):
        self.assertEqual(
            LanguagePacks(self.root, installer_locale="en").active.locale, "en-US"
        )
        self.assertEqual(
            LanguagePacks(self.root, "official.ko", "en").active.locale, "ko"
        )

    def test_template_update_preserves_translation_and_marks_review(self):
        old = self.pack({"language.title": {"sourceRevision": 0, "value": "Language"}})
        target = self.root / "updated"
        report = template(target, "community.en", "en-US", old)
        self.assertIn("language.title", report["review"])
        self.assertTrue(report["new"])
        value = json.loads((target / "messages.json").read_text(encoding="utf-8"))
        self.assertEqual(value["language.title"]["value"], "Language")
        with self.assertRaises(ValueError):
            template(target, "community.en", "en-US")

    def test_imported_label_tables_are_resolved_when_used(self):
        from watched_kettle.ui.pet_controls import STATE_LABELS, ACTION_TEST_STATES

        set_translator(load_pack(RESOURCE_ROOT / "en", official=True).translator())
        self.assertEqual(STATE_LABELS["running"], "Working")
        self.assertTrue(
            all(
                not any("\uac00" <= c <= "\ud7a3" for c in row[0])
                for row in ACTION_TEST_STATES
            )
        )

    def test_real_user_title_equal_to_old_placeholder_is_still_a_known_title(self):
        from watched_kettle.features.project_activity.service import (
            ProjectActivityService,
            ThreadMetadata,
            conversation_title,
        )

        service = ProjectActivityService()
        service.set_metadata(
            ThreadMetadata("real", title="Codex 대화", project_id="p"),
            service.generation,
        )
        service.set_metadata(ThreadMetadata("real", project_id="p"), service.generation)
        self.assertEqual(service.metadata["real"].title, "Codex 대화")
        self.assertEqual(conversation_title(None), "")

    def test_pet_only_bootstrap_contains_every_shared_renderer_message(self):
        root = Path(__file__).resolve().parents[1] / "settings-ui"
        paths = [
            *root.joinpath("src/core").glob("*"),
            *root.joinpath("src").glob("*"),
            *root.joinpath("electron").glob("*.cjs"),
        ]
        excluded = {
            "AssistantPages.tsx",
            "AssistantUnavailable.tsx",
            "TrendChart.tsx",
            "protocol.generated.ts",
            "protocol.type-test.ts",
        }
        messages = Translator().bootstrap("pet-only")["messages"]
        catalog = json.loads(
            (RESOURCE_ROOT / "catalog.json").read_text(encoding="utf-8")
        )["messages"]
        # Named IDs (pet.*, language.*) as well as message.NNNN; command names
        # share the dotted shape, so only catalog IDs are checked.
        prefixes = ("status.", "language.error.", "language.problem.")
        dynamic = {key for key in catalog if key.startswith(prefixes)}
        for path in paths:
            if (
                not path.is_file()
                or path.suffix not in {".tsx", ".ts", ".cjs"}
                or path.name in excluded
            ):
                continue
            text = path.read_text(encoding="utf-8")
            keys = {
                key
                for key in re.findall(r'"([a-z_]+(?:\.[a-z0-9_]+)+)"', text)
                if key in catalog
            }
            if any(f'"{prefix}" +' in text for prefix in prefixes):
                keys |= dynamic
            for key in sorted(keys):
                with self.subTest(file=path.name, key=key):
                    self.assertTrue(key in messages, key)

    def test_bootstrap_is_json_and_does_not_share_mutable_plural_forms(self):
        translator = load_pack(RESOURCE_ROOT / "en", official=True).translator()
        first = translator.bootstrap()
        json.dumps(first)
        first["messages"]["bubble.more_projects"]["value"]["one"] = "Changed"
        self.assertEqual(
            translator.text("bubble.more_projects", count=1), "1 more project"
        )
        total = len(first["messages"])
        self.assertLess(len(translator.bootstrap("pet-only")["messages"]), total)

    def test_english_units_keep_a_space_after_the_number(self):
        # Range controls and snooze buttons append the unit to the bare number.
        english = load_pack(RESOURCE_ROOT / "en", official=True).translator()
        self.assertEqual("8" + english.text("message.0545"), "8 sec")
        self.assertEqual("15" + english.text("message.0831"), "15 min")
        self.assertEqual("Oct 18" + english.text("message.0942"), "Oct 18 (today)")
        # Korean attaches the unit directly, as before.
        self.assertEqual("8" + Translator().text("message.0545"), "8초")

    def test_every_catalog_message_is_referenced(self):
        # Unused fragments make every community translator do dead work.
        root = Path(__file__).resolve().parents[1]
        sources = "\n".join(
            path.read_text(encoding="utf-8")
            for pattern in (
                "watched_kettle/**/*.py",
                "watched_kettle/**/*.qml",
                "watched_kettle/**/*.js",
                "settings-ui/src/**/*.ts*",
                "settings-ui/electron/*.cjs",
                "settings-ui/localization.cjs",
            )
            for path in root.glob(pattern)
        )
        catalog = json.loads(
            (RESOURCE_ROOT / "catalog.json").read_text(encoding="utf-8")
        )["messages"]
        # Keys built at runtime: t("status." + status), t("language.error." + code),
        # language problem codes and reference screen areas, and the widget label
        # tables, which list each suffix literally.
        dynamic = (
            "status.",
            "language.error.",
            "language.problem.",
            "language.screen.",
            "widget.",
        )
        for key in catalog:
            prefix = next((p for p in dynamic if key.startswith(p)), "")
            with self.subTest(key=key):
                self.assertTrue(
                    f'"{key}"' in sources
                    or (prefix and f'"{key[len(prefix) :]}"' in sources),
                    key,
                )


class LanguageSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.test_settings_bridge import SettingsBridgeTests

        SettingsBridgeTests.setUpClass()

    def setUp(self):
        from tests.test_settings_bridge import SettingsBridgeTests

        self.fixture = SettingsBridgeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.core = self.fixture.core

    def change(self):
        return self.core.execute(
            "settings.set",
            {
                "key": "languagePack",
                "value": "official.en",
                "epoch": self.core.account_epoch,
                "revision": self.core.revision,
                "petId": self.core.pet_vm.snapshot.pet_id,
            },
        )

    def test_successful_language_save_has_one_commit_and_does_not_switch_active_language(
        self,
    ):
        from unittest.mock import patch

        events = []
        self.core.changed.connect(events.append)
        revision = self.core.revision
        with patch.object(self.core, "_sync", wraps=self.core._sync) as sync:
            result = self.change()
        self.assertEqual(sync.call_count, 1)
        self.assertEqual(self.core.revision, revision + 1)
        self.assertEqual(events, ["settings"])
        self.assertTrue(result["saved"])
        self.assertEqual(result["snapshot"]["language"]["current"], "official.ko")
        self.assertEqual(result["snapshot"]["language"]["selected"], "official.en")
        self.assertTrue(result["snapshot"]["language"]["restartRequired"])

    def test_failed_save_restores_the_prior_setting_and_selection(self):
        from unittest.mock import patch
        from watched_kettle.application.settings_ui.contracts import CommandError

        revision = self.core.revision
        with patch.object(
            self.core, "_sync", side_effect=CommandError("save_failed", "test")
        ):
            with self.assertRaises(CommandError):
                self.change()
        self.assertFalse(self.fixture.settings.contains("app/languagePack"))
        self.assertEqual(self.core.revision, revision)
        self.assertEqual(self.core.languages.state()["selected"], "official.ko")

    def copy(self):
        return self.core.execute(
            "language.copy",
            {
                "epoch": self.core.account_epoch,
                "revision": self.core.revision,
                "petId": self.core.pet_vm.snapshot.pet_id,
            },
        )

    def test_copy_creates_selects_and_opens_the_pack_without_exposing_paths(self):
        from unittest.mock import patch

        target = "watched_kettle.application.settings_ui.core.QDesktopServices.openUrl"
        with (
            patch(target, return_value=True) as opened,
            patch.object(self.core, "_sync", wraps=self.core._sync) as sync,
        ):
            result = self.copy()
        root = self.core.languages.root
        self.assertEqual(result["id"], "custom.ko.1")
        self.assertEqual(sync.call_count, 1)
        self.assertTrue(result["saved"])
        self.assertEqual(result["snapshot"]["language"]["selected"], "custom.ko.1")
        self.assertEqual(result["snapshot"]["language"]["current"], "official.ko")
        self.assertEqual(self.fixture.settings.value("app/languagePack"), "custom.ko.1")
        self.assertIn("custom.ko.1", [pack["id"] for pack in result["packs"]])
        self.assertTrue((root / "custom.ko.1" / "messages.json").is_file())
        opened.assert_called_once()
        encoded = json.dumps(result, ensure_ascii=False)
        for path in (str(root), root.as_posix(), json.dumps(str(root))[1:-1]):
            self.assertNotIn(path, encoded)

    def test_failed_copy_selection_keeps_the_prior_setting(self):
        from unittest.mock import patch
        from watched_kettle.application.settings_ui.contracts import CommandError

        target = "watched_kettle.application.settings_ui.core.QDesktopServices.openUrl"
        with (
            patch(target, return_value=True) as opened,
            patch.object(
                self.core, "_sync", side_effect=CommandError("save_failed", "test")
            ),
        ):
            with self.assertRaises(CommandError):
                self.copy()
        opened.assert_not_called()
        self.assertFalse(self.fixture.settings.contains("app/languagePack"))
        self.assertEqual(self.core.languages.state()["selected"], "official.ko")

    def test_copy_write_failure_is_reported_without_saving(self):
        from unittest.mock import patch
        from watched_kettle.application.settings_ui.contracts import CommandError

        with (
            patch(
                "watched_kettle.localization.editing.write_json",
                side_effect=OSError("disk full"),
            ),
            patch.object(self.core, "_sync") as sync,
        ):
            with self.assertRaises(CommandError) as raised:
                self.copy()
        self.assertEqual(raised.exception.code, "save_failed")
        sync.assert_not_called()

    def test_discovery_queries_never_commit_settings(self):
        from unittest.mock import patch

        revision = self.core.revision
        with patch.object(self.core, "_sync") as sync:
            self.assertEqual(len(self.core.execute("language.list", {})), 2)
            self.assertEqual(len(self.core.execute("language.refresh", {})), 2)
        sync.assert_not_called()
        self.assertEqual(self.core.revision, revision)

    def test_english_snapshot_after_module_import_has_no_frozen_korean_labels(self):
        original = get_translator()
        self.addCleanup(set_translator, original)
        translator = load_pack(RESOURCE_ROOT / "en", official=True).translator()
        set_translator(translator)
        from tests.test_settings_bridge import SettingsBridgeTests

        fixture = SettingsBridgeTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        snapshot = fixture.core.snapshot()
        display = {
            "controls": snapshot["controls"],
            "bubble": snapshot["bubbleControls"],
            "animations": snapshot["animations"],
            "update": snapshot["update"],
        }
        encoded = json.dumps(display, ensure_ascii=False)
        self.assertFalse(any("가" <= char <= "힣" for char in encoded))

    def test_unreadable_pack_folder_does_not_stop_the_app(self):
        from unittest.mock import patch

        with TemporaryDirectory() as folder:
            with patch.object(Path, "iterdir", side_effect=PermissionError("private")):
                packs = LanguagePacks(folder, "community.missing")
            self.assertEqual(packs.active.locale, "ko")
            self.assertTrue(packs.state()["recovered"])
            self.assertTrue(any(pack.error for pack in packs.packs))

    def test_missing_official_english_recovers_to_the_source_language(self):
        from unittest.mock import patch

        with patch(
            "watched_kettle.localization.packs.load_pack",
            side_effect=OSError("missing"),
        ):
            packs = LanguagePacks(None, "official.en")
        self.assertEqual(packs.active.locale, "ko")
        self.assertTrue(packs.state()["recovered"])

    def test_sql_and_fallback_search_match_translated_labels_including_sql_characters(
        self,
    ):
        from dataclasses import replace
        from datetime import datetime, timezone
        from watched_kettle.storage.database import DatabaseManager
        from watched_kettle.storage.usage_repository import (
            SqliteUsageRepository,
            VolatileUsageRepository,
        )
        from watched_kettle.usage.models import TaskUsageRecord

        original = get_translator()
        self.addCleanup(set_translator, original)
        english = load_pack(RESOURCE_ROOT / "en", official=True).translator()
        translations = dict(english.messages)
        translations["message.0319"] = "Complete %'_"
        set_translator(Translator("en-US", translations, "test.en"))
        with TemporaryDirectory() as folder:
            db = DatabaseManager(Path(folder) / "usage.db")
            self.assertTrue(db.start().available)
            try:
                sql = SqliteUsageRepository(db)
                memory = VolatileUsageRepository()
                record = TaskUsageRecord(
                    datetime.now(timezone.utc),
                    "a",
                    "thread",
                    "done",
                    turn_hash="1",
                    total_tokens=10,
                    source_version=3,
                    data_quality="measured",
                )
                pending_record = replace(
                    record,
                    turn_hash="2",
                    outcome="failed",
                    total_tokens=None,
                    data_quality="unavailable",
                )
                for repo in (sql, memory):
                    repo.append(record)
                    repo.append(pending_record)
                    page = repo.query_tasks("a", search="complete %'_")
                    self.assertEqual([item.turn_hash for item in page.records], ["1"])
                    page = repo.query_tasks(
                        "a", search="checking", pending=frozenset({("thread", "2")})
                    )
                    self.assertEqual([item.turn_hash for item in page.records], ["2"])
            finally:
                db.close()
