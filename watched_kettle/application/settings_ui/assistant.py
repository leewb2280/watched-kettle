"""Optional assistant adapter, assembled only in the assistant edition."""

from __future__ import annotations

from watched_kettle.localization import t

from datetime import datetime
import re
from uuid import uuid4
from typing import cast

from watched_kettle import settings_protocol as wire_types
from watched_kettle.integrations.claude_code_status_line import (
    LAYOUT_FILE_NAME,
    read_layout,
    write_layout,
)
from watched_kettle.application.settings_ui.contracts import (
    boolean,
    choice,
    integer,
    require,
    text,
    wire,
    CommandError,
)
from watched_kettle.application.settings_ui.core import control, png_data
from watched_kettle.app_preferences import USAGE_CHART_DAYS
from watched_kettle.application.diagnostics import _safe_snapshot
from watched_kettle.usage.models import usage_limit_groups, usage_limit_options
from watched_kettle.usage.trends import current_hours, daily_series
from watched_kettle.usage.task_query import ORDERS
from watched_kettle.ui.bubble_models import source_display_label
from watched_kettle.ui.usage_widget.backdrop import acrylic_available
from watched_kettle.ui.project_bubble_rows import _badge_presentation


# Plan key for a tool switch; hook repairs are keyed by their provider.
TOOL_PLAN = "tool"


