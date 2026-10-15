"""Connect normalized agent decisions to a pet display callback."""

from dataclasses import replace

from PySide6.QtCore import QObject, QTimer

from watched_kettle.state.events import build_decision
from watched_kettle.state.presentation import ActivityPresentationPolicy
from watched_kettle.state.session_manager import (
    AgentSessionManager,
    DEFAULT_INACTIVITY_LIMITS,
    DEFAULT_STALE_SESSION_AGE_MS,
)


STALE_SESSION_SWEEP_INTERVAL_MS = 60 * 1_000
TRANSIENT_PRIORITY = {"failed": 30, "jumping": 20, "waving": 10}


class PetAgentController(QObject):
    """Own agent session state and temporary agent animations."""

    def __init__(
        self,
        on_display_state,
        on_presentation=None,
        session_manager=None,
        presentation_policy=None,
        stale_session_age_ms=DEFAULT_STALE_SESSION_AGE_MS,
        stale_sweep_interval_ms=STALE_SESSION_SWEEP_INTERVAL_MS,
        inactivity_limits=None,
        parent=None,
    ):
        super().__init__(parent)
        self.on_display_state = on_display_state
        self.on_presentation = on_presentation
        self.session_manager = session_manager or AgentSessionManager()
        self.presentation_policy = presentation_policy or ActivityPresentationPolicy()
        self.stale_session_age_ms = max(0, int(stale_session_age_ms))
        self.inactivity_limits = dict(
            DEFAULT_INACTIVITY_LIMITS
            if inactivity_limits is None
            else inactivity_limits
        )
        self.transient_state = None
        self.transient_session_id = None
        self.current_presentation = self.presentation_policy.restore(
            self.session_manager.get_aggregate(),
        )

        self.transient_timer = QTimer(self)
        self.transient_timer.setSingleShot(True)
        self.transient_timer.timeout.connect(self.finish_transient)

        self.stale_session_timer = QTimer(self)
        self.stale_session_timer.setInterval(max(1_000, int(stale_sweep_interval_ms)))
        self.stale_session_timer.timeout.connect(self.expire_stale_sessions)
        self._update_stale_timer()

    @property
    def aggregate_state(self):
        return self.session_manager.get_aggregate()

    @property
    def desired_state(self):
        if self.aggregate_state.state == "waiting":
            return "waiting"
        return self.transient_state or self.aggregate_state.state

    def apply_payload(self, payload):
        decision = build_decision(payload)
        if decision is None:
            return None
        return self.apply_decision(decision)

    def apply_decision(self, decision):
        result = self.session_manager.apply(decision)
        if result.aggregate.state == "waiting" or (
            decision.session_id == self.transient_session_id
            and decision.event in {"prompt", "cancelled", "session_end", "idle"}
        ):
            # Suppressed animations are discarded, never replayed after a wait.
            self._clear_transient()

        display = result.display
        if display.duration_ms > 0 and (
            self.transient_state is None
            or TRANSIENT_PRIORITY.get(display.state, 0)
            >= TRANSIENT_PRIORITY.get(self.transient_state, 0)
        ):
            self.transient_state = display.state
            self.transient_session_id = display.session_id
            self.transient_timer.start(display.duration_ms)

        # Routine tool traffic updates sessions without resetting the animation.
        state = self.desired_state
        self.on_display_state(state)
        self._publish_presentation(
            replace(
                self.presentation_policy.build(result),
                state=state,
            )
        )

        return result

    def finish_transient(self):
        if self.transient_state is None:
            return

        self._clear_transient()
        self.on_display_state(self.aggregate_state.state)
        self._publish_restore()

    def _clear_transient(self):
        self.transient_timer.stop()
        self.transient_state = None
        self.transient_session_id = None

    def restore_display(self):
        self.on_display_state(self.desired_state)
        if self.transient_state is None:
            self._publish_restore()

    def clear(self, source=None):
        """Return to idle, or forget one source's sessions (Codex account change)."""
        self._clear_transient()
        self.session_manager.clear(source)
        self.on_display_state(self.desired_state)
        self._publish_restore()

    def set_inactivity_limit(self, source, limit):
        """Replace one source's silence limit; None restores the general rule."""
        if limit is None:
            self.inactivity_limits.pop(source, None)
        else:
            self.inactivity_limits[source] = limit
        self._update_stale_timer()

    def _update_stale_timer(self):
        if self.stale_session_age_ms > 0 or self.inactivity_limits:
            self.stale_session_timer.start()
        else:
            self.stale_session_timer.stop()

    def expire_stale_sessions(self):
        """Recover from a missed terminal event without hiding user waits."""
        expired = self.session_manager.expire_stale(
            self.stale_session_age_ms,
            inactivity_limits=self.inactivity_limits,
        )
        if not expired:
            return expired
        self.on_display_state(self.desired_state)
        self._publish_restore()
        return expired

    def _publish_restore(self):
        self._publish_presentation(
            replace(
                self.presentation_policy.restore(
                    self.aggregate_state,
                    self.session_manager.list_sessions(),
                ),
                state=self.desired_state,
            )
        )

    def _publish_presentation(self, presentation):
        self.current_presentation = presentation
        if self.on_presentation is not None:
            self.on_presentation(presentation)
