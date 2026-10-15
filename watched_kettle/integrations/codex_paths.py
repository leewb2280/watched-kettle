"""Resolve the active Codex home without changing external configuration."""

import os
from pathlib import Path


def codex_home() -> Path:
    value = os.environ.get("CODEX_HOME", "").strip()
    return Path(value).expanduser().resolve() if value else Path.home() / ".codex"
