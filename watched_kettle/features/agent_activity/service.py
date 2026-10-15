"""Normalized agent-event feature boundary."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal


@dataclass(frozen=True)
class AgentActivitySnapshot:
    state: str = "idle"
    active_count: int = 0


class AgentActivityService(QObject):
    snapshot_changed = Signal(object)

    def __init__(self, pet_surface, parent=None, projects=None):
        super().__init__(parent)
        self.pet_surface = pet_surface
        self.snapshot = AgentActivitySnapshot()
        self.projects = projects

    def observe(self, payload):
        if self.projects is not None and not self.projects.observe(payload):
            return None
        result = self.pet_surface.apply_agent_payload(payload)
        presentation = getattr(
            self.pet_surface.agent_controller, "current_presentation", None
        )
        updated = AgentActivitySnapshot(
            state=(
                presentation.state
                if presentation
                else self.pet_surface.current_state or "idle"
            ),
            active_count=(presentation.active_count if presentation else 0),
        )
        if updated != self.snapshot:
            self.snapshot = updated
            self.snapshot_changed.emit(updated)
        return result
