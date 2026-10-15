"""Factories that keep runtime tests away from production IPC and user files."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from watched_kettle.integrations.codex_ipc import CodexHookServer


def isolated_codex_server(
    root: Path,
    *,
    server_name: str | None = None,
) -> CodexHookServer:
    """Create a dedicated server whose endpoints and files belong to one test."""
    root = Path(root)
    return CodexHookServer(
        server_name=server_name or f"watched-kettle-test-{uuid4().hex}",
        spool_directory=root / "spool",
        hook_config_path=root / "hooks.json",
        global_hook_config_path=root / "global-hooks.json",
        codex_config_path=root / "config.toml",
        hook_health_path=root / "hook-health.json",
        managed_spool_directory=None,
        managed_hook_health_path=None,
    )
