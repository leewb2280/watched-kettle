"""Install, repair and remove the Claude Code status line bridge (stage 13).

Claude Code has a single ``statusLine`` setting. Installing replaces it with
the bridge and keeps the user's previous status line in a sidecar file; the
bridge runs that command so the user's line stays unchanged. Removing puts the
previous setting back. A status line the user changed afterwards is never
overwritten. Only CLI and terminal-mode sessions run status lines; the VS Code
graphical panel does not (measured 2026-10-03).
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys

from watched_kettle.integrations.claude_code_install import (
    ClaudeCodeHookInstaller,
    _bash_quote,
    _dump_settings,
)
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
    default_hook_executable,
)
from watched_kettle.integrations.codex_spool import DEFAULT_USER_RUNTIME_ROOT


STATUS_LINE_FLAG = "--claude-code-status-line"
DEFAULT_SIDECAR_PATH = DEFAULT_USER_RUNTIME_ROOT / "claude-code-status-line.json"


@dataclass(frozen=True)
class ClaudeCodeStatusLineStatus:
    state: str
    settings_path: Path
    installed_events: int
    expected_events: int
    detected: bool
    settings_valid: bool
    message: str
    has_original: bool = False


def build_status_line_command(project_root=None, executable=None):
    if executable is not None or getattr(sys, "frozen", False):
        executable = (
            Path(executable).resolve()
            if executable is not None
            else default_hook_executable()
        )
        prefix = _bash_quote(executable)
    else:
        root = Path(project_root or Path(__file__).resolve().parents[2]).resolve()
        python = root / ".venv" / "Scripts" / "python.exe"
        prefix = f"{_bash_quote(python)} {_bash_quote(root / 'main_hook_bridge.py')}"
    return f"{prefix} {STATUS_LINE_FLAG} --managed-id {MANAGED_MARKER}"


def is_managed_status_line(value):
    command = value.get("command") if isinstance(value, dict) else None
    return isinstance(command, str) and STATUS_LINE_FLAG in command


class ClaudeCodeStatusLineInstaller:
    def __init__(self, settings_path=None, sidecar_path=None, command=None):
        self.settings_path = Path(
            settings_path or claude_config_dir() / "settings.json"
        )
        self.sidecar_path = Path(
            sidecar_path
            or os.environ.get("WATCHED_KETTLE_STATUS_LINE_CONFIG")
            or DEFAULT_SIDECAR_PATH
        )
        self.command_error = ""
        if command is None:
            try:
                command = build_status_line_command()
            except ValueError as error:
                command = ""
                self.command_error = str(error)
        self.command = command
        # Reuse the hook installer's tolerant settings reader and policy check.
        self._hooks = ClaudeCodeHookInstaller(self.settings_path, commands={})

    def inspect(self):
        detected = self.settings_path.parent.is_dir()
        payload, error = self._hooks._read_settings()
        if error:
            return self._status("invalid", detected, False, error)
        current = payload.get("statusLine")
        original = self._original() is not None
        if payload.get("disableAllHooks") is True:
            return self._status(
                "disabled",
                detected,
                True,
                "Claude Code 설정에서 hook과 status line이 모두 꺼져 있습니다.",
                original,
            )
        if self._hooks._policy_blocks_user_hooks():
            return self._status(
                "blocked_by_policy",
                detected,
                True,
                "관리자 정책이 사용자 status line 실행을 허용하지 않습니다.",
                original,
            )
        if is_managed_status_line(current):
            if current.get("command") == self.command:
                return self._status(
                    "installed",
                    detected,
                    True,
                    "Claude Code 한도를 받는 status line이 연결되어 있습니다.",
                    original,
                )
            return self._status(
                "drifted",
                detected,
                True,
                "status line 실행 경로가 바뀌었습니다. 복구하면 다시 맞춥니다.",
                original,
            )
        return self._status(
            "not_installed",
            detected,
            True,
            "사용자 status line이 있습니다. 연결하면 그대로 보여 주면서 한도를 받습니다."
            if current
            else "Claude Code 한도를 받는 status line이 연결되어 있지 않습니다.",
            original,
        )

    def preview_install(self):
        status = self.inspect()
        if not status.settings_valid:
            return self._blocked("install", status, status.message)
        if self.command_error or not self.command:
            return self._blocked(
                "install", status, self.command_error or "명령을 만들 수 없습니다."
            )
        payload, _ = self._hooks._read_settings()
        current = payload.get("statusLine")
        sidecar = None
        warnings = []
        if current and not is_managed_status_line(current):
            sidecar = json.dumps({"original": current}, ensure_ascii=False, indent=2)
            changes = ["기존 status line을 보관하고 그대로 보여 주도록 감쌈"]
        else:
            changes = ["Claude Code 하단 status line으로 한도 받기"]
            if not current:
                warnings.append(
                    "원래 status line이 없어 CLI 하단에 짧은 한도 문구가 생깁니다."
                )
        base = {
            key: value
            for key, value in (current or {}).items()
            if key in {"padding", "refreshInterval", "hideVimModeIndicator"}
        }
        if is_managed_status_line(current):
            base = {k: v for k, v in current.items() if k not in {"type", "command"}}
        merged = deepcopy(payload)
        merged["statusLine"] = {"type": "command", "command": self.command, **base}
        settings_text = _dump_settings(merged) if merged != payload else None
        if settings_text is None and sidecar is None:
            changes = ["변경 없음 · 이미 최신 상태"]
        if status.state in {"disabled", "blocked_by_policy"}:
            warnings.append(status.message + " 연결해도 실행되지 않습니다.")
        warnings.append(
            "CLI와 VS Code 터미널 모드에서만 갱신됩니다. VS Code 그래픽 패널은 status line을 실행하지 않습니다."
        )
        warnings.append("다른 Claude Code 설정은 보존합니다.")
        return self._plan("install", status, changes, warnings, settings_text, sidecar)

    def preview_repair(self):
        plan = self.preview_install()
        return HookChangePlan(
            operation="repair",
            status_before=plan.status_before,
            changes=plan.changes,
            warnings=plan.warnings,
            can_apply=plan.can_apply,
            hooks_text=plan.hooks_text,
            config_text=plan.config_text,
            hooks_fingerprint=plan.hooks_fingerprint,
            config_fingerprint=plan.config_fingerprint,
        )

    def preview_remove(self):
        status = self.inspect()
        if not status.settings_valid:
            return self._blocked("remove", status, status.message)
        payload, _ = self._hooks._read_settings()
        current = payload.get("statusLine")
        original = self._original()
        warnings = ["다른 Claude Code 설정은 보존합니다."]
        settings_text = None
        if is_managed_status_line(current):
            restored = deepcopy(payload)
            if original is not None:
                restored["statusLine"] = original
                changes = ["보관한 원래 status line으로 되돌림"]
            else:
                restored.pop("statusLine")
                changes = ["이 앱의 status line 제거"]
            settings_text = _dump_settings(restored)
        else:
            changes = ["변경 없음 · 이 앱의 status line이 연결되어 있지 않음"]
            if original is not None and current:
                warnings.append(
                    "status line이 이후에 바뀌어 덮어쓰지 않습니다. 보관한 원래 설정만 정리합니다."
                )
        sidecar = "" if self.sidecar_path.exists() else None
        return self._plan("remove", status, changes, warnings, settings_text, sidecar)

    def apply(self, plan: HookChangePlan):
        if not plan.can_apply:
            raise HookInstallError("적용할 수 없는 status line 변경 계획입니다.")
        if (
            _fingerprint(self.settings_path) != plan.hooks_fingerprint
            or _fingerprint(self.sidecar_path) != plan.config_fingerprint
        ):
            raise StaleHookPlanError(
                "Claude Code settings.json이 미리보기 후 변경되어 다시 확인해야 합니다."
            )
        changed, backups = [], []
        # The original line is saved before settings.json stops pointing at it.
        if plan.config_text:
            self.sidecar_path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write_text(self.sidecar_path, plan.config_text + "\n")
            changed.append(self.sidecar_path)
        if plan.hooks_text is not None:
            backup = _backup(self.settings_path)
            if backup is not None:
                backups.append(backup)
            _atomic_write_text(self.settings_path, plan.hooks_text)
            changed.append(self.settings_path)
        if plan.config_text == "" and self.sidecar_path.exists():
            self.sidecar_path.unlink()
            changed.append(self.sidecar_path)
        return HookApplyResult(
            operation=plan.operation,
            changed_paths=tuple(changed),
            backup_paths=tuple(backups),
            status=self.inspect(),
        )

    def _original(self):
        text, error = _read_utf8(self.sidecar_path)
        if error or not text:
            return None
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            return None
        original = value.get("original") if isinstance(value, dict) else None
        return original if isinstance(original, dict) else None

    def _status(self, state, detected, valid, message, has_original=False):
        return ClaudeCodeStatusLineStatus(
            state=state,
            settings_path=self.settings_path,
            installed_events=1 if state == "installed" else 0,
            expected_events=1,
            detected=detected,
            settings_valid=valid,
            message=message,
            has_original=has_original,
        )

    def _plan(self, operation, status, changes, warnings, settings_text, sidecar):
        return HookChangePlan(
            operation=operation,
            status_before=status,
            changes=tuple(changes),
            warnings=tuple(warnings),
            can_apply=True,
            hooks_text=settings_text,
            config_text=sidecar,
            hooks_fingerprint=_fingerprint(self.settings_path),
            config_fingerprint=_fingerprint(self.sidecar_path),
        )

    def _blocked(self, operation, status, warning):
        return HookChangePlan(
            operation=operation,
            status_before=status,
            changes=(),
            warnings=(warning,),
            can_apply=False,
            hooks_text=None,
            config_text=None,
            hooks_fingerprint=_fingerprint(self.settings_path),
            config_fingerprint=_fingerprint(self.sidecar_path),
        )
