"""Explicit pet gestures routed without owning activity or animation state."""


# The pet-only startup does not load agent-specific integrations, so each
# launcher is imported only when its action actually runs.
def _open_codex():
    from watched_kettle.integrations.codex_launcher import open_codex

    return open_codex()


def _open_claude():
    from watched_kettle.integrations.vscode_launcher import open_vscode

    return open_vscode()


class PetDoubleClickActions:
    def __init__(self, pet, preferences, open_home, show_error, openers=None):
        self.pet = pet
        self.preferences = preferences
        self.open_home = open_home
        self.show_error = show_error
        self.openers = dict(codex=_open_codex, claude=_open_claude)
        self.openers.update(openers or {})
        self.closed = False
        pet.double_click_requested.connect(self.execute)

    def execute(self):
        if self.closed:
            return
        action = self.preferences.load_double_click_action()
        if action == "wave_only":
            return
        if action == "settings_home":
            self.open_home()
            return
        result = self.openers[action]()
        if not result.opened:
            self.open_home()
            self.show_error(result.message)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.pet.double_click_requested.disconnect(self.execute)
