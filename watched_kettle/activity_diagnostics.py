"""Content-free diagnostic helpers; independent of state, Qt and logging."""

from collections import OrderedDict
from functools import wraps
import hashlib
import time
from typing import Callable


MAX_DIAGNOSTIC_KEYS = 512


def diagnostic_ref(value):
    text = str(value or "")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:10] if text else ""


def diagnostic_thread_ref(source, identifier):
    """Match the activity service's namespaced Claude conversation keys."""
    text = str(identifier or "")
    if text and source == "claude_code":
        text = "claude_code:" + text.removeprefix("claude_code:")
    return diagnostic_ref(text)


def diagnostic_guard(function):
    """Observation failures must not affect the operation being observed."""

    @wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception:
            return None

    return guarded


class DiagnosticRecorder:
    """Bounded change detection and repeat summaries with an optional sink."""

    def __init__(self):
        self.callback: Callable | None = None
        self.detailed = False
        self.states: OrderedDict[tuple, tuple] = OrderedDict()

    @diagnostic_guard
    def emit(self, event, **fields):
        if self.callback is not None:
            self.callback(event, **fields)

    @diagnostic_guard
    def record(self, event, key, *, repeat_seconds=0, now=None, compare=None, **fields):
        if self.callback is None:
            return
        clock = time.monotonic() if now is None else now
        identity = (event, key)
        # Attempt counts describe a summary; they do not create new failures.
        signature = {
            k: v
            for k, v in fields.items()
            if k != "attempt" and (compare is None or k in compare)
        }
        previous = self.states.get(identity)
        if previous and previous[0] == signature:
            if not repeat_seconds or clock - previous[1] < repeat_seconds:
                return
        self.states[identity] = (signature, clock)
        self.states.move_to_end(identity)
        while len(self.states) > MAX_DIAGNOSTIC_KEYS:
            self.states.popitem(last=False)
        self.emit(event, **fields)

    def forget(self, event, key):
        self.states.pop((event, key), None)
