"""User-scoped local IPC between Codex hooks and the desktop pet."""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from watched_kettle.integrations.codex_paths import codex_home
import time

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QLocalServer

from watched_kettle.activity_diagnostics import (
    DiagnosticRecorder,
    diagnostic_guard,
    diagnostic_ref,
    diagnostic_thread_ref,
)

from watched_kettle.integrations.codex_install import DEFAULT_GLOBAL_HOOKS_PATH
from watched_kettle.integrations.codex_client import configured_pet_server_name
from watched_kettle.integrations.codex_hooks import (
    MAX_IPC_EVENT_BYTES,
    sanitize_pet_event,
)
from watched_kettle.integrations.codex_spool import (
    DEFAULT_HOOK_HEALTH_PATH,
    DEFAULT_SPOOL_DIRECTORY,
    DEFAULT_USER_CLAUDE_CODE_HOOK_HEALTH_PATH,
    DEFAULT_USER_HOOK_HEALTH_PATH,
    DEFAULT_USER_SPOOL_DIRECTORY,
    drain_spooled_events,
    read_hook_health,
)


DEFAULT_HOOK_CONFIG_PATH = Path(__file__).resolve().parents[2] / ".codex" / "hooks.json"
DEFAULT_CODEX_CONFIG_PATH = codex_home() / "config.toml"
PIPE_TRANSPORT = "named_pipe"
QUEUE_TRANSPORT = "workspace_queue"
JSONL_TRANSPORT = "codex_jsonl"
TRANSCRIPT_TRANSPORT = "claude_code_transcript"
RECENT_EVENT_RETENTION_SECONDS = 10
JSONL_DUPLICATE_WINDOW_SECONDS = 3
_AUTO_MANAGED_RUNTIME = object()


@dataclass(frozen=True)
class _RecentEvent:
    signature: tuple
    transport: str
    recorded_at: float


