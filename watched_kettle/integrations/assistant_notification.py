"""Provider-neutral local input for schedule assistant notifications."""

from __future__ import annotations

from watched_kettle.localization import t

import argparse
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

from watched_kettle.integrations.codex_client import (
    configured_pet_server_name,
    send_pet_event,
)
from watched_kettle.integrations.codex_spool import (
    DEFAULT_USER_SPOOL_DIRECTORY,
    spool_pet_event,
)


def build_notification_payload(arguments):
    parser = argparse.ArgumentParser(
        prog="WatchedKettle --assistant-notification",
        description=t("message.0059"),
    )
    parser.add_argument("--assistant-notification", action="store_true")
    parser.add_argument("--message", required=True)
    parser.add_argument(
        "--urgency",
        choices=("high", "normal", "low"),
        default="normal",
    )
    parser.add_argument("--notification-id", default="")
    options = parser.parse_args(arguments)
    notification_id = options.notification_id.strip() or uuid4().hex
    return {
        "source": "schedule",
        "event": "notification",
        "session_id": notification_id,
        "event_id": notification_id,
        "message": options.message,
        "urgency": options.urgency,
    }


def run_assistant_notification(
    arguments,
    sender=send_pet_event,
    fallback=spool_pet_event,
):
    payload = build_notification_payload(arguments)
    server_name = configured_pet_server_name()
    delivered = bool(sender(payload, server_name))
    queued = False
    if not delivered:
        spool_directory = Path(
            os.environ.get("WATCHED_KETTLE_SPOOL_DIRECTORY")
            or DEFAULT_USER_SPOOL_DIRECTORY
        )
        queued = bool(fallback(payload, spool_directory=spool_directory))
    outcome = "delivered" if delivered else "queued" if queued else "undelivered"
    accepted = delivered or queued
    if sys.stdout is not None:
        sys.stdout.write(
            json.dumps(
                {
                    "accepted": accepted,
                    "delivered": delivered,
                    "outcome": outcome,
                },
                separators=(",", ":"),
            )
            + "\n"
        )
    return 0 if accepted else 1
