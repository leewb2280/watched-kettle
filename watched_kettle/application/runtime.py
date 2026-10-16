"""Application composition root and deterministic lifecycle."""

from __future__ import annotations

import logging
import os

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QSystemTrayIcon

from watched_kettle.activity_diagnostics import diagnostic_guard
from watched_kettle.application.coordinator import AppCoordinator
from watched_kettle.application.diagnostics import DiagnosticsExporter
from watched_kettle.application.logging import log_event
from watched_kettle.application.paths import AppPaths
from watched_kettle.features.agent_activity import AgentActivityService
from watched_kettle.features.integrations.activation import (
    TOOLS,
    ToolActivation,
    migrate_tool_activation,
)
from watched_kettle.features.integrations.viewmodel import IntegrationsViewModel
from watched_kettle.features.history.viewmodel import HistoryViewModel
from watched_kettle.features.notifications.service import NotificationService
from watched_kettle.features.notifications.actions import NotificationActionRouter
from watched_kettle.features.project_activity.service import ProjectActivityService
from watched_kettle.features.project_activity.metadata import (
    ConversationMetadataService,
)
from watched_kettle.ui.actionable_bubbles import (
    ActionableBubbleController,
    show_action_failure,
)
from watched_kettle.features.pet.viewmodel import PetViewModel
from watched_kettle.features.settings.viewmodel import SettingsViewModel
from watched_kettle.features.usage.viewmodel import UsageViewModel
from watched_kettle.integrations.claude_code_install import ClaudeCodeHookInstaller
from watched_kettle.integrations.claude_code_status_line_install import (
    ClaudeCodeStatusLineInstaller,
)
from watched_kettle.integrations.claude_code_transcript import (
    ClaudeCodeTranscriptMonitor,
)
from watched_kettle.integrations.codex_ipc import CodexHookServer
from watched_kettle.integrations.codex_install import CodexHookInstaller
from watched_kettle.integrations.codex_log_worker import ThreadedCodexLogMonitor
from watched_kettle.integrations.codex_paths import codex_home
from watched_kettle.integrations.windows_startup import WindowsStartupRegistration
from watched_kettle.state.session_manager import InactivityLimit
from watched_kettle.storage.database import (
    SCHEMA_VERSION,
)
from watched_kettle.application.routes import RouteId
from watched_kettle.ui.assistant_tray import AssistantSystemTray
from watched_kettle.ui.fonts import configure_application_font
from watched_kettle.ui.usage_companion import UsageCompanionController
from watched_kettle.usage.widget_state import codex_seen
from watched_kettle.usage.worker import UsageWorkerService