class CodexHookServer(QObject):
    """Receive bounded JSON events through a current-user-only local pipe."""

    payload_received = Signal(dict)

    def __init__(
        self,
        server_name=None,
        parent=None,
        spool_directory=DEFAULT_SPOOL_DIRECTORY,
        hook_config_path=DEFAULT_HOOK_CONFIG_PATH,
        global_hook_config_path=DEFAULT_GLOBAL_HOOKS_PATH,
        codex_config_path=DEFAULT_CODEX_CONFIG_PATH,
        hook_health_path=DEFAULT_HOOK_HEALTH_PATH,
        managed_spool_directory=_AUTO_MANAGED_RUNTIME,
        managed_hook_health_path=_AUTO_MANAGED_RUNTIME,
        claude_code_hook_health_path=_AUTO_MANAGED_RUNTIME,
    ):
        super().__init__(parent)
        self.server_name = server_name or configured_pet_server_name()
        self.event_count = 0
        self.transport_event_counts = {
            PIPE_TRANSPORT: 0,
            QUEUE_TRANSPORT: 0,
            JSONL_TRANSPORT: 0,
            TRANSCRIPT_TRANSPORT: 0,
        }
        self.received_event_counts = {
            PIPE_TRANSPORT: 0,
            QUEUE_TRANSPORT: 0,
            JSONL_TRANSPORT: 0,
            TRANSCRIPT_TRANSPORT: 0,
        }
        self.suppressed_duplicate_count = 0
        # Agents switched off in the settings window; their events are dropped.
        self.disabled_sources = set()
        self.disabled_source_drop_count = 0
        self.last_event = ""
        self.last_transport = ""
        self.last_received_at = None
        self.last_hook_received_at = None
        self.last_jsonl_received_at = None
        self.last_schedule_received_at = None
        self.schedule_event_count = 0
        self.codex_hook_event_count = 0
        self.claude_code_hook_event_count = 0
        self.last_claude_code_hook_received_at = None
        self.claude_code_status_line_count = 0
        self.last_claude_code_status_line_at = None
        self.last_error = ""
        self.log_monitor = None
        self.transcript_monitor = None
        # Optional ``trace(event, **fields)``; see ProjectActivityService.trace.
        self.trace = None
        self.activity_diagnostics = DiagnosticRecorder()
        self._recent_events = {}
        self._buffers = {}
        self.spool_directory = Path(spool_directory)
        production_runtime = self.spool_directory == DEFAULT_SPOOL_DIRECTORY
        if managed_spool_directory is _AUTO_MANAGED_RUNTIME:
            managed_spool_directory = (
                DEFAULT_USER_SPOOL_DIRECTORY if production_runtime else None
            )
        self.spool_directories = [self.spool_directory]
        if managed_spool_directory is not None:
            managed_spool_directory = Path(managed_spool_directory)
            if managed_spool_directory not in self.spool_directories:
                self.spool_directories.append(managed_spool_directory)
        self.hook_config_path = Path(hook_config_path)
        self.global_hook_config_path = Path(global_hook_config_path)
        self.codex_config_path = Path(codex_config_path)
        self.hook_health_path = Path(hook_health_path)
        if managed_hook_health_path is _AUTO_MANAGED_RUNTIME:
            managed_hook_health_path = (
                DEFAULT_USER_HOOK_HEALTH_PATH
                if production_runtime
                and self.hook_health_path == DEFAULT_HOOK_HEALTH_PATH
                else None
            )
        if claude_code_hook_health_path is _AUTO_MANAGED_RUNTIME:
            claude_code_hook_health_path = (
                DEFAULT_USER_CLAUDE_CODE_HOOK_HEALTH_PATH
                if production_runtime
                else None
            )
        self.claude_code_hook_health_path = (
            Path(claude_code_hook_health_path)
            if claude_code_hook_health_path is not None
            else None
        )
        self.hook_health_paths = [self.hook_health_path]
        if managed_hook_health_path is not None:
            managed_hook_health_path = Path(managed_hook_health_path)
            if managed_hook_health_path not in self.hook_health_paths:
                self.hook_health_paths.append(managed_hook_health_path)

        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.UserAccessOption)
        self.server.newConnection.connect(self._accept_connections)
        self.spool_timer = QTimer(self)
        self.spool_timer.setInterval(100)
        self.spool_timer.timeout.connect(self._drain_spool)

    @property
    def is_listening(self):
        return self.server.isListening()

    @property
    def is_queue_receiver_active(self):
        return self.spool_timer.isActive()

    def start(self):
        self.spool_timer.start()
        self._drain_spool()
        if self.server.isListening():
            return True
        if self.server.listen(self.server_name):
            self.last_error = ""
            return True
        self.last_error = self.server.errorString()
        return False

    def close(self):
        self.spool_timer.stop()
        self.attach_log_monitor(None)
        self.attach_transcript_monitor(None)
        for socket in tuple(self._buffers):
            socket.abort()
            socket.deleteLater()
        self._buffers.clear()
        self.server.close()

    def attach_log_monitor(self, monitor):
        """Attach an optional read-only Codex rollout fallback monitor."""
        if self.log_monitor is monitor:
            return
        if self.log_monitor is not None:
            try:
                self.log_monitor.payload_detected.disconnect(
                    self._receive_jsonl_payload
                )
            except (RuntimeError, TypeError):
                pass
        self.log_monitor = monitor
        if monitor is not None:
            monitor.payload_detected.connect(self._receive_jsonl_payload)

    def _receive_jsonl_payload(self, payload):
        self._deliver_payload(payload, JSONL_TRANSPORT)

    def attach_transcript_monitor(self, monitor):
        """Attach the Claude Code silent turn-end monitor (stage 13)."""
        if self.transcript_monitor is monitor:
            return
        if self.transcript_monitor is not None:
            try:
                self.transcript_monitor.payload_detected.disconnect(
                    self._receive_transcript_payload
                )
            except (RuntimeError, TypeError):
                pass
        self.transcript_monitor = monitor
        if monitor is not None:
            monitor.payload_detected.connect(self._receive_transcript_payload)

    def _receive_transcript_payload(self, payload):
        payload = sanitize_pet_event(payload)
        if payload is not None:
            self._deliver_payload(payload, TRANSCRIPT_TRANSPORT)

    def _drain_spool(self):
        for spool_directory in self.spool_directories:
            for payload in drain_spooled_events(spool_directory):
                self._deliver_payload(payload, QUEUE_TRANSPORT)

    def _accept_connections(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            if socket is None:
                continue
            if len(self._buffers) >= 32:
                socket.abort()
                socket.deleteLater()
                continue
            socket.setReadBufferSize(MAX_IPC_EVENT_BYTES + 1)
            self._buffers[socket] = bytearray()
            idle = QTimer(socket)
            idle.setSingleShot(True)
            idle.timeout.connect(lambda socket=socket: self._expire_socket(socket))
            socket.readyRead.connect(lambda idle=idle: idle.start(5000))
            idle.start(5000)
            socket.readyRead.connect(lambda socket=socket: self._read_socket(socket))
            socket.disconnected.connect(
                lambda socket=socket: self._finish_socket(socket)
            )
            self._read_socket(socket)

    def _expire_socket(self, socket):
        if socket in self._buffers:
            socket.abort()
            self._discard_socket(socket)

    def _read_socket(self, socket):
        if socket not in self._buffers:
            return
        self._buffers[socket].extend(bytes(socket.readAll()))
        if len(self._buffers[socket]) > MAX_IPC_EVENT_BYTES:
            socket.abort()
            self._discard_socket(socket)
            return

        while b"\n" in self._buffers.get(socket, b""):
            line, _, remainder = self._buffers[socket].partition(b"\n")
            self._buffers[socket] = bytearray(remainder)
            self._process_line(line, socket)

    def _finish_socket(self, socket):
        self._read_socket(socket)
        remaining = bytes(self._buffers.get(socket, b""))
        if remaining:
            self._process_line(remaining, socket)
        self._discard_socket(socket)

    def _discard_socket(self, socket):
        if socket not in self._buffers:
            return
        self._buffers.pop(socket, None)
        socket.deleteLater()

    def _process_line(self, line, socket):
        if not line or len(line) > MAX_IPC_EVENT_BYTES:
            return
        try:
            raw = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return

        payload = sanitize_pet_event(raw)
        if payload is None:
            return
        self._deliver_payload(payload, PIPE_TRANSPORT)
        socket.write(b"OK\n")
        socket.flush()

    def set_source_enabled(self, source, enabled):
        """Accept or drop one agent's events from every transport."""
        if enabled:
            self.disabled_sources.discard(source)
        else:
            self.disabled_sources.add(source)

    def _deliver_payload(self, payload, transport):
        if payload.get("source") in self.disabled_sources:
            # A hook left behind after the tool was switched off.
            self.disabled_source_drop_count += 1
            return False
        incoming_scope = payload.get("agent_scope", "unknown")
        known_scope = "unknown"
        if payload.get("source") == "codex":
            scope = payload.get("agent_scope", "unknown")
            # Legacy hooks also claimed main without inspecting thread identity.
            if transport != JSONL_TRANSPORT and scope == "main":
                scope = "unknown"
            if self.log_monitor is not None:
                known_scope = self.log_monitor.session_scope(payload["session_id"])
                if known_scope != "unknown":
                    scope = known_scope
            payload = {**payload, "agent_scope": scope}
        now = time.monotonic()
        received_at = datetime.now().astimezone()
        self.received_event_counts[transport] += 1
        if payload.get("source") == "schedule":
            self.last_schedule_received_at = received_at
            self.schedule_event_count += 1
        elif transport == JSONL_TRANSPORT:
            self.last_jsonl_received_at = received_at
        elif transport == TRANSCRIPT_TRANSPORT:
            pass
        else:
            self.last_hook_received_at = received_at

        self._discard_old_recent_events(now)
        event_key = (
            payload.get("source", ""),
            payload["session_id"],
            payload["event"],
            payload.get("turn_id", ""),
            payload.get("event_id", ""),
            payload.get("agent_scope", ""),
        )
        signature = (
            payload.get("parent_session_id", ""),
            payload.get("outcome_reason", ""),
            payload.get("approval_actor", "unknown"),
            payload.get("compaction_phase", ""),
            payload.get("tool_status", ""),
            payload.get("success"),
            # A status line update with new numbers is not a duplicate.
            payload.get("five_hour_percent"),
            payload.get("seven_day_percent"),
        )
        previous = self._recent_events.get(event_key)
        duplicate = (
            previous is not None
            and previous.signature == signature
            and self._is_duplicate(transport, previous, now)
        )
        self._trace_delivery(payload, transport, duplicate, incoming_scope, known_scope)
        if duplicate:
            self.suppressed_duplicate_count += 1
            return False

        # Retain the latest semantics for this request, so user -> auto -> user
        # is three changes rather than a replay of the first permission event.
        self._recent_events[event_key] = _RecentEvent(signature, transport, now)
        self.event_count += 1
        self.transport_event_counts[transport] += 1
        if payload.get("source") == "codex" and transport != JSONL_TRANSPORT:
            self.codex_hook_event_count += 1
        elif payload.get("event") == "rate_limits":
            self.claude_code_status_line_count += 1
            self.last_claude_code_status_line_at = received_at
        elif (
            payload.get("source") == "claude_code" and transport != TRANSCRIPT_TRANSPORT
        ):
            self.claude_code_hook_event_count += 1
            self.last_claude_code_hook_received_at = received_at
        self.last_event = payload["event"]
        self.last_transport = transport
        self.last_received_at = received_at
        self.payload_received.emit(payload)
        if (
            self.transcript_monitor is not None
            and payload.get("source") == "claude_code"
            and transport != TRANSCRIPT_TRANSPORT
        ):
            self.transcript_monitor.observe(payload)
        return True

    @diagnostic_guard
    def _trace_delivery(
        self,
        payload,
        transport,
        duplicate,
        incoming_scope="unknown",
        known_scope="unknown",
    ):
        source = str(payload.get("source") or "")
        fields = dict(
            source=str(payload.get("source") or ""),
            operation=str(payload.get("event") or ""),
            transport=transport,
            scope=str(payload.get("agent_scope") or ""),
            actor=str(payload.get("approval_actor") or ""),
            thread_ref=diagnostic_thread_ref(source, payload.get("session_id")),
            turn_ref=_trace_ref(payload.get("turn_id")),
            call_ref=_trace_ref(payload.get("event_id")),
            parent_ref=diagnostic_thread_ref(source, payload.get("parent_session_id")),
            result="duplicate" if duplicate else "accepted",
            incoming_scope=incoming_scope,
            known_scope=known_scope,
        )
        recorder = self.activity_diagnostics
        if not duplicate and payload.get("event") in {"prompt", "task_start"}:
            recorder.emit("activity_input", **fields)
        if not duplicate and payload.get("event") in {
            "tool_start",
        }:
            recorder.record(
                "activity_input",
                (fields["thread_ref"], fields["turn_ref"]),
                compare=("scope", "incoming_scope", "known_scope"),
                **fields,
            )
        if incoming_scope != fields["scope"]:
            recorder.record(
                "scope_corrected",
                fields["thread_ref"],
                compare=("scope", "incoming_scope", "known_scope"),
                **fields,
            )
        if self.trace is not None:
            self.trace("event_received", **fields)

    @staticmethod
    def _is_duplicate(transport, previous, now):
        elapsed = now - previous.recorded_at
        if elapsed < 0:
            return False
        if transport == JSONL_TRANSPORT and previous.transport != JSONL_TRANSPORT:
            return elapsed <= JSONL_DUPLICATE_WINDOW_SECONDS
        return elapsed <= 1

    def _discard_old_recent_events(self, now):
        stale = [
            key
            for key, record in self._recent_events.items()
            if now - record.recorded_at > RECENT_EVENT_RETENTION_SECONDS
        ]
        for key in stale:
            self._recent_events.pop(key, None)

    def queued_event_count(self):
        count = 0
        for spool_directory in self.spool_directories:
            try:
                count += sum(1 for _ in spool_directory.glob("*.json"))
            except OSError:
                continue
        return count

    def hook_health_status(self):
        records = [read_hook_health(path) for path in self.hook_health_paths]
        valid = [record for record in records if record["valid"]]
        if valid:
            return max(valid, key=lambda record: record["recorded_at"])
        return next(
            (record for record in records if record["exists"]),
            records[0],
        )

    def hook_config_status(self, hook_config_path=None):
        """Return bounded local configuration facts for the settings UI."""
        hook_config_path = Path(hook_config_path or self.hook_config_path)
        if not hook_config_path.is_file():
            return {"exists": False, "valid": False, "event_count": 0}
        try:
            payload = json.loads(hook_config_path.read_text("utf-8"))
            hooks = payload.get("hooks")
            if not isinstance(hooks, dict):
                raise ValueError("hooks must be an object")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return {"exists": True, "valid": False, "event_count": 0}
        return {
            "exists": True,
            "valid": True,
            "event_count": len(hooks),
        }

    def hook_trust_status(self, expected_count, hook_config_path=None):
        """Read only the approval records for this project's hook file."""
        hook_config_path = Path(hook_config_path or self.hook_config_path)
        empty = {
            "exists": False,
            "valid": False,
            "approved_count": 0,
            "expected_count": expected_count,
            "possibly_stale": False,
        }
        if not self.codex_config_path.is_file():
            return empty
        try:
            payload = tomllib.loads(self.codex_config_path.read_text(encoding="utf-8"))
            state = payload.get("hooks", {}).get("state", {})
            if not isinstance(state, dict):
                raise ValueError("hooks.state must be a table")
            hook_prefix = f"{hook_config_path.resolve()}:".casefold()
            approved_count = sum(
                1
                for key, value in state.items()
                if isinstance(key, str)
                and key.casefold().startswith(hook_prefix)
                and isinstance(value, dict)
                and isinstance(value.get("trusted_hash"), str)
                and value["trusted_hash"].startswith("sha256:")
            )
            possibly_stale = (
                approved_count > 0
                and hook_config_path.stat().st_mtime_ns
                > self.codex_config_path.stat().st_mtime_ns
            )
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, ValueError):
            return {
                **empty,
                "exists": True,
            }
        return {
            "exists": True,
            "valid": True,
            "approved_count": approved_count,
            "expected_count": expected_count,
            "possibly_stale": possibly_stale,
        }

    def hooks_feature_status(self):
        """Report the canonical feature switch; hooks default to enabled."""
        default = {
            "exists": False,
            "valid": False,
            "enabled": True,
            "explicit": False,
            "deprecated_alias": False,
        }
        if not self.codex_config_path.is_file():
            return default
        try:
            payload = tomllib.loads(self.codex_config_path.read_text(encoding="utf-8"))
            features = payload.get("features", {})
            if not isinstance(features, dict):
                raise ValueError("features must be a table")
            if "hooks" in features:
                value = features["hooks"]
                if not isinstance(value, bool):
                    raise ValueError("features.hooks must be boolean")
                return {
                    **default,
                    "exists": True,
                    "valid": True,
                    "enabled": value,
                    "explicit": True,
                }
            if "codex_hooks" in features:
                value = features["codex_hooks"]
                if not isinstance(value, bool):
                    raise ValueError("features.codex_hooks must be boolean")
                return {
                    **default,
                    "exists": True,
                    "valid": True,
                    "enabled": value,
                    "explicit": True,
                    "deprecated_alias": True,
                }
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, ValueError):
            return {
                **default,
                "exists": True,
            }
        return {
            **default,
            "exists": True,
            "valid": True,
        }

    def diagnostics(self):
        """Expose privacy-safe connection diagnostics without raw hook data.

        While Codex is switched off its files are not read; the Codex facts
        report empty states and only the receiver's own counters remain.
        """
        codex_off = "codex" in self.disabled_sources
        no_config = {"exists": False, "valid": False, "event_count": 0}
        hook_config = no_config if codex_off else self.hook_config_status()
        global_hook_config = (
            no_config
            if codex_off
            else self.hook_config_status(self.global_hook_config_path)
        )
        log_monitor = (
            self.log_monitor.diagnostics()
            if self.log_monitor is not None
            else {
                "active": False,
                "sessions_root_exists": False,
                "tracked_files": 0,
                "event_count": 0,
                "last_event": "",
                "last_detected_at": None,
                "last_error": "",
            }
        )
        config_exists = self.codex_config_path.is_file()
        codex_environment = {
            "detected": bool(config_exists or log_monitor["sessions_root_exists"]),
            "config_exists": config_exists,
            "sessions_root_exists": log_monitor["sessions_root_exists"],
        }
        empty_trust = {
            "exists": False,
            "valid": False,
            "approved_count": 0,
            "possibly_stale": False,
        }
        return {
            "pipe_listening": self.is_listening,
            "queue_receiver_active": self.is_queue_receiver_active,
            "queued_events": self.queued_event_count(),
            "event_count": self.event_count,
            "pipe_event_count": self.transport_event_counts[PIPE_TRANSPORT],
            "queue_event_count": self.transport_event_counts[QUEUE_TRANSPORT],
            "jsonl_event_count": self.transport_event_counts[JSONL_TRANSPORT],
            "received_pipe_event_count": self.received_event_counts[PIPE_TRANSPORT],
            "received_queue_event_count": self.received_event_counts[QUEUE_TRANSPORT],
            "received_jsonl_event_count": self.received_event_counts[JSONL_TRANSPORT],
            "suppressed_duplicate_count": self.suppressed_duplicate_count,
            "last_event": self.last_event,
            "last_transport": self.last_transport,
            "last_received_at": self.last_received_at,
            "last_hook_received_at": self.last_hook_received_at,
            "last_jsonl_received_at": self.last_jsonl_received_at,
            "last_schedule_received_at": self.last_schedule_received_at,
            "schedule_event_count": self.schedule_event_count,
            "codex_hook_event_count": self.codex_hook_event_count,
            "last_error": self.last_error,
            "hook_config": hook_config,
            "global_hook_config": global_hook_config,
            "hook_health": self.hook_health_status(),
            "hooks_feature": (
                {
                    "exists": False,
                    "valid": False,
                    "enabled": True,
                    "explicit": False,
                    "deprecated_alias": False,
                }
                if codex_off
                else self.hooks_feature_status()
            ),
            "hook_trust": (
                {**empty_trust, "expected_count": 0}
                if codex_off
                else self.hook_trust_status(hook_config["event_count"])
            ),
            "global_hook_trust": (
                {**empty_trust, "expected_count": 0}
                if codex_off
                else self.hook_trust_status(
                    global_hook_config["event_count"],
                    self.global_hook_config_path,
                )
            ),
            "codex_enabled": not codex_off,
            "disabled_source_drop_count": self.disabled_source_drop_count,
            "codex_environment": codex_environment,
            "jsonl_monitor": log_monitor,
            "claude_code": self.claude_code_diagnostics(),
        }

    def claude_code_diagnostics(self):
        """Claude Code receive state; installation is reported by its installer."""
        monitor = self.transcript_monitor
        return {
            "hook_event_count": self.claude_code_hook_event_count,
            "last_hook_received_at": self.last_claude_code_hook_received_at,
            "status_line_count": self.claude_code_status_line_count,
            "last_status_line_at": self.last_claude_code_status_line_at,
            "hook_health": read_hook_health(self.claude_code_hook_health_path)
            if self.claude_code_hook_health_path is not None
            else None,
            # Key names avoid the diagnostics redaction tokens (session, transcript).
            "turn_end_monitor": {
                "attached": monitor is not None,
                "active_turns": len(monitor.watched_sessions) if monitor else 0,
                "detected_count": monitor.detected_count if monitor else 0,
            },
        }


def _trace_ref(value):
    return diagnostic_ref(value)
