import unittest

from watched_kettle.state.events import PetDecision
from watched_kettle.state.session_manager import AgentSessionManager, MAX_RECENT_EVENTS


class FakeClock:
    def __init__(self):
        self.value = 1_700_000_000_000

    def __call__(self):
        self.value += 1
        return self.value

    def advance(self, milliseconds):
        self.value += int(milliseconds)


def decision(session_id, state=None, visual=None, terminal=False, duration=0):
    return PetDecision(
        source="codex",
        event="test",
        session_id=session_id,
        persistent_state=state,
        visual_state=visual,
        duration_ms=duration,
        terminal=terminal,
    )


class AgentSessionManagerTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.manager = AgentSessionManager(now_ms=self.clock)

    def test_empty_manager_is_idle(self):
        self.assertEqual(self.manager.get_aggregate().state, "idle")

    def test_highest_priority_session_wins(self):
        self.manager.apply(decision("review", "review"))
        self.manager.apply(decision("running", "running"))
        self.manager.apply(decision("waiting", "waiting"))

        self.assertEqual(self.manager.get_aggregate().state, "waiting")
        self.assertEqual(self.manager.get_aggregate().session_id, "waiting")

    def test_most_recent_session_wins_priority_tie(self):
        self.manager.apply(decision("old", "running"))
        self.manager.apply(decision("new", "running"))

        self.assertEqual(self.manager.get_aggregate().session_id, "new")

    def test_transient_state_returns_to_aggregate(self):
        self.manager.apply(decision("work", "running"))
        result = self.manager.apply(decision("notice", visual="waving", duration=2_200))

        self.assertEqual(result.display.state, "waving")
        self.assertEqual(result.display.return_state.state, "running")
        self.assertEqual(result.aggregate.state, "running")

    def test_terminal_event_removes_session_before_return_state(self):
        self.manager.apply(decision("work", "running"))
        result = self.manager.apply(
            decision("work", visual="jumping", terminal=True, duration=2_600)
        )

        self.assertEqual(result.display.state, "jumping")
        self.assertEqual(result.display.return_state.state, "idle")
        self.assertEqual(result.sessions, ())

    def test_terminal_event_reveals_next_active_session(self):
        self.manager.apply(decision("first", "waiting"))
        self.manager.apply(decision("second", "running"))
        result = self.manager.apply(
            decision("first", visual="jumping", terminal=True, duration=2_600)
        )

        self.assertEqual(result.display.return_state.state, "running")
        self.assertEqual(result.display.return_state.session_id, "second")

    def test_duration_is_clamped(self):
        result = self.manager.apply(
            decision("notice", visual="waving", duration=70_000)
        )

        self.assertEqual(result.display.duration_ms, 60_000)

    def test_recent_events_are_bounded(self):
        for _ in range(MAX_RECENT_EVENTS + 3):
            self.manager.apply(decision("work", "running"))

        session = self.manager.list_sessions()[0]
        self.assertEqual(len(session.recent_events), MAX_RECENT_EVENTS)

    def test_clear_returns_to_idle(self):
        self.manager.apply(decision("work", "running"))

        aggregate = self.manager.clear()

        self.assertEqual(aggregate.state, "idle")
        self.assertEqual(self.manager.list_sessions(), ())

    def test_stale_running_and_review_sessions_expire(self):
        self.manager.apply(decision("running", "running"))
        self.manager.apply(decision("review", "review"))
        self.clock.advance(5_000)

        expired = self.manager.expire_stale(5_000)

        self.assertEqual(
            {session.session_id for session in expired},
            {"running", "review"},
        )
        self.assertEqual(self.manager.get_aggregate().state, "idle")

    def test_stale_waiting_session_is_preserved(self):
        self.manager.apply(decision("waiting", "waiting"))
        self.clock.advance(50_000)

        expired = self.manager.expire_stale(5_000)

        self.assertEqual(expired, ())
        self.assertEqual(self.manager.get_aggregate().state, "waiting")


if __name__ == "__main__":
    unittest.main()
