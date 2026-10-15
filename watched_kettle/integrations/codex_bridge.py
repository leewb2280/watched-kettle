"""Command-hook entry logic that fails open when the pet is unavailable."""

from __future__ import annotations

import sys

from watched_kettle.integrations.codex_hooks import (
    normalize_codex_hook,
    read_hook_payload,
)
from watched_kettle.integrations.codex_client import send_pet_event


def run_hook_bridge(
    stream=None,
    sender=send_pet_event,
    server_name=None,
    fallback=None,
    health_recorder=None,
    normalize=normalize_codex_hook,
):
    """Filter and deliver a hook payload; always return a successful exit code.

    ``normalize`` maps the parsed payload (None when oversized or invalid) to a
    sanitized pet event for one agent source.
    """
    stream = stream or sys.stdin.buffer
    event = None
    outcome = "ignored"
    try:
        payload = read_hook_payload(stream)
        event = normalize(payload)
        if event is not None:
            try:
                if server_name is None:
                    delivered = sender(event)
                else:
                    delivered = sender(event, server_name)
            except Exception:
                delivered = False
            if delivered:
                outcome = "delivered"
            elif fallback is not None:
                try:
                    queued = bool(fallback(event))
                except Exception:
                    queued = False
                outcome = "queued" if queued else "undelivered"
            else:
                outcome = "undelivered"
    except Exception:
        # Pet integration must never delay or fail the agent operation.
        pass
    finally:
        if health_recorder is not None:
            try:
                health_recorder(event, outcome)
            except Exception:
                pass
    return 0
