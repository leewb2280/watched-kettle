"""Shutdown never waits forever for a worker thread (STB-03)."""

import unittest
from unittest.mock import patch

from watched_kettle import thread_shutdown
from watched_kettle.thread_shutdown import wait_for_thread


class Thread:
    def __init__(self, stops):
        self.stops = stops
        self.timeouts = []

    def wait(self, timeout):
        self.timeouts.append(timeout)
        return self.stops


class ThreadShutdownTests(unittest.TestCase):
    def test_a_stopped_thread_is_simply_joined(self):
        thread = Thread(stops=True)
        with patch.object(thread_shutdown, "log_event") as log:
            self.assertTrue(wait_for_thread(thread, "usage.worker"))
        self.assertEqual(thread.timeouts, [thread_shutdown.SHUTDOWN_WAIT_MS])
        log.assert_not_called()

    def test_a_stuck_thread_is_logged_kept_and_left_behind(self):
        thread = Thread(stops=False)
        with patch.object(thread_shutdown, "log_event") as log:
            self.assertFalse(wait_for_thread(thread, "usage.worker", timeout_ms=5))
        self.assertEqual(thread.timeouts, [5])
        self.assertEqual(
            log.call_args.args[:2], ("usage.worker", "thread_stop_timeout")
        )
        self.assertIn(thread, thread_shutdown._abandoned)
        thread_shutdown._abandoned.remove(thread)


if __name__ == "__main__":
    unittest.main()