class AssistantSettingsAdapter:
    def __init__(self, core, runtime):
        self.core, self.runtime = core, runtime
        self.usage = runtime.usage_vm
        self.plans = {}
        self.usage.snapshot_changed.connect(lambda _s: core.changed.emit("usage"))
        self.usage.claude_code_changed.connect(lambda _s: core.changed.emit("usage"))
        runtime.history_vm.snapshot_changed.connect(
            lambda _s: core.changed.emit("activity")
        )
        runtime.projects.changed.connect(lambda: core.changed.emit("activity"))
        watch = getattr(runtime, "connection_watch", None)
        if watch is not None:
            # Home lists the connection alerts and follows the activity topic.
            watch.changed.connect(lambda _s: core.changed.emit("activity"))
        runtime.usage_service.account_changed.connect(self._account_changed)

    def _account_changed(self, _value):
        self.core.account_epoch += 1
        self.plans.clear()
        self.core.changed.emit("account")

    def usage_snapshot(self) -> wire_types.UsageResponse:
        vm = self.usage
        hidden = not vm.widget_visible
        # Acrylic follows the app theme; a custom color or opacity does not apply.
        acrylic = vm.widget_material == "acrylic" and acrylic_available()
        limits = usage_limit_options(vm.snapshot.buckets)
        controls = [
            control(
                "quiet_summary",
                t("message.0482"),
                vm.quiet_summary_enabled,
                groupId="usage_notices",
                group=t("message.0493"),
                disabled=not vm.enabled,
            ),
            control(
                "widget_visible",
                t("message.0483"),
                vm.widget_visible,
                groupId="widget",
                group=t("message.0494"),
            ),
            control(
                "widget_shape",
                t("message.0484"),
                vm.widget_shape,
                "select",
                options=[
                    dict(value=v, label=label)
                    for v, label in (
                        ("rings", t("message.0269")),
                        ("bars", t("message.0270")),
                        ("chips", t("message.0271")),
                    )
                ],
                groupId="widget",
                group=t("message.0494"),
                disabled=hidden,
            ),
            control(
                "widget_emphasis",
                t("message.0485"),
                vm.widget_emphasis,
                "select",
                options=[
                    dict(value=v, label=label)
                    for v, label in (
                        ("auto", t("message.0506")),
                        ("five_hour", t("message.0333")),
                        ("seven_day", t("message.0334")),
                    )
                ],
                groupId="widget",
                group=t("message.0494"),
                disabled=hidden,
                description=t("message.0495"),
            ),
            control(
                "widget_tasks",
                t("message.0264"),
                vm.widget_tasks_visible,
                groupId="widget",
                group=t("message.0494"),
                disabled=hidden,
            ),
            control(
                "widget_today",
                t("message.0265"),
                vm.widget_today_visible,
                groupId="widget",
                group=t("message.0494"),
                disabled=hidden,
                description=t("message.0496"),
            ),
            control(
                "widget_material",
                t("message.0486"),
                vm.widget_material,
                "select",
                options=[
                    dict(value="opaque", label=t("message.0502")),
                    dict(value="acrylic", label=t("message.0503")),
                ],
                groupId="widget_appearance",
                group=t("message.0497"),
                disabled=hidden or not acrylic_available(),
                description=(
                    t("message.0500") if acrylic_available() else t("message.0501")
                ),
            ),
            control(
                "widget_theme",
                t("message.0487"),
                vm.widget_theme_mode,
                "select",
                options=[
                    dict(value="app", label=t("message.0504")),
                    dict(value="custom", label=t("message.0505")),
                ],
                groupId="widget_appearance",
                group=t("message.0497"),
                disabled=hidden or acrylic,
            ),
            control(
                "widget_color",
                t("message.0488"),
                vm.widget_background_color,
                "color",
                groupId="widget_appearance",
                group=t("message.0497"),
                disabled=hidden or acrylic or vm.widget_theme_mode != "custom",
            ),
            control(
                "widget_opacity",
                t("message.0489"),
                vm.widget_background_opacity,
                "range",
                min=0,
                max=100,
                step=1,
                unit="%",
                groupId="widget_appearance",
                group=t("message.0497"),
                disabled=hidden or acrylic,
            ),
            control(
                "widget_scale",
                t("message.0490"),
                vm.widget_scale_percent,
                "range",
                min=70,
                max=130,
                step=10,
                unit="%",
                groupId="widget_appearance",
                group=t("message.0497"),
                disabled=hidden,
            ),
            control(
                "chart_days",
                t("message.0491"),
                vm.chart_days,
                "select",
                options=[
                    dict(value=v, label=t("message.0425", value0=v))
                    for v in USAGE_CHART_DAYS
                ],
                groupId="history",
                group=t("message.0498"),
            ),
        ]
        claude_code = vm.claude_code_snapshot
        return dict(
            epoch=self.core.account_epoch,
            enabled=vm.enabled,
            claude_code_enabled=vm.claude_code_enabled,
            any_enabled=vm.any_enabled,
            data=wire(vm.snapshot),
            limits=wire(limits),
            limit_groups=wire(
                usage_limit_groups(
                    limits,
                    codex_enabled=vm.enabled,
                    claude_code_enabled=vm.claude_code_enabled,
                )
            ),
            controls=controls,
            hours=list(vm.widget_hour_range),
            trends=wire(self._trends(claude_code)),
            claude_code=dict(
                data=wire(claude_code),
                # Limit cards explain when the status line is not connected.
                # Claude Code's settings file is not read while it is off.
                status_line=(self._status_line_snapshot() or {}).get("state")
                if vm.claude_code_enabled
                else None,
            )
            if claude_code is not None
            else None,
        )

    def _trends(self, claude_code):
        """The overview charts' values for each tool (usage.trends)."""
        vm = self.usage
        days = vm.chart_days
        codex = vm.snapshot
        now = datetime.now().astimezone()
        # Codex recomputes on its own refreshes; right after midnight the
        # profile can still be yesterday's and must not fill today's hours.
        return dict(
            now_hour=now.hour,
            codex=dict(
                enabled=vm.enabled,
                hours=current_hours(codex.trend_hours, now.date()),
                quota=codex.trend_quota or {},
                daily=daily_series(
                    [(item.start_date, item.tokens) for item in codex.daily_buckets],
                    days,
                ),
            ),
            claude_code=dict(
                enabled=bool(vm.claude_code_enabled and claude_code is not None),
                hours=current_hours(
                    getattr(claude_code, "trend_hours", None), now.date()
                ),
                quota=getattr(claude_code, "trend_quota", None) or {},
                daily=daily_series(getattr(claude_code, "daily_tokens", ()), days),
            ),
        )

    def execute(self, method, args):
        if method == "usage.snapshot":
            return self.usage_snapshot()
        if method == "usage.widget_preview":
            return self._widget_preview(args)
        if method == "activity.snapshot":
            return self._activity_snapshot(args)
        if method == "integration.snapshot":
            return self._integration_snapshot(args)
        require(
            args.get("epoch") == self.core.account_epoch,
            t("message.0479"),
            "stale_context",
        )
        vm = self.usage
        if method == "usage.set":
            self._set_usage(args)
        elif method == "usage.query":
            self._query_usage(args)
        elif method == "usage.select":
            self._select_usage(args)
        elif method == "usage.move":
            vm.move_usage_project(
                text(args.get("key"), 2048), choice(args.get("direction"), (-1, 1))
            )
        elif method == "usage.action" and self._provider(args) == "claude_code":
            choice(args.get("action"), ("clear",))
            vm.claude_code("clear_history")
        elif method == "usage.action":
            self._usage_action(args)
        elif method == "activity.clear":
            self.runtime.notification_service.clear_history()
        elif method == "activity.open":
            token = text(args.get("token"), 64)
            require(
                token in self.runtime.action_router.targets,
                t("message.0507"),
                "expired",
            )
            return dict(opened=self.runtime.action_router.open(token))
        elif method == "integration.preview" and args.get("operation") in (
            "enable",
            "disable",
        ):
            tool = choice(args.get("provider"), self.runtime.tools)
            plan = self.runtime.preview_tool(tool, args["operation"] == "enable")
            self.plans.clear()
            token = uuid4().hex
            self.plans[token] = (TOOL_PLAN, plan)
            return dict(
                token=token,
                canApply=plan.can_apply,
                changes=list(plan.changes),
                warnings=list(plan.warnings),
            )
        elif method == "integration.preview":
            return self._preview_integration(args)
        elif method == "integration.apply":
            self._apply_integration(args)
        elif method == "integration.set" and args.get("key") == "status_line_layout":
            value = args.get("value")
            require(isinstance(value, dict) and isinstance(value.get("lines"), list))
            write_layout(self._status_line_layout_path(), value)
        elif method == "integration.set":
            key = choice(
                args.get("key"),
                ("claude_code_work_minutes", "claude_code_waiting_minutes"),
            )
            work, waiting = self.runtime.preferences.load_claude_code_timeouts()
            if key == "claude_code_work_minutes":
                work = integer(args.get("value"), 1, 120)
            else:
                waiting = integer(args.get("value"), 1, 240)
            self.runtime.set_claude_code_timeouts(work, waiting)
            self.core._sync()
        else:
            raise CommandError("unsupported", t("message.0509"))
        self.core.changed.emit("usage")
        self.core.changed.emit("activity")
        return dict(
            accepted=True,
            saved=method in {"usage.set", "integration.set"},
            epoch=self.core.account_epoch,
        )

    def _widget_preview(self, args) -> wire_types.WidgetPreview:
        companion = getattr(self.runtime, "usage_companion", None)
        if companion is None:
            raise CommandError("invalid_argument", t("message.0492"))
        image, sample = companion.preview(
            sample=args.get("sample") is True,
            expanded=args.get("expanded") is True,
        )
        # Logical size, so a 150% Windows display does not show it larger.
        ratio = image.devicePixelRatio() or 1
        return dict(
            image=png_data(image),
            sample=sample,
            width=round(image.width() / ratio),
            height=round(image.height() / ratio),
        )

    def _activity_snapshot(self, args) -> wire_types.ActivityResponse:
        return dict(
            epoch=self.core.account_epoch,
            entries=wire(self.runtime.history_vm.refresh(emit=False).entries),
            projects=[
                dict(
                    key=card.key,
                    label=card.label,
                    source=source_display_label(card.source),
                    summary=card.summary,
                    rows=[
                        dict(
                            title=row.title,
                            state=row.state,
                            label=_badge_presentation(
                                row, self.runtime.pet.bubble_controller.theme
                            )[0],
                            action_token=self.runtime.action_router.register(
                                "thread", row.thread_id
                            ),
                        )
                        for row in card.rows
                    ],
                )
                for card in self.runtime.projects.cards
            ],
            notices=[
                cast(
                    wire_types.NoticeRecord,
                    dict(
                        wire(record),
                        # Same target the history entry registers, so opening
                        # from either list confirms the notice the same way.
                        action_token=self.runtime.action_router.register(
                            "usage" if record.category == "usage" else "notice",
                            record.record_id,
                        ),
                    ),
                )
                for record in self.runtime.notification_service.snapshot.recent
            ],
        )

    def _integration_snapshot(self, args) -> wire_types.IntegrationResponse:
        codex = self.usage.enabled
        # Codex's hook files are not read while it is off.
        install = self.runtime.integrations_vm.install_status() if codex else None
        return dict(
            diagnostics=cast(
                wire_types.Diagnostics,
                _safe_snapshot(self.runtime.integrations_vm.refresh_requested()),
            ),
            codex_active=codex,
            codex_detected=self.runtime.codex_detected(),
            status=install.message if install else "",
            install=dict(
                state=install.state,
                message=install.message,
                installed_events=install.installed_events,
                expected_events=install.expected_events,
            )
            if install
            else dict(
                state="inactive", message="", installed_events=0, expected_events=0
            ),
            storage=wire(self.runtime.database.availability),
            claude_code=self._claude_code_snapshot(),
            connection_alerts=[
                cast(
                    wire_types.ConnectionAlert,
                    dict(tool=alert.tool, kind=alert.kind),
                )
                for alert in getattr(
                    getattr(self.runtime, "connection_watch", None), "snapshot", ()
                )
            ],
        )

    def _set_usage(self, args):
        vm = self.usage
        key, value = text(args.get("key")), args.get("value")
        # Each tool's own switch lives on the connections page.
        bools = {
            "quiet_summary": vm.set_quiet_summary_enabled,
            "widget_visible": vm.set_widget_visible,
            "widget_tasks": vm.set_widget_tasks_visible,
            "widget_today": vm.set_widget_today_visible,
        }
        if key in bools:
            bools[key](boolean(value))
        elif key == "widget_shape":
            vm.set_widget_shape(choice(value, ("rings", "bars", "chips")))
        elif key == "widget_emphasis":
            vm.set_widget_emphasis(choice(value, ("auto", "five_hour", "seven_day")))
        elif key == "widget_material":
            vm.set_widget_material(choice(value, ("opaque", "acrylic")))
        elif key == "widget_theme":
            vm.set_widget_theme_mode(choice(value, ("app", "custom")))
        elif key == "widget_color":
            require(isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value))
            vm.set_widget_background_color(value)
        elif key == "widget_opacity":
            vm.set_widget_background_opacity(integer(value, 0, 100))
        elif key == "widget_scale":
            vm.set_widget_scale_percent(integer(value, 70, 130))
        elif key == "chart_days":
            vm.set_chart_days(choice(value, USAGE_CHART_DAYS))
        elif key == "widget_hours":
            require(isinstance(value, list) and len(value) == 2)
            start, end = integer(value[0], 0, 23), integer(value[1], 1, 24)
            require(start < end)
            vm.set_widget_hour_range(start, end)
        else:
            raise CommandError("unsupported", t("message.0508"))
        self.core._sync()

    def _query_usage(self, args):
        vm = self.usage
        kind = choice(args.get("kind"), ("projects", "conversations", "tasks"))
        search = text(args.get("search", ""), 200)
        claude = self._provider(args) == "claude_code"
        orders = {
            "projects": ("recent", "name") if claude else ("recent", "name", "custom"),
            "conversations": ("recent", "top"),
            "tasks": ORDERS,
        }
        order = choice(args.get("order", "recent"), orders[kind])
        offset = integer(args.get("offset", 0), 0, 10000000)
        if claude:
            if kind == "tasks":
                vm.claude_code(
                    "set_task_query",
                    search,
                    order,
                    integer(args.get("limit", 100), 100, 10000),
                )
            else:
                vm.claude_code(
                    "set_project_query"
                    if kind == "projects"
                    else "set_conversation_query",
                    search,
                    order,
                    offset,
                )
        elif kind == "projects":
            vm.set_project_query(search, order, offset)
        elif kind == "conversations":
            vm.set_conversation_query(search, order, offset)
        else:
            vm.set_task_query(
                search,
                order,
                integer(args.get("limit", 100), 100, 10000),
                vm.snapshot.selected_thread_hash or None,
            )

    def _select_usage(self, args):
        vm = self.usage
        kind = choice(args.get("kind"), ("project", "conversation"))
        key = text(args.get("key"), 2048)
        if self._provider(args) == "claude_code":
            vm.claude_code(
                "select_usage_project"
                if kind == "project"
                else "select_usage_conversation",
                key,
            )
        elif kind == "project":
            vm.select_usage_project(key)
        else:
            vm.select_usage_conversation(key)

    def _usage_action(self, args):
        vm = self.usage
        actions = {
            "refresh": vm.refresh_requested,
            "clear": vm.clear_requested,
            "clear_device": vm.clear_device_requested,
            "reset_widget": vm.reset_widget_settings,
            "reset_style": vm.reset_widget_style,
            "reset_scale": vm.reset_widget_scale,
            "reset_hours": vm.reset_widget_hour_range,
            "reset_position": vm.reset_widget_position,
        }
        actions[choice(args.get("action"), actions)]()
        self.core._sync()

    def _preview_integration(self, args):
        operation = choice(args.get("operation"), ("install", "repair", "remove"))
        provider = choice(
            args.get("provider", "codex"), self.runtime.active_providers()
        )
        # Tool hooks follow the tool's switch; only the status line, an
        # option of Claude Code, connects and disconnects on its own.
        require(
            operation == "repair" or provider == "claude_code_status_line",
            t("message.0480"),
            "unsupported",
        )
        fn = {
            "install": self.runtime.integrations_vm.preview_install,
            "repair": self.runtime.integrations_vm.preview_repair,
            "remove": self.runtime.integrations_vm.preview_remove,
        }[operation]
        plan = fn(provider)
        self.plans.clear()
        token = uuid4().hex
        self.plans[token] = (provider, plan)
        return dict(
            token=token,
            canApply=plan.can_apply,
            changes=list(plan.changes),
            warnings=list(plan.warnings),
        )

    def _apply_integration(self, args):
        entry = self.plans.pop(text(args.get("token"), 64), None)
        require(
            entry is not None,
            t("message.0481"),
            "expired",
        )
        provider, plan = entry
        if provider == TOOL_PLAN:
            self.runtime.apply_tool(plan)
        elif provider in self.runtime.active_providers():
            self.runtime.integrations_vm.apply_plan(plan, provider)
        else:
            raise CommandError("expired", t("message.0499"))

    def _provider(self, args):
        providers = ("codex",) + (
            ("claude_code",) if self.usage.claude_code_snapshot is not None else ()
        )
        return choice(args.get("provider", "codex"), providers)

    def _claude_code_snapshot(self):
        vm = self.runtime.integrations_vm
        if "claude_code" not in vm.providers:
            return None
        work, waiting = self.runtime.preferences.load_claude_code_timeouts()
        if not self.usage.claude_code_enabled:
            # Off: only whether Claude Code is on this PC, from its folder.
            return dict(
                active=False,
                install=dict(
                    state="inactive",
                    message="",
                    installed_events=0,
                    expected_events=0,
                    detected=self.runtime.claude_code_detected(),
                ),
                work_minutes=work,
                waiting_minutes=waiting,
                status_line=None,
            )
        install = vm.install_status("claude_code")
        return dict(
            active=True,
            install=dict(
                state=install.state,
                message=install.message,
                installed_events=install.installed_events,
                expected_events=install.expected_events,
                detected=install.detected,
            ),
            work_minutes=work,
            waiting_minutes=waiting,
            status_line=self._status_line_snapshot(),
        )

    def _status_line_snapshot(self):
        vm = self.runtime.integrations_vm
        if "claude_code_status_line" not in vm.providers:
            return None
        status = vm.install_status("claude_code_status_line")
        claude = self.usage.claude_code_snapshot
        return dict(
            state=status.state,
            message=status.message,
            has_original=status.has_original,
            observed_at=wire(getattr(claude, "limits_observed_at", None)),
            layout=read_layout(self._status_line_layout_path()),
        )

    def _status_line_layout_path(self):
        sidecar = self.runtime.claude_code_status_line_installer.sidecar_path
        return sidecar.with_name(LAYOUT_FILE_NAME)