class ApplicationRuntime(QObject):
    """Own application services, UI composition, and deterministic shutdown."""

    def __init__(
        self,
        app,
        pet,
        preferences,
        paths=None,
        parent=None,
        *,
        codex_server: CodexHookServer | None = None,
        usage_client_factory=None,
        codex_sessions_root=None,
        require_tray: bool = False,
    ):
        """Compose one runtime, taking lifecycle ownership of an injected server."""
        super().__init__(parent or app)
        self.app = app
        self.pet = pet
        self.preferences = preferences
        self.paths = paths or AppPaths.default()
        self._started = False
        self._closed = False
        self.lifecycle_errors = {}
        try:
            self.ui_font_family = configure_application_font(app)

            self.diagnostics_exporter = DiagnosticsExporter(self.paths, SCHEMA_VERSION)
            self.codex_hook_installer = CodexHookInstaller()
            self.claude_code_hook_installer = ClaudeCodeHookInstaller()
            self.claude_code_status_line_installer = ClaudeCodeStatusLineInstaller()
            # Before the usage worker reads either tool switch.
            migrated = migrate_tool_activation(
                preferences,
                self.claude_code_hook_installer,
                self.claude_code_status_line_installer,
            )
            if migrated is not None:
                log_event(
                    "application.integrations",
                    "tool_activation_migrated",
                    codex=preferences.load_usage_enabled(),
                    claude_code=migrated,
                )
            usage_options = (
                {"client_factory": usage_client_factory} if usage_client_factory else {}
            )
            self.usage_service = UsageWorkerService(
                self.paths,
                preferences,
                parent=self,
                lifecycle_errors=self.lifecycle_errors,
                **usage_options,
            )
            self.database = self.usage_service  # status-only facade used by diagnostics

            log_options = (
                {"sessions_root": codex_sessions_root}
                if codex_sessions_root is not None
                else {}
            )
            self.codex_log_monitor = ThreadedCodexLogMonitor(parent=self, **log_options)
            self.codex_log_monitor.usage_detected.connect(
                self.usage_service.observe_local_usage_batch
            )
            self.codex_server = (
                codex_server if codex_server is not None else CodexHookServer()
            )
            if self.codex_server.parent() is None:
                self.codex_server.setParent(self)
            self.claude_code_transcript_monitor = ClaudeCodeTranscriptMonitor(
                parent=self
            )
            self.startup_registration = WindowsStartupRegistration()
            self.notification_service = NotificationService(parent=self)
            self.projects = ProjectActivityService(
                parent=self, duration=pet.bubble_controller.duration_seconds
            )
            self.action_router = NotificationActionRouter(parent=self)
            self.metadata_service = ConversationMetadataService(
                self.projects, parent=self, **usage_options
            )
            self.codex_log_monitor.recovery_detected.connect(
                self.projects.restore_activity
            )
            self.claude_code_transcript_monitor.title_detected.connect(
                self.projects.set_claude_code_title
            )
            self.usage_service.account_changed.connect(
                self.codex_log_monitor.account_changed
            )
            self.usage_service.account_changed.connect(
                self.metadata_service.account_changed
            )
            old_bubbles = pet.bubble_controller
            self.bubbles = ActionableBubbleController(
                pet,
                self.projects,
                self.notification_service,
                self.action_router,
                enabled=old_bubbles.enabled,
                scale_percent=old_bubbles.scale_percent,
                duration_seconds=old_bubbles.duration_seconds,
                theme=old_bubbles.theme,
                element_registry=old_bubbles.element_registry,
                parent=pet,
            )
            old_bubbles.close()
            old_bubbles.deleteLater()
            pet.bubble_controller = self.bubbles
            self.bubbles.set_duration_policy(pet.bubble_duration_policy)
            self.activity_service = AgentActivityService(
                pet, parent=self, projects=self.projects
            )
            self.pet_vm = PetViewModel(pet, parent=self)
            self.usage_vm = UsageViewModel(self.usage_service, preferences, parent=self)
            self.integrations_vm = IntegrationsViewModel(
                self.codex_server,
                self.codex_hook_installer,
                parent=self,
                project_activity=self.projects,
                claude_code_installer=self.claude_code_hook_installer,
                status_line_installer=self.claude_code_status_line_installer,
                provider_active=lambda provider: provider in self.active_providers(),
            )
            self.tool_activation = ToolActivation(
                preferences,
                # The same installers the connections page inspects.
                self.integrations_vm.installer,
                switches={
                    "codex": self.usage_vm.set_enabled,
                    "claude_code": self.usage_vm.set_claude_code_enabled,
                },
            )
            self._codex_opener = getattr(pet, "codex_opener", None)
            self.settings_vm = SettingsViewModel(
                self.pet_vm,
                self.usage_vm,
                self.startup_registration,
                parent=self,
            )
            self.history_vm = HistoryViewModel(
                self.notification_service,
                self.usage_vm,
                parent=self,
                projects=self.projects,
                router=self.action_router,
            )
            self.notification_service.bind_navigation(self.projects, self.action_router)
            self.projects.changed.connect(self.history_vm.refresh)
            self.center = self._electron_center()
            self.usage_companion = UsageCompanionController(
                pet,
                self.pet_vm,
                self.usage_vm,
                # A click shows the usage page; the menu opens widget settings.
                lambda: self.center.open_route(RouteId.USAGE),
                parent=self,
                app_theme=preferences.load_app_theme,
                activity=self._widget_activity,
                open_settings=lambda: self.center.open_route(RouteId.WIDGET_SETTINGS),
            )
            # Task counts and the app theme live outside the usage snapshot.
            self.projects.changed.connect(self.usage_companion.refresh)
            self.center.adapter.changed.connect(self._settings_changed)
            self.action_router.internal_open = self.center.open_target
            self.action_router.claude_code_client = self.projects.claude_code_client
            self.action_router.failed.connect(show_action_failure)
            self.usage_vm.snapshot_changed.connect(self._update_source_marks)
            self.integrations_vm.snapshot_changed.connect(self._update_source_marks)
            self.projects.changed.connect(self._project_changed)
            self._project_generation = self.projects.generation
            self.tray = (
                AssistantSystemTray(
                    self.pet_vm,
                    self.usage_vm,
                    self.notification_service,
                    self.center.open_route,
                    pet.frames["idle"][0],
                    parent=self,
                    updates=self.settings_vm.updates,
                )
                if require_tray or QSystemTrayIcon.isSystemTrayAvailable()
                else _NullTray()
            )
            self.coordinator = AppCoordinator(
                self.codex_server,
                self.activity_service,
                self.usage_service,
                self.notification_service,
                self.pet_vm,
                self.center,
                self.tray,
            )
            self.codex_server.attach_log_monitor(self.codex_log_monitor)
            self.codex_server.attach_transcript_monitor(
                self.claude_code_transcript_monitor
            )
            self._apply_claude_code_timeouts()
            for tool in TOOLS:
                self._apply_tool_state(tool, self.tool_enabled(tool), initial=True)
            self._update_source_marks()
            self._enable_activity_diagnostics()
            if os.environ.get("WATCHED_KETTLE_TRACE_ACTIVITY") == "1":
                self._enable_activity_trace()
            app.aboutToQuit.connect(self.close)
        except Exception:
            self.close()
            raise

    def start(self):
        if self._started:
            return
        self._started = True
        log_event("application.runtime", "started")
        # Codex logs are not read while Codex is switched off.
        codex_logs = self.codex_log_monitor if self.tool_enabled("codex") else None
        for name, component in (
            ("codex_log_monitor", codex_logs),
            ("codex_server", self.codex_server),
            ("usage_service", self.usage_service),
            ("conversation_metadata", self.metadata_service),
        ):
            if component is None:
                continue
            try:
                component.start()
                log_event(
                    "application.runtime",
                    "component_started",
                    operation=name,
                    state="ready",
                )
            except Exception as error:
                self.lifecycle_errors[name] = type(error).__name__
                log_event(
                    "application.runtime",
                    "component_start_failed",
                    logging.ERROR,
                    operation=name,
                    error_code=type(error).__name__,
                )

    @diagnostic_guard
    def _enable_activity_diagnostics(self):
        """Connect content-free observations; state owners never import logging."""
        for component, owner in (
            ("features.project_activity", self.projects),
            ("integrations.codex_ipc", self.codex_server),
            ("features.project_metadata", self.metadata_service),
            ("ui.actionable_bubbles", self.bubbles),
            ("features.notification_actions", self.action_router),
        ):
            owner.activity_diagnostics.callback = (
                lambda event, component=component, **fields: log_event(
                    component, event, **fields
                )
            )
        self.action_router.diagnostic_context = self._navigation_diagnostic_context
        log_event(
            "application.runtime",
            "activity_diagnostics_enabled",
            phase="minimal",
            enabled=True,
        )

    def _navigation_diagnostic_context(self, thread_ref):
        from watched_kettle.activity_diagnostics import diagnostic_ref

        thread = next(
            (
                key
                for key in self.projects.metadata
                if diagnostic_ref(key) == thread_ref
            ),
            "",
        )
        fields = (
            self.projects.diagnostic_summary(thread)
            if thread
            else {"context_available": False}
        )
        fields["context_available"] = bool(thread)
        lookup = self.metadata_service.last_diagnostics.get(thread_ref, {})
        fields["lookup_result"] = lookup.get("lookup_result", "unknown")
        fields["lookup_error_code"] = lookup.get("error_code", "")
        fields["lookup_epoch"] = lookup.get("epoch", 0)
        fields["lookup_generation"] = lookup.get("generation", 0)
        fields["lookup_version"] = lookup.get("target_version", 0)
        fields["lookup_request_id"] = lookup.get("request_id", 0)
        row = self.bubbles._diagnostic_rows.get(thread_ref, {})
        fields["card_ref"] = row.get("card_ref", "")
        fields["project_kind"] = row.get("project_kind", "unknown")
        fields["included"] = bool(row)
        fields["visible"] = any(
            diagnostic_ref(key) == row.get("card_ref") and window.isVisible()
            for key, window in self.bubbles.card_windows.items()
        )
        return fields

    @diagnostic_guard
    def _enable_activity_trace(self):
        """Log hashed per-event decisions to diagnose stuck activity rows."""

        def trace(component, only_event=None):
            def emit(event, **fields):
                if only_event is None or event == only_event:
                    log_event(component, event, **fields)

            return emit

        # Lifecycle observations already go through the minimal diagnostic sink.
        self.projects.trace = trace("features.project_activity", "event_observed")
        self.codex_server.trace = trace("integrations.codex_ipc")
        if hasattr(self, "metadata_service"):
            self.metadata_service.worker.activity_diagnostics.detailed = True
        log_event("application.runtime", "activity_trace_enabled", enabled=True)

    def set_claude_code_timeouts(self, work_minutes, waiting_minutes):
        """Save and apply Claude Code inactivity limits in minutes."""
        self.preferences.save_claude_code_timeouts(work_minutes, waiting_minutes)
        self._apply_claude_code_timeouts()

    def _apply_claude_code_timeouts(self):
        work, waiting = self.preferences.load_claude_code_timeouts()
        limit = InactivityLimit(work_ms=work * 60_000, waiting_ms=waiting * 60_000)
        # The pet and its project cards release a silent session together.
        self.projects.set_inactivity_limit("claude_code", limit)
        controller = getattr(self.pet, "agent_controller", None)
        if controller is not None and hasattr(controller, "set_inactivity_limit"):
            controller.set_inactivity_limit("claude_code", limit)

    def _widget_activity(self):
        counts = {}
        for card in self.projects.cards:
            entry = counts.setdefault(card.source, {"running": 0, "attention": 0})
            entry["running"] += card.running
            entry["attention"] += card.waiting
        return counts

    # ---- tool switches (features/integrations/activation.py) -------------

    tools = TOOLS

    def tool_enabled(self, tool):
        if tool == "codex":
            return bool(self.usage_vm.enabled)
        return bool(self.usage_vm.claude_code_enabled)

    def active_providers(self):
        """Installer providers whose tool is switched on."""
        return (("codex",) if self.tool_enabled("codex") else ()) + (
            ("claude_code", "claude_code_status_line")
            if self.tool_enabled("claude_code")
            else ()
        )

    def codex_detected(self):
        """Whether Codex is on this PC, from its folder alone."""
        try:
            return codex_home().is_dir()
        except OSError:
            return False

    def claude_code_detected(self):
        try:
            installer = self.integrations_vm.installer("claude_code")
            return installer.settings_path.parent.is_dir()
        except (OSError, KeyError, AttributeError):
            return False

    def preview_tool(self, tool, enabled):
        return self.tool_activation.preview(tool, enabled)

    def apply_tool(self, plan):
        result = self.tool_activation.apply(plan)
        self._apply_tool_state(plan.tool, plan.enabled)
        log_event(
            "application.integrations",
            "tool_switched",
            operation=plan.tool,
            enabled=plan.enabled,
            state="complete" if result.complete else "partial",
        )
        self.integrations_vm.refresh_requested()
        return result

    def _apply_tool_state(self, tool, enabled, initial=False):
        """Start or stop everything that reads one tool, and drop its work."""
        self.codex_server.set_source_enabled(tool, enabled)
        if tool == "codex":
            self.metadata_service.set_enabled(enabled, started=self._started)
            # Double-clicking the pet opens Codex only while Codex is in use.
            self.pet.codex_opener = self._codex_opener if enabled else None
            if not enabled:
                self.codex_log_monitor.close()
            elif self._started:
                self.codex_log_monitor.start()
        if initial or enabled:
            return
        controller = getattr(self.pet, "agent_controller", None)
        if controller is not None:
            controller.clear(source=tool)
        self.projects.reset(source=tool)
        self.tray.request_refresh()
        self.usage_companion.refresh()

    def _update_source_marks(self, *_args):
        """Dot each agent source only when Codex and Claude Code are both in use."""
        claude_code = False
        # Claude Code's settings file is not read while it is off.
        if self.tool_enabled("claude_code"):
            try:
                status = self.integrations_vm.installer("claude_code").inspect()
                claude_code = status.installed_events > 0
            except Exception:
                claude_code = False
        shown = claude_code and codex_seen(self.usage_vm.snapshot)
        self.bubbles.set_source_marks_shown(shown)
        tray = getattr(self, "tray", None)
        if tray is not None:
            tray.set_source_marks_shown(shown)

    def _settings_changed(self, topic):
        if topic == "settings":
            self.usage_companion.refresh()

    def _electron_center(self):
        from watched_kettle.application.settings_ui.core import CoreSettingsAdapter
        from watched_kettle.application.settings_ui.assistant import (
            AssistantSettingsAdapter,
        )
        from watched_kettle.application.settings_ui.host import SettingsWindowHost

        adapter = CoreSettingsAdapter(
            self.pet_vm, self.settings_vm, self.preferences, self.app, self
        )
        adapter.assistant = AssistantSettingsAdapter(adapter, self)
        return SettingsWindowHost(adapter, self)

    def close(self):
        if self._closed:
            return
        self._closed = True
        log_event("application.runtime", "closing")
        for name, method in (
            ("tray", "close"),
            ("usage_companion", "close"),
            ("center", "shutdown"),
            ("bubbles", "close"),
            ("conversation_metadata", "close"),
            ("usage_service", "close"),
            ("codex_server", "close"),
            ("claude_code_transcript_monitor", "close"),
            ("codex_log_monitor", "close"),
        ):
            attribute = "metadata_service" if name == "conversation_metadata" else name
            component = getattr(self, attribute, None)
            if component is None:
                continue
            try:
                getattr(component, method)()
                log_event(
                    "application.runtime",
                    "component_closed",
                    operation=name,
                    state="closed",
                )
            except Exception as error:
                self.lifecycle_errors[f"close:{name}"] = type(error).__name__
                log_event(
                    "application.runtime",
                    "component_close_failed",
                    logging.ERROR,
                    operation=name,
                    error_code=type(error).__name__,
                )
        log_event(
            "application.runtime",
            "closed",
            logging.WARNING if self.lifecycle_errors else logging.INFO,
            state="error" if self.lifecycle_errors else "closed",
        )

    def _project_changed(self):
        if self._project_generation != self.projects.generation:
            self._project_generation = self.projects.generation
            self.action_router.reset()
            self.notification_service.clear_history()
            # A Codex account change must not hide Claude Code work.
            self.pet.agent_controller.clear(source="codex")
        self.tray.request_refresh()


class _NullTray:
    def request_refresh(self):
        pass

    def set_source_marks_shown(self, _shown):
        pass

    def close(self):
        pass

    def refresh(self):
        pass

    def hide(self):
        pass

    def set_icon(self, _pixmap):
        pass
