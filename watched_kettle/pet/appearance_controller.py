"""Cosmetic appearance lifetime; never creates activity or notification events."""

from typing import Any
from collections.abc import Mapping
import random

from PySide6.QtCore import QObject, QTimer, Qt
from PySide6.QtGui import QPainter, QPixmap

from watched_kettle.pet.appearance_assets import (
    APPEARANCE_INTERVALS,
    AppearanceChoice,
    AppearanceStatus,
    invalid_appearance,
)


# A look change without drawn frames cross-fades the two front idle frames.
FADE_FRAMES = 8
FADE_INTERVAL_MS = 50


class AppearanceTransitions:
    """Frames between two looks: drawn by the package, reversed, or a fade."""

    def __init__(self, spec, strips, still=None):
        self.strips = dict(strips)
        self.intervals = {(v.source, v.target): v.interval for v in spec.transitions}
        # Look id -> its front idle frame; needed only for fades.
        self.still = still
        self._fade = None

    def get(self, source, target):
        """(frames, interval in ms) from source to target."""
        if (source, target) in self.strips:
            return self.strips[(source, target)], self.intervals[(source, target)]
        if (target, source) in self.strips:
            frames = self.strips[(target, source)]
            return frames[::-1], self.intervals[(target, source)]
        if self.still is None:
            raise invalid_appearance()
        if self._fade is None or self._fade[0] != (source, target):
            self._fade = (
                (source, target),
                cross_fade(self.still(source), self.still(target)),
            )
        return self._fade[1], FADE_INTERVAL_MS


def cross_fade(start, end, count=FADE_FRAMES):
    """In-between frames only: the looks themselves show before and after."""
    frames = []
    for index in range(1, count + 1):
        progress = index / (count + 1)
        frame = QPixmap(start.size())
        frame.fill(Qt.GlobalColor.transparent)
        painter = QPainter(frame)
        painter.setOpacity(1 - progress)
        painter.drawPixmap(0, 0, start)
        painter.setOpacity(progress)
        painter.drawPixmap(0, 0, end)
        painter.end()
        frames.append(frame)
    return frames


class AppearanceController(QObject):
    def __init__(
        self,
        spec,
        transitions,
        *,
        mode,
        current,
        can_start,
        on_commit,
        on_change,
        on_frame,
        save_mode,
        save_current,
        interval="package",
        order="package",
        delay=None,
        parent=None,
    ):
        super().__init__(parent)
        self.spec = spec
        self.transitions = (
            AppearanceTransitions(spec, transitions)
            if isinstance(transitions, Mapping)
            else transitions
        )
        self.mode = mode
        self.current = current
        self.target = None if mode == "auto" or mode == current else mode
        self._can_start = can_start
        self._on_commit = on_commit
        self._on_change = on_change
        self._on_frame = on_frame
        self._save_mode = save_mode
        self._save_current = save_current
        # A fixed delay (tests) replaces the interval choice.
        self._fixed_delay = delay
        self.interval = interval
        self.order = order
        self._frames: Any = None
        self._interval = 0
        self._index = 0
        self._safe = False
        self._ready = False
        self._suspended = True
        self.auto_timer = QTimer(self)
        self.auto_timer.setSingleShot(True)
        self.auto_timer.timeout.connect(self._auto_due)
        self.safe_timer = QTimer(self)
        self.safe_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.safe_timer.setSingleShot(True)
        self.safe_timer.setInterval(300)
        self.safe_timer.timeout.connect(self._safe_ready)
        self.frame_timer = QTimer(self)
        self.frame_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.frame_timer.timeout.connect(self._next_frame)

    @property
    def active(self):
        return self._frames is not None

    @property
    def pending(self):
        return self.target is not None

    @property
    def pixmap(self):
        if not self.active:
            return None
        return self._frames[self._index]

    def snapshot(self):
        return AppearanceStatus(
            self.mode,
            self.current,
            self.target,
            self.active,
            self.pending,
            tuple(AppearanceChoice(v.id, v.label) for v in self.spec.variants),
            self.interval,
            self.order,
            self.spec.auto,
        )

    def _delay(self):
        if self._fixed_delay is not None:
            return self._fixed_delay()
        auto = self.spec.auto
        low, high = APPEARANCE_INTERVALS.get(
            self.interval, (auto.min_seconds, auto.max_seconds)
        )
        return random.randint(low * 1000, high * 1000)

    def set_timing(self, interval=None, order=None):
        """Change automatic timing; a waiting automatic change is rescheduled."""
        if interval is not None:
            self.interval = interval
        if order is not None:
            self.order = order
        if self.auto_timer.isActive():
            self.auto_timer.stop()
            self._schedule_auto()
        self._on_change()

    def set_mode(self, value):
        if value not in ("auto", *self.spec.ids):
            raise invalid_appearance()
        if value == self.mode:
            return
        self._save_mode(value)
        self.auto_timer.stop()
        self.frame_timer.stop()
        self._frames = None
        self.mode = value
        self.target = None if value in {"auto", self.current} else value
        if value == "auto":
            self._schedule_auto()
        self._on_frame()
        self._on_change()
        self.notify_safety()
        self._start_if_ready()

    def _schedule_auto(self):
        if self.mode == "auto" and not self._suspended:
            self.auto_timer.start(self._delay())

    def resume(self):
        self._suspended = False
        self._safe = self._ready = False
        self._schedule_auto()
        self.notify_safety()

    def suspend(self):
        self._suspended = True
        self.auto_timer.stop()
        self.safe_timer.stop()
        self.frame_timer.stop()
        self._frames = None
        self._safe = self._ready = False
        self.target = (
            None if self.mode == "auto" or self.mode == self.current else self.mode
        )
        self._on_frame()
        self._on_change()

    def shutdown(self):
        self.auto_timer.stop()
        self.safe_timer.stop()
        self.frame_timer.stop()
        self._suspended = True
        self._frames = None
        self.target = None

    def notify_safety(self):
        if self._suspended:
            return
        safe = bool(self._can_start())
        if safe != self._safe:
            self._safe = safe
            self._ready = False
            if safe:
                self.safe_timer.start()
            else:
                self.safe_timer.stop()
                if self.active:
                    self.frame_timer.stop()
                    self._frames = None
                    if self.mode == "auto":
                        self.target = None
                        self._schedule_auto()
                    self._on_frame()
                    self._on_change()

    def _safe_ready(self):
        self._ready = self._safe and not self._suspended and self._can_start()
        self._start_if_ready()

    def _next_target(self):
        ids = self.spec.ids
        order = self.spec.auto.order if self.order == "package" else self.order
        if order == "sequence":
            return ids[(ids.index(self.current) + 1) % len(ids)]
        return random.choice([v for v in ids if v != self.current])

    def _auto_due(self):
        if self._suspended or self.mode != "auto":
            return
        self.target = self._next_target()
        self._on_change()
        self.notify_safety()
        self._start_if_ready()

    def _start_if_ready(self):
        if (
            self.active
            or not self.pending
            or not self._ready
            or self._suspended
            or not self._can_start()
        ):
            return
        self._frames, self._interval = self.transitions.get(self.current, self.target)
        self._index = 0
        self.frame_timer.start(self._interval)
        self._on_change()
        self._on_frame()

    def _next_frame(self):
        self.notify_safety()
        if not self.active:
            return
        self._index += 1
        if self._index >= len(self._frames):
            self.frame_timer.stop()
            self.current = self.target
            self.target = None
            self._frames = None
            self._save_current(self.current)
            self._on_commit(self.current)
            self._schedule_auto()
            self._on_change()
        self._on_frame()
