"""Preview and manage the user-global Claude Code hooks without losing settings.

Claude Code keeps hooks inside ``settings.json`` next to every other user
setting, so only entries carrying the managed marker are added, repaired or
removed. On Windows Claude Code runs command strings under Git Bash, or under
PowerShell when Git Bash is missing, so hooks use the exec form and the status
line a form both shells read alike (docs/support-claude-code.md).
"""

from __future__ import annotations

from watched_kettle.localization import t

from copy import deepcopy
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sys

from watched_kettle.integrations.claude_code_hooks import CLAUDE_CODE_HOOK_EVENTS
from watched_kettle.integrations.claude_code_transcript import claude_config_dir
from watched_kettle.integrations.codex_install import (
    MANAGED_MARKER,
    HookApplyResult,
    HookChangePlan,
    HookInstallError,
    StaleHookPlanError,
    _atomic_write_text,
    _backup,
    _fingerprint,
    _read_utf8,
    _windows_command,
    default_hook_executable,
)


MANAGED_HOOK_EVENTS = tuple(CLAUDE_CODE_HOOK_EVENTS)
TOOL_HOOK_EVENTS = frozenset(
    {"PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest"}
)
HOOK_TIMEOUT_SECONDS = 5
BRIDGE_FLAG = "--claude-code-hook-bridge"
# Enterprise policy files are read only to explain why hooks would not run.
MANAGED_POLICY_PATHS = tuple(
    Path(root) / "ClaudeCode" / "managed-settings.json"
    for root in (
        os.environ.get("ProgramFiles") or r"C:\Program Files",
        os.environ.get("ProgramData") or r"C:\ProgramData",
    )
)
# Unquoted, these characters form one plain word in Git Bash and PowerShell.
_SHELL_NEUTRAL_WORD = re.compile(r"[\w/:.\-]+")


@dataclass(frozen=True)
class ClaudeCodeHookStatus:
    state: str
    settings_path: Path
    installed_events: int
    expected_events: int
    detected: bool
    settings_valid: bool
    message: str


def build_managed_commands(project_root=None, executable=None):
    """Return the exec-form ``command`` and ``args`` for each hook event.

    Claude Code 2.1.139+ spawns an exec-form hook directly, with no shell to
    reinterpret the path, whichever shell it would otherwise use.
    """
    command, prefix = bridge_invocation(project_root, executable)
    return {
        event: {
            "command": command,
            "args": [
                *prefix,
                BRIDGE_FLAG,
                "--event",
                event,
                "--managed-id",
                MANAGED_MARKER,
            ],
        }
        for event in MANAGED_HOOK_EVENTS
    }


def bridge_invocation(project_root=None, executable=None):
    """Return the bridge executable and the arguments that precede its flags."""
    if executable is not None or getattr(sys, "frozen", False):
        executable = (
            Path(executable).resolve()
            if executable is not None
            else default_hook_executable()
        )
        return str(executable), []
    root = Path(project_root or Path(__file__).resolve().parents[2]).resolve()
    python = root / ".venv" / "Scripts" / "python.exe"
    return str(python), [str(root / "main_hook_bridge.py")]


def shell_neutral_command(executable, *arguments):
    """Return a command string Git Bash and PowerShell both run unchanged.

    An unquoted path of plain characters is an invocation in either shell.
    Other paths need quoting that the shells disagree on, so they fall back to
    an explicit PowerShell call that hides them from the outer shell.
    """
    words = [str(value).replace("\\", "/") for value in (executable, *arguments)]
    if all(_SHELL_NEUTRAL_WORD.fullmatch(word) for word in words):
        return " ".join(words)
    return _windows_command(executable, *arguments)


