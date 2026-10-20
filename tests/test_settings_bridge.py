"""Real Qt models at the Electron boundary; no user settings or live hook edits."""

import base64
from io import BytesIO
import json
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import QProcess, QSettings
from PySide6.QtNetwork import QLocalSocket
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from watched_kettle.application.click_through import ClickThroughHotkeys
from watched_kettle.application.paths import AppPaths
from watched_kettle.application.runtime import ApplicationRuntime
from watched_kettle.application.settings_ui.contracts import (
    CommandError,
    MAX_FRAME_BYTES,
)
from watched_kettle.application.settings_ui.core import CoreSettingsAdapter
from watched_kettle.application.settings_ui.host import SettingsWindowHost
from watched_kettle.app_preferences import ApplicationPreferences
from watched_kettle.app import resolve_startup_pet
from watched_kettle.branding import APPLICATION_VERSION
from watched_kettle.features.pet.viewmodel import PetViewModel
from watched_kettle.features.settings.core_viewmodel import CoreSettingsViewModel
from watched_kettle.localization import t
from watched_kettle.features.notifications.models import NoticeRequest
from watched_kettle.features.notifications.actions import ActionTarget
from watched_kettle.pet.bubble_theme import BUBBLE_THEME_LIMITS
from watched_kettle.pet.window import DesktopPet
from tests.runtime_support import isolated_codex_server
from tests.test_pet_importer import make_atlas
from watched_kettle.integrations.claude_code_install import (
    MANAGED_HOOK_EVENTS,
    ClaudeCodeHookInstaller,
    build_managed_commands,
)
from watched_kettle.integrations.claude_code_status_line_install import (
    ClaudeCodeStatusLineInstaller,
)
from watched_kettle.integrations.windows_hotkeys import (
    ERROR_HOTKEY_ALREADY_REGISTERED,
    GlobalHotkeys,
)
from watched_kettle.integrations.windows_startup import StartupRegistrationStatus


def wait_until(condition, timeout_ms=5000):
    """Process events until ``condition()`` holds; CI runners can be slow."""
    waited = 0
    while not condition() and waited < timeout_ms:
        QTest.qWait(10)
        waited += 10
    return condition()


def read_line(client, timeout_ms=5000):
    """Read one newline-terminated frame from ``client``."""
    wait_until(client.canReadLine, timeout_ms)
    return bytes(client.readLine())


class ElectronCommandAllowlistTests(unittest.TestCase):
    """The Electron main process forwards only the commands it lists."""

    def test_every_command_the_renderer_sends_is_forwarded(self):
        exposure = Path("settings-ui/electron/commands.generated.cjs").read_text(
            encoding="utf-8"
        )
        allowed = set(
            json.loads(exposure.split("module.exports = ", 1)[1].rstrip(";\n"))[
                "renderer"
            ]
        )
        namespaces = "|".join(sorted({name.split(".")[0] for name in allowed}))
        literal = re.compile(
            rf'\b(?:request|command|call|read)\(\s*"((?:{namespaces})\.[a-z_.]+)"'
        )
        sent = {
            name: source.name
            for source in Path("settings-ui/src").rglob("*.ts*")
            if not source.name.endswith((".generated.ts", ".type-test.ts"))
            for name in literal.findall(source.read_text(encoding="utf-8"))
        }
        # A missing entry fails in the window as "허용되지 않은 명령입니다."
        self.assertIn("update.download", sent)
        self.assertEqual(
            {name: file for name, file in sent.items() if name not in allowed}, {}
        )


class FakeStartupRegistration:
    def inspect(self):
        return StartupRegistrationStatus(True, False, False, "", "")


class FakeChild:
    """Stand-in for the Electron QProcess; only state and termination matter."""

    def __init__(self):
        self.running = True
        self.killed = False

    def state(self):
        if self.running:
            return QProcess.ProcessState.Running
        return QProcess.ProcessState.NotRunning

    def kill(self):
        self.killed = True
        self.running = False

    terminate = kill

    def waitForFinished(self, _timeout):
        return not self.running

    def processId(self):
        return 4321


class SettingsBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings = QSettings(
            str(self.root / "settings.ini"), QSettings.Format.IniFormat
        )
        self.preferences = ApplicationPreferences(self.settings)
        self.pet = DesktopPet(
            Path("pets/mori-bot"),
            settings=self.settings,
            user_pets_root=self.root / "pets",
            pets_roots=(Path("pets"), self.root / "pets"),
        )
        self.vm = PetViewModel(self.pet)
        self.core = CoreSettingsAdapter(
            self.vm,
            CoreSettingsViewModel(FakeStartupRegistration()),
            self.preferences,
            self.app,
        )
        self.host = SettingsWindowHost(self.core)
        self.runtime = None

    def tearDown(self):
        self.host.shutdown()
        if self.runtime:
            self.runtime.close()
        self.pet.close()
        self.app.processEvents()
        self.temp.cleanup()

    def context(self, **args):
        return dict(
            petId=self.vm.snapshot.pet_id,
            revision=self.core.revision,
            epoch=self.core.account_epoch,
            **args,
        )

    def test_restart_command_requires_lifecycle_owner_and_rejects_busy_operations(self):
        with self.assertRaises(CommandError) as unsupported:
            self.host._execute("app.restart", {})
        self.assertEqual(unsupported.exception.code, "unsupported")
        restart = Mock()
        self.host.restart = restart
        for state in ("downloading", "preparing", "installing"):
            with patch.object(
                type(self.core.updates), "state", property(lambda _self: state)
            ):
                with self.assertRaises(CommandError) as busy:
                    self.host._execute("app.restart", {})
                self.assertEqual(busy.exception.code, "operation_busy")
        with patch.object(self.core.pet_batch, "job", {}):
            with self.assertRaises(CommandError) as busy:
                self.host._execute("app.restart", {})
            self.assertEqual(busy.exception.code, "operation_busy")
        restart.assert_not_called()
        self.assertEqual(self.host._execute("app.restart", {}), {"accepted": True})
        restart.assert_called_once_with()

    def prepare_import(self, version=2):
        path = self.root / "웹 펫.png"
        make_atlas(version).save(path)
        return self.host._execute("file.pet.prepare", dict(path=str(path)))

    def install_user_pet(self, pet_id):
        import shutil

        destination = self.root / "pets" / pet_id
        shutil.copytree(Path("pets/mori-bot"), destination)
        path = destination / "pet.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data.update(id=pet_id, displayName="추가한 펫 " + pet_id)
        path.write_text(json.dumps(data), encoding="utf-8")
        return destination

    def test_pet_lock_and_shortcut_are_common_but_action_bubbles_are_not(self):
        api = Mock()
        api.RegisterHotKey.return_value = True
        shortcuts = ClickThroughHotkeys(
            self.preferences,
            self.pet,
            hotkeys=GlobalHotkeys(
                api=api, last_error=lambda: ERROR_HOTKEY_ALREADY_REGISTERED
            ),
        )
        self.addCleanup(shortcuts.close)
        self.core.click_through = shortcuts

        def controls():
            return {c["key"]: c for c in self.core.snapshot()["controls"]}

        self.assertEqual(controls()["click_through_hotkey"]["status"], "unassigned")
        self.assertNotIn("click_through_bubbles", controls())
        result = self.core.execute(
            "settings.set", self.context(key="click_through", value=True)
        )
        self.assertTrue(result["snapshot"]["pet"]["click_through"])
        self.assertTrue(self.pet.click_through)

        self.core.execute(
            "settings.set",
            self.context(key="click_through_hotkey", value="Ctrl+Alt+P"),
        )
        self.assertEqual(controls()["click_through_hotkey"]["value"], "Ctrl+Alt+P")
        self.assertEqual(controls()["click_through_hotkey"]["status"], "registered")
        api.RegisterHotKey.return_value = False
        self.core.execute(
            "settings.set",
            self.context(key="click_through_hotkey", value="Ctrl+Alt+L"),
        )
        self.assertEqual(controls()["click_through_hotkey"]["status"], "in_use")
        self.assertEqual(self.preferences.load_pet_click_through_hotkey(), "Ctrl+Alt+L")
        for value in ("Shift+P", "ctrl+alt+p", 5, None):
            with self.assertRaises(CommandError):
                self.core.execute(
                    "settings.set",
                    self.context(key="click_through_hotkey", value=value),
                )
        self.core.execute(
            "settings.set", self.context(key="click_through_hotkey", value="")
        )
        self.assertEqual(controls()["click_through_hotkey"]["status"], "unassigned")
        with self.assertRaises(CommandError):
            self.core.execute(
                "settings.set", self.context(key="click_through_bubbles", value=True)
            )

    def test_pet_shortcut_toggles_the_lock(self):
        api = Mock()
        api.RegisterHotKey.return_value = True
        hotkeys = GlobalHotkeys(api=api)
        shortcuts = ClickThroughHotkeys(self.preferences, self.pet, hotkeys=hotkeys)
        self.addCleanup(shortcuts.close)
        shortcuts.set_pet_hotkey("Ctrl+Alt+P")
        hotkeys.triggered.emit("pet_lock")
        self.assertTrue(self.pet.click_through)
        hotkeys.triggered.emit("pet_lock")
        self.assertFalse(self.pet.click_through)
        shortcuts.close()
        hotkeys.triggered.emit("pet_lock")
        self.assertFalse(self.pet.click_through)

    def test_saved_lock_waits_for_a_tray_or_shortcut_to_undo_it(self):
        api = Mock()
        api.RegisterHotKey.return_value = True
        shortcuts = ClickThroughHotkeys(
            self.preferences, self.pet, hotkeys=GlobalHotkeys(api=api)
        )
        self.addCleanup(shortcuts.close)
        self.pet.set_click_through(True)
        shortcuts.release_without_tray(True)
        self.assertTrue(self.pet.click_through)
        shortcuts.release_without_tray(False)
        self.assertFalse(self.pet.click_through)
        # Only this run starts unlocked; the saved choice is kept.
        self.assertTrue(self.preferences.load_pet_click_through())
        self.pet.set_click_through(True)
        shortcuts.set_pet_hotkey("Ctrl+Alt+P")
        shortcuts.release_without_tray(False)
        self.assertTrue(self.pet.click_through)

    def test_widget_lock_shortcut_and_action_bubble_choice_in_assistant(self):
        from PySide6.QtCore import Qt

        core = self.assistant()
        runtime = self.runtime
        api = Mock()
        api.RegisterHotKey.return_value = True
        runtime.click_through.hotkeys.api = api
        controls = {c["key"]: c for c in core.snapshot()["controls"]}
        self.assertIn("click_through_bubbles", controls)
        core.execute(
            "settings.set", self.context(key="click_through_bubbles", value=True)
        )
        self.assertTrue(self.pet.click_through_bubbles)

        def usage_controls():
            return {c["key"]: c for c in core.execute("usage.snapshot", {})["controls"]}

        self.assertEqual(
            usage_controls()["widget_click_through_hotkey"]["status"], "unassigned"
        )
        core.execute(
            "usage.set",
            dict(epoch=core.account_epoch, key="widget_click_through", value=True),
        )
        window = runtime.usage_companion.window
        self.assertTrue(window.flags() & Qt.WindowType.WindowTransparentForInput)
        self.assertTrue(self.pet.usage_widget_click_through)
        core.execute(
            "usage.set",
            dict(
                epoch=core.account_epoch,
                key="widget_click_through_hotkey",
                value="Ctrl+Alt+W",
            ),
        )
        self.assertEqual(
            usage_controls()["widget_click_through_hotkey"]["status"], "registered"
        )
        runtime.click_through.hotkeys.triggered.emit("widget_lock")
        self.assertFalse(runtime.usage_vm.widget_click_through)
        self.assertFalse(window.flags() & Qt.WindowType.WindowTransparentForInput)

        # The pet lock cannot take the widget's shortcut, nor the reverse.
        def pet_hotkey(value):
            return dict(
                petId=self.vm.snapshot.pet_id,
                revision=core.revision,
                epoch=core.account_epoch,
                key="click_through_hotkey",
                value=value,
            )

        with self.assertRaises(CommandError) as raised:
            core.execute("settings.set", pet_hotkey("Ctrl+Alt+W"))
        self.assertEqual(str(raised.exception), t("hotkey.duplicate"))
        self.assertEqual(self.preferences.load_pet_click_through_hotkey(), "")
        core.execute("settings.set", pet_hotkey("Ctrl+Alt+P"))
        with self.assertRaises(CommandError):
            core.execute(
                "usage.set",
                dict(
                    epoch=core.account_epoch,
                    key="widget_click_through_hotkey",
                    value="Ctrl+Alt+P",
                ),
            )
        self.assertEqual(
            self.preferences.load_usage_widget_click_through_hotkey(), "Ctrl+Alt+W"
        )

    def test_double_click_setting_round_trips_and_rejects_unknown_actions(self):
        self.assertEqual(self.core.snapshot()["doubleClickAction"], "settings_home")
        before = self.core.revision
        for value in ("codex", "claude", "wave_only", "settings_home"):
            result = self.core.execute(
                "settings.set", self.context(key="double_click_action", value=value)
            )
            self.assertTrue(result["saved"])
            self.assertEqual(result["snapshot"]["doubleClickAction"], value)
            self.assertEqual(
                ApplicationPreferences(self.settings).load_double_click_action(), value
            )
        self.assertEqual(self.core.revision, before + 4)
        for value in ("unknown", None, 123):
            with self.assertRaises(CommandError):
                self.core.execute(
                    "settings.set", self.context(key="double_click_action", value=value)
                )
        self.assertEqual(self.core.revision, before + 4)

    def test_pet_only_home_is_not_redirected_to_pet_settings(self):
        host = SettingsWindowHost(self.core)
        try:
            host.open_route("home", show=False)
            self.assertEqual(host.route["page"], "home")
            host.open_route("pet_settings", show=False)
            self.assertEqual(host.route["page"], "pet")
        finally:
            host.shutdown()

    def test_batch_catalog_reuses_thumbnails_and_invalidates_changed_files(self):
        destination = self.install_user_pet("thumbnail-test")
        entry = next(
            entry for entry in self.vm.all_pets() if entry.id == "thumbnail-test"
        )
        self.core._thumbnails.clear()
        with patch.object(
            self.core, "_idle_cell", wraps=self.core._idle_cell
        ) as loader:
            first = self.core._thumbnail(entry)
            self.assertTrue(first.startswith("data:image/png"))
            self.assertEqual(self.core._thumbnail(entry), first)
            self.assertEqual(loader.call_count, 1)
        (destination / "spritesheet.webp").write_bytes(b"broken image")
        self.assertEqual(self.core._thumbnail(entry), "")

    def test_catalog_read_and_save_keep_distinct_side_effects(self):
        self.install_user_pet("custom")
        before = self.core.revision
        changes = []
        self.core.changed.connect(changes.append)
        with patch.object(self.core, "_sync", wraps=self.core._sync) as sync:
            self.core.execute("pet.catalog", {})
            self.assertEqual(self.core.revision, before)
            self.assertEqual(changes, [])
            sync.assert_not_called()
            result = self.core.execute(
                "pet.catalog.save",
                self.context(
                    sort="custom", order=["custom", "mori-bot"], hidden=["custom"]
                ),
            )
            sync.assert_called_once_with()
        self.assertTrue(result["saved"])
        self.assertEqual(self.core.revision, before + 1)
        self.assertEqual(result["snapshot"]["revision"], before + 1)
        self.assertEqual(changes, ["settings"])

    def test_catalog_save_failure_restores_previous_preferences(self):
        self.install_user_pet("custom")
        previous = self.vm.catalog_preferences()
        before = self.core.revision
        changes = []
        self.core.changed.connect(changes.append)
        with patch.object(
            self.core, "_sync", side_effect=CommandError("save_failed", "저장 실패")
        ) as sync:
            with self.assertRaises(CommandError):
                self.core.execute(
                    "pet.catalog.save",
                    self.context(
                        sort="custom", order=["custom", "mori-bot"], hidden=["custom"]
                    ),
                )
            self.assertEqual(sync.call_count, 2)
        self.assertEqual(self.vm.catalog_preferences(), previous)
        self.assertEqual(self.core.revision, before + 1)
        self.assertEqual(changes, ["settings"])

    def test_trash_round_trip_through_commands_preserves_live_pet(self):
        self.install_user_pet("custom")
        self.settings.setValue("pets/custom/width", 224)
        original_theme = self.pet.bubble_controller.theme
        entry = next(
            row for row in self.core.catalog()["entries"] if row["id"] == "custom"
        )
        self.assertEqual(entry["source"], "user")
        self.assertTrue(entry["canDelete"])
        moved = self.core.execute("pet.trash.move", self.context(id="custom"))
        self.assertEqual(self.pet.pet_id, "mori-bot")
        self.assertEqual(self.pet.bubble_controller.theme, original_theme)
        listing = self.core.execute("pet.trash.list", {})
        self.assertEqual(listing["total"], 1)
        self.assertNotIn(str(self.root), json.dumps(listing))
        self.assertTrue(listing["entries"][0]["thumbnail"].startswith("data:image/png"))
        self.core.execute("pet.trash.restore", self.context(trashId=moved["trashId"]))
        self.assertEqual(self.pet.pet_id, "mori-bot")
        self.assertEqual(self.settings.value("pets/custom/width"), 224)
        moved = self.core.execute("pet.trash.move", self.context(id="custom"))
        self.core.execute("pet.trash.delete", self.context(trashId=moved["trashId"]))
        self.assertIsNone(self.settings.value("pets/custom/width"))
        self.assertEqual(self.core.trash_catalog()["total"], 0)

    def test_trash_protects_builtin_and_rejects_stale_context_and_epoch(self):
        self.install_user_pet("custom")
        self.assertFalse(
            next(
                row for row in self.core.catalog()["entries"] if row["id"] == "mori-bot"
            )["canDelete"]
        )
        with self.assertRaises(CommandError):
            self.core.execute("pet.trash.move", self.context(id="mori-bot"))
        for change in ({"revision": -1}, {"petId": "other"}, {"epoch": -1}):
            args = self.context(id="custom")
            args.update(change)
            with self.assertRaises(CommandError):
                self.core.execute("pet.trash.move", args)
        self.assertTrue((self.root / "pets" / "custom").exists())

    def test_current_pet_requires_successful_replacement_before_move(self):
        self.install_user_pet("custom")
        self.core.execute("pet.select", self.context(id="custom"))
        with self.assertRaises(CommandError):
            self.core.execute("pet.trash.move", self.context(id="custom"))
        with patch.object(self.vm, "change_pet", return_value=False):
            with self.assertRaises(CommandError):
                self.core.execute(
                    "pet.trash.move",
                    self.context(id="custom", replacementId="mori-bot"),
                )
        self.assertEqual(self.pet.pet_id, "custom")
        self.assertTrue((self.root / "pets" / "custom").exists())
        self.preferences.save_hidden_pet_ids(("mori-bot",))
        self.core.execute(
            "pet.trash.move", self.context(id="custom", replacementId="mori-bot")
        )
        self.assertEqual(self.pet.pet_id, "mori-bot")
        self.assertNotIn("mori-bot", self.preferences.load_hidden_pet_ids())
        self.assertFalse((self.root / "pets" / "custom").exists())

    def test_current_pet_move_failure_returns_to_previous_pet(self):
        self.install_user_pet("custom")
        self.core.execute("pet.select", self.context(id="custom"))
        with patch.object(self.vm.packages, "move", side_effect=PermissionError()):
            with self.assertRaises(CommandError):
                self.core.execute(
                    "pet.trash.move",
                    self.context(id="custom", replacementId="mori-bot"),
                )
        self.assertEqual(self.pet.pet_id, "custom")
        self.assertEqual(self.preferences.load_selected_pet_id(), "custom")

    def test_select_hidden_pet_reveals_it_and_failure_restores_visibility(self):
        destination = self.install_user_pet("custom")
        self.preferences.save_hidden_pet_ids(("custom",))
        with patch.object(self.vm, "change_pet", return_value=False):
            with self.assertRaises(CommandError):
                self.core.execute("pet.select", self.context(id="custom"))
        self.assertIn("custom", self.preferences.load_hidden_pet_ids())
        self.core.execute("pet.select", self.context(id="custom"))
        self.assertNotIn("custom", self.preferences.load_hidden_pet_ids())
        self.assertEqual(self.pet.pet_directory, destination)

    def test_import_from_trash_proposes_restore_without_duplicating_or_switching(self):
        prepared = self.prepare_import()
        added = self.core.execute(
            "pet.import.commit", dict(token=prepared["token"], name="복원할 펫")
        )
        moved = self.core.execute("pet.trash.move", self.context(id=added["id"]))
        result = self.core.execute(
            "pet.import.commit", dict(token=prepared["token"], name="덮어쓰면 안 됨")
        )
        self.assertTrue(result["restoreRequired"])
        self.assertEqual(result["trashId"], moved["trashId"])
        self.assertEqual(self.pet.pet_id, "mori-bot")
        self.assertNotIn(added["id"], {entry.id for entry in self.vm.all_pets()})
        self.core.execute("pet.trash.restore", self.context(trashId=result["trashId"]))
        self.assertEqual(
            next(
                entry.display_name
                for entry in self.vm.all_pets()
                if entry.id == added["id"]
            ),
            "복원할 펫",
        )

    def test_empty_trash_retains_failed_items_and_reports_partial_result(self):
        for pet_id in ("first", "second"):
            self.install_user_pet(pet_id)
            self.core.execute("pet.trash.move", self.context(id=pet_id))
        original = self.vm.packages.delete
        calls = []

        def delete(trash_id):
            calls.append(trash_id)
            if len(calls) == 1:
                raise PermissionError()
            original(trash_id)

        with patch.object(self.vm.packages, "delete", side_effect=delete):
            result = self.core.execute("pet.trash.empty", self.context())
        self.assertEqual(result["deleted"], 1)
        self.assertEqual(len(result["failed"]), 1)
        self.assertEqual(self.core.trash_catalog()["total"], 1)

    def test_import_registers_without_switching_and_uses_existing_selection(self):
        original_id = self.pet.pet_id
        self.pet.set_state("running")
        original_theme = self.pet.bubble_controller.theme
        prepared = self.prepare_import()
        self.assertEqual(set(prepared), {"token", "name", "thumbnail", "spriteVersion"})
        self.assertNotIn(str(self.root), json.dumps(prepared))
        revision = self.core.revision
        result = self.core.execute(
            "pet.import.commit", dict(token=prepared["token"], name="나의 웹 펫")
        )
        self.assertEqual(self.pet.pet_id, original_id)
        self.assertEqual(self.pet.current_state, "running")
        self.assertEqual(self.pet.bubble_controller.theme, original_theme)
        self.assertGreater(self.core.revision, revision)
        self.assertIn(
            result["id"], {row["id"] for row in self.core.catalog()["entries"]}
        )
        self.core.execute("pet.select", self.context(id=result["id"]))
        self.assertEqual(self.pet.pet_id, result["id"])
        self.assertEqual(self.pet.sprite_version, 2)
        self.assertEqual(len(self.pet.look_frames), 16)
        (self.root / "웹 펫.png").unlink()
        self.assertEqual(
            resolve_startup_pet(
                preferences=self.preferences,
                pets_root=Path("pets"),
                additional_pets_roots=(self.root / "pets",),
            ),
            self.root / "pets" / result["id"],
        )
        restored = DesktopPet(
            self.root / "pets" / result["id"],
            settings=self.settings,
            user_pets_root=self.root / "pets",
        )
        self.addCleanup(restored.close)
        self.assertEqual(restored.pet_id, result["id"])
        self.assertEqual(restored.pet_display_name, "나의 웹 펫")

    def test_import_cancel_disconnect_and_timer_clear_preparation(self):
        prepared = self.prepare_import()
        self.core.execute("pet.import.cancel", dict(token=prepared["token"]))
        self.assertIsNone(self.core.pet_importer.prepared)
        self.prepare_import()
        self.host._disconnect()
        self.assertIsNone(self.core.pet_importer.prepared)
        self.prepare_import()
        self.core.import_timer.start(1)
        self.assertTrue(wait_until(lambda: self.core.pet_importer.prepared is None))
        self.assertFalse((self.root / "pets").exists())

    def test_import_errors_remain_specific_and_selection_failure_keeps_current_pet(
        self,
    ):
        with self.assertRaisesRegex(CommandError, "파일"):
            self.host._execute(
                "file.pet.prepare", dict(path=str(self.root / "missing.png"))
            )
        prepared = self.prepare_import(version=1)
        with self.assertRaisesRegex(CommandError, "이름"):
            self.core.execute(
                "pet.import.commit", dict(token=prepared["token"], name=" ")
            )
        result = self.core.execute(
            "pet.import.commit", dict(token=prepared["token"], name="V1")
        )
        duplicate = self.core.execute(
            "pet.import.commit", dict(token=prepared["token"], name="rename")
        )
        self.assertTrue(duplicate["alreadyExists"])
        self.assertEqual(duplicate["name"], "V1")
        original_id = self.pet.pet_id
        (self.root / "pets" / result["id"] / "spritesheet.webp").write_bytes(b"broken")
        with self.assertRaisesRegex(CommandError, "불러오지"):
            self.core.execute("pet.select", self.context(id=result["id"]))
        self.assertEqual(self.pet.pet_id, original_id)

    def test_raw_import_path_is_not_a_renderer_command(self):
        exposure = Path("settings-ui/electron/commands.generated.cjs").read_text(
            encoding="utf-8"
        )
        allowed = json.loads(exposure.split("module.exports = ", 1)[1].rstrip(";\n"))[
            "renderer"
        ]
        self.assertNotIn("file.pet.prepare", allowed)
        with self.assertRaises(CommandError):
            self.core.execute("file.pet.prepare", dict(path="C:/private.png"))

    def assistant(self):
        self.runtime = ApplicationRuntime(
            self.app,
            self.pet,
            self.preferences,
            AppPaths(self.root),
            codex_server=isolated_codex_server(self.root),
            codex_sessions_root=self.root / "sessions",
        )
        self.runtime.settings_vm.startup_registration = FakeStartupRegistration()
        self.claude_settings = self.root / "claude" / "settings.json"
        self.runtime.integrations_vm.claude_code_installer = ClaudeCodeHookInstaller(
            settings_path=self.claude_settings,
            commands=build_managed_commands(executable=self.root / "Bridge.exe"),
            policy_paths=(),
        )
        # Turning Claude Code on also writes its status line; keep it per test.
        status_line = ClaudeCodeStatusLineInstaller(
            settings_path=self.claude_settings,
            sidecar_path=self.root / "claude-code-status-line.json",
        )
        status_line._hooks.policy_paths = ()
        self.runtime.claude_code_status_line_installer = status_line
        self.runtime.integrations_vm.status_line_installer = status_line
        # Tool switches write hook files; never the developer's real ~/.codex.
        from watched_kettle.integrations.codex_install import CodexHookInstaller

        self.runtime.integrations_vm.hook_installer = CodexHookInstaller(
            hooks_path=self.root / "codex" / "hooks.json",
            config_path=self.root / "codex" / "config.toml",
        )
        return self.runtime.center.adapter

    @staticmethod
    def switch_tool(core, tool, enabled):
        """Turn one tool on or off the way the connections page does."""
        plan = core.execute(
            "integration.preview",
            dict(
                epoch=core.account_epoch,
                operation="enable" if enabled else "disable",
                provider=tool,
            ),
        )
        core.execute(
            "integration.apply", dict(epoch=core.account_epoch, token=plan["token"])
        )
        return plan

    @staticmethod
    def adapter_context(core, **args):
        return dict(
            petId=core.pet_vm.snapshot.pet_id,
            revision=core.revision,
            epoch=core.account_epoch,
            **args,
        )

    def test_update_auto_check_setting_and_one_notice_per_version(self):
        self.assertTrue(self.core.snapshot()["update"]["auto_check"])
        self.core.execute(
            "settings.set", self.context(key="update_auto_check", value=False)
        )
        self.assertFalse(self.preferences.load_update_auto_check())
        self.assertFalse(self.core.snapshot()["update"]["auto_check"])
        with patch.object(self.vm, "announce", return_value=True) as announce:
            self.core.updates.found.emit("9.9.9")
            self.core.updates.found.emit("9.9.9")
        announce.assert_called_once()
        self.assertIn("(v9.9.9)", announce.call_args.args[0])
        self.assertEqual(self.preferences.load_update_announced_version(), "9.9.9")

    def test_an_update_tells_once_where_to_see_whats_new(self):
        # setUp's adapter is a new install: it records the version silently.
        self.assertEqual(
            self.preferences.load_last_launched_version(), APPLICATION_VERSION
        )
        cases = (
            ("", False),
            (APPLICATION_VERSION, False),
            ("99.0.0", False),
            ("0.0.1", True),
            # Shown or not, the notice is not replayed on the next start.
            (APPLICATION_VERSION, False),
            # 0.15.6 and earlier recorded only update checks.
            (None, True),
        )
        with patch(
            "watched_kettle.application.settings_ui.core.UPDATED_NOTICE_DELAY_MS", 0
        ):
            for previous, expected in cases:
                with (
                    self.subTest(previous=previous),
                    patch.object(self.vm, "announce", return_value=False) as announce,
                ):
                    if previous is None:
                        self.settings.remove("updates/lastLaunchedVersion")
                        self.preferences.save_update_last_check(1_700_000_000)
                    else:
                        self.settings.setValue("updates/lastLaunchedVersion", previous)
                    self.core._note_launched_version()
                    QTest.qWait(20)
                    self.assertEqual(announce.called, expected)
                    if expected:
                        self.assertIn(
                            f"(v{APPLICATION_VERSION})", announce.call_args.args[0]
                        )
                    self.assertEqual(
                        self.preferences.load_last_launched_version(),
                        APPLICATION_VERSION,
                    )

    def test_about_page_reaches_both_editions_without_local_paths(self):
        host = SettingsWindowHost(self.core)
        try:
            host.open_route("about", show=False)
            self.assertEqual(host.route["page"], "about")
        finally:
            host.shutdown()
        about = self.core.snapshot()["about"]
        self.assertEqual(about["version"], APPLICATION_VERSION)
        self.assertEqual(about["edition"], "pet-only")
        self.assertEqual(about["whatsNewVersion"], APPLICATION_VERSION)
        self.assertTrue(about["whatsNew"])
        for url in about["links"].values():
            self.assertTrue(
                url.startswith("https://github.com/leewb2280/watched-kettle"), url
            )
        # A source run has no bundled licenses folder, and no path is sent.
        self.assertFalse(about["licensesAvailable"])
        self.assertNotIn(str(Path.cwd()), json.dumps(about, ensure_ascii=False))

    def test_licenses_folder_opens_only_when_bundled(self):
        with self.assertRaises(CommandError):
            self.core.execute("about.open_licenses", {})
        folder = self.root / "licenses"
        folder.mkdir()
        with (
            patch(
                "watched_kettle.application.settings_ui.core.licenses_folder",
                return_value=folder,
            ),
            patch(
                "watched_kettle.application.settings_ui.core.QDesktopServices.openUrl",
                return_value=True,
            ) as open_url,
        ):
            self.assertEqual(
                self.core.execute("about.open_licenses", {}), {"opened": True}
            )
        self.assertEqual(Path(open_url.call_args.args[0].toLocalFile()), folder)

    def test_an_app_notice_keeps_to_bubbles_off_snooze_and_a_hidden_pet(self):
        controller = self.pet.bubble_controller
        with patch.object(controller, "preview") as preview:
            self.pet.hide()
            self.assertFalse(self.vm.announce("새 버전"))
            self.pet.show()
            controller.snooze(60_000)
            self.assertFalse(self.vm.announce("새 버전"))
            controller.resume()
            controller.set_enabled(False)
            self.assertFalse(self.vm.announce("새 버전"))
            controller.set_enabled(True)
            self.assertTrue(self.vm.announce("새 버전"))
        preview.assert_called_once_with("새 버전", duration_ms=10_000)

    def test_real_settings_round_trip_and_stale_editor(self):
        draft = self.core.editor()
        result = self.core.execute("settings.set", self.context(key="width", value=144))
        self.assertTrue(result["saved"])
        self.assertEqual(result["snapshot"]["pet"]["pet_width"], 144)
        reopened = QSettings(self.settings.fileName(), QSettings.Format.IniFormat)
        self.assertEqual(reopened.allKeys(), self.settings.allKeys())
        self.assertEqual(reopened.value(f"pets/{self.pet.pet_id}/width", type=int), 144)
        with self.assertRaisesRegex(CommandError, "변경"):
            self.core.execute(
                "bubble.save",
                dict(
                    theme=draft["theme"],
                    petId=draft["petId"],
                    revision=draft["revision"],
                ),
            )

    def test_pet_size_control_restores_labels_presets_and_range_description(self):
        width = next(
            control
            for control in self.core.snapshot()["controls"]
            if control["key"] == "width"
        )

        self.assertEqual(width["kind"], "pet_size")
        self.assertEqual((width["min"], width["max"], width["step"]), (0, 9, 1))
        self.assertEqual(len(width["options"]), 10)
        self.assertIn({"value": 192, "label": "192px · 원본 크기"}, width["options"])
        self.assertIn({"value": 256, "label": "256px · 확장 크기"}, width["options"])
        self.assertEqual(
            width["presets"],
            [
                {"value": 112, "label": "기본"},
                {"value": 192, "label": "원본"},
                {"value": 224, "label": "표준 최대"},
                {"value": 352, "label": "확장 최대"},
            ],
        )
        self.assertIn("원본 스프라이트 셀은 192×208px", width["description"])
        self.assertIn("256~352px는 큰 화면용 확장 크기", width["description"])

    def test_look_range_control_exposes_pixel_unit(self):
        look = next(
            control
            for control in self.core.snapshot()["controls"]
            if control["key"] == "look"
        )

        self.assertEqual(look["kind"], "range")
        self.assertEqual(look["unit"], "px")
        self.assertEqual((look["min"], look["max"], look["step"]), (120, 480, 20))

    def test_pet_preview_uses_original_cell_and_does_not_change_revision(self):
        before = self.core.revision
        preview = self.core.execute("pet.preview", {"petId": self.vm.snapshot.pet_id})
        encoded = preview["image"].split(",", 1)[1]
        image = Image.open(BytesIO(base64.b64decode(encoded)))

        self.assertEqual(preview["petId"], self.vm.snapshot.pet_id)
        self.assertEqual(preview["sourceSize"], {"width": 192, "height": 208})
        self.assertEqual(
            image.size,
            (preview["cropBounds"]["width"], preview["cropBounds"]["height"]),
        )
        self.assertNotEqual(image.size, (96, 104))
        self.assertGreater(preview["contentBounds"]["width"], 0)
        self.assertGreater(preview["contentBounds"]["height"], 0)
        self.assertEqual(preview["revision"], before)
        self.assertEqual(self.core.revision, before)

    def test_pet_preview_uses_full_cell_when_alpha_is_empty(self):
        spritesheet = self.root / "empty-preview.png"
        Image.new("RGBA", (192, 208), (0, 0, 0, 0)).save(spritesheet)
        entry = SimpleNamespace(id="empty", spritesheet_path=spritesheet)

        with patch.object(self.vm, "all_pets", return_value=(entry,)):
            preview = self.core.pet_preview("empty")

        self.assertEqual(
            preview["contentBounds"],
            {"x": 0, "y": 0, "width": 192, "height": 208},
        )
        self.assertEqual(
            preview["cropBounds"],
            {"x": 0, "y": 0, "width": 192, "height": 208},
        )

    def test_pet_preview_rejects_unknown_pet(self):
        with self.assertRaisesRegex(CommandError, "찾을 수 없습니다"):
            self.core.execute("pet.preview", {"petId": "missing"})

    def test_pet_preview_tracks_selection_and_revision_boundary(self):
        original_id = self.vm.snapshot.pet_id
        original_entry = next(
            entry for entry in self.vm.all_pets() if entry.id == original_id
        )
        alternate_entry = SimpleNamespace(
            id="alternate-preview", spritesheet_path=original_entry.spritesheet_path
        )

        with patch.object(
            self.vm, "all_pets", return_value=(original_entry, alternate_entry)
        ):
            old_preview = self.core.execute("pet.preview", {"petId": original_id})
            self.core.revision += 1
            new_preview = self.core.execute(
                "pet.preview", {"petId": alternate_entry.id}
            )

        self.assertEqual(old_preview["petId"], original_id)
        self.assertEqual(new_preview["petId"], alternate_entry.id)
        self.assertGreater(new_preview["revision"], old_preview["revision"])
        self.assertEqual(new_preview["revision"], self.core.revision)

    def test_animation_does_not_invalidate_draft_and_preview_is_isolated(self):
        draft = self.core.editor()
        self.pet.set_state("working")
        self.vm.refresh()
        self.assertEqual(draft["revision"], self.core.revision)
        before = self.pet.bubble_controller.theme
        result = self.core.execute(
            "bubble.render", dict(theme={**draft["theme"], "background": "#ff0000"})
        )
        self.assertTrue(result["image"].startswith("data:image/png;base64,"))
        self.assertEqual(before, self.pet.bubble_controller.theme)
        self.assertIsNone(self.pet.custom_bubble_theme)

    def test_catalog_lists_name_order_with_sharp_cropped_thumbnails(self):
        real = next(iter(self.vm.all_pets()))
        broken = self.root / "broken.png"
        broken.write_bytes(b"not an image")

        def entry(pet_id, name, path):
            return SimpleNamespace(
                id=pet_id,
                display_name=name,
                description="",
                spritesheet_path=path,
                directory=Path("pets") / pet_id,
            )

        entries = (
            entry("zeta", "Zeta", real.spritesheet_path),
            entry("alpha", "alpha", real.spritesheet_path),
            entry("broken", "Mid", broken),
        )
        with patch.object(self.vm, "all_pets", return_value=entries):
            catalog = self.core.catalog()

        rows = catalog["entries"]
        self.assertEqual([row["id"] for row in rows], ["alpha", "broken", "zeta"])
        self.assertEqual(rows[1]["thumbnail"], "")
        encoded = rows[0]["thumbnail"].split(",", 1)[1]
        thumbnail = Image.open(BytesIO(base64.b64decode(encoded)))
        self.assertEqual(thumbnail.format, "PNG")
        self.assertLessEqual(thumbnail.width, 220)
        self.assertLessEqual(thumbnail.height, 240)
        # Larger than the old 96px tile because transparent margins are cropped.
        self.assertGreater(max(thumbnail.size), 104)

    def test_editor_exposes_normalization_limits_and_frame_labels(self):
        editor = self.core.editor()
        self.assertEqual(
            {key: (row["min"], row["max"]) for key, row in editor["limits"].items()},
            BUBBLE_THEME_LIMITS,
        )
        self.assertEqual(editor["limits"]["radius"]["unit"], "px")
        self.assertEqual(editor["limits"]["border_width"]["step"], 0.05)
        self.assertEqual(editor["labels"]["frame_style"]["standard"], "기본")
        for style in editor["choices"]["frame_style"]:
            self.assertIn(style, editor["labels"]["frame_style"])
        rendered = self.core.execute(
            "bubble.render", dict(theme={**editor["theme"], "radius": 500})
        )
        self.assertEqual(rendered["theme"]["radius"], BUBBLE_THEME_LIMITS["radius"][1])

    def test_element_import_keeps_registry_reason(self):
        not_image = self.root / "note.png"
        not_image.write_bytes(b"plain text")

        with self.assertRaises(CommandError) as raised:
            self.core.import_element(not_image, "ornament")

        self.assertEqual(raised.exception.code, "element_invalid")
        self.assertNotIn("요청을 처리하지 못했습니다", str(raised.exception))
        self.assertTrue(str(raised.exception))

    def test_custom_theme_choice_explains_missing_custom_design(self):
        def theme_control():
            return next(
                control
                for control in self.core.snapshot()["bubbleControls"]
                if control["key"] == "bubble_theme"
            )

        self.assertIsNone(self.pet.custom_bubble_theme)
        missing = theme_control()
        custom = next(row for row in missing["options"] if row["value"] == "custom")
        self.assertIn("아직 없음", custom["label"])
        self.assertIn("말풍선 꾸미기", missing["description"])

        self.core.execute(
            "bubble.save", self.context(theme=self.core.editor()["theme"])
        )
        saved = theme_control()
        custom = next(row for row in saved["options"] if row["value"] == "custom")
        self.assertEqual(custom["label"], "내가 꾸민 디자인")
        self.assertIsNone(saved["description"])

    def test_catalog_and_editor_have_real_assets_and_fields(self):
        catalog = self.core.catalog()
        self.assertTrue(catalog["entries"])
        self.assertTrue(
            all(
                row["thumbnail"].startswith("data:image/png")
                for row in catalog["entries"]
            )
        )
        editor = self.core.editor()
        self.assertIn("shape", editor["choices"])
        self.core.execute("bubble.save", self.context(theme=editor["theme"]))
        self.assertIsNotNone(self.pet.custom_bubble_theme)
        self.core.execute("bubble.reset", self.context())
        self.assertIsNone(self.pet.custom_bubble_theme)

    def test_appearance_changes_merge_with_latest_saved_fields(self):
        self.core.execute(
            "settings.set", self.context(key="appearance:theme", value="dark")
        )
        self.core.execute(
            "settings.set", self.context(key="appearance:material", value="mica")
        )
        self.assertEqual(self.core.appearance()["theme"], "dark")
        self.assertEqual(self.core.appearance()["material"], "mica")

    def test_pet_only_rejects_assistant_commands_and_invalid_values(self):
        for method, args in (
            ("usage.snapshot", {}),
            ("settings.set", self.context(key="width", value=True)),
            ("settings.set", self.context(key="bubbles", value=True)),
        ):
            with self.assertRaises(CommandError):
                self.core.execute(method, args)
        self.assertEqual(self.core.snapshot()["edition"], "pet-only")
        self.assertNotIn("expected_command", self.core.snapshot()["startup"])

    def test_update_open_accepts_official_and_local_test_pages_only(self):
        updates = self.core.updates
        target = "watched_kettle.application.settings_ui.core.QDesktopServices.openUrl"
        with patch(target, return_value=True) as open_url:
            for url in (
                "https://github.com/leewb2280/watched-kettle/releases/tag/v9.9.9",
                "http://127.0.0.1:8765/releases/tag/v9.9.9",
            ):
                updates._set("available", "새 버전", page_url=url)
                self.assertEqual(
                    self.core.execute("update.open", {}), dict(opened=True)
                )
                self.assertEqual(open_url.call_args.args[0].toString(), url)
            for url in (
                "",
                "http://github.com/leewb2280/watched-kettle/releases",
                "http://localhost:8765/releases/tag/v9.9.9",
                "https://example.com/releases/tag/v9.9.9",
            ):
                updates._set("available", "새 버전", page_url=url)
                with self.assertRaises(CommandError):
                    self.core.execute("update.open", {})
            self.assertEqual(open_url.call_count, 2)

    def test_update_state_reaches_the_snapshot_and_download_is_guarded(self):
        updates = self.core.updates
        changes = []
        self.core.changed.connect(changes.append)
        self.assertEqual(self.core.snapshot()["update"]["state"], "idle")
        json.dumps(self.core.snapshot()["update"])
        # A release the installer cannot apply here (source run) is refused.
        updates._set("available", "새 버전", version="9.9.9", can_install=False)
        self.assertIn("settings", changes)
        self.assertEqual(self.core.snapshot()["update"]["version"], "9.9.9")
        with patch.object(updates, "download") as download:
            with self.assertRaises(CommandError):
                self.core.execute("update.download", {})
            download.assert_not_called()
            updates._set("available", "새 버전", can_install=True)
            self.assertEqual(
                self.core.execute("update.download", {}), dict(pending=True)
            )
            download.assert_called_once()
        with patch.object(updates, "cancel") as cancel:
            self.core.execute("update.cancel", {})
            cancel.assert_called_once()
        # The pet says the app will be back while the silent install runs.
        with patch.object(self.vm, "preview_bubble") as preview:
            updates._set("installing", "설치")
            preview.assert_called_once_with("업데이트를 설치하고 곧 다시 켜집니다.")

    def test_real_assistant_models_are_serializable_and_widget_mutations_apply(self):
        core = self.assistant()
        for method in (
            "settings.snapshot",
            "usage.snapshot",
            "activity.snapshot",
            "integration.snapshot",
        ):
            json.dumps(core.execute(method, {}))
        core.execute(
            "usage.set", dict(epoch=core.account_epoch, key="widget_scale", value=90)
        )
        self.assertEqual(self.runtime.usage_vm.widget_scale_percent, 90)
        with self.assertRaises(CommandError):
            core.execute("usage.set", dict(epoch=-1, key="widget_scale", value=100))

    def test_acrylic_material_turns_off_color_and_opacity_controls(self):
        core = self.assistant()

        def controls():
            return {
                control["key"]: control
                for control in core.execute("usage.snapshot", {})["controls"]
            }

        def set_material(value):
            core.execute(
                "usage.set",
                dict(epoch=core.account_epoch, key="widget_material", value=value),
            )

        target = "watched_kettle.application.settings_ui.assistant.acrylic_available"
        with patch(target, return_value=True):
            self.assertEqual(controls()["widget_material"]["value"], "opaque")
            self.assertFalse(controls()["widget_material"]["disabled"])
            set_material("acrylic")
            self.assertEqual(self.runtime.usage_vm.widget_material, "acrylic")
            for key in ("widget_theme", "widget_color", "widget_opacity"):
                self.assertTrue(controls()[key]["disabled"], key)
            self.assertFalse(controls()["widget_scale"]["disabled"])
            # Resetting the style returns to the opaque card.
            self.runtime.usage_vm.preferences.reset_usage_widget_style()
            self.assertEqual(self.runtime.usage_vm.widget_material, "opaque")
            with self.assertRaises(CommandError):
                set_material("mica")
        with patch(target, return_value=False):
            material = controls()["widget_material"]
            self.assertTrue(material["disabled"])
            self.assertIn("Windows 11", material["description"])

    def test_usage_controls_follow_widget_switch_and_integration_reports_state(self):
        core = self.assistant()

        def controls():
            return {
                control["key"]: control
                for control in core.execute("usage.snapshot", {})["controls"]
            }

        usage = core.execute("usage.snapshot", {})
        self.assertIsInstance(usage["enabled"], bool)
        self.assertNotIn("enabled", controls())
        self.assertEqual(controls()["widget_shape"]["value"], "rings")
        self.assertTrue(controls()["widget_emphasis"]["description"])
        # The background color only applies when it is chosen directly, and
        # says so while it is locked.
        self.assertTrue(controls()["widget_color"]["disabled"])
        self.assertEqual(
            controls()["widget_color"]["description"],
            t("usage.widget_color_description"),
        )
        core.execute(
            "usage.set",
            dict(epoch=core.account_epoch, key="widget_theme", value="custom"),
        )
        self.assertFalse(controls()["widget_color"]["disabled"])
        core.execute(
            "usage.set",
            dict(epoch=core.account_epoch, key="widget_shape", value="chips"),
        )
        self.assertEqual(self.runtime.usage_vm.widget_shape, "chips")
        with self.assertRaises(CommandError):
            core.execute(
                "usage.set",
                dict(epoch=core.account_epoch, key="widget_shape", value="donut"),
            )
        core.execute(
            "usage.set",
            dict(epoch=core.account_epoch, key="widget_visible", value=False),
        )
        hidden = controls()
        self.assertFalse(hidden["widget_visible"].get("disabled"))
        self.assertFalse(hidden["chart_days"].get("disabled"))
        for key in ("widget_shape", "widget_emphasis", "widget_today", "widget_color"):
            self.assertTrue(hidden[key]["disabled"], key)
        core.execute(
            "usage.set",
            dict(epoch=core.account_epoch, key="widget_visible", value=True),
        )
        self.assertFalse(controls()["widget_shape"]["disabled"])

        integration = core.execute("integration.snapshot", {})
        json.dumps(integration)
        self.assertIn(
            integration["install"]["state"],
            {
                "installed",
                "not_installed",
                "partial",
                "drifted",
                "other_copy",
                "disabled",
                "invalid",
            },
        )
        self.assertEqual(integration["install"]["message"], integration["status"])

        from watched_kettle.features.integrations.watch import ConnectionAlert

        watch = self.runtime.connection_watch
        # The snapshot's own refresh would check the isolated tools again.
        self.runtime.integrations_vm.snapshot_changed.disconnect(watch.check)
        watch.snapshot = (ConnectionAlert("claude_code", "found"),)
        self.assertEqual(
            core.execute("integration.snapshot", {})["connection_alerts"],
            [{"tool": "claude_code", "kind": "found"}],
        )

    def test_switched_off_codex_stops_readers_but_explicit_app_launch_stays(self):
        core = self.assistant()
        runtime = self.runtime
        from watched_kettle.integrations.windows_apps import AppOpenResult
        from unittest.mock import Mock

        opener = Mock(return_value=AppOpenResult(True))
        runtime.pet_actions.openers["codex"] = opener
        runtime.preferences.save_double_click_action("codex")
        runtime.start()
        self.assertTrue(runtime.codex_log_monitor.is_active)
        self.switch_tool(core, "codex", False)
        self.assertFalse(runtime.codex_log_monitor.is_active)
        self.assertFalse(runtime.metadata_service.enabled)
        self.assertFalse(runtime.metadata_service.refresh_timer.isActive())
        self.assertIn("codex", runtime.codex_server.disabled_sources)
        self.pet.double_click_requested.emit()
        opener.assert_called_once_with()
        self.switch_tool(core, "codex", True)
        self.assertTrue(runtime.codex_log_monitor.is_active)
        self.assertTrue(runtime.metadata_service.refresh_timer.isActive())
        self.assertNotIn("codex", runtime.codex_server.disabled_sources)
        self.assertIs(runtime.pet_actions.openers["codex"], opener)

    def test_tool_switches_are_independent_and_only_on_the_connections_page(self):
        core = self.assistant()
        context = dict(epoch=core.account_epoch)
        # Claude Code is off until chosen; it never follows the Codex switch.
        self.assertFalse(core.execute("usage.snapshot", {})["claude_code_enabled"])
        self.switch_tool(core, "claude_code", True)
        self.switch_tool(core, "codex", False)
        snapshot = core.execute("usage.snapshot", {})
        self.assertFalse(snapshot["enabled"])
        self.assertTrue(snapshot["claude_code_enabled"])
        self.assertTrue(snapshot["any_enabled"])
        self.assertEqual([g["key"] for g in snapshot["limit_groups"]], ["claude_code"])
        self.switch_tool(core, "claude_code", False)
        self.assertFalse(core.execute("usage.snapshot", {})["any_enabled"])
        self.switch_tool(core, "codex", True)
        self.assertFalse(core.execute("usage.snapshot", {})["claude_code_enabled"])
        for key in ("enabled", "claude_code_enabled"):
            with self.assertRaises(CommandError):
                core.execute("usage.set", dict(**context, key=key, value=True))
        with self.assertRaises(CommandError):
            core.execute(
                "integration.preview",
                dict(**context, operation="enable", provider="claude_code_status_line"),
            )

    def test_usage_trends_are_per_tool_and_follow_switches(self):
        core = self.assistant()
        context = dict(epoch=core.account_epoch)
        trends = core.execute("usage.snapshot", {})["trends"]
        self.assertIn(trends["now_hour"], range(24))
        for tool in ("codex", "claude_code"):
            self.assertLessEqual(
                {"enabled", "hours", "quota", "daily"}, set(trends[tool])
            )
            self.assertLessEqual(
                {"days", "total", "average", "peak_date"}, set(trends[tool]["daily"])
            )
        self.assertTrue(trends["codex"]["enabled"])
        self.assertFalse(trends["claude_code"]["enabled"])
        self.switch_tool(core, "claude_code", True)
        self.assertTrue(
            core.execute("usage.snapshot", {})["trends"]["claude_code"]["enabled"]
        )
        self.switch_tool(core, "codex", False)
        self.assertFalse(
            core.execute("usage.snapshot", {})["trends"]["codex"]["enabled"]
        )
        # Every offered range is kept; 14 days used to fall back to 7.
        core.execute("usage.set", dict(**context, key="chart_days", value=14))
        days = next(
            control
            for control in core.execute("usage.snapshot", {})["controls"]
            if control["key"] == "chart_days"
        )
        self.assertEqual(days["value"], 14)
        self.assertEqual([o["value"] for o in days["options"]], [7, 14, 30])

    def test_bubble_duration_controls_expose_effective_policy_and_units(self):
        core = self.assistant()
        controls = {
            control["key"]: control for control in core.snapshot()["bubbleControls"]
        }

        self.assertEqual(controls["bubble_duration"]["unit"], "초")
        for kind in ("result", "general", "schedule"):
            control = controls[f"duration:{kind}"]
            self.assertEqual(control["kind"], "optional_number")
            self.assertIsNone(control["value"])
            self.assertEqual(control["effectiveValue"], 8)
            self.assertEqual(control["fallbackLabel"], "공통 시간")
            self.assertEqual(control["unit"], "초")
        completion = controls["duration:completion"]
        self.assertIsNone(completion["value"])
        self.assertEqual(completion["effectiveValue"], 15)
        self.assertEqual(completion["fallbackLabel"], "완료 기본값")

    def test_bubble_scale_and_timing_share_sections_and_follow_bubble_switch(self):
        core = self.assistant()
        timing_keys = ("bubble_duration",) + tuple(
            f"duration:{kind}"
            for kind in ("result", "general", "schedule", "completion")
        )

        def controls():
            return {
                control["key"]: control for control in core.snapshot()["bubbleControls"]
            }

        current = controls()
        self.assertEqual(current["bubble_scale"]["unit"], "%")
        self.assertEqual({current[key]["group"] for key in timing_keys}, {"표시 시간"})
        for key in ("bubble_scale",) + timing_keys:
            self.assertFalse(current[key]["disabled"], key)

        core.execute(
            "settings.set", self.adapter_context(core, key="bubbles", value=False)
        )
        muted = controls()
        for key in ("bubble_scale",) + timing_keys:
            self.assertTrue(muted[key]["disabled"], key)
        self.assertNotIn("disabled", muted["bubbles"])
        self.assertEqual(
            muted["bubble_scale"]["value"], current["bubble_scale"]["value"]
        )

        core.execute(
            "settings.set", self.adapter_context(core, key="bubbles", value=True)
        )
        for key in ("bubble_scale",) + timing_keys:
            self.assertFalse(controls()[key]["disabled"], key)

    def test_duration_override_reset_preserves_common_and_full_reset_compatibility(
        self,
    ):
        core = self.assistant()

        core.execute(
            "settings.set",
            self.adapter_context(core, key="bubble_duration", value=23),
        )
        for index, kind in enumerate(
            ("result", "general", "schedule", "completion"), start=1
        ):
            core.execute(
                "settings.set",
                self.adapter_context(core, key=f"duration:{kind}", value=20 + index),
            )

        core.execute(
            "pet.action",
            self.adapter_context(core, action="duration_overrides_reset"),
        )
        policy = core.pet_vm.snapshot.bubble_duration_policy
        self.assertEqual(policy.common, 23)
        self.assertEqual(
            (policy.result, policy.general, policy.schedule, policy.completion),
            (None, None, None, None),
        )
        self.assertEqual(
            [policy.seconds(kind) for kind in ("result", "general", "schedule")],
            [23, 23, 23],
        )
        self.assertEqual(policy.seconds("completion"), 15)
        reopened = ApplicationPreferences(
            QSettings(self.settings.fileName(), QSettings.Format.IniFormat)
        ).load_bubble_duration_policy()
        self.assertEqual(reopened, policy)

        core.execute(
            "pet.action",
            self.adapter_context(core, action="durations_reset"),
        )
        self.assertEqual(
            core.pet_vm.snapshot.bubble_duration_policy.common,
            8,
        )

    def test_duration_override_accepts_null_and_range_but_rejects_outside_values(self):
        core = self.assistant()
        core.execute(
            "settings.set",
            self.adapter_context(core, key="duration:result", value=37),
        )
        self.assertEqual(core.pet_vm.snapshot.bubble_duration_policy.result, 37)
        core.execute(
            "settings.set",
            self.adapter_context(core, key="duration:result", value=None),
        )
        self.assertIsNone(core.pet_vm.snapshot.bubble_duration_policy.result)
        for value in (4, 61):
            with self.assertRaises(CommandError):
                core.execute(
                    "settings.set",
                    self.adapter_context(core, key="duration:result", value=value),
                )

    def test_response_limit_remains_bounded_and_duplicates_do_not_execute_twice(self):
        with (
            patch.object(self.host, "_send") as send,
            patch.object(
                self.host, "_execute", return_value="a" * MAX_FRAME_BYTES
            ) as execute,
        ):
            message = dict(id="one", method="settings.snapshot", args={})
            self.host._request(message)
            self.host._request(message)
            self.assertEqual(execute.call_count, 1)
            self.assertEqual(send.call_args.args[0]["error"]["code"], "response_limit")
            self.assertLess(self.host.response_bytes, 1024)
        self.host._changed("account")
        self.assertFalse(self.host.responses)

    def test_large_catalog_replies_drain_before_queued_requests(self):
        self.host._start_server()
        client = QLocalSocket()
        client.connectToServer(self.host.server.fullServerName())
        self.assertTrue(wait_until(lambda: self.host.socket is not None))
        client.write(
            json.dumps(dict(version=1, token=self.host.token)).encode() + b"\n"
        )
        self.assertEqual(json.loads(read_line(client))["event"], "ready")
        # Six individually valid replies exceed the total outbound queue cap
        # if buffered input is handled without yielding to the socket writer.
        reply = "x" * (MAX_FRAME_BYTES // 3)
        commands = [dict(id=f"large-{i}", method="pet.catalog") for i in range(6)]
        with patch.object(self.host, "_execute", return_value=reply):
            client.write(b"".join(json.dumps(row).encode() + b"\n" for row in commands))
            for row in commands:
                answer = json.loads(read_line(client))
                self.assertEqual(answer["id"], row["id"])
                self.assertEqual(answer["result"], reply)
                self.assertTrue(self.host.authenticated)
        client.abort()

    def test_named_pipe_requires_auth_then_accepts_partial_frames(self):
        self.host._start_server()
        client = QLocalSocket()
        client.connectToServer(self.host.server.fullServerName())
        self.assertTrue(client.waitForConnected(2000))
        QTest.qWait(30)
        handshake = json.dumps(dict(version=1, token=self.host.token)).encode() + b"\n"
        client.write(handshake[:12])
        client.flush()
        QTest.qWait(10)
        self.assertFalse(self.host.authenticated)
        client.write(handshake[12:])
        client.flush()
        self.assertTrue(wait_until(lambda: self.host.authenticated))
        self.assertIn(b'"ready"', read_line(client))
        client.write(b'{"id":"snapshot","method":"settings.snapshot","args":{}}\n')
        client.flush()
        # Pushed events may arrive first; the answer is the frame with our id.
        response = {}
        while response.get("id") != "snapshot":
            line = read_line(client)
            self.assertTrue(line, "no response to settings.snapshot")
            response = json.loads(line)
        self.assertEqual(response["result"]["edition"], "pet-only")
        client.abort()

    def test_save_error_never_reports_saved(self):
        with (
            patch.object(
                self.core,
                "_sync",
                side_effect=CommandError("save_failed", "save_failed"),
            ),
            patch.object(self.host, "_send") as send,
        ):
            self.host._request(
                dict(
                    id="failure",
                    method="settings.set",
                    args=self.context(key="width", value=144),
                )
            )
            self.assertFalse(send.call_args.args[0]["ok"])
            self.assertEqual(send.call_args.args[0]["error"]["code"], "save_failed")

    def test_notice_requires_visible_ack_and_account_boundary_cancels_it(self):
        core = self.assistant()
        host = self.runtime.center
        service = self.runtime.notification_service
        service.submit(NoticeRequest("qa", "only confirm after display"))
        record_id = service.snapshot.recent[0].record_id
        with patch.object(host, "_launch"):
            self.assertFalse(host.open_target(ActionTarget("notice", record_id)))
        self.assertFalse(service.snapshot.recent[0].confirmed)
        navigation_id = host.route["navigationId"]
        host.visible = True
        self.assertTrue(
            host._execute("navigation.ack", {"navigationId": navigation_id})[
                "confirmed"
            ]
        )
        self.assertTrue(service.snapshot.recent[0].confirmed)
        self.assertFalse(
            host._execute("navigation.ack", {"navigationId": navigation_id})[
                "confirmed"
            ]
        )
        service.submit(NoticeRequest("qa", "second record"))
        new_id = service.snapshot.recent[0].record_id
        with patch.object(host, "_launch"):
            host.open_target(ActionTarget("notice", new_id))
        navigation_id = host.route["navigationId"]
        core.assistant._account_changed(True)
        self.assertFalse(
            host._execute("navigation.ack", {"navigationId": navigation_id})[
                "confirmed"
            ]
        )
        self.assertFalse(service.snapshot.recent[0].confirmed)

    def test_notice_center_confirms_all_and_groups_entries(self):
        core = self.assistant()
        service = self.runtime.notification_service
        service.submit(NoticeRequest("qa", "first record"))
        service.submit(NoticeRequest("qa", "second record"))
        snapshot = core.execute("activity.snapshot", {})
        self.assertEqual({e["group"] for e in snapshot["entries"]}, {"notice"})
        with self.assertRaises(CommandError):
            core.execute("activity.confirm_all", dict(epoch=-1))
        self.assertFalse(any(r.confirmed for r in service.snapshot.recent))
        core.execute("activity.confirm_all", dict(epoch=core.account_epoch))
        self.assertTrue(all(r.confirmed for r in service.snapshot.recent))

    def test_preview_install_is_read_only_and_apply_checks_original_files(self):
        from watched_kettle.integrations.codex_install import (
            CodexHookInstaller,
            StaleHookPlanError,
        )

        core = self.assistant()
        hooks = self.root / "hooks.json"
        config = self.root / "config.toml"
        self.runtime.integrations_vm.hook_installer = CodexHookInstaller(
            hooks_path=hooks, config_path=config
        )
        self.switch_tool(core, "codex", False)
        plan = core.execute(
            "integration.preview",
            {"epoch": 0, "operation": "enable", "provider": "codex"},
        )
        self.assertFalse(hooks.exists())
        self.assertFalse(self.runtime.usage_vm.enabled)
        hooks.write_text('{"hooks": {}}', encoding="utf-8")
        with self.assertRaises(StaleHookPlanError):
            core.execute("integration.apply", {"epoch": 0, "token": plan["token"]})
        # A stale review changes neither the file nor the switch.
        self.assertEqual(hooks.read_text(encoding="utf-8"), '{"hooks": {}}')
        self.assertFalse(self.runtime.usage_vm.enabled)

    def test_codex_switch_round_trip_preserves_other_hooks_and_claude_code(self):
        from watched_kettle.integrations.codex_install import CodexHookInstaller

        core = self.assistant()
        hooks = self.root / "hooks.json"
        config = self.root / "config.toml"
        other_hook = {
            "hooks": {
                "SessionStart": [
                    {"hooks": [{"type": "command", "command": "echo user-hook"}]}
                ]
            }
        }
        hooks.write_text(json.dumps(other_hook), encoding="utf-8")
        config.write_text('model = "user-model"\n', encoding="utf-8")
        self.runtime.integrations_vm.hook_installer = CodexHookInstaller(
            hooks_path=hooks, config_path=config
        )

        def preview(operation, provider="codex"):
            return core.execute(
                "integration.preview",
                dict(epoch=core.account_epoch, operation=operation, provider=provider),
            )

        def apply(plan):
            core.execute(
                "integration.apply", dict(epoch=core.account_epoch, token=plan["token"])
            )

        apply(preview("enable", "claude_code"))
        claude_before = self.claude_settings.read_bytes()
        plan = preview("enable")
        self.assertTrue(plan["canApply"])
        self.assertIn("Codex 사용을 켭니다", plan["changes"])
        self.assertEqual(json.loads(hooks.read_text(encoding="utf-8")), other_hook)
        apply(plan)
        self.assertEqual(
            core.execute("integration.snapshot", {})["install"]["state"], "installed"
        )
        config_before = config.read_bytes()
        hooks_before = hooks.read_bytes()
        preview("disable")  # No apply: the same contract used by Cancel.
        self.assertEqual(hooks.read_bytes(), hooks_before)
        self.assertTrue(core.execute("usage.snapshot", {})["enabled"])
        apply(preview("disable"))
        snapshot = core.execute("integration.snapshot", {})
        # Off: Codex's files are not read, and its own hook is gone.
        self.assertFalse(snapshot["codex_active"])
        self.assertEqual(snapshot["install"]["state"], "inactive")
        self.assertEqual(json.loads(hooks.read_text(encoding="utf-8")), other_hook)
        self.assertEqual(config.read_bytes(), config_before)
        self.assertEqual(self.claude_settings.read_bytes(), claude_before)
        usage = core.execute("usage.snapshot", {})
        self.assertFalse(usage["enabled"])
        self.assertTrue(usage["claude_code_enabled"])
        # Repairing a switched-off tool's hook is refused.
        with self.assertRaises(CommandError):
            preview("repair")
        apply(preview("enable"))
        self.assertEqual(
            core.execute("integration.snapshot", {})["install"]["state"], "installed"
        )

    def test_claude_code_switch_and_timeouts_round_trip(self):
        core = self.assistant()
        snapshot = core.execute("integration.snapshot", {})
        json.dumps(snapshot)
        claude = snapshot["claude_code"]
        # Off by default: nothing is read beyond whether the folder exists.
        self.assertFalse(claude["active"])
        self.assertEqual(claude["install"]["state"], "inactive")
        self.assertIsNone(claude["status_line"])
        monitor = snapshot["diagnostics"]["claude_code"]["turn_end_monitor"]
        self.assertEqual(
            monitor, {"attached": True, "active_turns": 0, "detected_count": 0}
        )
        self.assertEqual((claude["work_minutes"], claude["waiting_minutes"]), (10, 30))

        plan = core.execute(
            "integration.preview",
            {"epoch": 0, "operation": "enable", "provider": "claude_code"},
        )
        self.assertTrue(plan["canApply"])
        self.assertFalse(self.claude_settings.exists())
        core.execute("integration.apply", {"epoch": 0, "token": plan["token"]})
        claude = core.execute("integration.snapshot", {})["claude_code"]
        self.assertTrue(claude["active"])
        installed = claude["install"]
        self.assertEqual(installed["state"], "installed")
        self.assertEqual(installed["installed_events"], len(MANAGED_HOOK_EVENTS))
        self.assertTrue(self.runtime.usage_vm.claude_code_enabled)

        result = core.execute(
            "integration.set",
            {"epoch": 0, "key": "claude_code_work_minutes", "value": 5},
        )
        self.assertTrue(result["saved"])
        limit = self.pet.agent_controller.inactivity_limits["claude_code"]
        self.assertEqual((limit.work_ms, limit.waiting_ms), (5 * 60_000, 30 * 60_000))
        reopened = QSettings(self.settings.fileName(), QSettings.Format.IniFormat)
        self.assertEqual(
            reopened.value("claude_code/work_timeout_minutes", type=int), 5
        )
        for args in (
            {"key": "claude_code_work_minutes", "value": 0},
            {"key": "claude_code_waiting_minutes", "value": 241},
            {"key": "unknown", "value": 5},
        ):
            with self.assertRaises(CommandError):
                core.execute("integration.set", {"epoch": 0, **args})
        for args in (
            {"operation": "install", "provider": "other"},
            {"operation": "enable", "provider": "other"},
            # Claude Code's own hooks follow its switch, not install/remove.
            {"operation": "remove", "provider": "claude_code"},
        ):
            with self.assertRaises(CommandError):
                core.execute("integration.preview", {"epoch": 0, **args})

        # The built-in status line layout is a JSON file the hook bridge reads.
        status_line = core.execute("integration.snapshot", {})["claude_code"][
            "status_line"
        ]
        self.assertEqual(status_line["layout"]["lines"][1][0], "context")
        core.execute(
            "integration.set",
            {
                "epoch": 0,
                "key": "status_line_layout",
                "value": {"lines": [["model"], ["five_hour", "x"]], "color": False},
            },
        )
        saved = core.execute("integration.snapshot", {})["claude_code"]["status_line"]
        self.assertEqual(saved["layout"]["lines"], [["model"], ["five_hour"]])
        self.assertFalse(saved["layout"]["color"])
        with self.assertRaises(CommandError):
            core.execute(
                "integration.set",
                {"epoch": 0, "key": "status_line_layout", "value": "model"},
            )

    def test_usage_sort_commands_keep_each_domain_order_contract(self):
        core = self.assistant()
        vm = self.runtime.usage_vm
        with patch.object(vm, "set_conversation_query") as query:
            core.execute(
                "usage.query",
                dict(epoch=0, kind="conversations", order="top", search="", offset=0),
            )
            query.assert_called_once_with("", "top", 0)
        with patch.object(vm, "set_task_query") as query:
            core.execute(
                "usage.query",
                dict(epoch=0, kind="tasks", order="input", search="model", limit=200),
            )
            query.assert_called_once_with("model", "input", 200, None)
        with self.assertRaises(CommandError):
            core.execute(
                "usage.query", dict(epoch=0, kind="conversations", order="custom")
            )

    def test_hidden_subscriptions_stop_and_reject_unknown_topics(self):
        self.host._execute("window.subscribe", {"topics": ["usage", "settings"]})
        self.host._execute("window.visibility", {"visible": False})
        self.assertFalse(self.host.subscriptions)
        with self.assertRaises(CommandError):
            self.host._execute("window.subscribe", {"topics": ["filesystem"]})

    def hidden_child(self):
        child, sent = FakeChild(), []
        self.host.process = child
        self.host._send = sent.append
        return child, sent

    def test_hidden_renderer_is_retired_after_the_idle_interval(self):
        child, sent = self.hidden_child()
        self.host.visible = True

        self.host._execute("window.visibility", {"visible": False})
        self.assertTrue(self.host.retire_timer.isActive())
        self.assertEqual(self.host.retire_timer.interval(), 5 * 60 * 1000)
        self.host._execute("window.visibility", {"visible": True})
        self.assertFalse(self.host.retire_timer.isActive())
        self.host.hide()
        self.assertTrue(self.host.retire_timer.isActive())
        self.host._retire()

        self.assertTrue(self.host.retiring)
        self.assertIn({"event": "quit", "data": {}}, sent)
        self.assertFalse(child.killed)

    def test_retired_exit_is_silent_and_reopen_waits_for_it(self):
        child, _sent = self.hidden_child()
        self.host._retire()

        self.host.open_route("pet_settings")
        self.assertTrue(self.host.pending_open)
        with (
            patch.object(self.host, "_launch") as launch,
            patch.object(self.host, "_show_error") as error,
        ):
            child.running = False
            self.host._process_finished(1, QProcess.ExitStatus.CrashExit)

        launch.assert_called_once()
        error.assert_not_called()
        self.assertFalse(self.host.retiring)
        self.assertFalse(self.host.pending_open)

    def test_reopening_grants_the_foreground_before_navigating(self):
        _child, sent = self.hidden_child()
        self.host.authenticated = True
        order = []
        self.host._send = lambda message: order.append(message["event"])
        with patch(
            "watched_kettle.application.settings_ui.host.allow_foreground",
            side_effect=lambda pid: order.append(("grant", pid)),
        ):
            self.host.open_route("usage")

        self.assertEqual(order, [("grant", 4321), "navigate"])
        self.assertFalse(sent)

    def test_retire_kills_a_child_that_ignores_quit(self):
        child, _sent = self.hidden_child()
        self.host._retire()

        self.host._force_retire()

        self.assertTrue(child.killed)

    def test_visible_or_stopped_renderer_is_not_retired(self):
        child, sent = self.hidden_child()
        self.host.visible = True
        self.host._retire()
        self.assertFalse(self.host.retiring)

        self.host.visible = False
        child.running = False
        self.host._retire()
        self.host._schedule_retire()

        self.assertFalse(self.host.retiring)
        self.assertFalse(self.host.retire_timer.isActive())
        self.assertNotIn({"event": "quit", "data": {}}, sent)

    def test_invalid_handshake_cannot_execute_a_command(self):
        self.host._start_server()
        client = QLocalSocket()
        client.connectToServer(self.host.server.fullServerName())
        self.assertTrue(client.waitForConnected(2000))
        QTest.qWait(20)
        client.write(b'{"version":1,"token":"wrong"}\n')
        client.flush()
        QTest.qWait(30)
        self.assertFalse(self.host.authenticated)
        self.assertIsNone(self.host.socket)
        client.abort()
