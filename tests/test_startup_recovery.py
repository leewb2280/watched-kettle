import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from watched_kettle.app_preferences import ApplicationPreferences
from watched_kettle.app import (
    create_pet_with_recovery,
    prepare_codex_detection_notice,
)
from watched_kettle.config import DEFAULT_PET_ID
from watched_kettle.startup_recovery import (
    FailedPetLoad,
    StartupPetLoadError,
    create_startup_pet,
    startup_pet_candidates,
)
from watched_kettle.ui.startup_recovery import (
    StartupRecoveryChoice,
    StartupRecoveryDialog,
)
from tests.test_pet_preferences import FakeSettings


def write_catalog_pet(root, directory_name, pet_id):
    directory = root / directory_name
    directory.mkdir()
    (directory / "pet.json").write_text(
        json.dumps({"id": pet_id, "displayName": directory_name}),
        encoding="utf-8",
    )
    (directory / "spritesheet.webp").write_bytes(b"catalog-placeholder")
    return directory


class StartupPetRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_codex_not_detected_notice_is_one_time_and_rearms(self):
        settings = FakeSettings()
        preferences = ApplicationPreferences(settings)

        first = prepare_codex_detection_notice(preferences, False)
        second = prepare_codex_detection_notice(preferences, False)

        self.assertIn("펫 기능은 그대로", first["message"])
        self.assertIsNone(second)
        self.assertIsNone(prepare_codex_detection_notice(preferences, True))
        self.assertIsNotNone(prepare_codex_detection_notice(preferences, False))

    def test_candidates_use_selected_default_then_remaining_order(self):
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            default = write_catalog_pet(root, "default", DEFAULT_PET_ID)
            selected = write_catalog_pet(root, "selected", "selected-id")
            remaining = write_catalog_pet(root, "z-last", "remaining-id")
            preferences = ApplicationPreferences(
                FakeSettings({"selectedPetId": "selected-id"})
            )

            candidates = startup_pet_candidates(None, preferences, root)

            self.assertEqual(candidates, [selected, default, remaining])

    def test_candidates_restore_selected_pet_from_user_root(self):
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            user_root = root / "user"
            bundled_root = root / "bundled"
            user_root.mkdir()
            bundled_root.mkdir()
            selected = write_catalog_pet(
                user_root,
                "my-helper",
                "my-helper",
            )
            default = write_catalog_pet(
                bundled_root,
                "default",
                DEFAULT_PET_ID,
            )
            preferences = ApplicationPreferences(
                FakeSettings({"selectedPetId": "my-helper"})
            )

            candidates = startup_pet_candidates(
                None,
                preferences,
                user_root,
                (bundled_root,),
            )

            self.assertEqual(candidates, [selected, default])

    def test_candidates_skip_hidden_selected_and_follow_custom_order(self):
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            hidden = write_catalog_pet(root, "hidden", "hidden-id")
            custom_first = write_catalog_pet(root, "z-name", "z-id")
            custom_second = write_catalog_pet(root, "a-name", "a-id")
            preferences = ApplicationPreferences(
                FakeSettings(
                    {
                        "selectedPetId": "hidden-id",
                        "petCatalog/sortMode": "custom",
                        "petCatalog/customOrder": '["z-id", "a-id"]',
                        "petCatalog/hiddenIds": '["hidden-id"]',
                    }
                )
            )

            candidates = startup_pet_candidates(None, preferences, root)

            self.assertEqual(candidates, [custom_first, custom_second])
            self.assertNotIn(hidden, candidates)

    def test_damaged_selected_pet_falls_back_to_next_candidate(self):
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            bad = write_catalog_pet(root, "bad", "bad-id")
            good = write_catalog_pet(root, "good", DEFAULT_PET_ID)
            preferences = ApplicationPreferences(
                FakeSettings({"selectedPetId": "bad-id"})
            )
            created = object()

            def factory(directory, settings=None):
                if directory == bad:
                    raise ValueError("잘못된 spritesheet")
                self.assertEqual(directory, good)
                return created

            result = create_startup_pet(
                factory,
                None,
                preferences,
                root,
            )

            self.assertIs(result.pet, created)
            self.assertEqual(result.directory, good)
            self.assertEqual(len(result.failures), 1)
            self.assertEqual(result.failures[0].directory, bad)

    def test_no_loadable_pet_raises_recoverable_error(self):
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            preferences = ApplicationPreferences(FakeSettings())

            with self.assertRaises(StartupPetLoadError) as context:
                create_startup_pet(
                    lambda directory, settings=None: object(),
                    None,
                    preferences,
                    root,
                )

            self.assertIn("사용 가능한 펫", context.exception.user_message)
            self.assertIn(str(root), context.exception.details)

    def test_explicit_bad_directory_is_reported_for_recovery(self):
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            chosen = root / "broken"
            preferences = ApplicationPreferences(FakeSettings())

            with self.assertRaises(StartupPetLoadError) as context:
                create_startup_pet(
                    lambda directory, settings=None: (
                        (_ for _ in ()).throw(FileNotFoundError("pet.json"))
                    ),
                    chosen,
                    preferences,
                    root,
                )

            self.assertEqual(context.exception.failures[0].directory, chosen)

    def test_recovery_dialog_can_retry_or_choose_a_folder(self):
        error = StartupPetLoadError(
            Path("pets"),
            [FailedPetLoad(Path("pets/bad"), "ValueError", "손상됨")],
        )
        retry_dialog = StartupRecoveryDialog(error, Path("pets"))
        retry_dialog.retry()
        self.assertEqual(retry_dialog.choice.action, "retry")

        choose_dialog = StartupRecoveryDialog(error, Path("pets"))
        with patch.object(
            __import__(
                "watched_kettle.ui.startup_recovery",
                fromlist=["QFileDialog"],
            ).QFileDialog,
            "getExistingDirectory",
            return_value="C:/Pets/good",
        ):
            choose_dialog.choose_directory()

        self.assertEqual(choose_dialog.choice.action, "choose")
        self.assertEqual(
            choose_dialog.choice.pet_directory,
            Path("C:/Pets/good"),
        )

    def test_app_recovery_flow_loads_a_user_selected_folder(self):
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            broken = root / "broken"
            good = root / "good"
            calls = []

            def factory(directory, settings=None):
                calls.append(directory)
                if directory == broken:
                    raise FileNotFoundError("pet.json")
                return object()

            def request(error, initial_directory):
                self.assertEqual(initial_directory, broken)
                return StartupRecoveryChoice("choose", good)

            result, selected = create_pet_with_recovery(
                broken,
                ApplicationPreferences(FakeSettings()),
                root,
                pet_factory=factory,
                recovery_request=request,
            )

            self.assertIsNotNone(result)
            self.assertEqual(selected, good)
            self.assertEqual(calls, [broken, good])

    def test_app_recovery_flow_can_exit_cleanly(self):
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            result, selected = create_pet_with_recovery(
                root / "broken",
                ApplicationPreferences(FakeSettings()),
                root,
                pet_factory=lambda directory, settings=None: (
                    (_ for _ in ()).throw(ValueError("broken"))
                ),
                recovery_request=lambda error, initial: (StartupRecoveryChoice("quit")),
            )

            self.assertIsNone(result)
            self.assertEqual(selected, root / "broken")


if __name__ == "__main__":
    unittest.main()
