"""Notices when a tool in use lost this app's hooks or a new tool appeared.

The watch only judges. The runtime turns each new alert into a system notice;
the tray and the settings home read the snapshot while it lasts
(docs/bubble-architecture.md 2절).

- broken: a switched-on tool whose folder is here but whose hooks are missing,
  partly changed or unreadable. Each episode is told once per app run, and
  again after it recovers and breaks anew. A tool the user or a policy turned
  off in its own settings is not broken, nor is one whose hooks belong to
  another copy of this app on the PC (installed or source run): both copies
  spool events to the same folder, so they still arrive.
- found: a switched-off tool whose folder appeared after this app first
  looked. Told once ever; the first check only records what is already here,
  since the installer showed those tools.
"""

from __future__ import annotations

from watched_kettle.localization import t

from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal

from watched_kettle.features.integrations.activation import TOOL_LABELS, TOOLS

KNOWN_TOOLS_KEY = "integrations/knownTools"
BROKEN_STATES = frozenset({"not_installed", "partial", "drifted", "invalid"})
FIRST_CHECK_MS = 5_000
CHECK_INTERVAL_MS = 10 * 60 * 1000


@dataclass(frozen=True)
class ConnectionAlert:
    tool: str
    kind: str
    state: str = ""

    @property
    def label(self):
        return TOOL_LABELS[self.tool]

    @property
    def message(self):
        label = self.label
        if self.kind == "broken":
            return t("message.0453", value0=label)
        return t("message.0452", value0=label)


class ConnectionWatch(QObject):
    changed = Signal(object)
    announce_ready = Signal(object)

    def __init__(self, settings, enabled, inspect, detected, parent=None):
        """``inspect(tool)`` returns the tool's hook status; it is called only
        while the tool is switched on (activation.py)."""
        super().__init__(parent)
        self.settings = settings
        self.enabled = enabled
        self.inspect = inspect
        self.detected = detected
        self.snapshot: tuple[ConnectionAlert, ...] = ()
        self._announced: set[tuple[str, str]] = set()
        self._found: set[str] = set()
        self._first = QTimer(self)
        self._first.setSingleShot(True)
        self._first.setInterval(FIRST_CHECK_MS)
        self._first.timeout.connect(self.check)
        self._timer = QTimer(self)
        self._timer.setInterval(CHECK_INTERVAL_MS)
        self._timer.timeout.connect(self.check)

    def start(self):
        self._first.start()
        self._timer.start()

    def close(self):
        self._first.stop()
        self._timer.stop()

    def check(self, *_args):
        known = self._known()
        first = known is None
        known = set(known or ())
        alerts = []
        for tool in TOOLS:
            enabled = bool(self.enabled(tool))
            detected = self._detected(tool)
            if enabled:
                self._found.discard(tool)
                state = self._state(tool) if detected else ""
                if state in BROKEN_STATES:
                    alerts.append(ConnectionAlert(tool, "broken", state))
            elif detected and not first and tool not in known:
                self._found.add(tool)
            if detected:
                known.add(tool)
            if tool in self._found:
                alerts.append(ConnectionAlert(tool, "found"))
        if first or known != set(self._known() or ()):
            self.settings.setValue(KNOWN_TOOLS_KEY, ",".join(sorted(known)))
        current = {(a.tool, a.kind) for a in alerts}
        # A recovered tool is told again when it breaks anew; found stays told.
        self._announced = {
            key for key in self._announced if key in current or key[1] == "found"
        }
        snapshot = tuple(alerts)
        if snapshot != self.snapshot:
            self.snapshot = snapshot
            self.changed.emit(snapshot)
        for alert in alerts:
            key = (alert.tool, alert.kind)
            if key not in self._announced:
                self._announced.add(key)
                self.announce_ready.emit(alert)
        return snapshot

    def alert(self, tool):
        return next((a for a in self.snapshot if a.tool == tool), None)

    def _known(self):
        value = self.settings.value(KNOWN_TOOLS_KEY, None)
        if value is None:
            return None
        if isinstance(value, (list, tuple)):
            value = ",".join(str(v) for v in value)
        return {name for name in str(value).split(",") if name in TOOLS}

    def _detected(self, tool):
        try:
            return bool(self.detected(tool))
        except OSError:
            return False

    def _state(self, tool):
        try:
            return str(self.inspect(tool).state)
        except Exception:
            # An unreadable file is the "invalid" state, not a crash.
            return "invalid"
