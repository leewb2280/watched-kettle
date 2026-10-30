"""Bounded waits for worker threads at shutdown.

Every worker slice has its own time limit, but a worker stuck in a system call
would hold the whole shutdown, and an update's Setup waits for the app to
exit. Shutdown waits a bounded time, logs a worker that did not stop and goes
on. The thread is never terminated, so a SQLite transaction is not cut short;
the database rolls back an unfinished one when the process ends.
"""

from __future__ import annotations

import logging

from watched_kettle.application.logging import log_event

SHUTDOWN_WAIT_MS = 15_000
# Threads that did not stop are kept referenced so their Qt objects are not
# destroyed while running, which would abort the process.
_abandoned = []


def wait_for_thread(thread, component, timeout_ms=SHUTDOWN_WAIT_MS):
    """True when ``thread`` stopped; otherwise it is logged and left behind."""
    if thread.wait(timeout_ms):
        return True
    _abandoned.append(thread)
    log_event(
        component,
        "thread_stop_timeout",
        logging.WARNING,
        duration_ms=timeout_ms,
    )
    return False
