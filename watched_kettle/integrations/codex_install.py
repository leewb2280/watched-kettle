"""Preview and manage the user-global Codex hook without losing other hooks."""

from __future__ import annotations

from watched_kettle.localization import t

import base64
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path

from watched_kettle.integrations.codex_paths import codex_home
import re
import shlex
import sys
import tomllib
from uuid import uuid4


MANAGED_MARKER = "watched-kettle-managed-v1"
# Hooks installed by Private Beta builds; still ours to repair or remove.
LEGACY_MANAGED_MARKERS = ("codex-desktop-pets-managed-v1",)
MANAGED_DESCRIPTION = "Privacy-filtered lifecycle events for Watched Kettle."
MANAGED_HOOK_EVENTS = (
    "SessionStart",
    "SessionEnd",
    "SubagentStart",
    "SubagentStop",
    "UserPromptSubmit",
    "PreToolUse",
    "PermissionRequest",
    "PostToolUse",
    "PreCompact",
    "PostCompact",
    "Stop",
)
HOOK_BRIDGE_EXECUTABLE = "WatchedKettleHookBridge.exe"
DEFAULT_GLOBAL_HOOKS_PATH = codex_home() / "hooks.json"
DEFAULT_CODEX_CONFIG_PATH = codex_home() / "config.toml"


class HookInstallError(RuntimeError):
    pass


class StaleHookPlanError(HookInstallError):
    pass


@dataclass(frozen=True)
class HookFeatureStatus:
    valid: bool
    enabled: bool
    explicit: bool = False
    deprecated_alias: bool = False
    needs_enable: bool = False
    error: str = ""


@dataclass(frozen=True)
class HookInstallStatus:
    state: str
    hooks_path: Path
    config_path: Path
    installed_events: int
    expected_events: int
    feature: HookFeatureStatus
    hooks_exists: bool
    hooks_valid: bool
    message: str


@dataclass(frozen=True)
class HookChangePlan:
    operation: str
    status_before: HookInstallStatus
    changes: tuple[str, ...]
    warnings: tuple[str, ...]
    can_apply: bool
    hooks_text: str | None
    config_text: str | None
    hooks_fingerprint: str | None
    config_fingerprint: str | None

    @property
    def has_changes(self):
        return self.hooks_text is not None or self.config_text is not None


@dataclass(frozen=True)
class HookApplyResult:
    operation: str
    changed_paths: tuple[Path, ...]
    backup_paths: tuple[Path, ...]
    status: HookInstallStatus


def default_hook_executable(main_executable=None):
    """Prefer the Qt-free bridge next to the app; older bundles lack it."""
    main_executable = Path(main_executable or sys.executable).resolve()
    bridge = main_executable.with_name(HOOK_BRIDGE_EXECUTABLE)
    return bridge if bridge.is_file() else main_executable


def build_managed_hook(project_root=None, executable=None):
    """Build a schema-compatible command whose marker is safe to identify."""
    if executable is not None or getattr(sys, "frozen", False):
        executable = (
            Path(executable).resolve()
            if executable is not None
            else default_hook_executable()
        )
        command_windows = _windows_command(
            executable, "--codex-hook-bridge", "--managed-id", MANAGED_MARKER
        )
        command = (
            f"{shlex.quote(str(executable))} --codex-hook-bridge "
            f"--managed-id {shlex.quote(MANAGED_MARKER)}"
        )
    else:
        project_root = Path(
            project_root or Path(__file__).resolve().parents[2]
        ).resolve()
        wrapper = project_root / ".codex" / "hooks" / "codex_pet_bridge.ps1"
        python = project_root / ".venv" / "bin" / "python"
        bridge = project_root / ".codex" / "hooks" / "codex_pet_bridge.py"
        # The wrapper's first parameter is ManagedId. Quoted '-ManagedId' would
        # bind as a positional value, rather than a PowerShell parameter name.
        command_windows = _windows_command(wrapper, MANAGED_MARKER)
        command = (
            f"{shlex.quote(str(python))} {shlex.quote(str(bridge))} "
            f"--managed-id {shlex.quote(MANAGED_MARKER)}"
        )

    return {
        "type": "command",
        "command": command,
        "commandWindows": command_windows,
        "timeout": 3,
    }


