"""Core application lifecycle with no assistant services or imports."""

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QSystemTrayIcon

from watched_kettle.features.pet.viewmodel import PetViewModel
from watched_kettle.features.settings.core_viewmodel import CoreSettingsViewModel
from watched_kettle.application.settings_ui.core import CoreSettingsAdapter
from watched_kettle.application.settings_ui.host import SettingsWindowHost
from watched_kettle.ui.pet_tray import PetSystemTray


class PetRuntime(QObject):
    def __init__(
        self,
        app,
        pet,
        preferences,
        paths=None,
        parent=None,
        *,
        require_tray=False,
    ):
        super().__init__(parent or app)
        self.app = app
        self.pet = pet
        self.preferences = preferences
        self.paths = paths
        self.pet_vm = PetViewModel(pet, parent=self)
        self.settings_vm = CoreSettingsViewModel(parent=self)
        adapter = CoreSettingsAdapter(
            self.pet_vm, self.settings_vm, preferences, app, self
        )
        self.settings = SettingsWindowHost(adapter, self)
        self.tray = (
            PetSystemTray(
                self.pet_vm,
                lambda: self.settings.open_route("pet_settings"),
                lambda: self.settings.open_route("app_startup"),
                pet.frames["idle"][0],
                parent=self,
                updates=self.settings_vm.updates,
            )
            if require_tray or QSystemTrayIcon.isSystemTrayAvailable()
            else None
        )
        pet.center_requested.connect(self.settings.open_route)
        app.aboutToQuit.connect(self.close)
        self._closed = False

    def start(self):
        return None

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self.tray is not None:
            self.tray.close()
        self.settings.shutdown()
        self.pet.save_window_placement()
