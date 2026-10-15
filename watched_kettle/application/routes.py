"""Stable settings-window navigation identifiers and legacy routing."""

from dataclasses import dataclass
from enum import Enum


class RouteId(str, Enum):
    OVERVIEW = "overview"
    TASKS = "tasks"
    USAGE = "usage"
    NOTIFICATIONS_HISTORY = "notifications_history"
    INTEGRATIONS_DIAGNOSTICS = "integrations_diagnostics"
    PET_SETTINGS = "pet_settings"
    APP_STARTUP = "app_startup"
    WIDGET_SETTINGS = "widget_settings"

    # Source-compatible names for callers that only need the representative route.
    NOTIFICATIONS = NOTIFICATIONS_HISTORY
    HISTORY = NOTIFICATIONS_HISTORY
    INTEGRATIONS = INTEGRATIONS_DIAGNOSTICS
    DIAGNOSTICS = INTEGRATIONS_DIAGNOSTICS
    PET_APPEARANCE = PET_SETTINGS
    BEHAVIOR_DISPLAY = PET_SETTINGS
    PREFERENCES = APP_STARTUP

    @classmethod
    def normalize(cls, value, fallback=None):
        fallback = fallback or cls.OVERVIEW
        if isinstance(value, RouteTarget):
            return value.route
        raw = getattr(value, "value", value)
        legacy = LEGACY_ROUTE_TARGETS.get(str(raw))
        if legacy is not None:
            return legacy.route
        try:
            return value if isinstance(value, cls) else cls(str(value))
        except ValueError:
            return fallback

    @classmethod
    def resolve(cls, value, section="", fallback=None):
        """Resolve a representative route plus an optional legacy sub-page."""
        fallback = fallback or cls.OVERVIEW
        if isinstance(value, RouteTarget):
            return value
        raw = getattr(value, "value", value)
        legacy = LEGACY_ROUTE_TARGETS.get(str(raw))
        if legacy is not None:
            return legacy
        return RouteTarget(cls.normalize(value, fallback), str(section or ""))


@dataclass(frozen=True)
class RouteTarget:
    route: RouteId
    section: str = ""


LEGACY_ROUTE_TARGETS = {
    "notifications": RouteTarget(RouteId.NOTIFICATIONS_HISTORY, "notifications"),
    "history": RouteTarget(RouteId.NOTIFICATIONS_HISTORY, "history"),
    "integrations": RouteTarget(RouteId.INTEGRATIONS_DIAGNOSTICS, "integrations"),
    "diagnostics": RouteTarget(RouteId.INTEGRATIONS_DIAGNOSTICS, "diagnostics"),
    "pet_appearance": RouteTarget(RouteId.PET_SETTINGS, "appearance"),
    "behavior_display": RouteTarget(RouteId.PET_SETTINGS, "behavior"),
    "preferences": RouteTarget(RouteId.APP_STARTUP, "startup"),
}
