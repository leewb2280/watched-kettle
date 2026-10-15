"""Timed horizontal wandering for a desktop pet window."""

import random

from PySide6.QtCore import QElapsedTimer, QObject, QPoint, QRect, QTimer

from watched_kettle.config import (
    AUTO_MOVEMENT_INTERVAL,
    AUTO_MOVEMENT_MAX_DELAY,
    AUTO_MOVEMENT_MAX_DISTANCE,
    AUTO_MOVEMENT_MIN_DELAY,
    AUTO_MOVEMENT_MIN_DISTANCE,
    AUTO_MOVEMENT_SPEED,
)


def horizontal_limits(bounds, window_width):
    """Return inclusive X limits that keep a window inside ``bounds``."""
    minimum_x = bounds.left()
    maximum_x = max(
        minimum_x,
        bounds.right() - int(window_width) + 1,
    )
    return minimum_x, maximum_x


def choose_horizontal_target(
    current_x,
    window_width,
    bounds,
    minimum_distance=AUTO_MOVEMENT_MIN_DISTANCE,
    maximum_distance=AUTO_MOVEMENT_MAX_DISTANCE,
    chooser=random.choice,
    randint=random.randint,
):
    """Choose a reachable target without crossing the selected display."""
    minimum_x, maximum_x = horizontal_limits(bounds, window_width)
    current_x = min(max(int(current_x), minimum_x), maximum_x)
    available = {
        -1: current_x - minimum_x,
        1: maximum_x - current_x,
    }
    directions = [
        direction
        for direction, distance in available.items()
        if distance >= minimum_distance
    ]
    if not directions:
        return None

    direction = chooser(directions)
    furthest = min(maximum_distance, available[direction])
    distance = randint(minimum_distance, furthest)
    return current_x + direction * distance


class AutoMovementController(QObject):
    """Schedule and execute short walks inside one display work area."""

    def __init__(
        self,
        enabled,
        can_start,
        bounds_provider,
        position_provider,
        size_provider,
        on_start,
        on_move,
        on_finish,
        parent=None,
    ):
        super().__init__(parent)
        self.enabled = bool(enabled)
        self.can_start = can_start
        self.bounds_provider = bounds_provider
        self.position_provider = position_provider
        self.size_provider = size_provider
        self.on_start = on_start
        self.on_move = on_move
        self.on_finish = on_finish

        self.active_state = None
        self.target_x = None
        self.current_x = None
        self.locked_y = None
        self.locked_bounds = None

        self.delay_timer = QTimer(self)
        self.delay_timer.setSingleShot(True)
        self.delay_timer.timeout.connect(self.start)

        self.move_timer = QTimer(self)
        self.move_timer.timeout.connect(self._move_tick)
        self.elapsed_timer = QElapsedTimer()

    @property
    def is_active(self):
        return self.active_state is not None

    def schedule(self):
        self.delay_timer.stop()
        if not self.enabled or self.is_active or not self.can_start():
            return
        self.delay_timer.start(
            random.randint(
                AUTO_MOVEMENT_MIN_DELAY,
                AUTO_MOVEMENT_MAX_DELAY,
            )
        )

    def start(self, force=False):
        self.delay_timer.stop()
        if self.is_active:
            return
        if not force and (not self.enabled or not self.can_start()):
            return

        bounds = self.bounds_provider()
        if bounds is None or not isinstance(bounds, QRect) or bounds.isEmpty():
            return

        position = self.position_provider()
        size = self.size_provider()
        minimum_x, maximum_x = horizontal_limits(bounds, size.width())
        start_x = min(max(position.x(), minimum_x), maximum_x)
        maximum_y = max(bounds.top(), bounds.bottom() - size.height() + 1)
        start_y = min(max(position.y(), bounds.top()), maximum_y)
        target_x = choose_horizontal_target(
            start_x,
            size.width(),
            bounds,
        )
        if target_x is None:
            return

        self.current_x = float(start_x)
        self.target_x = int(target_x)
        self.locked_y = int(start_y)
        self.locked_bounds = QRect(bounds)
        self.active_state = (
            "running-right" if self.target_x > start_x else "running-left"
        )

        if position.x() != start_x or position.y() != start_y:
            self.on_move(QPoint(start_x, start_y))
        self.on_start(self.active_state)
        self.elapsed_timer.start()
        self.move_timer.start(AUTO_MOVEMENT_INTERVAL)

    def _move_tick(self):
        elapsed_ms = max(1, self.elapsed_timer.restart())
        self.advance(elapsed_ms)

    def advance(self, elapsed_ms):
        """Advance an active walk; separated for deterministic tests."""
        if not self.is_active:
            return

        current_bounds = self.bounds_provider()
        if current_bounds is None or QRect(current_bounds) != self.locked_bounds:
            self.cancel(return_to_idle=True)
            return

        direction = 1 if self.target_x > self.current_x else -1
        distance = AUTO_MOVEMENT_SPEED * max(0, elapsed_ms) / 1_000
        next_x = self.current_x + direction * distance
        reached = next_x >= self.target_x if direction > 0 else next_x <= self.target_x
        if reached:
            next_x = float(self.target_x)

        self.current_x = next_x
        self.on_move(QPoint(round(next_x), self.locked_y))
        if reached:
            self.finish()

    def finish(self):
        if not self.is_active:
            return
        active_state = self.active_state
        self._clear_active()
        self.on_finish(active_state)
        self.schedule()

    def cancel(self, return_to_idle=False):
        self.delay_timer.stop()
        if not self.is_active:
            self.move_timer.stop()
            return

        active_state = self.active_state
        self._clear_active()
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
            self.cancel(return_to_idle=True)
        else:
            self.schedule()

    def _clear_active(self):
        self.move_timer.stop()
        self.active_state = None
        self.target_x = None
        self.current_x = None
        self.locked_y = None
        self.locked_bounds = None
