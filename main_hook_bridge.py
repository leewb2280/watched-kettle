"""PyInstaller entry point for the Qt-free Codex hook bridge."""

from watched_kettle.hook_bridge_entrypoint import main


if __name__ == "__main__":
    raise SystemExit(main())
