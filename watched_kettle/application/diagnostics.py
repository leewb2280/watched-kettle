"""Export a bounded diagnostic bundle without user content or database rows."""

from __future__ import annotations

import json
import platform
import zipfile
from pathlib import Path

from PySide6 import __version__ as PYSIDE_VERSION
from PySide6.QtCore import qVersion

from watched_kettle.application.logging import redact_diagnostic_text, logging_status
from watched_kettle.branding import APPLICATION_VERSION


_SENSITIVE_KEYS = (
    "command",
    "email",
    "path",
    "prompt",
    "session",
    "thread",
    "transcript",
    "output",
)


def _safe_snapshot(value: object) -> object:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            normalized = str(key).casefold()
            if any(token in normalized for token in _SENSITIVE_KEYS):
                continue
            result[str(key)] = _safe_snapshot(item)
        return result
    if isinstance(value, (list, tuple, set, frozenset)):
        return {"item_count": len(value)}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_diagnostic_text(value)


class DiagnosticsExporter:
    """Create a support ZIP containing metadata and already-redacted logs only."""

    def __init__(self, paths, schema_version: int):
        self.paths = paths
        self.schema_version = int(schema_version)

    def export(self, target: Path, integration_snapshot: dict | None = None) -> Path:
        """Write a diagnostic ZIP and return its absolute path."""
        target = Path(target)
        if target.suffix.casefold() != ".zip":
            target = target.with_suffix(".zip")
        target.parent.mkdir(parents=True, exist_ok=True)
        log_status = logging_status()
        metadata = {
            "application_version": APPLICATION_VERSION,
            "platform": platform.system(),
            "platform_release": platform.release(),
            "python_version": platform.python_version(),
            "pyside_version": PYSIDE_VERSION,
            "qt_version": qVersion(),
            "database_schema_version": self.schema_version,
            "integration": _safe_snapshot(integration_snapshot or {}),
            "logging": log_status,
            "log_schema_version": log_status["schema_version"],
            "run_id": log_status["run_id"],
        }
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr(
                "diagnostics.json",
                json.dumps(metadata, ensure_ascii=False, indent=2),
            )
            for log_path in sorted(self.paths.logs.glob("app.log*")):
                try:
                    content = log_path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                bundle.writestr(
                    f"logs/{log_path.name}",
                    redact_diagnostic_text(content),
                )
        return target.resolve()
