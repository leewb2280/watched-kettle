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
        self._observing = False
        if projects is not None:
            projects.changed.connect(self._project_codex)

    def observe(self, payload):
        self._observing = True
        try:
            if self.projects is not None and not self.projects.observe(payload):
                return None
            return self.pet_surface.apply_agent_payload(payload)
        finally:
            self._observing = False
            self._project_codex()

    def observe_turn_outcome(self, outcome):
        if self.projects is None:
            return
        self._observing = True
        try:
            payload = self.projects.apply_turn_outcome(outcome)
            if payload is not None:
                self.pet_surface.apply_agent_payload(payload)
        finally:
            self._observing = False
            self._project_codex()

    def _project_codex(self):
        if self._observing:
            return
        controller = getattr(self.pet_surface, "agent_controller", None)
        if (
            self.projects is not None
            and controller is not None
            and hasattr(controller, "project_codex_observations")
        ):
            controller.project_codex_observations(self.projects.codex_observations())
        presentation = getattr(controller, "current_presentation", None)
        updated = AgentActivitySnapshot(
            state=(
                presentation.state
                if presentation
                else getattr(self.pet_surface, "current_state", None) or "idle"
            ),
            active_count=(presentation.active_count if presentation else 0),
        )
        if updated != self.snapshot:
            self.snapshot = updated
            self.snapshot_changed.emit(updated)
