"""One "use this tool" switch per agent: its managed files and its usage switch.

Turning a tool on installs its managed hooks and turns its usage on; a hook
that Codex or Claude Code blocks only limits activity, so the tool still turns
on. Turning a tool off removes its managed hooks (and the Claude Code status
line) and always turns it off, even when a file cannot be changed: the app
then drops that tool's events (docs/bubble-architecture.md 2절).
"""

from __future__ import annotations

from dataclasses import dataclass

TOOLS = ("codex", "claude_code")
TOOL_LABELS = {"codex": "Codex", "claude_code": "Claude Code"}
# Settings key of the one-time move from the separate hook and usage switches.
ACTIVATION_MIGRATION_KEY = "internal/toolActivation"
# Install states that mean this app's hooks are (partly) in the user's file.
MANAGED_STATES = ("installed", "partial", "drifted")


@dataclass(frozen=True)
class ActivationStep:
    provider: str
    plan: object | None
    error: str = ""


@dataclass(frozen=True)
class ActivationPlan:
    tool: str
    enabled: bool
    steps: tuple[ActivationStep, ...]

    @property
    def can_apply(self):
        # The switch always applies; blocked files become warnings.
        return True

    @property
    def changes(self):
        label = TOOL_LABELS[self.tool]
        lines = [f"{label} 사용을 {'켭니다' if self.enabled else '끕니다'}"]
        for step in self.steps:
            if step.plan is not None and step.plan.can_apply:
                lines.extend(step.plan.changes)
        return tuple(lines)

    @property
    def warnings(self):
        lines = []
        for step in self.steps:
            plan = step.plan
            if step.error or plan is None or not plan.can_apply:
                lines.append(_blocked_message(self.tool, self.enabled, step.provider))
            if plan is not None:
                lines.extend(plan.warnings)
        if not self.enabled:
            lines.append("저장된 사용량 기록은 지우지 않습니다. 다시 켜면 보입니다.")
        return tuple(dict.fromkeys(lines))


@dataclass(frozen=True)
class ActivationResult:
    tool: str
    enabled: bool
    complete: bool


def _blocked_message(tool, enabled, provider):
    if provider == "claude_code_status_line":
        return (
            "Claude Code status line을 되돌리지 못했습니다. 설정 파일을 확인해 주세요."
        )
    label = TOOL_LABELS[tool]
    if enabled:
        return f"{label} hook을 설치할 수 없어 활동 표시가 제한됩니다."
    return f"{label} hook을 지우지 못했습니다. 남은 hook의 이벤트는 앱이 무시합니다."


def tool_providers(tool, enabled):
    """Installer providers one switch change touches, in apply order."""
    if tool == "codex":
        return ("codex",)
    if tool == "claude_code":
        # The status line stays a separate opt-in while Claude Code is on.
        return (
            ("claude_code",) if enabled else ("claude_code", "claude_code_status_line")
        )
    raise KeyError(tool)


class ToolActivation:
    """Preview and apply one tool's switch over the existing installers."""

    def __init__(self, preferences, installers, switches=None):
        """``installers`` maps provider names, or is a lookup that may raise."""
        self.preferences = preferences
        self._lookup = installers if callable(installers) else installers.__getitem__
        self.switches = switches or {
            "codex": preferences.save_usage_enabled,
            "claude_code": preferences.save_claude_code_usage_enabled,
        }

    def installer(self, provider):
        try:
            return self._lookup(provider)
        except KeyError:
            return None

    def preview(self, tool, enabled):
        steps = []
        for provider in tool_providers(tool, bool(enabled)):
            installer = self.installer(provider)
            if installer is None:
                continue
            try:
                plan = (
                    installer.preview_install()
                    if enabled
                    else installer.preview_remove()
                )
            except Exception as error:
                steps.append(ActivationStep(provider, None, type(error).__name__))
                continue
            steps.append(ActivationStep(provider, plan))
        return ActivationPlan(tool, bool(enabled), tuple(steps))

    def apply(self, plan):
        """Change the files that can change, then save the switch either way.

        A file that changed after the review raises StaleHookPlanError before
        the switch is saved, so the user reviews the change again.
        """
        from watched_kettle.integrations.codex_install import StaleHookPlanError

        complete = True
        for step in plan.steps:
            if step.error or step.plan is None or not step.plan.can_apply:
                complete = False
                continue
            if not step.plan.has_changes:
                continue
            try:
                self.installer(step.provider).apply(step.plan)
            except StaleHookPlanError:
                raise
            except Exception:
                complete = False
        self.switches[plan.tool](plan.enabled)
        sync = getattr(self.preferences.settings, "sync", None)
        if sync is not None:
            sync()
        return ActivationResult(plan.tool, plan.enabled, complete)


def migrate_tool_activation(preferences, claude_code_installer, status_line_installer):
    """Once: derive the Claude Code switch from this app's files, keep Codex's.

    Earlier releases saved a Claude Code usage switch that inherited the Codex
    one, so a Codex-only choice could still read Claude Code transcripts.
    Returns the derived Claude Code value, or None when already migrated.
    """
    settings = preferences.settings
    if settings.value(ACTIVATION_MIGRATION_KEY, 0, type=int) >= 1:
        return None
    enabled = False
    for installer in (claude_code_installer, status_line_installer):
        if installer is None:
            continue
        try:
            status = installer.inspect()
        except Exception:
            continue
        # Hooks count even when Claude Code turned every hook off.
        if status.state in MANAGED_STATES or getattr(status, "installed_events", 0):
            enabled = True
    preferences.save_claude_code_usage_enabled(enabled)
    settings.setValue(ACTIVATION_MIGRATION_KEY, 1)
    return enabled
