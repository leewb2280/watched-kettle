import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from watched_kettle.state.events import PetDecision
from watched_kettle.state.controller import PetAgentController
from watched_kettle.state.session_manager import AgentSessionManager


class FakeClock:
    def __init__(self):
        self.value = 1_700_000_000_000

    def __call__(self):
        self.value += 1
        return self.value

    def advance(self, milliseconds):
        self.value += int(milliseconds)


class PetAgentControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.displayed = []
        self.presentations = []
        self.controller = PetAgentController(
            self.displayed.append,
            on_presentation=self.presentations.append,
        )

    def tearDown(self):
        self.controller.deleteLater()

    def test_invalid_payload_does_not_change_display(self):
        result = self.controller.apply_payload({"source": "codex", "event": "unknown"})

        self.assertIsNone(result)
        self.assertEqual(self.displayed, [])

    def test_persistent_event_displays_aggregate_state(self):
        self.controller.apply_payload(
            {"source": "codex", "event": "SessionStart", "session_id": "one"}
        )

        self.assertEqual(self.displayed[-1], "running")
        self.assertEqual(self.controller.desired_state, "running")
        self.assertEqual(self.presentations[-1].state, "running")
        self.assertEqual(self.presentations[-1].active_count, 1)

    def test_transient_event_returns_to_current_aggregate(self):
        self.controller.apply_payload(
            {"source": "codex", "event": "SessionStart", "session_id": "one"}
        )
        self.controller.apply_decision(
            PetDecision(
                source="notes-app",
                event="notification",
                session_id="notes-app:one",
                visual_state="waving",
                duration_ms=1_000,
            )
        )

        self.assertEqual(self.displayed[-1], "waving")

        self.controller.finish_transient()

        self.assertEqual(self.displayed[-1], "running")
        self.assertEqual(self.controller.desired_state, "running")

    def test_new_prompt_in_same_session_cancels_old_transient(self):
        self.controller.apply_decision(
            PetDecision(
                source="codex",
                event="done",
                session_id="codex:one",
                visual_state="jumping",
                duration_ms=2_600,
                terminal=True,
            )
        )

        self.controller.apply_payload(
            {"source": "codex", "event": "UserPromptSubmit", "session_id": "one"}
        )

        self.assertEqual(self.displayed[-1], "running")
        self.assertIsNone(self.controller.transient_state)
        self.assertFalse(self.controller.transient_timer.isActive())

    def test_restore_display_keeps_active_transient(self):
        self.controller.apply_decision(
            PetDecision(
                source="notes-app",
                event="notification",
                session_id="notes-app:one",
                visual_state="waving",
                duration_ms=1_000,
            )
        )
        self.displayed.clear()

        self.controller.restore_display()

        self.assertEqual(self.displayed, ["waving"])

    def test_clear_cancels_transient_and_returns_to_idle(self):
        self.controller.apply_decision(
            PetDecision(
                source="notes-app",
                event="notification",
                session_id="notes-app:one",
                visual_state="waving",
                duration_ms=1_000,
            )
        )

        self.controller.clear()

        self.assertEqual(self.displayed[-1], "idle")
        self.assertEqual(self.controller.desired_state, "idle")
        self.assertFalse(self.controller.transient_timer.isActive())

    def test_stale_session_sweep_returns_display_to_idle(self):
        clock = FakeClock()
        self.controller.deleteLater()
        self.controller = PetAgentController(
            self.displayed.append,
            on_presentation=self.presentations.append,
            session_manager=AgentSessionManager(now_ms=clock),
            stale_session_age_ms=5_000,
        )
        self.controller.apply_payload(
            {"source": "codex", "event": "SessionStart", "session_id": "one"}
        )
        clock.advance(5_000)

        expired = self.controller.expire_stale_sessions()

        self.assertEqual(len(expired), 1)
        self.assertEqual(self.displayed[-1], "idle")
        self.assertEqual(self.presentations[-1].active_count, 0)

    def test_stale_sweep_does_not_dismiss_confirmation_wait(self):
        clock = FakeClock()
        self.controller.deleteLater()
        self.controller = PetAgentController(
            self.displayed.append,
            on_presentation=self.presentations.append,
            session_manager=AgentSessionManager(now_ms=clock),
            stale_session_age_ms=5_000,
        )
        self.controller.apply_payload(
            {
                "source": "codex",
                "event": "PermissionRequest",
                "approval_actor": "user",
                "session_id": "one",
            }
        )
        clock.advance(50_000)

        expired = self.controller.expire_stale_sessions()

        self.assertEqual(expired, ())
        self.assertEqual(self.controller.desired_state, "waiting")


if __name__ == "__main__":
    unittest.main()