class CodexHookInstaller:
    """Idempotent lifecycle for the Watched Kettle managed hook."""

    def __init__(
        self,
        hooks_path=DEFAULT_GLOBAL_HOOKS_PATH,
        config_path=DEFAULT_CODEX_CONFIG_PATH,
        managed_hook=None,
    ):
        self.hooks_path = Path(hooks_path)
        self.config_path = Path(config_path)
        self.managed_hook = deepcopy(managed_hook or build_managed_hook())

    def inspect(self):
        hooks_exists = self.hooks_path.is_file()
        hooks_payload, hooks_error = self._read_hooks()
        config_text, config_error = _read_utf8(self.config_path)
        feature = (
            _inspect_feature(config_text or "")
            if not config_error
            else HookFeatureStatus(
                valid=False,
                enabled=False,
                error=config_error,
            )
        )

        if hooks_error:
            return HookInstallStatus(
                state="invalid",
                hooks_path=self.hooks_path,
                config_path=self.config_path,
                installed_events=0,
                expected_events=len(MANAGED_HOOK_EVENTS),
                feature=feature,
                hooks_exists=hooks_exists,
                hooks_valid=False,
                message=hooks_error,
            )

        installed, markers, exact = self._managed_counts(hooks_payload)
        expected = len(MANAGED_HOOK_EVENTS)
        if not feature.valid:
            state = "invalid"
            message = feature.error or t("message.0113")
        elif feature.explicit and not feature.enabled:
            state = "disabled"
            message = t("message.0114")
        elif installed == expected and markers == exact == expected:
            state = "installed"
            message = t("message.0074")
        elif markers:
            state = "partial" if installed else "drifted"
            message = t("message.0075")
        else:
            state = "not_installed"
            message = t("message.0076")

        return HookInstallStatus(
            state=state,
            hooks_path=self.hooks_path,
            config_path=self.config_path,
            installed_events=installed,
            expected_events=expected,
            feature=feature,
            hooks_exists=hooks_exists,
            hooks_valid=True,
            message=message,
        )

    def preview_install(self):
        status = self.inspect()
        warnings = []
        if not status.hooks_valid or not status.feature.valid:
            return self._blocked_plan("install", status, status.message)
        if status.feature.explicit and not status.feature.enabled:
            return self._blocked_plan(
                "install",
                status,
                t("message.0115"),
            )

        hooks_payload, _ = self._read_hooks()
        merged = self._merge_managed_hook(hooks_payload)
        hooks_text = None
        changes = []
        if merged != hooks_payload:
            hooks_text = _dump_hooks(merged)
            changes.append(t("message.0064", value0=len(MANAGED_HOOK_EVENTS)))

        config_text, _ = _read_utf8(self.config_path)
        config_text = config_text or ""
        next_config = None
        if status.feature.needs_enable:
            try:
                next_config = _enable_hooks_text(config_text)
            except ValueError as error:
                return self._blocked_plan("install", status, str(error))
            changes.append(t("message.0116"))

        if status.state in {"partial", "drifted"}:
            warnings.append(t("message.0066"))
        if not changes:
            changes.append(t("message.0065"))

        return HookChangePlan(
            operation="install",
            status_before=status,
            changes=tuple(changes),
            warnings=tuple(warnings),
            can_apply=True,
            hooks_text=hooks_text,
            config_text=next_config,
            hooks_fingerprint=_fingerprint(self.hooks_path),
            config_fingerprint=_fingerprint(self.config_path),
        )

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
        if not status.hooks_valid:
            return self._blocked_plan("remove", status, status.message)
        hooks_payload, _ = self._read_hooks()
        cleaned = self._remove_managed_hooks(hooks_payload)
        hooks_text = _dump_hooks(cleaned) if cleaned != hooks_payload else None
        changes = (
            (t("message.0067"),) if hooks_text is not None else (t("message.0068"),)
        )
        return HookChangePlan(
            operation="remove",
            status_before=status,
            changes=changes,
            warnings=(t("message.0124"),),
            can_apply=True,
            hooks_text=hooks_text,
            config_text=None,
            hooks_fingerprint=_fingerprint(self.hooks_path),
            config_fingerprint=_fingerprint(self.config_path),
        )

    def preview_legacy_migration(self):
        """Point Private Beta hooks at this build without touching config.toml."""
        status = self.inspect()
        if not status.hooks_valid:
            return self._blocked_plan("migrate", status, status.message)
        hooks_payload, _ = self._read_hooks()
        if not _has_legacy_hook(hooks_payload):
            return HookChangePlan(
                operation="migrate",
                status_before=status,
                changes=(t("message.0128"),),
                warnings=(),
                can_apply=True,
                hooks_text=None,
                config_text=None,
                hooks_fingerprint=_fingerprint(self.hooks_path),
                config_fingerprint=_fingerprint(self.config_path),
            )
        return HookChangePlan(
            operation="migrate",
            status_before=status,
            changes=(t("message.0125"),),
            warnings=(t("message.0124"),),
            can_apply=True,
            hooks_text=_dump_hooks(self._merge_managed_hook(hooks_payload)),
            config_text=None,
            hooks_fingerprint=_fingerprint(self.hooks_path),
            config_fingerprint=_fingerprint(self.config_path),
        )

    def apply(self, plan: HookChangePlan):
        if not plan.can_apply:
            raise HookInstallError(t("message.0069"))
        if _fingerprint(self.hooks_path) != plan.hooks_fingerprint:
            raise StaleHookPlanError(t("message.0117"))
        if _fingerprint(self.config_path) != plan.config_fingerprint:
            raise StaleHookPlanError(t("message.0118"))

        writes = []
        if plan.config_text is not None:
            writes.append((self.config_path, plan.config_text))
        if plan.hooks_text is not None:
            writes.append((self.hooks_path, plan.hooks_text))

        backup_paths = []
        for path, _ in writes:
            backup = _backup(path)
            if backup is not None:
                backup_paths.append(backup)

        changed_paths = []
        for path, text in writes:
            _atomic_write_text(path, text)
            changed_paths.append(path)

        return HookApplyResult(
            operation=plan.operation,
            changed_paths=tuple(changed_paths),
            backup_paths=tuple(backup_paths),
            status=self.inspect(),
        )

    def _read_hooks(self):
        text, read_error = _read_utf8(self.hooks_path)
        if read_error:
            return None, read_error
        if text is None:
            return {"description": MANAGED_DESCRIPTION, "hooks": {}}, ""
        try:
            payload = json.loads(text)
            _validate_hooks_payload(payload)
        except (json.JSONDecodeError, ValueError) as error:
            return None, t("message.0126", value0=error)
        return payload, ""

    def _merge_managed_hook(self, payload):
        merged = self._remove_managed_hooks(payload)
        hooks = merged.setdefault("hooks", {})
        for event in MANAGED_HOOK_EVENTS:
            hooks.setdefault(event, []).append({"hooks": [deepcopy(self.managed_hook)]})
        return merged

    @staticmethod
    def _remove_managed_hooks(payload):
        cleaned = deepcopy(payload)
        hooks = cleaned.get("hooks", {})
        for event in tuple(hooks):
            groups = []
            for group in hooks[event]:
                remaining = [
                    hook for hook in group["hooks"] if not _is_managed_hook(hook)
                ]
                if remaining:
                    next_group = deepcopy(group)
                    next_group["hooks"] = remaining
                    groups.append(next_group)
            if groups:
                hooks[event] = groups
            else:
                hooks.pop(event, None)
        return cleaned

    def _managed_counts(self, payload):
        installed = 0
        markers = 0
        exact = 0
        hooks = payload.get("hooks", {})
        for event, groups in hooks.items():
            for group in groups:
                for hook in group["hooks"]:
                    if not _is_managed_hook(hook):
                        continue
                    markers += 1
                    if hook == self.managed_hook:
                        exact += 1
                        if event in MANAGED_HOOK_EVENTS:
                            installed += 1
        return installed, markers, exact

    def _blocked_plan(self, operation, status, warning):
        return HookChangePlan(
            operation=operation,
            status_before=status,
            changes=(),
            warnings=(warning,),
            can_apply=False,
            hooks_text=None,
            config_text=None,
            hooks_fingerprint=_fingerprint(self.hooks_path),
            config_fingerprint=_fingerprint(self.config_path),
        )


