"""Idle presentation used when the optional assistant is not installed."""


class IdlePetController:
    desired_state = "idle"
    current_presentation = None

    def __init__(self, on_display_state, on_presentation=None, parent=None):
        self.on_display_state = on_display_state

    def apply_payload(self, _payload):
        return None

    def restore_display(self):
        self.on_display_state("idle")

    def clear(self, source=None):
        del source
        self.restore_display()
