"""Application tray for the pet-only edition."""

from PySide6.QtCore import QObject
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon


class PetSystemTray(QObject):
    def __init__(self, pet_vm, open_settings, check_updates, icon_pixmap, parent=None):
        super().__init__(parent)
        self.pet_vm = pet_vm
        self.tray = QSystemTrayIcon(QIcon(icon_pixmap), self)
        self.tray.setToolTip("Watched Kettle")
        self.menu = QMenu()
        self.visibility_action = self.menu.addAction("펫 숨기기")
        self.visibility_action.triggered.connect(pet_vm.toggle_visibility)
        settings = self.menu.addAction("펫 설정")
        settings.triggered.connect(open_settings)
        update = self.menu.addAction("업데이트 확인")
        update.triggered.connect(check_updates)
        self.menu.addSeparator()
        quit_action = self.menu.addAction("종료")
        quit_action.triggered.connect(QApplication.quit)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._activated)
        pet_vm.snapshot_changed.connect(lambda _snapshot: self.refresh())
        self.refresh()
        self.tray.show()

    def _activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.pet_vm.pet.reveal()

    def refresh(self):
        self.visibility_action.setText(
            "펫 숨기기" if self.pet_vm.pet.isVisible() else "펫 표시"
        )
        self.tray.setIcon(QIcon(self.pet_vm.pet.frames["idle"][0]))

    def request_refresh(self):
        self.refresh()

    def close(self):
        self.tray.hide()
        self.menu.close()
        self.menu.deleteLater()
