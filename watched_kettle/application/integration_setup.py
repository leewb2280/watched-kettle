"""Apply the installer's Codex and Claude Code choices without starting the app.

``--configure-integrations --codex=on --claude-code=off`` installs or removes
this app's managed hook for each named tool and sets that tool's usage switch.
A tool that is not named keeps its hooks and settings unchanged.
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


def run_integration_setup(arguments, preferences=None, installers=None):
    """Return 0 when every named tool was applied, 2 when any was blocked."""
    try:
        choices = parse_tool_choices(arguments)
    except ValueError:
        return 2
    if not choices:
        return 2
    if preferences is None:
        from watched_kettle.app_preferences import ApplicationPreferences

        preferences = ApplicationPreferences()
    if installers is None:
        from watched_kettle.integrations.claude_code_install import (
            ClaudeCodeHookInstaller,
        )
        from watched_kettle.integrations.codex_install import CodexHookInstaller

        installers = {
            "codex": CodexHookInstaller(),
            "claude_code": ClaudeCodeHookInstaller(),
        }
    save_switch = {
        # usage/enabled is the Codex-only switch (docs/bubble-architecture.md 2절).
        "codex": preferences.save_usage_enabled,
        "claude_code": preferences.save_claude_code_usage_enabled,
    }
    exit_code = 0
    for tool, enabled in choices.items():
        installer = installers[tool]
        plan = installer.preview_install() if enabled else installer.preview_remove()
        if not plan.can_apply:
            # A blocked change (hooks disabled in config, unreadable file)
            # keeps the user's files and switch untouched.
            exit_code = 2
            continue
        if plan.has_changes:
            installer.apply(plan)
        save_switch[tool](enabled)
    preferences.settings.sync()
    return exit_code
