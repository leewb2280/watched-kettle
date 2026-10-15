"""Read-only connection diagnostics and explicit hook-management commands."""

from PySide6.QtCore import QObject, Signal


class IntegrationsViewModel(QObject):
    snapshot_changed = Signal(object)

    def __init__(
        self,
        codex_server,
        hook_installer,
        parent=None,
        project_activity=None,
        claude_code_installer=None,
        status_line_installer=None,
    ):
        super().__init__(parent)
        self.codex_server = codex_server
        self.hook_installer = hook_installer
        self.claude_code_installer = claude_code_installer
        self.status_line_installer = status_line_installer
        self.project_activity = project_activity
        self.snapshot = {}

    def refresh_requested(self):
        self.snapshot = self.codex_server.diagnostics() if self.codex_server else {}
        if self.project_activity is not None:
            self.snapshot["project_activity"] = self.project_activity.diagnostics()
        # State and counts only: installer messages can name local paths.
        installs = {}
        for provider in self.providers:
            try:
                status = self.install_status(provider)
            except Exception as error:
                installs[provider] = {"state": "error", "error": type(error).__name__}
                continue
            installs[provider] = {
                "state": status.state,
                "installed_events": status.installed_events,
                "expected_events": status.expected_events,
            }
        self.snapshot["hook_installs"] = installs
        self.snapshot_changed.emit(self.snapshot)
        return self.snapshot

    @property
    def providers(self):
        return (
            ("codex",)
            + (("claude_code",) if self.claude_code_installer is not None else ())
            + (
                ("claude_code_status_line",)
                if self.status_line_installer is not None
                else ()
            )
        )

    def installer(self, provider="codex"):
        if provider == "claude_code" and self.claude_code_installer is not None:
            return self.claude_code_installer
        if (
            provider == "claude_code_status_line"
            and self.status_line_installer is not None
        ):
            return self.status_line_installer
        if provider == "codex":
            return self.hook_installer
        raise KeyError(provider)

    def install_status(self, provider="codex"):
        return self.installer(provider).inspect()

    def preview_install(self, provider="codex"):
        return self.installer(provider).preview_install()

    def preview_repair(self, provider="codex"):
        return self.installer(provider).preview_repair()

    def preview_remove(self, provider="codex"):
        return self.installer(provider).preview_remove()

    def apply_plan(self, plan, provider="codex"):
        result = self.installer(provider).apply(plan)
        self.refresh_requested()
        return result
