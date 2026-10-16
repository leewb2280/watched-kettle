"""Installer-side tool switches, run without starting the app.

The Windows installer calls ``WatchedKettle.exe --configure-integrations
--codex=on|off --claude-code=on|off`` after copying files. Each named tool goes
through the same switch as the settings window (features/integrations/
activation.py): its managed files and its usage switch change together, and a
tool that is not named keeps both.
"""

from __future__ import annotations

TOOL_FLAGS = {"--codex": "codex", "--claude-code": "claude_code"}


def parse_tool_choices(arguments):
    """Return {tool: enabled} for each ``--tool=on|off`` argument."""
    choices = {}
    for argument in arguments:
        flag, separator, value = str(argument).partition("=")
        if flag not in TOOL_FLAGS:
            continue
        if not separator or value not in {"on", "off"}:
            raise ValueError(f"expected {flag}=on or {flag}=off")
        choices[TOOL_FLAGS[flag]] = value == "on"
    return choices


def default_installers():
    from watched_kettle.integrations.claude_code_install import (
        ClaudeCodeHookInstaller,
    )
    from watched_kettle.integrations.claude_code_status_line_install import (
        ClaudeCodeStatusLineInstaller,
    )
    from watched_kettle.integrations.codex_install import CodexHookInstaller

    return {
        "codex": CodexHookInstaller(),
        "claude_code": ClaudeCodeHookInstaller(),
        "claude_code_status_line": ClaudeCodeStatusLineInstaller(),
    }


def run_integration_setup(arguments, preferences=None, installers=None):
    """Return 0 when every named tool's files changed, 2 when any could not.

    The switch is saved either way, so a blocked removal still turns the tool
    off and the app ignores its leftover hooks.
    """
    try:
        choices = parse_tool_choices(arguments)
    except ValueError:
        return 2
    if not choices:
        return 2
    if preferences is None:
        from watched_kettle.app_preferences import ApplicationPreferences

        preferences = ApplicationPreferences()
    from watched_kettle.features.integrations.activation import ToolActivation

    activation = ToolActivation(
        preferences, installers if installers is not None else default_installers()
    )
    exit_code = 0
    for tool, enabled in choices.items():
        result = activation.apply(activation.preview(tool, enabled))
        if not result.complete:
            exit_code = 2
    return exit_code
