"""Bounded, privacy-safe application logging."""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path


LOGGER_NAME = "watched_kettle"
LOG_FILE_NAME = "app.log"
MAX_LOG_BYTES = 2 * 1024 * 1024
LOG_BACKUP_COUNT = 3
LOG_SCHEMA_VERSION = 1
_LOG_FAILURES = 0
_RUN_ID = uuid.uuid4().hex
_EVENT_FIELDS = frozenset(
    {
        "operation",
        "phase",
        "state",
        "error_code",
        "duration_ms",
        "attempt",
        "request_id",
        "operation_id",
        "exit_code",
        "delay_ms",
        "ready",
        "enabled",
        "refresh_id",
        "queue_size",
        "result",
        # Update download size and partial update file counts (numbers only).
        "bytes",
        "linked",
        "copied",
        "extracted",
        # Activity trace (WATCHED_KETTLE_TRACE_ACTIVITY): hashes and enums only.
        "source",
        "scope",
        "transport",
        "reason",
        "actor",
        "uncertain",
        "thread_ref",
        "turn_ref",
        "call_ref",
        "parent_ref",
        "selected_ref",
        "member_count",
        "project_ref",
        "card_ref",
        "incoming_scope",
        "known_scope",
        "generation",
        "epoch",
        "target_version",
        "request_generation",
        "request_epoch",
        "request_version",
        "rpc_code",
        "project_known",
        "title_present",
        "information_retained",
        "active",
        "completed",
        "compacting",
        "visible",
        "included",
        "project_kind",
        "target_kind",
        "context_available",
        "lookup_result",
        "lookup_error_code",
        "lookup_epoch",
        "lookup_generation",
        "lookup_version",
        "lookup_request_id",
        "fallback_result",
        "fallback_error_code",
    }
)
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")
_WINDOWS_PATH = re.compile(r"(?i)(?:[A-Z]:\\|\\\\)[^\r\n\t\"<>|]+")
_SENSITIVE_FIELD = re.compile(
    r"(?i)\b(prompt|command|transcript|tool_output|email|file_path|working_directory)\b"
    r"\s*[=:]\s*([^,;\r\n]+)"
)


def redact_diagnostic_text(value: object) -> str:
    """Remove common identity-bearing fields from diagnostic text."""
    text = str(value)
    text = _EMAIL.sub("<redacted-email>", text)
    text = _WINDOWS_PATH.sub("<redacted-path>", text)
    return _SENSITIVE_FIELD.sub(lambda match: f"{match.group(1)}=<redacted>", text)


def _safe_event_fields(fields):
    safe = {}
    for key, value in fields.items():
        key = str(key)
        if key not in _EVENT_FIELDS or value is None:
            continue
        if isinstance(value, bool):
            safe[key] = value
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            safe[key] = value
        elif isinstance(value, str):
            safe[key] = redact_diagnostic_text(value)
    return safe


def log_event(component, event, level=logging.INFO, **fields):
    """Write one bounded, privacy-safe structured lifecycle event."""
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)
    payload = {
        "component": redact_diagnostic_text(component),
        "event": redact_diagnostic_text(event),
        **_safe_event_fields(fields),
    }
    logging.getLogger(LOGGER_NAME).log(
        int(level),
        str(event),
        extra={"structured_event": payload},
    )


class PrivacyFilter(logging.Filter):
    """Apply a final redaction layer before a record reaches disk."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_diagnostic_text(record.getMessage())
        record.args = ()
        return True


class PrivacyFormatter(logging.Formatter):
    def formatException(self, exc_info):
        # Exception text may be arbitrary user content; retain types only.
        error = exc_info[1]
        names = []
        seen = set()
        while error is not None and id(error) not in seen and len(names) < 8:
            seen.add(id(error))
            names.append(type(error).__name__)
            error = error.__cause__ or error.__context__
        return "exception_types=" + ",".join(names)

    def formatStack(self, stack_info):
        return "stack_omitted"

    def format(self, record):
        event = getattr(record, "structured_event", None)
        payload = {
            "schema": LOG_SCHEMA_VERSION,
            "ts": datetime.fromtimestamp(record.created, timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "run_id": _RUN_ID,
        }
        if isinstance(event, dict):
            payload.update(event)
        else:
            payload.update(
                {
                    "component": record.name,
                    "event": "message",
                    "message": redact_diagnostic_text(record.getMessage()),
                }
            )
        if record.exc_info:
            payload["exception_types"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class SafeRotatingFileHandler(RotatingFileHandler):
    def shouldRollover(self, record):
        # TextIO.tell() is a byte offset; len(text) undercounts UTF-8 and CRLF.
        if self.maxBytes <= 0:
            return False
        if self.stream is None:
            self.stream = self._open()
        self.stream.seek(0, 2)
        message = (self.format(record) + self.terminator).replace("\n", os.linesep)
        encoded = message.encode(self.encoding, errors=self.errors or "strict")
        return self.stream.tell() + len(encoded) >= self.maxBytes

    def handleError(self, record):
        global _LOG_FAILURES
        _LOG_FAILURES += 1
        # Never let logging print an unredacted record/traceback to stderr.


def logging_status():
    return {
        "write_failures": _LOG_FAILURES,
        "code": "logging_unavailable" if _LOG_FAILURES else "ok",
        "schema_version": LOG_SCHEMA_VERSION,
        "run_id": _RUN_ID,
    }


def _archive_legacy_log(log_path: Path):
    if not log_path.is_file() or log_path.stat().st_size == 0:
        return
    try:
        first = (
            log_path.read_text(encoding="utf-8", errors="replace")
            .lstrip()
            .splitlines()[0]
        )
        parsed = json.loads(first)
        if isinstance(parsed, dict) and parsed.get("schema") == LOG_SCHEMA_VERSION:
            return
    except (OSError, IndexError, ValueError, TypeError):
        pass
    target = log_path.with_name(f"{log_path.name}.legacy")
    index = 1
    while target.exists():
        target = log_path.with_name(f"{log_path.name}.legacy.{index}")
        index += 1
    log_path.replace(target)


def configure_logging(log_directory: Path) -> Path | None:
    """A failed file log must never prevent the desktop pet from starting."""
    global _LOG_FAILURES, _RUN_ID
    close_logging()
    _RUN_ID = uuid.uuid4().hex
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        directory = Path(log_directory)
        directory.mkdir(parents=True, exist_ok=True)
        log_path = directory / LOG_FILE_NAME
        _archive_legacy_log(log_path)
        handler = SafeRotatingFileHandler(
            log_path,
            maxBytes=MAX_LOG_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
    except (OSError, ValueError):
        _LOG_FAILURES += 1
        handler = logging.NullHandler()
        log_path = None
    setattr(handler, "_watched_kettle_handler", True)
    handler.addFilter(PrivacyFilter())
    handler.setFormatter(
        PrivacyFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logger.addHandler(handler)
    log_event("application.logging", "configured")
    return log_path


def close_logging() -> None:
    """Flush and close application-owned handlers, primarily for tests."""
    logger = logging.getLogger(LOGGER_NAME)
    for handler in tuple(logger.handlers):
        if getattr(handler, "_watched_kettle_handler", False):
            logger.removeHandler(handler)
            handler.close()
