"""External packages must remain independent, bounded and cancellable assets."""

from io import BytesIO
from email.message import Message
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zipfile import ZipFile, ZipInfo

from PIL import Image
from PySide6.QtWidgets import QApplication

from tests.test_pet_importer import make_atlas
from watched_kettle.application.settings_ui.pet_import import (
    PetImportController,
    preparation,
)
from watched_kettle.pet.bubble_frame import frame_style_for, registered_frame
from watched_kettle.pet.importer import PetImporter, PetImportError
from watched_kettle.pet.import_sources import (
    InstalledPets,
    Fetcher,
    SourceError,
    online_pet,
    parse_command,
)
from watched_kettle.localization import t
from watched_kettle.pet.loader import load_pet


class PetSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.importer = PetImporter(self.root / "pets")

    def package(self, name="package", decorated=False):
        folder = self.root / name
        folder.mkdir()
        make_atlas().save(folder / "spritesheet.png")
        manifest = dict(
            id="demo",
            displayName="Demo",
            description="Source description",
            spritesheetPath="spritesheet.png",
        )
        if decorated:
            (folder / "bubble").mkdir()
            Image.new("RGBA", (20, 20), "red").save(folder / "bubble" / "star.png")
            manifest["bubbleTheme"] = dict(
                frame=dict(
                    overlay=[
                        dict(
                            anchor="top-center",
                            image="bubble/star.png",
                            width=20,
                            height=20,
                        )
                    ]
                )
            )
        (folder / "pet.json").write_text(json.dumps(manifest), encoding="utf-8")
        return folder, manifest

    def archive(self, folder, prefix=""):
        path = self.root / "package.zip"
        with ZipFile(path, "w") as archive:
            for item in folder.rglob("*"):
                if item.is_file():
                    archive.write(item, prefix + item.relative_to(folder).as_posix())
        return path

    def test_known_commands_are_parsed_without_shell_semantics(self):
        for command, expected in (
            ("npx codexpetdb install 'a-tom'", ("codexpetdb", "a-tom")),
            (' npx --yes petscodex install "cat" ', ("petscodex", "cat")),
            ("npx -y codexpetdb install pet", ("codexpetdb", "pet")),
            ("petdb install pet", ("codexpetdb", "pet")),
        ):
            self.assertEqual(parse_command(command), expected)
        for command in (
            "npm install petscodex",
            "npx petscodex install cat --force",
            "npx petscodex install cat; echo hi",
            "npx petscodex install ../cat",
            "npx petscodex install $(cmd)",
            "npx petscodex install cat\nwhoami",
            "npx other install cat",
            "npx petscodex install cat | cmd",
        ):
            with self.subTest(command=command), self.assertRaises(SourceError):
                parse_command(command)

    def test_fetch_is_bounded_cancellable_and_restricts_origins(self):
        cancel = threading.Event()
        fetch = Fetcher(cancel, lambda *_: None)
        for url in (
            "http://codexpetdb.com/pet",
            "https://localhost/pet",
            "https://cdn.codexpetdb.com.evil/pet",
            "https://user:secret@codexpetdb.com/pet",
        ):
            with self.assertRaises(SourceError):
                fetch(url, 100)

        class Response(BytesIO):
            def __init__(self, data, length):
                super().__init__(data)
                self.headers = Message()
                self.headers["Content-Type"] = "application/json"
                self.headers["Content-Length"] = str(length)

        with patch("watched_kettle.pet.import_sources.build_opener") as opener:
            opener.return_value.open.return_value = Response(b"{}", 2)
            self.assertEqual(
                fetch("https://codexpetdb.com/pet", 100, "application/json"), b"{}"
            )
            opener.return_value.open.return_value = Response(b"{}", 200)
            with self.assertRaises(SourceError):
                fetch("https://codexpetdb.com/pet", 100)
            opener.return_value.open.return_value = Response(b"{}", 3)
            with self.assertRaises(SourceError):
                fetch("https://codexpetdb.com/pet", 100)
        cancel.set()
        with self.assertRaises(SourceError):
            fetch("https://codexpetdb.com/pet", 100)

    def test_zip_folder_and_image_share_identity_and_keep_description(self):
        folder, _ = self.package()
        expected = self.importer.prepare(folder / "spritesheet.png").pet_id
        for source in (folder, self.archive(folder), self.archive(folder, "wrapper/")):
            prepared = self.importer.prepare(source)
            self.assertEqual(prepared.pet_id, expected)
            self.assertEqual(prepared.extras["description"], "Source description")
        result = self.importer.commit(prepared.token, prepared.name)
        (folder / "spritesheet.png").unlink()
        manifest = json.loads((self.root / "pets" / result.id / "pet.json").read_text())
        self.assertEqual(manifest["description"], "Source description")
        self.assertEqual(self.importer.commit(prepared.token, "Other").name, "Demo")

    def test_decorations_survive_and_change_identity_without_registering_preview(self):
        folder, _ = self.package(decorated=True)
        prepared = self.importer.prepare(folder)
        self.assertIsNone(registered_frame(frame_style_for(prepared.pet_id)))
        result = self.importer.commit(prepared.token, prepared.name)
        # Writing decoration files must not replace the name shown after adding.
        self.assertEqual(result.name, "Demo")
        target = self.root / "pets" / result.id
        self.assertTrue(list((target / "bubble").glob("*.png")))
        load_pet(target)
        self.assertIsNotNone(registered_frame(frame_style_for(result.id)))
        duplicate = self.importer.prepare(self.archive(folder, "pet/"))
        self.assertEqual(duplicate.pet_id, prepared.pet_id)
        self.assertTrue(self.importer.commit(duplicate.token, "Changed").already_exists)
        Image.new("RGBA", (20, 20), "blue").save(folder / "bubble" / "star.png")
        self.assertNotEqual(self.importer.prepare(folder).pet_id, prepared.pet_id)

    def test_omitted_fields_and_foreign_decorations_are_reported_apart(self):
        folder, manifest = self.package()
        manifest.update(
            tags=["cute"],
            vibes="calm",
            bubbleTheme=dict(pattern="user:abc", ornament="pet:other:star"),
        )
        (folder / "pet.json").write_text(json.dumps(manifest), encoding="utf-8")
        wire = preparation(self.importer.prepare(folder))
        self.assertEqual(wire["warnings"], ["tags", "vibes"])
        self.assertTrue(wire["omittedThemeReferences"])
        plain, _ = self.package("plain")
        wire = preparation(self.importer.prepare(plain))
        self.assertEqual(wire["warnings"], [])
        self.assertFalse(wire["omittedThemeReferences"])

    def test_archive_rejects_unsafe_layouts_and_links(self):
        folder, _ = self.package()
        for extra in (
            "../escape",
            "C:/escape",
            "folder\\escape",
            "PET.JSON",
            "second/pet.json",
        ):
            path = self.archive(folder)
            with ZipFile(path, "a") as archive:
                entry = ZipInfo("entry")
                entry.filename = extra
                archive.writestr(entry, "{}")
            with self.subTest(extra=extra), self.assertRaises(PetImportError):
                self.importer.prepare(path)
        path = self.archive(folder)
        with ZipFile(path, "a") as archive:
            link = ZipInfo("link")
            link.external_attr = 0o120777 << 16
            archive.writestr(link, "outside")
        with self.assertRaises(PetImportError):
            self.importer.prepare(path)

    def test_declared_paths_metadata_and_versions_are_validated(self):
        folder, original = self.package()
        for value in (
            dict(original, spritesheetPath="../outside.png"),
            dict(original, spriteVersionNumber=1),
            dict(original, defaultWidth=float("inf")),
            dict(original, idleActivities=[{"state": "running", "duration": -1}]),
        ):
            (folder / "pet.json").write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(PetImportError):
                self.importer.prepare(folder)
        (folder / "pet.json").write_text('{"id":"one","id":"two"}')
        with self.assertRaises(PetImportError):
            self.importer.prepare(folder)

    def test_animated_preview_uses_original_rows_and_expires(self):
        folder, _ = self.package()
        prepared = self.importer.prepare(folder)
        for state, frames in (
            ("idle", 6),
            ("running-left", 8),
            ("look-0", 8),
            ("look-1", 8),
        ):
            data, count, interval = self.importer.preview(prepared.token, state)
            with Image.open(BytesIO(data)) as strip:
                self.assertEqual(strip.size, (frames * 192, 208))
            self.assertEqual(count, frames)
            self.assertGreater(interval, 0)
        self.importer.cancel()
        with self.assertRaises(PetImportError):
            self.importer.preview(prepared.token, "idle")

    def codexpetdb(self, prefix=""):
        folder, manifest = self.package()
        manifest["id"] = "a-tom"
        (folder / "pet.json").write_text(json.dumps(manifest))
        data = self.archive(folder, prefix).read_bytes()
        discovery = dict(
            product="CodexPetDB",
            schemaVersion=1,
            assets=dict(origin="https://cdn.codexpetdb.com", delivery="cdn"),
            catalogUrl="https://cdn.codexpetdb.com/catalogs/v1/pets.json",
        )
        pet = dict(
            slug="a-tom",
            assets=dict(
                prefix="revisions/01234567-0123-7123-8123-012345678901/",
                byteSize=dict(package=len(data)),
                sha256=dict(package=hashlib.sha256(data).hexdigest()),
            ),
        )
        # Overrides replace a response; otherwise it reflects the dicts above.
        responses = {}

        def fetch(url, limit, kind=""):
            if url.endswith("codexpetdb.json"):
                return responses.get("discovery") or json.dumps(discovery).encode()
            if url.endswith("pets.json"):
                return (
                    responses.get("catalog")
                    or json.dumps(dict(schemaVersion=1, pets=[pet])).encode()
                )
            return data

        return pet, responses, fetch

    def test_codexpetdb_verifies_catalog_digest_and_manifest_id(self):
        pet, _, fetch = self.codexpetdb()
        prepared = online_pet("npx codexpetdb install a-tom", self.importer, fetch)
        self.assertEqual(prepared.name, "Demo")
        pet["assets"]["sha256"]["package"] = "0" * 64
        with self.assertRaises(SourceError):
            online_pet("npx codexpetdb install a-tom", self.importer, fetch)

    def test_codexpetdb_accepts_a_wrapper_folder_like_a_local_zip(self):
        _, _, fetch = self.codexpetdb(prefix="a-tom/")
        prepared = online_pet("npx codexpetdb install a-tom", self.importer, fetch)
        self.assertEqual(prepared.name, "Demo")

    def test_changed_source_formats_report_integrity_not_a_bad_package(self):
        _, responses, fetch = self.codexpetdb()
        for key, body in (
            ("discovery", b"not json"),
            ("discovery", b"[]"),
            ("discovery", json.dumps(dict(product="CodexPetDB", schemaVersion=1))),
            ("catalog", json.dumps(dict(schemaVersion=1, pets={}))),
            ("catalog", json.dumps(dict(schemaVersion=1, pets=["a-tom"]))),
            ("catalog", json.dumps(dict(schemaVersion=1, pets=[dict(slug="a-tom")]))),
        ):
            with self.subTest(key=key, body=body):
                responses.clear()
                responses[key] = body if isinstance(body, bytes) else body.encode()
                with self.assertRaises(SourceError) as raised:
                    online_pet("npx codexpetdb install a-tom", self.importer, fetch)
                expected = (
                    "pet.import.not_found"
                    if body == json.dumps(dict(schemaVersion=1, pets=["a-tom"]))
                    else "pet.import.integrity_failed"
                )
                self.assertEqual(str(raised.exception), t(expected))

        def petscodex(url, limit, kind=""):
            return json.dumps(dict(sha=None)).encode()

        with self.assertRaises(SourceError):
            online_pet("npx petscodex install cat", self.importer, petscodex)

    def test_petscodex_reads_one_pinned_revision(self):
        folder, manifest = self.package()
        manifest["id"] = "cat"
        calls = []

        def fetch(url, limit, kind=""):
            calls.append(url)
            if url.endswith("commits/main"):
                return json.dumps(dict(sha="a" * 40)).encode()
            if url.endswith("pet.json"):
                return json.dumps(manifest).encode()
            return (folder / "spritesheet.png").read_bytes()

        self.assertEqual(
            online_pet("npx petscodex install cat", self.importer, fetch).name, "Demo"
        )
        self.assertTrue(all("a" * 40 in url for url in calls[1:]))

    def test_installed_list_exposes_opaque_ids_and_never_changes_original(self):
        home = self.root / "codex"
        (home / "pets").mkdir(parents=True)
        folder, _ = self.package()
        folder.rename(home / "pets" / "demo")
        with patch.dict(os.environ, {"CODEX_HOME": str(home)}):
            installed = InstalledPets()
            first = installed.scan()
            self.assertEqual(first[0]["name"], "Demo")
            self.assertNotIn(str(home), json.dumps(first))
            prepared = self.importer.prepare(installed.path(first[0]["id"]))
            self.importer.commit(prepared.token, prepared.name)
            installed.scan()
            with self.assertRaises(ValueError):
                installed.path(first[0]["id"])
            self.assertTrue((home / "pets" / "demo" / "pet.json").is_file())

    def test_worker_cancel_discards_late_completion_and_preparation_is_not_published(
        self,
    ):
        folder, _ = self.package()
        entered, finish = threading.Event(), threading.Event()
        adapter = SimpleNamespace(
            pet_importer=self.importer,
            import_timer=SimpleNamespace(start=lambda _: None),
        )
        controller = PetImportController(adapter)
        adapter.cancel_pet_import = lambda: (
            controller.cancel(),
            self.importer.cancel(),
        )
        real_prepare = PetImporter.prepare

        def slow_prepare(importer, path):
            entered.set()
            finish.wait(3)
            return real_prepare(importer, path)

        with patch.object(PetImporter, "prepare", slow_prepare):
            job = controller.start(path=folder)
            self.assertTrue(entered.wait(2))
            controller.cancel(job["jobId"])
            finish.set()
            controller.worker.join(3)
        self.assertEqual(controller.status(job["jobId"])["state"], "cancelled")
        self.assertIsNone(self.importer.prepared)
        self.assertFalse((self.root / "pets").exists())

    def test_cancelled_download_does_not_block_or_overwrite_a_new_attempt(self):
        folder, _ = self.package()
        entered, finish = threading.Event(), threading.Event()
        adapter = SimpleNamespace(
            pet_importer=self.importer,
            import_timer=SimpleNamespace(start=lambda _: None),
        )
        controller = PetImportController(adapter)
        adapter.cancel_pet_import = lambda: (
            controller.cancel(),
            self.importer.cancel(),
        )

        def stuck_download(command, importer, fetch):
            entered.set()
            finish.wait(3)
            raise SourceError("late failure")

        with patch(
            "watched_kettle.application.settings_ui.pet_import.online_pet",
            stuck_download,
        ):
            first = controller.start(command="npx codexpetdb install a-tom")
            self.assertTrue(entered.wait(2))
            old_worker = controller.worker
            controller.cancel(first["jobId"])
            second = controller.start(path=folder)
            controller.worker.join(3)
            finish.set()
            old_worker.join(3)
        self.assertNotEqual(first["jobId"], second["jobId"])
        ready = controller.status(second["jobId"])
        self.assertEqual(ready["state"], "ready")
        self.assertEqual(ready["error"], "")
        controller.cancel()

    def test_worker_ready_result_keeps_storage_untouched(self):
        folder, _ = self.package()
        starts = []
        adapter = SimpleNamespace(
            pet_importer=self.importer,
            import_timer=SimpleNamespace(start=starts.append),
        )
        controller = PetImportController(adapter)
        adapter.cancel_pet_import = lambda: (
            controller.cancel(),
            self.importer.cancel(),
        )
        job = controller.start(path=folder)
        controller.worker.join(3)
        ready = controller.status(job["jobId"])
        self.assertEqual(ready["state"], "ready")
        token = ready["prepared"]["token"]
        self.assertEqual(controller.status(job["jobId"])["prepared"]["token"], token)
        self.assertEqual(starts, [600000])
        self.assertFalse((self.root / "pets").exists())
        controller.cancel()
        self.assertEqual(controller.status(job["jobId"])["state"], "cancelled")
