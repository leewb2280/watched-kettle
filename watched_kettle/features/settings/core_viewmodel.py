"""Settings commands available without the optional assistant."""

from PySide6.QtCore import QObject

from watched_kettle.integrations.windows_startup import WindowsStartupRegistration
from watched_kettle.application.update_check import UpdateService


class CoreSettingsViewModel(QObject):
    def __init__(self, startup_registration=None, parent=None):
        super().__init__(parent)
        self.startup_registration = startup_registration or WindowsStartupRegistration()
        self.updates = UpdateService(parent=self)

    def startup_status(self):
        return self.startup_registration.inspect()

    def set_startup_enabled(self, value):
        return self.startup_registration.set_enabled(value)
