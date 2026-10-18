"""Ephemeral, bounded navigation targets shared by bubbles and lists."""

from watched_kettle.localization import t

from dataclasses import dataclass
from collections import OrderedDict
import re
import os
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices

from watched_kettle.activity_diagnostics import (
    DiagnosticRecorder,
    diagnostic_guard,
    diagnostic_ref,
    diagnostic_thread_ref,
)

from watched_kettle.features.project_activity.service import (
    CLAUDE_CODE_THREAD_PREFIX,
    thread_source,
)
from watched_kettle.integrations.claude_code_launcher import (
    ClaudeCodeLauncher,
    open_url,
)


@dataclass(frozen=True)
class ActionTarget:
    kind: str
    identifier: str = ""


class NotificationActionRouter(QObject):
    failed = Signal(str)

    def __init__(self, parent=None, opener=None):
        super().__init__(parent)
        self.opener = opener or QDesktopServices.openUrl
        self.targets: dict[str, ActionTarget] = {}
        self.activity_diagnostics = DiagnosticRecorder()
        self.diagnostic_context = None
        self._diagnostic_targets: OrderedDict[str, dict] = OrderedDict()
        self._diagnostic_serial = 0
        self.internal_open = None
        self.app_available = installed_codex_app()
        # thread ID -> where the Claude Code session runs; set by the runtime.
        self.claude_code_client = None
        # An injected opener (tests) handles every link; otherwise VS Code
        # links use the launcher's own opener, which keeps a source run's
        # terminal clean.
        self.claude_code_launcher = ClaudeCodeLauncher(
            (lambda url: self.opener(url))
            if opener is not None
            else (lambda url: open_url(url, QDesktopServices.openUrl))
        )

    def register(self, kind, identifier=""):
        target = ActionTarget(kind, identifier)
        for token, existing in self.targets.items():
            if existing == target:
                return token
        token = uuid4().hex
        self.targets[token] = target
        self._remember_diagnostic_target(token, target)
        return token

    @diagnostic_guard
    def _remember_diagnostic_target(self, token, target):
        if self.activity_diagnostics.callback is None:
            return
        source = thread_source(target.identifier) if target.kind == "thread" else ""
        self._diagnostic_targets[diagnostic_ref(token)] = dict(
            source=source,
            target_kind=target.kind,
            thread_ref=diagnostic_thread_ref(source, target.identifier)
            if target.kind == "thread"
            else "",
        )
        while len(self._diagnostic_targets) > 512:
            self._diagnostic_targets.popitem(last=False)

    def retain(self, tokens):
        self.targets = {k: v for k, v in self.targets.items() if k in tokens}

    def reset(self):
        self.targets.clear()

    def label(self, kind, identifier=""):
        if kind == "thread" and thread_source(identifier) != "codex":
            return self.claude_code_launcher.label(self._client(identifier))
        if kind == "thread":
            return t("message.0077") if self.app_available else t("message.0454")
        return {
            "usage": t("message.0200"),
            "notice": t("message.0201"),
            "projects": t("message.0079"),
        }.get(kind, t("message.0201"))

    def open(self, token):
        self._diagnostic_serial += 1
        fields = self._navigation_fields(token) or {
            "request_id": self._diagnostic_serial
        }
        self.activity_diagnostics.emit("navigation_requested", **fields)
        outcome = {"reason": "unknown", "result": "failed"}
        opened = self._open_observed(token, outcome)
        self.activity_diagnostics.emit("navigation_result", **fields, **outcome)
        if (
            outcome["result"] != "dispatch_accepted"
            and outcome["result"] != "internal_accepted"
        ):
            self._diagnose_navigation_context(fields)
        return opened

    @diagnostic_guard
    def _navigation_fields(self, token):
        target = self.targets.get(token)
        if target is not None:
            self._remember_diagnostic_target(token, target)
        remembered = self._diagnostic_targets.get(diagnostic_ref(token), {})
        return dict(remembered, request_id=self._diagnostic_serial)

    @diagnostic_guard
    def _diagnose_navigation_context(self, fields):
        if self.diagnostic_context is not None:
            snapshot = self.diagnostic_context(fields.get("thread_ref", ""))
            self.activity_diagnostics.emit(
                "navigation_context", **dict(snapshot, **fields)
            )

    def _open_observed(self, token, outcome):
        target = self.targets.get(token)
        if target is None:
            outcome["reason"] = "token_expired"
            self.failed.emit(t("message.0455"))
            return False
        try:
            if target.kind == "thread" and thread_source(target.identifier) != "codex":
                return self._open_claude_code(target.identifier, outcome)
            if target.kind == "thread":
                if not re.fullmatch(
                    r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}", target.identifier
                ):
                    outcome["reason"] = "invalid_identifier"
                    if self.internal_open:
                        self.internal_open(ActionTarget("diagnostics"))
                    self.failed.emit(t("message.0458"))
                    return False
                if self.app_available:
                    outcome["reason"] = "dispatch_rejected"
                    url = QUrl()
                    url.setScheme("codex")
                    url.setHost("threads")
                    url.setPath("/" + target.identifier)
                    try:
                        opened = self.opener(url)
                    except (OSError, RuntimeError, ValueError) as error:
                        outcome.update(
                            reason="dispatch_exception", error_code=type(error).__name__
                        )
                        opened = False
                    if opened:
                        outcome.update(result="dispatch_accepted", reason="thread_link")
                        return True
                    try:
                        opened_root = self.opener(QUrl("codex://"))
                    except (OSError, RuntimeError, ValueError) as error:
                        outcome["fallback_error_code"] = type(error).__name__
                        opened_root = False
                    outcome["fallback_result"] = (
                        "accepted" if opened_root else "rejected"
                    )
                    if opened_root:
                        outcome.update(result="fallback", reason="app_root")
                        self.failed.emit(t("message.0459"))
                        return False
                else:
                    outcome["reason"] = "handler_unconfirmed"
                if self.internal_open:
                    self.internal_open(ActionTarget("diagnostics"))
                self.failed.emit(t("message.0456"))
                return False
            opened = bool(self.internal_open and self.internal_open(target))
            outcome.update(
                result="internal_accepted" if opened else "failed",
                reason="internal_target",
            )
            return opened
        except (OSError, RuntimeError, ValueError) as error:
            outcome.update(
                reason="navigation_exception", error_code=type(error).__name__
            )
            self.failed.emit(t("message.0457"))
            return False

    def _client(self, identifier):
        lookup = self.claude_code_client
        return lookup(identifier) if lookup else ""

    def _open_claude_code(self, identifier, outcome=None):
        """Open where the session runs, else the activity list (stage 14)."""
        session = identifier.removeprefix(CLAUDE_CODE_THREAD_PREFIX)
        opened, message = self.claude_code_launcher.open(
            session, self._client(identifier)
        )
        if message:
            self.failed.emit(message)
        if opened:
            if outcome is not None:
                outcome.update(
                    result="fallback" if message else "dispatch_accepted",
                    reason="folder_fallback" if message else "claude_target",
                )
            return not message
        accepted = bool(
            self.internal_open and self.internal_open(ActionTarget("projects"))
        )
        if outcome is not None:
            outcome.update(
                result="fallback" if accepted else "failed",
                reason="activity_list" if accepted else "claude_dispatch_failed",
            )
        return accepted


def installed_codex_app():
    """Detect the Win32 or packaged Codex URI handler without a build allowlist."""
    if os.name != "nt":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "codex"):
            return True
    except OSError:
        # Packaged protocol registrations are not always projected into HKCR.
        # The package-family directory is stable across Codex build updates.
        local = os.environ.get("LOCALAPPDATA", "")
        try:
            return bool(
                local
                and (Path(local) / "Packages" / "OpenAI.Codex_2p2nqsd0c76g0").is_dir()
            )
        except OSError:
            return False
