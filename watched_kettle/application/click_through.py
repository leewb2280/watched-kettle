"""Global shortcuts that lock and unlock the pet and the usage widget.

Both runtimes create one. The pet's shortcut exists in both editions; the
widget's is bound only by the assistant runtime. Saving a shortcut replaces
the registration at once, and the status tells the settings window whether
another app already owns the combination.
"""

from PySide6.QtCore import QObject

from watched_kettle.integrations.windows_hotkeys import REGISTERED, GlobalHotkeys

PET_LOCK = "pet_lock"
WIDGET_LOCK = "widget_lock"


class ClickThroughHotkeys(QObject):
    def __init__(self, preferences, pet, parent=None, *, hotkeys=None):
        super().__init__(parent)
        self.preferences = preferences
        self.hotkeys = hotkeys if hotkeys is not None else GlobalHotkeys(self)
        self.pet = pet
        self.actions = {PET_LOCK: pet.toggle_click_through}
        self.closed = False
        self.hotkeys.triggered.connect(self._triggered)
        self.hotkeys.register(PET_LOCK, preferences.load_pet_click_through_hotkey())

    def bind_widget(self, toggle):
        self.actions[WIDGET_LOCK] = toggle
        self.hotkeys.register(
            WIDGET_LOCK, self.preferences.load_usage_widget_click_through_hotkey()
        )

    def status(self, name):
        return self.hotkeys.status(name)

    def taken(self, name, text):
        """Whether the other lock already uses this shortcut.

        Windows would report the second registration as in use by another
        app, so the settings window refuses it with its own message.
        """
        other = WIDGET_LOCK if name == PET_LOCK else PET_LOCK
        saved = {
            PET_LOCK: self.preferences.load_pet_click_through_hotkey,
            WIDGET_LOCK: self.preferences.load_usage_widget_click_through_hotkey,
        }
        return bool(text) and other in self.actions and saved[other]() == text

    def set_pet_hotkey(self, text):
        self.preferences.save_pet_click_through_hotkey(text)
        return self.hotkeys.register(
            PET_LOCK, self.preferences.load_pet_click_through_hotkey()
        )

    def set_widget_hotkey(self, text):
        self.preferences.save_usage_widget_click_through_hotkey(text)
        return self.hotkeys.register(
            WIDGET_LOCK, self.preferences.load_usage_widget_click_through_hotkey()
        )

    def release_without_tray(self, tray_available):
        """Start unlocked when neither the tray nor a shortcut could unlock.

        The saved choice stays, so the next start with a tray locks again.
        """
        if (
            not tray_available
            and self.pet.click_through
            and self.status(PET_LOCK) != REGISTERED
        ):
            self.pet.set_click_through(False, persist=False)

    def _triggered(self, name):
        action = self.actions.get(name)
        if action is not None and not self.closed:
            action()

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.hotkeys.close()