def _validate_hooks_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError("root must be an object")
    hooks = payload.get("hooks")
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


def _hook_commands(hook):
    if not isinstance(hook, dict):
        return ()
    return tuple(
        value
        for value in (hook.get("command"), hook.get("commandWindows"))
        if isinstance(value, str)
    )


def _is_managed_hook(hook):
    return any(
        marker in value
        for value in _hook_commands(hook)
        for marker in (MANAGED_MARKER, *LEGACY_MANAGED_MARKERS)
    )


def _has_legacy_hook(payload):
    return any(
        marker in value
        for groups in payload.get("hooks", {}).values()
        for group in groups
        for hook in group["hooks"]
        for value in _hook_commands(hook)
        for marker in LEGACY_MANAGED_MARKERS
    )


def _inspect_feature(text):
    if not text.strip():
        return HookFeatureStatus(
            valid=True,
            enabled=True,
            needs_enable=True,
        )
    try:
        payload = tomllib.loads(text)
        features = payload.get("features", {})
        if not isinstance(features, dict):
            raise ValueError("[features] must be a table")
        if "hooks" in features:
            value = features["hooks"]
            if not isinstance(value, bool):
                raise ValueError("features.hooks must be boolean")
            return HookFeatureStatus(
                valid=True,
                enabled=value,
                explicit=True,
            )
        if "codex_hooks" in features:
            value = features["codex_hooks"]
            if not isinstance(value, bool):
                raise ValueError("features.codex_hooks must be boolean")
            return HookFeatureStatus(
                valid=True,
                enabled=value,
                explicit=True,
                deprecated_alias=True,
                needs_enable=False,
            )
    except (tomllib.TOMLDecodeError, ValueError) as error:
        return HookFeatureStatus(
            valid=False,
            enabled=False,
            error=t("message.0127", value0=error),
        )
    return HookFeatureStatus(
        valid=True,
        enabled=True,
        needs_enable=True,
    )