class ClaudeCodeHookInstaller:
    """Idempotent lifecycle for the Watched Kettle Claude Code hooks."""

    def __init__(
        self,
        settings_path=None,
        commands=None,
        policy_paths=MANAGED_POLICY_PATHS,
        command_error="",
    ):
        self.settings_path = Path(
            settings_path or claude_config_dir() / "settings.json"
        )
        self.policy_paths = tuple(Path(path) for path in policy_paths)
        self.command_error = command_error
        if commands is None:
            try:
                commands = build_managed_commands()
            except ValueError as error:
                commands = {}
                self.command_error = str(error)
        self.commands = dict(commands)

    def inspect(self):
        detected = self.settings_path.parent.is_dir()
        expected = len(MANAGED_HOOK_EVENTS)
        payload, error = self._read_settings()
        if error:
            return self._status("invalid", 0, detected, False, error)
        installed, markers, exact = self._managed_counts(payload)
        if payload.get("disableAllHooks") is True:
            state, message = (
                "disabled",
                t("message.0062"),
            )
        elif self._policy_blocks_user_hooks():
            state = "blocked_by_policy"
            message = t("message.0063")
        elif installed == expected and markers == exact == expected:
            state, message = "installed", t("message.0074")
        elif markers:
            state = "partial" if installed else "drifted"
            message = t("message.0075")
        else:
            state, message = (
                "not_installed",
                t("message.0076"),
            )
        return self._status(state, installed, detected, True, message)

    def preview_install(self):
        status = self.inspect()
        if not status.settings_valid:
            return self._blocked_plan("install", status, status.message)
        if self.command_error or not self.commands:
            return self._blocked_plan(
                "install", status, self.command_error or t("message.0071")
            )
        payload, _ = self._read_settings()
        merged = self._merge_managed_hooks(payload)
        changes = []
        warnings = []
        settings_text = None
        if merged != payload:
            settings_text = _dump_settings(merged)
            changes.append(t("message.0064", value0=len(MANAGED_HOOK_EVENTS)))
        else:
            changes.append(t("message.0065"))
        if status.state in {"partial", "drifted"}:
            warnings.append(t("message.0066"))
        if status.state in {"disabled", "blocked_by_policy"}:
            warnings.append(status.message + t("message.0072"))
        warnings.append(t("message.0060"))
        warnings.append(t("message.0061"))
        return self._plan("install", status, changes, warnings, settings_text)

    def preview_repair(self):
        plan = self.preview_install()
        return HookChangePlan(
            operation="repair",
            status_before=plan.status_before,
            changes=plan.changes,
            warnings=plan.warnings,
            can_apply=plan.can_apply,
            hooks_text=plan.hooks_text,
            config_text=None,
            hooks_fingerprint=plan.hooks_fingerprint,
            config_fingerprint=None,
        )

    def preview_remove(self):
        status = self.inspect()
        if not status.settings_valid:
            text, _ = _read_utf8(self.settings_path)
            if text is not None and MANAGED_MARKER in text:
                return self._blocked_plan("remove", status, status.message)
            # A broken file without our marker has nothing of ours to remove.
            return self._plan(
                "remove",
                status,
                [t("message.0068")],
                [],
                None,
            )
        payload, _ = self._read_settings()
        cleaned = self._remove_managed_hooks(payload)
        settings_text = _dump_settings(cleaned) if cleaned != payload else None
        changes = (
            [t("message.0067")] if settings_text is not None else [t("message.0068")]
        )
        return self._plan(
            "remove",
            status,
            changes,
            [t("message.0060")],
            settings_text,
        )

    def apply(self, plan: HookChangePlan):
        if not plan.can_apply:
            raise HookInstallError(t("message.0069"))
        if _fingerprint(self.settings_path) != plan.hooks_fingerprint:
            raise StaleHookPlanError(t("message.0070"))
        changed_paths = []
        backup_paths = []
        if plan.hooks_text is not None:
            backup = _backup(self.settings_path)
            if backup is not None:
                backup_paths.append(backup)
            _atomic_write_text(self.settings_path, plan.hooks_text)
            changed_paths.append(self.settings_path)
        return HookApplyResult(
            operation=plan.operation,
            changed_paths=tuple(changed_paths),
            backup_paths=tuple(backup_paths),
            status=self.inspect(),
        )

    def _read_settings(self):
        text, error = _read_utf8(self.settings_path)
        if error:
            return None, error
        if text is None or not text.strip():
            return {}, ""
        try:
            payload = json.loads(text)
            _validate_settings(payload)
        except (json.JSONDecodeError, ValueError) as error:
            return None, t("message.0073", value0=error)
        return payload, ""

    def _merge_managed_hooks(self, payload):
        merged = self._remove_managed_hooks(payload)
        hooks = merged.setdefault("hooks", {})
        for event in MANAGED_HOOK_EVENTS:
            group = {"hooks": [self._managed_hook(event)]}
            if event in TOOL_HOOK_EVENTS:
                group = {"matcher": "*", **group}
            hooks.setdefault(event, []).append(group)
        return merged

    @staticmethod
    def _remove_managed_hooks(payload):
        cleaned = deepcopy(payload)
        hooks = cleaned.get("hooks")
        if not isinstance(hooks, dict):
            return cleaned
        for event in tuple(hooks):
            groups = []
            for group in hooks[event]:
                remaining = [
                    hook for hook in group["hooks"] if not _is_managed_hook(hook)
                ]
                if len(remaining) == len(group["hooks"]):
                    groups.append(group)
                elif remaining:
                    groups.append({**group, "hooks": remaining})
            if groups:
                hooks[event] = groups
            else:
                hooks.pop(event)
        if not hooks:
            cleaned.pop("hooks")
        return cleaned

    def _managed_hook(self, event):
        return {
            "type": "command",
            **self.commands[event],
            "timeout": HOOK_TIMEOUT_SECONDS,
        }

    def _managed_counts(self, payload):
        installed = markers = exact = 0
        for event, groups in (payload.get("hooks") or {}).items():
            for group in groups:
                for hook in group["hooks"]:
                    if not _is_managed_hook(hook):
                        continue
                    markers += 1
                    if event in self.commands and hook == self._managed_hook(event):
                        exact += 1
                        installed += 1
        return installed, markers, exact

    def _policy_blocks_user_hooks(self):
        for path in self.policy_paths:
            text, error = _read_utf8(path)
            if error or not text:
                continue
            try:
                policy = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(policy, dict) and policy.get("allowManagedHooksOnly") is True:
                return True
        return False

    def _status(self, state, installed, detected, valid, message):
        return ClaudeCodeHookStatus(
            state=state,
            settings_path=self.settings_path,
            installed_events=installed,
            expected_events=len(MANAGED_HOOK_EVENTS),
            detected=detected,
            settings_valid=valid,
            message=message,
        )

    def _plan(self, operation, status, changes, warnings, settings_text):
        return HookChangePlan(
            operation=operation,
            status_before=status,
            changes=tuple(changes),
            warnings=tuple(warnings),
            can_apply=True,
            hooks_text=settings_text,
            config_text=None,
            hooks_fingerprint=_fingerprint(self.settings_path),
            config_fingerprint=None,
        )

    def _blocked_plan(self, operation, status, warning):
        return HookChangePlan(
            operation=operation,
            status_before=status,
            changes=(),
            warnings=(warning,),
            can_apply=False,
            hooks_text=None,
            config_text=None,
            hooks_fingerprint=_fingerprint(self.settings_path),
            config_fingerprint=None,
        )


def _validate_settings(payload):
    if not isinstance(payload, dict):
        raise ValueError("root must be an object")
    if "hooks" not in payload:
        return
    hooks = payload["hooks"]
    if not isinstance(hooks, dict):
        raise ValueError("hooks must be an object")
    for event, groups in hooks.items():
        if not isinstance(event, str) or not isinstance(groups, list):
            raise ValueError("hook event groups must be arrays")
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                raise ValueError("hook group must contain a hooks array")
            if not all(isinstance(hook, dict) for hook in group["hooks"]):
                raise ValueError("hook entries must be objects")


def _is_managed_hook(hook):
    """Exec-form entries carry the marker in ``args``; earlier ones in ``command``."""
    if not isinstance(hook, dict):
        return False
    args = hook.get("args")
    values = [hook.get("command"), *(args if isinstance(args, list) else ())]
    return any(isinstance(value, str) and MANAGED_MARKER in value for value in values)


def _dump_settings(payload):
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
