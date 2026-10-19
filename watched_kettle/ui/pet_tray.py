"""Application tray for the pet-only edition."""

from watched_kettle.localization import t

from PySide6.QtCore import QObject
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon


def update_action_text(updates):
    """The tray's update entry names a version a check already found."""
    update = updates.snapshot() if updates is not None else {}
    if update.get("state") == "available" and update.get("version"):
        return t("message.0291", value0=update["version"])
    return t("message.0290")


def check_updates(updates, open_page):
    """Open the version row and start the check the tray entry names."""
    open_page()
    update = updates.snapshot() if updates is not None else {}
    # A found version or a running download is already on the page.
    if update.get("state") in ("idle", "current") or (
        update.get("state") == "error" and update.get("retry") == "check"
    ):
        updates.check()


class PetSystemTray(QObject):
    def __init__(
        self,
        pet_vm,
        open_settings,
        open_updates,
        icon_pixmap,
        parent=None,
        updates=None,
    ):
        super().__init__(parent)
        self.pet_vm = pet_vm
        self.tray = QSystemTrayIcon(QIcon(icon_pixmap), self)
        self.tray.setToolTip("Watched Kettle")
        self.menu = QMenu()
        self.visibility_action = self.menu.addAction(t("message.0224"))
        self.visibility_action.triggered.connect(pet_vm.toggle_visibility)
        # The way back when a locked pet no longer takes clicks.
        self.click_through_action = self.menu.addAction(t("click_through.pet"))
        self.click_through_action.setCheckable(True)
        self.click_through_action.triggered.connect(pet_vm.set_click_through)
        self.menu.addSeparator()
        settings = self.menu.addAction(t("message.0225"))
        settings.triggered.connect(open_settings)
        self.updates = updates
        self.update_action = self.menu.addAction(update_action_text(updates))
        self.update_action.triggered.connect(
            lambda: check_updates(updates, open_updates)
        )
        if updates is not None:
            updates.changed.connect(
                lambda: self.update_action.setText(update_action_text(updates))
            )
        self.menu.addSeparator()
        quit_action = self.menu.addAction(t("message.0226"))
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
            t("message.0224") if self.pet_vm.pet.isVisible() else t("message.0234")
        )
        self.click_through_action.setChecked(self.pet_vm.pet.click_through)
        self.tray.setIcon(QIcon(self.pet_vm.pet.frames["idle"][0]))

    def request_refresh(self):
        self.refresh()

    def close(self):
        self.tray.hide()
        self.menu.close()
        self.menu.deleteLater()