def _enable_hooks_text(text):
    newline = "\r\n" if "\r\n" in text else "\n"
    if not text.strip():
        candidate = f"[features]{newline}hooks = true{newline}"
    else:
        header = re.search(
            r"(?m)^[ \t]*\[features\][ \t]*(?:#.*)?(?:\r?\n|$)",
            text,
        )
        if header:
            insertion = f"hooks = true{newline}"
            candidate = text[: header.end()] + insertion + text[header.end() :]
        else:
            separator = "" if text.endswith(("\n", "\r")) else newline
            candidate = (
                f"{text}{separator}{newline}[features]{newline}hooks = true{newline}"
            )
    try:
        parsed = tomllib.loads(candidate)
    except tomllib.TOMLDecodeError as error:
        raise ValueError(t("message.0119", value0=error)) from error
    if parsed.get("features", {}).get("hooks") is not True:
        raise ValueError(t("message.0110"))
    return candidate


def _read_utf8(path):
    path = Path(path)
    if not path.exists():
        return None, ""
    if not path.is_file():
        return None, t("message.0111", value0=path)
    try:
        return path.read_text(encoding="utf-8"), ""
    except (OSError, UnicodeDecodeError) as error:
        return None, t("message.0120", value0=error)


def _dump_hooks(payload):
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _fingerprint(path):
    path = Path(path)
    if not path.exists():
        return None
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise HookInstallError(t("message.0121", value0=error)) from error


def _backup(path):
    path = Path(path)
    if not path.is_file():
        return None
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = path.with_name(f"{path.name}.backup-{timestamp}")
    try:
        backup.write_bytes(path.read_bytes())
    except OSError as error:
        raise HookInstallError(t("message.0122", value0=error)) from error
    return backup


def _atomic_write_text(path, text):
    path = Path(path)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with temporary.open("x", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError as error:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise HookInstallError(t("message.0123", value0=error)) from error


def _windows_command(executable, *arguments):
    """Keep the invocation opaque to the caller's PowerShell or cmd parser.

    A quoted executable alone is a string expression in PowerShell. Encode the
    entire call so the outer shell also cannot expand path characters such as
    ``$`` or ``%``. The POSIX command retains the visible management marker.
    """
    if '"' in str(executable):
        raise ValueError(t("message.0112"))
    literals = (
        "'" + str(value).replace("'", "''") + "'" for value in (executable, *arguments)
    )
    script = "$ErrorActionPreference = 'Stop'; & " + " ".join(literals)
    script += "; exit $LASTEXITCODE"
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return (
        "powershell.exe -NoLogo -NoProfile -NonInteractive "
        "-ExecutionPolicy Bypass -EncodedCommand " + encoded
    )
