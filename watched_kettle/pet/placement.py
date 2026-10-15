"""Persistable, monitor-aware desktop pet placement helpers."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRect


@dataclass(frozen=True)
class SavedWindowPlacement:
    screen_name: str
    x: int
    y: int
    work_x: int
    work_y: int
    work_width: int
    work_height: int
    relative_x: float
    relative_y: float

    @property
    def work_area(self):
        return QRect(
            self.work_x,
            self.work_y,
            self.work_width,
            self.work_height,
        )


def clamp_window_position(position, size, bounds, reserved_bottom=0):
    """Keep a window and its optional lower caption inside one work area."""
    maximum_x = max(bounds.left(), bounds.right() - size.width() + 1)
    maximum_y = max(
        bounds.top(),
        bounds.bottom() - size.height() - max(0, int(reserved_bottom)) + 1,
    )
    return QPoint(
        min(max(position.x(), bounds.left()), maximum_x),
        min(max(position.y(), bounds.top()), maximum_y),
    )


def create_saved_placement(
    screen_name,
    position,
    size,
    work_area,
    reserved_bottom=0,
):
    """Capture absolute and normalized coordinates for resilient restore."""
    clamped = clamp_window_position(
        position,
        size,
        work_area,
        reserved_bottom,
    )
    maximum_x = max(work_area.left(), work_area.right() - size.width() + 1)
    maximum_y = max(
        work_area.top(),
        work_area.bottom() - size.height() - max(0, int(reserved_bottom)) + 1,
    )
    span_x = maximum_x - work_area.left()
    span_y = maximum_y - work_area.top()
    relative_x = (clamped.x() - work_area.left()) / span_x if span_x > 0 else 0.0
    relative_y = (clamped.y() - work_area.top()) / span_y if span_y > 0 else 0.0
    return SavedWindowPlacement(
        screen_name=str(screen_name or ""),
        x=clamped.x(),
        y=clamped.y(),
        work_x=work_area.x(),
        work_y=work_area.y(),
        work_width=work_area.width(),
        work_height=work_area.height(),
        relative_x=min(max(float(relative_x), 0.0), 1.0),
        relative_y=min(max(float(relative_y), 0.0), 1.0),
    )


def restore_window_position(
    placement,
    screens,
    primary_screen,
    size,
    reserved_bottom=0,
):
    """Resolve a saved placement against the monitors available now."""
    screens = list(screens or ())
    if placement is None or not screens:
        return None

    target = next(
        (
            screen
            for screen in screens
            if str(screen.name() or "") == placement.screen_name
        ),
        None,
    )
    if target is None:
        target = next(
            (
                screen
                for screen in screens
                if screen.availableGeometry() == placement.work_area
            ),
            None,
        )
    if target is None:
        target = primary_screen if primary_screen in screens else screens[0]

    bounds = target.availableGeometry()
    if bounds == placement.work_area:
        desired = QPoint(placement.x, placement.y)
    else:
        maximum_x = max(bounds.left(), bounds.right() - size.width() + 1)
        maximum_y = max(
            bounds.top(),
            bounds.bottom() - size.height() - max(0, int(reserved_bottom)) + 1,
        )
        desired = QPoint(
            bounds.left() + round((maximum_x - bounds.left()) * placement.relative_x),
            bounds.top() + round((maximum_y - bounds.top()) * placement.relative_y),
        )
    return clamp_window_position(
        desired,
        size,
        bounds,
        reserved_bottom,
    )
