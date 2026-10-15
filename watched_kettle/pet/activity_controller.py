import random

from PySide6.QtCore import QObject, QTimer

from watched_kettle.config import (
    ANIMATIONS,
    DEFAULT_IDLE_ACTIVITIES,
    IDLE_ACTIVITY_MAX_DELAY,
    IDLE_ACTIVITY_MIN_DELAY,
)


def load_idle_activities(manifest, available_states):
    """Validate the optional idle activity configuration in a manifest."""
    configured = manifest.get(
        "idleActivities",
        DEFAULT_IDLE_ACTIVITIES,
    )
    activities = []

    if not isinstance(configured, (list, tuple)):
        return activities

    for item in configured:
        if isinstance(item, str):
            state = item
            weight = 1
            duration = ANIMATIONS.get(state, {}).get("frames", 1) * ANIMATIONS.get(
                state, {}
            ).get("interval", 1_000)
        elif isinstance(item, dict):
            state = item.get("state")
            weight = item.get("weight", 1)
            duration = item.get("duration", 2_000)
        else:
            continue

        if state not in available_states or state == "idle":
            continue

        try:
            weight = float(weight)
            duration = int(duration)
        except (TypeError, ValueError):
            continue

        if weight <= 0 or duration <= 0:
            continue

        activities.append(
            {
                "state": state,
                "weight": weight,
                "duration": duration,
            }
        )

    return activities


class IdleActivityController(QObject):
    """Schedule ambient pet actions independently of the pet window UI."""

    def __init__(
        self,
        activities,
        enabled,
        can_start,
        on_start,
        on_finish,
        parent=None,
    ):
        super().__init__(parent)
        self.activities = activities
        self.enabled = bool(enabled)
        self.can_start = can_start
        self.on_start = on_start
        self.on_finish = on_finish
        self.active_state = None

        self.delay_timer = QTimer(self)
        self.delay_timer.setSingleShot(True)
        self.delay_timer.timeout.connect(self.start)

        self.end_timer = QTimer(self)
        self.end_timer.setSingleShot(True)
        self.end_timer.timeout.connect(self.finish)

    @property
    def is_active(self):
        return self.active_state is not None

    def schedule(self):
        self.delay_timer.stop()

        if not self.enabled or not self.activities or not self.can_start():
            return

        delay = random.randint(
            IDLE_ACTIVITY_MIN_DELAY,
            IDLE_ACTIVITY_MAX_DELAY,
        )
        self.delay_timer.start(delay)

    def start(self):
        if not self.enabled or not self.activities or not self.can_start():
            return

        activity = random.choices(
            self.activities,
            weights=[item["weight"] for item in self.activities],
            k=1,
        )[0]

        self.active_state = activity["state"]
        self.on_start(self.active_state)
        self.end_timer.start(activity["duration"])

    def finish(self):
        if not self.is_active:
            return

        active_state = self.active_state
        self.active_state = None
        self.end_timer.stop()
        self.on_finish(active_state)

    def cancel(self, return_to_idle=False):
        self.delay_timer.stop()

        if not self.is_active:
            self.end_timer.stop()
            return

        active_state = self.active_state
        self.active_state = None
        self.end_timer.stop()

        if return_to_idle:
            self.on_finish(active_state)

    def note_user_activity(self):
        self.delay_timer.stop()

        if self.is_active:
            self.cancel(return_to_idle=True)
        else:
            self.schedule()

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)

        if not self.enabled:
            self.delay_timer.stop()
            self.cancel(return_to_idle=True)
        else:
            self.schedule()
