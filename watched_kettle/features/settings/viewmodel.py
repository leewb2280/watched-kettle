"""Application preference commands exposed to the environment page."""

from PySide6.QtCore import QObject, Signal

from watched_kettle.application.update_check import UpdateService


class SettingsViewModel(QObject):
    snapshot_changed = Signal(object)

    def __init__(self, pet_vm, usage_vm, startup_registration, parent=None):
        super().__init__(parent)
        self.pet_vm = pet_vm
        self.usage_vm = usage_vm
        self.startup_registration = startup_registration
        self.updates = UpdateService(parent=self)
        pet_vm.snapshot_changed.connect(self.snapshot_changed)
        usage_vm.snapshot_changed.connect(self.snapshot_changed)

    @property
    def pet_snapshot(self):
        return self.pet_vm.snapshot

    @property
    def usage_enabled(self):
        return self.usage_vm.enabled

    @property
    def quiet_summary_enabled(self):
        return self.usage_vm.quiet_summary_enabled

    def set_usage_enabled(self, value):
        self.usage_vm.set_enabled(value)

    def set_quiet_summary_enabled(self, value):
        self.usage_vm.set_quiet_summary_enabled(value)

    def set_bubble_scale(self, value):
        self.pet_vm.set_bubble_scale(value)

    def set_bubble_duration(self, value):
        self.pet_vm.set_bubble_duration(value)

    def set_bubble_theme(self, value):
        self.pet_vm.set_bubble_theme(value)

    def startup_status(self):
        return self.startup_registration.inspect()

    def set_startup_enabled(self, value):
        return self.startup_registration.set_enabled(value)
