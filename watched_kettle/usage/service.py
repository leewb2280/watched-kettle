"""Account and observed-task usage orchestration."""

from __future__ import annotations

from watched_kettle.localization import t

from watched_kettle.usage.turn_measurement import (
    TaskObservation,
    TurnMeasurements,
    complete_measurement,
)

import sqlite3
import logging
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

from PySide6.QtCore import QObject, QTimer, Signal

from watched_kettle.application.logging import log_event
from watched_kettle.state.events import normalize_agent_source, normalize_event_name
from watched_kettle.usage.models import (
    QuotaUsageSample,
    UsageAvailability,
    UsageSnapshot,
    UsageRefreshState,
    aggregate_local_token_events,
    aggregate_quota_activity,
    main_codex_limit_id,
    merge_rate_limit_buckets,
    parse_account_usage,
    parse_rate_limit_buckets,
    resolve_usage_limit,
)
from watched_kettle.usage.contracts import UsageRepository
from watched_kettle.usage.presentation import format_tray_summary
from watched_kettle.usage.notice_policy import UsageNoticePolicy
from watched_kettle.usage.account_session import AccountSession, RequestContext
from watched_kettle.usage.identifiers import hash_identifier
from watched_kettle.usage.device import DeviceBatch, parse_device_batch
from watched_kettle.usage.log_recovery import LocalTurnRecovery
from watched_kettle.usage.recovery_pages import RecoveryPages
from watched_kettle.usage.task_query import PAGE_SIZE, ORDERS
from watched_kettle.usage.trends import AVERAGE_DAYS, codex_quota_trend, hourly_profile
from watched_kettle.usage.conversation_catalog import UsageConversationCatalog
from watched_kettle.usage.project_history import ProjectHistory
from watched_kettle.features.notifications.models import NoticeRequest
from watched_kettle.integrations.account_monitor import masked_email


RATE_REFRESH_MS = 5 * 60 * 1000
USAGE_REFRESH_MS = 10 * 60 * 1000
# Today's device values belong to a local day. Nothing else recomputes them at
# midnight when Codex is idle or the app server is unavailable, so a cheap date
# check runs every minute (also catching up after sleep).
DAY_CHECK_MS = 60 * 1000
ALERT_THRESHOLDS = (70, 90, 100)
LATEST_TASK_COUNT = 20


class CodexUsageService(QObject):
    snapshot_changed = Signal(object)
    availability_changed = Signal(object)
    assistant_notice_ready = Signal(dict)
    notice_requested = Signal(object)
    account_changed = Signal(bool)

    def __init__(
        self,
        client,
        preferences,
        repository: UsageRepository,
        parent=None,
        now=None,
        local_timezone=None,
        account_monitor=None,
    ):
        super().__init__(parent)
        self.client = client
        self.account_monitor = account_monitor
        self._verified_account = None
        self._applied_auth_generation = -1
        self._connecting_auth_generation: int | None = None
        self._reconnecting = False
        self._refresh_serial = 0
        self._refresh_limits_ok = False
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.setInterval(30_000)
        self.refresh_timer.timeout.connect(self._refresh_timeout)
        self.preferences = preferences
        self.repository = repository
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._local_timezone = (
            local_timezone or datetime.now().astimezone().tzinfo or timezone.utc
        )
        self.enabled = preferences.load_usage_enabled()
        self.quiet_summary_enabled = preferences.load_usage_quiet_summary_enabled()
        self.snapshot = UsageSnapshot(
            availability=UsageAvailability("disabled", t("message.0346"))
            if not self.enabled
            else UsageAvailability()
        )
        self._account_identity = ""
        self._account_supported = False
        self.account = AccountSession()
        self.measurements = TurnMeasurements()
        self.turn_recovery = LocalTurnRecovery(
            self.observe_local_turn_evidence, self, on_state=self._recovery_state
        )
        self._recovery_started_for: tuple[str, int] | None = None
        self._recovery_changes: dict[tuple[str, str], tuple] = {}
        self._recovery_applied: dict[tuple[str, str], tuple] = {}
        self.recovery_timer = QTimer(self)
        self.recovery_timer.setSingleShot(True)
        self.recovery_timer.setInterval(200)
        self.recovery_timer.timeout.connect(self._flush_recovery)
        self.recovery_pages = RecoveryPages(self)
        self._history_search = ""
        self._history_order = "recent"
        self._history_limit = PAGE_SIZE
        self._conversation_mode = False
        self.project_history = ProjectHistory(self)
        self._conversation_search = ""
        self._conversation_order = "recent"
        self._conversation_offset = 0
        self._selected_thread = ""
        self.conversation_catalog = UsageConversationCatalog(self)
        self._conversation_timer = QTimer(self)
        self._conversation_timer.setSingleShot(True)
        self._conversation_timer.setInterval(200)
        self._conversation_timer.timeout.connect(self._refresh_conversation_names)
        self.conversation_catalog.changed.connect(self._schedule_conversation_names)

        self.notice_policy = UsageNoticePolicy(
            repository,
            self._now,
            self._local_timezone,
            self._emit_notice,
            self._storage_failed,
        )
        self._initial_limits_received = False
        self._daily_summary_pending = False
        self._usage_refresh_pending = False

        self.selected_limit_key = (
            preferences.load_usage_widget_limit_key()
            if hasattr(preferences, "load_usage_widget_limit_key")
            else ""
        )

        self.rate_timer = QTimer(self)
        self.rate_timer.setInterval(RATE_REFRESH_MS)
        self.rate_timer.timeout.connect(self._refresh_rate_limits)
        self.usage_timer = QTimer(self)
        self.usage_timer.setInterval(USAGE_REFRESH_MS)
        self.usage_timer.timeout.connect(self._refresh_account_usage)
        self._activity_day: date | None = None
        self.day_timer = QTimer(self)
        self.day_timer.setInterval(DAY_CHECK_MS)
        self.day_timer.timeout.connect(self._check_day)

        client.ready_changed.connect(self._client_ready_changed)
        client.response_received.connect(self._response_received)
        client.notification_received.connect(self._notification_received)
        client.error_changed.connect(self._client_error_changed)
        if account_monitor is not None:
            account_monitor.checking.connect(self._account_checking)
            account_monitor.checked.connect(self._account_checked)

    def start(self):
        log_event(
            "usage.service",
            "started",
            enabled=self.enabled,
            state=self.snapshot.availability.state,
        )
        self.day_timer.start()
        if not self.enabled:
            # Codex is off: no account probe, no auth.json polling, no app-server.
            self._publish(availability=UsageAvailability("disabled", t("message.0346")))
            return
        if self.account_monitor is not None:
            already_running = self.account_monitor.running
            self.account_monitor.start()
            if already_running:
                self.account_monitor.check(suspicious=True)
            return
        self._publish(availability=UsageAvailability("starting", t("message.0385")))
        self.client.start()

    def close(self):
        log_event("usage.service", "closed", state=self.snapshot.availability.state)
        if self.account_monitor is not None:
            self.account_monitor.close()
        self._finish_refresh("cancelled", t("message.0371"))
        self._reset_account("disabled")
        self.rate_timer.stop()
        self.usage_timer.stop()
        self.day_timer.stop()
        self.client.close()

    def _check_day(self):
        if not self.enabled or self._activity_day is None:
            return
        if self._now().astimezone(self._local_timezone).date() != self._activity_day:
            self._refresh_hourly_activity()

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        self.preferences.save_usage_enabled(self.enabled)
        if self.enabled:
            self.start()
        else:
            self._finish_refresh("cancelled", t("message.0373"))
            self._reset_account("disabled")
            self.rate_timer.stop()
            self.usage_timer.stop()
            self.client.close()
            if self.account_monitor is not None:
                self.account_monitor.close()
            self._publish(availability=UsageAvailability("disabled", t("message.0346")))

    def set_quiet_summary_enabled(self, enabled):
        self.quiet_summary_enabled = bool(enabled)
        self.preferences.save_usage_quiet_summary_enabled(self.quiet_summary_enabled)

    def refresh(self, force=False, refresh_id=0):
        if not self.enabled:
            return False
        if force:
            if self.snapshot.refresh.busy:
                return True
            self._recovery_started_for = None
            self._refresh_serial = max(self._refresh_serial + 1, refresh_id)
            log_event(
                "usage.service",
                "refresh_started",
                refresh_id=self._refresh_serial,
                phase="verifying",
                operation="account_check",
            )
            self._refresh_limits_ok = False
            # Do not let a pre-click automatic response complete this refresh.
            self.account.requests = {
                rid: context
                for rid, context in self.account.requests.items()
                if context.kind not in {"account", "limits", "usage"}
            }
            self._usage_refresh_pending = False
            self._publish(
                refresh=UsageRefreshState(
                    self._refresh_serial, "refreshing", "verifying", t("message.0366")
                )
            )
            self.refresh_timer.start()
            if self.account_monitor is not None:
                accepted = self.account_monitor.check(
                    self._refresh_serial, reason="manual"
                )
                if not accepted:
                    self._finish_refresh("error", t("message.0393"))
                return accepted
        if not self.client.ready:
            if force:
                self._refresh_phase("connecting", t("message.0386"))
                self.client.start()
            return bool(force)
        self._refresh_phase("account", t("message.0366"))
        return self._request("account/read", None, "account") is not None

    def _refresh_phase(self, phase, message):
        if self.snapshot.refresh.busy:
            self._publish(
                refresh=replace(self.snapshot.refresh, phase=phase, message=message)
            )

    def _finish_refresh(self, state, message):
        refresh = self.snapshot.refresh
        if not refresh.busy:
            return
        self.refresh_timer.stop()
        self.account.requests = {
            rid: context
            for rid, context in self.account.requests.items()
            if context.refresh_id != refresh.request_id
        }
        if self.account_monitor is not None:
            self.account_monitor.cancel(refresh.request_id)
        log_event(
            "usage.service",
            "refresh_finished",
            logging.WARNING if state in {"error", "partial"} else logging.INFO,
            refresh_id=refresh.request_id,
            state=state,
            phase=refresh.phase,
        )
        self._publish(
            refresh=replace(
                refresh,
                state=state,
                phase="",
                message=message,
                completed_at=self._now(),
            )
        )

    def _refresh_timeout(self):
        self._finish_refresh(
            "partial" if self._refresh_limits_ok else "error",
            t("message.0374") if self._refresh_limits_ok else t("message.0375"),
        )

    def cancel_refresh(self, request_id):
        if self.snapshot.refresh.request_id == request_id:
            self._refresh_timeout()

    def _account_checking(self, suspicious):
        if suspicious:
            log_event(
                "usage.service",
                "account_checking",
                refresh_id=self.snapshot.refresh.request_id,
                phase="verifying",
                state="started",
            )
            self._refresh_limits_ok = False
            self._refresh_phase("verifying", t("message.0366"))
            self.account.invalidate()
            self.measurements.reset()
            self._usage_refresh_pending = False
            self._publish(account_checking=True)

    def _account_checked(self, check):
        log_event(
            "usage.service",
            "account_check_finished",
            logging.WARNING
            if check.error_code or check.state == "error"
            else logging.INFO,
            refresh_id=check.refresh_id,
            operation_id=check.operation_id,
            phase=check.reason,
            state=check.state,
            error_code=check.error_code or None,
        )
        if check.refresh_id and (
            not self.snapshot.refresh.busy
            or check.refresh_id != self.snapshot.refresh.request_id
        ):
            return
        previous = self._verified_account
        # Failed quota checks do not invent an account-ID change.
        same_login = previous is not None and (
            previous.auth_type,
            previous.email_fingerprint,
        ) == (check.auth_type, check.email_fingerprint)
        if check.state == "error" or (check.error_code and same_login):
            if self.enabled:
                self._publish(
                    account_checking=False,
                    availability=UsageAvailability(
                        "offline",
                        t("message.0403"),
                    ),
                )
            else:
                self._publish(account_checking=False)
            self._finish_refresh("error", t("message.0376"))
            return
        changed = previous is not None and previous.identity != check.identity
        if changed:
            self._refresh_limits_ok = False
            if not self.snapshot.refresh.busy:
                self._publish(
                    refresh=UsageRefreshState(self.snapshot.refresh.request_id)
                )
        reconnect_reason = (
            "initial"
            if previous is None
            else "identity_changed"
            if changed
            else "auth_file_changed"
            if check.auth_generation != self._applied_auth_generation
            else "connection_recovery"
            if not self.client.ready
            or self.snapshot.availability.state
            in {"offline", "signed_out", "unsupported_auth"}
            else "same_account"
        )
        reconnect = reconnect_reason != "same_account"
        was_checking = self.snapshot.account_checking
        log_event(
            "usage.service",
            "connection_replace" if reconnect else "connection_retained",
            phase=reconnect_reason,
            operation_id=check.operation_id,
            refresh_id=check.refresh_id,
        )
        self._verified_account = check
        if reconnect:
            self._reconnecting = True
            self._reset_account(preserve_refresh=True)
            self.client.close()
            self._reconnecting = False
            self.account_changed.emit(changed)
        self._publish(
            account_checking=False,
            account_email=check.email_label,
            account_plan=check.plan,
        )
        if not changed and check.state == "available" and self.enabled:
            self._flush_recovery()
        if not self.enabled:
            self._publish(availability=UsageAvailability("disabled", t("message.0346")))
            return
        if check.state != "available":
            self._reset_account(check.state, preserve_refresh=True)
            message = (
                t("message.0377") if check.state == "signed_out" else t("message.0378")
            )
            self._publish(availability=UsageAvailability(check.state, message))
            self._finish_refresh(
                "signed_out" if check.state == "signed_out" else "error", message
            )
            return
        if reconnect or not self.client.ready:
            self._connecting_auth_generation = check.auth_generation
            self._refresh_phase(
                "connecting",
                t("message.0387") if changed else t("message.0386"),
            )
            self.client.start()
        elif was_checking or check.reason == "account_notification":
            # The probe already verified account/read. Continue with quotas,
            # rather than issue another account/read that produces an update.
            self._account_supported = True
            self._account_identity = check.email_fingerprint
            self._refresh_phase("limits", t("message.0372"))
            self._refresh_rate_limits()
        elif check.refresh_id or self.snapshot.availability.state != "available":
            self.refresh()

    def clear_history(self, expected_account=None, expected_generation=None):
        if self.snapshot.account_checking:
            return False
        if expected_account is not None and (
            expected_account != self.snapshot.account_hash
            or expected_generation != self.account.generation
        ):
            self._publish(
                clearing_history=False,
                history_message=t("message.0388"),
            )
            return False
        if not self.snapshot.account_hash:
            return False
        self.turn_recovery.clear()
        self.recovery_pages.cancel()
        self._selected_thread = ""
        self._conversation_offset = 0
        self.project_history.selected = ""
        self.project_history.offset = 0
        self._conversation_timer.stop()
        self.conversation_catalog.clear()
        self.repository.clear_thread_labels()
        self.recovery_timer.stop()
        self._recovery_changes.clear()
        self._recovery_applied.clear()
        self._publish(
            clearing_history=True, history_message="", recovery_pending=frozenset()
        )
        try:
            cleared = self.repository.clear(self.snapshot.account_hash, self._now())
        except (OSError, sqlite3.DatabaseError) as error:
            self._storage_failed(error)
            self._publish(clearing_history=False, history_message=t("message.0394"))
            return False
        if not hasattr(self.repository, "replace_threshold_markers"):
            self.preferences.save_usage_threshold_markers(())
            self.preferences.save_usage_last_summary_date("")
        self._publish(
            recent_tasks=(),
            latest_tasks=(),
            legacy_tasks=(),
            task_history_has_more=False,
            conversations=(),
            projects=(),
            project_count=0,
            project_offset=0,
            selected_project_key="",
            projects_has_more=False,
            selected_conversation=None,
            selected_thread_hash="",
            conversations_has_more=False,
            clearing_history=False,
            history_message=t("message.0379"),
        )
        self._refresh_hourly_activity()
        return cleared

    def set_selected_limit_key(self, key):
        self.selected_limit_key = str(key or "")
        self._refresh_hourly_activity()

    def observe_local_usage_batch(self, records):
        if not self.enabled:
            return
        if isinstance(records, DeviceBatch):
            tokens, quotas = records.tokens, records.quotas
        elif isinstance(records, (tuple, list)):
            tokens, quotas = parse_device_batch(records)
        else:
            return
        try:
            self.repository.device.append(tokens, quotas)
            self._refresh_hourly_activity()
        except (OSError, sqlite3.DatabaseError) as error:
            self._storage_failed(error)

    def clear_device_history(self):
        try:
            cleared = self.repository.device.clear(self._now())
            self._refresh_hourly_activity()
            self._publish(device_history_message=t("message.0389"))
            return cleared
        except (OSError, sqlite3.DatabaseError) as error:
            self._storage_failed(error)
            self._publish(device_history_message=t("message.0395"))
            return False

    def observe_agent_payload(self, payload):
        if (
            not self.enabled
            or self.snapshot.account_checking
            or not self._account_supported
            or not self.snapshot.account_hash
            or not isinstance(payload, dict)
        ):
            return
        if normalize_agent_source(payload.get("source")) != "codex" or str(
            payload.get("agent_scope") or "main"
        ).casefold() not in {"", "main"}:
            return
        event = normalize_event_name(
            payload.get("hook_event_name") or payload.get("event")
        )
        thread_id = str(payload.get("session_id") or "").strip()
        turn_id = str(payload.get("turn_id") or "").strip()
        if not thread_id:
            return
        key = (thread_id, turn_id)
        task: TaskObservation | None
        self._expire_tasks()
        if key in self.measurements.finished:
            return
        if event == "prompt":
            if key in self.measurements.tasks:
                return
            for other_key, other in tuple(self.measurements.tasks.items()):
                if other.thread_id == thread_id:
                    other.reason = "overlapping_turn"
                    if other.completed_at:
                        self._complete_task(other_key)
            task = TaskObservation(
                self.snapshot.account_hash,
                thread_id,
                turn_id,
                self._now(),
                reason="missing_turn_id" if not turn_id else "",
            )
            self.measurements.tasks[key] = task
        elif event in {"done", "failed"}:
            task = self.measurements.tasks.get(key)
            if task is None:
                task = TaskObservation(
                    self.snapshot.account_hash,
                    thread_id,
                    turn_id,
                    self._now(),
                    reason="missing_start",
                )
                self.measurements.tasks[key] = task
            if task.completed_at:
                return
            task.completed_at = self._now()
            task.outcome = "failed" if event == "failed" else "done"
            self._complete_task(key)
            self._refresh_rate_limits()
            self._daily_summary_pending = True
            self._refresh_account_usage()

    def _expire_tasks(self):
        now = self._now()
        for key, task in tuple(self.measurements.tasks.items()):
            if (now - task.started_at).total_seconds() > 12 * 3600:
                task.reason = "observation_expired"
                task.completed_at = task.completed_at or now
                self._complete_task(key)
        self.measurements.finished = {
            key: stamp
            for key, stamp in self.measurements.finished.items()
            if (now - stamp).total_seconds() < 12 * 3600
        }
        while len(self.measurements.finished) > 512:
            self.measurements.finished.pop(next(iter(self.measurements.finished)))
        while len(self.measurements.tasks) >= 512:
            key = next(iter(self.measurements.tasks))
            self.measurements.tasks[key].reason = "observation_limit"
            self.measurements.tasks[key].completed_at = now
            self._complete_task(key)

    def tray_summary(self) -> str:
        return format_tray_summary(self.snapshot.for_display())

    def _reset_account(self, state="starting", preserve_refresh=False):
        if not preserve_refresh:
            self._finish_refresh("cancelled", t("message.0380"))
        self.account.invalidate()
        self._account_supported = False
        self._account_identity = ""
        self.account.requests.clear()
        self.measurements.reset()
        self.turn_recovery.clear()
        self.recovery_pages.cancel()
        self._history_search = ""
        self._history_order = "recent"
        self._history_limit = PAGE_SIZE
        self._conversation_search = ""
        self._conversation_order = "recent"
        self._conversation_offset = 0
        self._selected_thread = ""
        self.project_history.reset()
        self._conversation_timer.stop()
        self.conversation_catalog.clear()
        self.repository.clear_thread_labels()
        self.recovery_timer.stop()
        self._recovery_changes.clear()
        self._recovery_applied.clear()
        self._recovery_started_for = None
        self.notice_policy.reset()
        self._initial_limits_received = False
        self._daily_summary_pending = False
        self._usage_refresh_pending = False
        device_snapshot = self.snapshot
        self.snapshot = UsageSnapshot(
            refresh=device_snapshot.refresh,
            hourly_activity=device_snapshot.hourly_activity if self.enabled else (),
            observed_today_tokens=device_snapshot.observed_today_tokens
            if self.enabled
            else None,
            last_sample_at=device_snapshot.last_sample_at if self.enabled else None,
            device_legacy_records=device_snapshot.device_legacy_records
            if self.enabled
            else (),
            availability=UsageAvailability(state, t("message.0390")),
            storage_error=self.snapshot.storage_error,
            selected_quota_key=self.selected_limit_key,
        )
        self.snapshot_changed.emit(self.snapshot.for_display())

    def _client_ready_changed(self, ready):
        if ready and self._connecting_auth_generation is not None:
            self._applied_auth_generation = self._connecting_auth_generation
            self._connecting_auth_generation = None
        log_event(
            "usage.service",
            "client_ready_changed",
            state="ready" if ready else "offline",
            ready=ready,
        )
        self._reset_account("starting" if ready else "offline", preserve_refresh=True)
        if ready and self.enabled:
            self.rate_timer.start()
            self.usage_timer.start()
            self._refresh_phase("account", t("message.0366"))
            self.refresh()
        else:
            self.rate_timer.stop()
            self.usage_timer.stop()
            if not self._reconnecting:
                self._finish_refresh("error", t("message.0391"))

    def _client_error_changed(self, message):
        if message and self.enabled and not self.client.ready:
            log_event(
                "usage.service",
                "client_error",
                logging.WARNING,
                error_code="connection_failed",
            )
            self._publish(availability=UsageAvailability("offline", str(message)))
            self._finish_refresh("error", t("message.0381"))

    def _request(self, method, params, kind, task_key=None):
        if kind in {"account", "limits", "usage"} and any(
            c.kind == kind for c in self.account.requests.values()
        ):
            return None
        request_id = self.client.request(method, params)
        if request_id is not None:
            self.account.requests[request_id] = RequestContext(
                self.account.generation,
                kind,
                task_key,
                self.snapshot.refresh.request_id
                if self.snapshot.refresh.busy and kind in {"account", "limits", "usage"}
                else 0,
            )
        elif kind in {"account", "limits", "usage"}:
            log_event(
                "usage.service",
                "request_rejected",
                logging.WARNING,
                operation=method,
                refresh_id=self.snapshot.refresh.request_id,
                error_code="request_rejected",
            )
            self._finish_refresh(
                "partial" if self._refresh_limits_ok else "error",
                t("message.0396") if self._refresh_limits_ok else t("message.0397"),
            )
        return request_id

    def _refresh_rate_limits(self):
        if self.snapshot.account_checking or (
            self.snapshot.refresh.busy and self.snapshot.refresh.phase != "limits"
        ):
            return
        if self.client.ready and self._account_supported:
            self._request("account/rateLimits/read", None, "limits")

    def _refresh_account_usage(self):
        if self.snapshot.account_checking or (
            self.snapshot.refresh.busy and self.snapshot.refresh.phase != "usage"
        ):
            return None
        self._expire_tasks()
        if not self.client.ready or not self._account_supported:
            return None
        if any(c.kind == "usage" for c in self.account.requests.values()):
            self._usage_refresh_pending = True
            return None
        self._usage_refresh_pending = False
        return self._request("account/usage/read", {}, "usage")

    def _response_received(self, request_id, method, params, result, error):
        context = self.account.consume(request_id)
        if context is None or not self.enabled:
            return
        if self.snapshot.account_checking:
            return
        kind, key = context.kind, context.task_key
        if error is not None:
            error_code = (
                str(error.get("code") or "request_failed")
                if isinstance(error, dict)
                else "request_failed"
            )
            log_event(
                "usage.service",
                "request_failed",
                logging.WARNING,
                operation=method,
                request_id=request_id,
                error_code=error_code,
            )
            if key in self.measurements.tasks:
                task = self.measurements.tasks[key]
                task.reason = "request_failed"
                if task.completed_at:
                    self._complete_task(key)
            if kind == "usage":
                self._usage_refresh_pending = False
            message = str(error.get("message", "")) if isinstance(error, dict) else ""
            if "authentication required" in message.casefold():
                self._finish_refresh("signed_out", t("message.0377"))
                self._reset_account("signed_out")
                self._publish(
                    availability=UsageAvailability("signed_out", t("message.0377"))
                )
                return
            if context.refresh_id:
                timed_out = isinstance(error, dict) and error.get("code") == "timeout"
                self._finish_refresh(
                    "partial" if self._refresh_limits_ok else "error",
                    t("message.0398")
                    if self._refresh_limits_ok
                    else (t("message.0404") if timed_out else t("message.0399")),
                )
            self._publish(availability=UsageAvailability("offline", t("message.0399")))
            return
        if kind == "account":
            self._handle_account(result)
        elif kind == "limits":
            if not parse_rate_limit_buckets(result):
                self._finish_refresh("error", t("message.0400"))
                self._publish(
                    availability=UsageAvailability(
                        "offline",
                        t("message.0407"),
                    )
                )
                return
            self._handle_limits(result)
        elif kind == "usage":
            if not isinstance(result, dict) or not (
                isinstance(result.get("summary"), dict)
                or isinstance(result.get("dailyUsageBuckets"), list)
            ):
                self._finish_refresh(
                    "partial" if self._refresh_limits_ok else "error",
                    t("message.0405"),
                )
                return
            self._handle_account_usage(result)
            if context.refresh_id:
                self._finish_refresh("success", t("message.0406"))
            if self._usage_refresh_pending:
                self._refresh_account_usage()

    def _handle_account(self, result):
        if not isinstance(result, dict) or "account" not in result:
            self._finish_refresh("error", t("message.0382"))
            return
        account = result.get("account") if isinstance(result, dict) else None
        if account is not None and (
            not isinstance(account, dict) or not account.get("type")
        ):
            self._finish_refresh("error", t("message.0382"))
            self._publish(availability=UsageAvailability("offline", t("message.0382")))
            return
        if not isinstance(account, dict) or account.get("type") != "chatgpt":
            state = "signed_out" if not account else "unsupported_auth"
            self._finish_refresh(
                "signed_out" if not account else "error",
                t("message.0377") if not account else t("message.0392"),
            )
            self._reset_account(state)
            self._publish(
                availability=UsageAvailability(
                    state,
                    t("message.0377") if account is None else t("message.0378"),
                )
            )
            return
        # Email is only an in-memory change detector, never a persistence key.
        email = str(account.get("email") or "")
        identity = hash_identifier(email) if email else ""
        if (
            self._verified_account is not None
            and identity != self._verified_account.email_fingerprint
        ):
            self._account_checking(True)
            self.account_monitor.check(
                self.snapshot.refresh.request_id if self.snapshot.refresh.busy else 0,
                suspicious=True,
                reason="identity_mismatch",
            )
            return
        if self._account_supported and identity != self._account_identity:
            self._reset_account(preserve_refresh=True)
        self._account_identity = identity
        self._account_supported = True
        self._publish(
            account_email=masked_email(email),
            account_plan=self._verified_account.plan
            if self._verified_account is not None
            else str(account.get("planType") or ""),
        )
        self._refresh_phase("limits", t("message.0372"))
        self._refresh_rate_limits()

    def _handle_limits(self, result, sparse=False):
        account_id = result.get("accountId") if isinstance(result, dict) else None
        if (
            not sparse
            and self._verified_account is not None
            and self._verified_account.account_hash
            and isinstance(account_id, str)
            and hash_identifier(account_id) != self._verified_account.account_hash
        ):
            self._account_checking(True)
            self.account_monitor.check(
                self.snapshot.refresh.request_id if self.snapshot.refresh.busy else 0,
                suspicious=True,
                reason="identity_mismatch",
            )
            return
        account_hash = self.snapshot.account_hash
        if not sparse:
            new_hash = (
                hash_identifier(account_id) if isinstance(account_id, str) else ""
            )
            if new_hash != account_hash:
                identity = self._account_identity
                email, plan = self.snapshot.account_email, self.snapshot.account_plan
                self._reset_account(preserve_refresh=True)
                self._publish(account_email=email, account_plan=plan)
                self._account_identity = identity
                self._account_supported = True
                account_hash = new_hash
            self._publish(account_hash=account_hash)
        elif account_id and hash_identifier(account_id) != account_hash:
            self._reset_account()
            self.refresh()
            return
        reset_credits = (
            result.get("rateLimitResetCredits") if isinstance(result, dict) else None
        )
        reset_credit_count = self.snapshot.reset_credit_count
        reset_credit_supplied = False
        if isinstance(reset_credits, dict):
            try:
                reset_credit_count = int(str(reset_credits.get("availableCount")))
                reset_credit_supplied = True
            except (TypeError, ValueError):
                pass
        fresh = parse_rate_limit_buckets(result)
        if not fresh:
            if reset_credit_supplied:
                self._publish(
                    reset_credit_count=reset_credit_count,
                    last_updated_at=self._now(),
                )
            if sparse:
                self._refresh_rate_limits()
            return
        buckets = (
            merge_rate_limit_buckets(self.snapshot.buckets, fresh) if sparse else fresh
        )
        self._publish(
            account_hash=account_hash,
            buckets=buckets,
            **self._history_values(account_hash, latest=True),
            reset_credit_count=reset_credit_count,
            availability=UsageAvailability(
                "available",
                t("message.0401") if account_hash else t("message.0402"),
            ),
            last_updated_at=self._now(),
        )
        if account_hash:
            if self._conversation_mode:
                self.conversation_catalog.start(force=self.snapshot.refresh.busy)
            self._record_rate_limit_samples(fresh, self._now())
            self._refresh_hourly_activity(account_hash)
            recovery_key = (account_hash, self.account.generation)
            if self._recovery_started_for != recovery_key:
                self._recovery_started_for = recovery_key
                self.recovery_pages.start(manual=self.snapshot.refresh.busy)
        self._check_thresholds(buckets, alert=self._initial_limits_received)
        self._initial_limits_received = True
        if not sparse:
            self._refresh_limits_ok = True
            self._refresh_phase("usage", t("message.0383"))
            self._refresh_account_usage()

    def _handle_account_usage(self, result):
        summary, daily = parse_account_usage(result)
        sampled_at = self._now()
        self._publish(summary=summary, daily_buckets=daily, last_updated_at=sampled_at)
        account_hash = self.snapshot.account_hash
        self._refresh_hourly_activity(account_hash, daily)
        if self._daily_summary_pending:
            self._daily_summary_pending = False
            self._maybe_daily_summary()

    def _refresh_hourly_activity(self, account_hash=None, daily=None):
        account_hash = account_hash or self.snapshot.account_hash
        try:
            token_events = self.repository.device.tokens()
            legacy = self.repository.device.legacy()
            quota_samples = (
                self.repository.load_quota_samples(account_hash) if account_hash else ()
            )
        except (OSError, sqlite3.DatabaseError) as error:
            self._storage_failed(error)
            return

        now = self._now()
        local_day = now.astimezone(self._local_timezone).date()
        self._activity_day = local_day
        hourly = aggregate_local_token_events(
            token_events,
            local_day=local_day,
            local_timezone=self._local_timezone,
            now=now,
        )
        trend_hours = hourly_profile(
            [bucket.tokens for bucket in hourly],
            [
                [
                    bucket.tokens
                    for bucket in aggregate_local_token_events(
                        token_events,
                        local_day=local_day - timedelta(days=offset),
                        local_timezone=self._local_timezone,
                        now=now,
                    )
                ]
                for offset in range(1, AVERAGE_DAYS + 1)
            ],
            now.astimezone(self._local_timezone).hour,
            day=local_day,
        )
        trend_quota = codex_quota_trend(
            quota_samples,
            local_day,
            self._local_timezone,
            now,
            limit_id=main_codex_limit_id(self.snapshot.buckets),
        )
        observed_values = [
            bucket.tokens
            for bucket in hourly
            if bucket.tokens is not None and bucket.observed_intervals > 0
        ]
        observed = sum(observed_values) if observed_values else None
        selected = resolve_usage_limit(self.snapshot.buckets, self.selected_limit_key)
        selected_key = selected.key if selected is not None else self.selected_limit_key
        selected_limit_id, separator, selected_slot = selected_key.partition("|")
        selected_quota_samples = [
            sample
            for sample in quota_samples
            if separator
            and sample.limit_id == selected_limit_id
            and sample.window_slot == selected_slot
        ]
        quota_hourly = aggregate_quota_activity(
            quota_samples,
            selected_key,
            local_day=local_day,
            local_timezone=self._local_timezone,
            now=now,
        )
        quota_values = [
            bucket.percent_points
            for bucket in quota_hourly
            if bucket.percent_points is not None
        ]
        self._publish(
            device_legacy_records=legacy,
            hourly_activity=hourly,
            observed_today_tokens=observed,
            unclassified_today_tokens=None,
            last_sample_at=token_events[-1].occurred_at if token_events else None,
            quota_hourly_activity=quota_hourly,
            trend_hours=trend_hours,
            trend_quota=trend_quota,
            observed_today_percent_points=sum(quota_values) if quota_values else None,
            selected_quota_observation_count=sum(
                sample.observed_at.astimezone(self._local_timezone).date() == local_day
                for sample in selected_quota_samples
            ),
            quota_last_sample_at=selected_quota_samples[-1].observed_at
            if selected_quota_samples
            else None,
            selected_quota_key=selected_key,
        )

    def _record_rate_limit_samples(self, buckets, observed_at):
        account_hash = self.snapshot.account_hash
        if not account_hash:
            return
        samples = []
        stamp = observed_at.astimezone(timezone.utc).isoformat()
        for bucket in buckets:
            for slot, window in (
                ("primary", bucket.primary),
                ("secondary", bucket.secondary),
            ):
                if window is None or window.used_percent is None:
                    continue
                reset_key = (
                    window.resets_at.isoformat() if window.resets_at else "unknown"
                )
                samples.append(
                    QuotaUsageSample(
                        account_hash,
                        hash_identifier(
                            f"app-server|{bucket.limit_id}|{slot}|{stamp}|"
                            f"{window.used_percent}|{reset_key}"
                        ),
                        bucket.limit_id,
                        slot,
                        observed_at,
                        window.used_percent,
                        window.window_duration_mins,
                        window.resets_at,
                    )
                )
        if samples:
            try:
                self.repository.append_server_quota_samples(
                    account_hash, tuple(samples)
                )
            except (OSError, sqlite3.DatabaseError) as error:
                self._storage_failed(error)

    def _complete_task(self, key):
        task = self.measurements.tasks.pop(key, None)
        if task is None or key in self.measurements.finished:
            return
        self.measurements.finished[key] = task.completed_at or self._now()
        task.reason = task.reason or "local_log_unavailable"
        record = complete_measurement(task, None, self._now())
        try:
            self.repository.append(record)
            self._publish(**self._history_values(task.account_hash, latest=True))
            if record.turn_hash:
                self._recovery_started_for = (
                    task.account_hash,
                    self.account.generation,
                )
                self.turn_recovery.add_records((record,))
                if not self.recovery_pages.timer.isActive():
                    self.recovery_pages.start()
        except (OSError, sqlite3.DatabaseError) as error:
            self._storage_failed(error)

    def _queue_recovery(self, key, state, reason="", evidence=None):
        scope = (self.snapshot.account_hash, self.account.generation)
        if not self.enabled or not scope[0] or self._recovery_started_for != scope:
            return
        value = (scope, state, reason, evidence)
        previous = self._recovery_changes.get(key)
        if previous and state == "measured" and evidence is None:
            value = (scope, state, reason, previous[3])
        if self._recovery_applied.get(key) == value:
            self._recovery_changes.pop(key, None)
            if not self._recovery_changes:
                self.recovery_timer.stop()
            return
        if previous == value:
            return
        self._recovery_changes[key] = value
        if not self.recovery_timer.isActive():
            self.recovery_timer.start(200)

    def _recovery_state(self, thread_hash, turn_hash, state, reason):
        self._queue_recovery((thread_hash, turn_hash), state, reason)

    def observe_local_turn_evidence(self, evidence):
        self._queue_recovery(
            (hash_identifier(evidence.thread_id), hash_identifier(evidence.turn_id)),
            "measured",
            evidence=evidence,
        )

    def _flush_recovery(self):
        self.recovery_timer.stop()
        if self.snapshot.account_checking or not self.enabled:
            return
        scope = (self.snapshot.account_hash, self.account.generation)
        changes = {k: v for k, v in self._recovery_changes.items() if v[0] == scope}
        self._recovery_changes.clear()
        if not changes:
            return
        evidence = tuple(v[3] for v in changes.values() if v[3] is not None)
        reasons = tuple((*k, v[2]) for k, v in changes.items() if v[1] == "unavailable")
        pending = set(self.snapshot.recovery_pending)
        for key, value in changes.items():
            if value[1] == "checking":
                pending.add(key)
            else:
                pending.discard(key)
        try:
            changed = (
                self.repository.apply_recovery_batch(scope[0], evidence, reasons)
                if evidence or reasons
                else False
            )
            history = (
                self._history_values(scope[0], frozenset(pending), latest=True)
                if changed
                or (
                    self._history_search
                    and frozenset(pending) != self.snapshot.recovery_pending
                )
                else {}
            )
            records = history.get("recent_tasks", self.snapshot.recent_tasks)
            self._recovery_applied.update(changes)
            if len(self._recovery_applied) > 1024:
                retained = {(r.thread_hash, r.turn_hash) for r in records}
                self._recovery_applied = {
                    k: v for k, v in self._recovery_applied.items() if k in retained
                }
            completed = {
                (r.thread_hash, r.turn_hash)
                for r in records
                if r.data_quality != "unavailable"
            }
            self.turn_recovery.acknowledge(completed)
            pending.difference_update(completed)
            if changed or frozenset(pending) != self.snapshot.recovery_pending:
                self._publish(
                    **history,
                    recovery_pending=frozenset(pending),
                    _recovery=True,
                )
        except (OSError, sqlite3.DatabaseError) as error:
            for key, value in changes.items():
                self._recovery_changes.setdefault(key, value)
            self.recovery_timer.start(1000)
            self._storage_failed(error)

    def _notification_received(self, method, params):
        if not self.enabled:
            return
        if method in {"account/updated", "account/login/completed"}:
            if self.account_monitor is not None:
                ordinary = method == "account/updated"
                if ordinary and any(
                    context.kind == "account"
                    for context in self.account.requests.values()
                ):
                    return
                self.account_monitor.check(
                    self.snapshot.refresh.request_id
                    if self.snapshot.refresh.busy
                    else 0,
                    suspicious=True,
                    reason="account_notification" if ordinary else "login_completed",
                )
                return
            self._reset_account()
            self.refresh()
        elif method == "account/rateLimits/updated" and self._account_supported:
            if self.snapshot.account_checking or self.snapshot.refresh.busy:
                return
            self._handle_limits(params, sparse=True)

    def _check_thresholds(self, buckets, alert=True):
        return self.notice_policy.check_thresholds(self.snapshot, buckets, alert)

    def _maybe_daily_summary(self):
        return self.notice_policy.daily_summary(
            self.snapshot, self.quiet_summary_enabled
        )

    def _emit_notice(self, message, urgency, deduplication_key="", replacement_key=""):
        message = str(message)[:120]
        self.notice_requested.emit(
            NoticeRequest(
                source="system",
                session_id="work-codex-usage",
                urgency=urgency,
                message=message,
                deduplication_key=deduplication_key,
                replacement_key=replacement_key,
                category="usage",
            )
        )
        # Transitional compatibility for callers not yet hosted by an
        # ApplicationRuntime. New application wiring consumes NoticeRequest.
        self.assistant_notice_ready.emit(
            {
                "source": "system",
                "event": "notification",
                "session_id": "work-codex-usage",
                "urgency": urgency,
                "message": message,
            }
        )

    def _publish(self, _recovery=False, **changes):
        self.snapshot = replace(self.snapshot, **changes)
        if "availability" in changes:
            self.availability_changed.emit(self.snapshot.availability)
        self._publishing_recovery = _recovery
        try:
            self.snapshot_changed.emit(self.snapshot.for_display())
        finally:
            self._publishing_recovery = False

    def set_task_query(
        self,
        search="",
        order="recent",
        limit=PAGE_SIZE,
        expected_account=None,
        expected_generation=None,
        thread_hash=None,
    ):
        if self.snapshot.account_checking or not self.snapshot.account_hash:
            return False
        if expected_account is not None and (
            expected_account != self.snapshot.account_hash
            or expected_generation != self.account.generation
        ):
            return False
        if self._conversation_mode and (
            not self._selected_thread or thread_hash != self._selected_thread
        ):
            return False
        self._history_search = str(search).strip()[:200]
        self._history_order = order if order in ORDERS else "recent"
        self._history_limit = max(
            PAGE_SIZE, min(int(limit), self._history_limit + PAGE_SIZE)
        )
        self._publish(**self._history_values(self.snapshot.account_hash))
        return True

    def _history_values(self, account_hash, pending=None, latest=False):
        # latest_tasks is re-read only where task rows change, so paging and
        # selecting conversations keep their no-task-query contract.
        values = dict(
            task_history_managed=True,
            task_history_search=self._history_search,
            task_history_order=self._history_order,
            task_history_limit=self._history_limit,
            task_history_has_more=False,
            recent_tasks=(),
            legacy_tasks=(),
        )
        if latest:
            values["latest_tasks"] = ()
        if not account_hash:
            return values
        try:
            pending = self.snapshot.recovery_pending if pending is None else pending
            if latest:
                values["latest_tasks"] = self.repository.query_tasks(
                    account_hash, LATEST_TASK_COUNT, pending=pending
                ).records
            if self._conversation_mode:
                if self.project_history.enabled:
                    values.update(self.project_history.values(account_hash))
                page = self.repository.query_conversations(
                    account_hash,
                    self._conversation_search,
                    self._conversation_order,
                    self._conversation_offset,
                    project_key=self.project_history.selected
                    if self.project_history.enabled
                    else None,
                )
                selected = (
                    self.repository.query_conversations(
                        account_hash, thread_hash=self._selected_thread, limit=1
                    ).records
                    if self._selected_thread
                    else ()
                )
                values.update(
                    conversation_mode=True,
                    conversations=page.records,
                    conversation_search=self._conversation_search,
                    conversation_order=self._conversation_order,
                    conversation_offset=self._conversation_offset,
                    conversations_has_more=page.has_more,
                    selected_thread_hash=self._selected_thread,
                    selected_conversation=selected[0] if selected else None,
                    conversation_status=self.conversation_catalog.status,
                )
                if not selected:
                    self._selected_thread = ""
                    values["selected_thread_hash"] = ""
                    return values
            page = self.repository.query_tasks(
                account_hash,
                PAGE_SIZE,
                self._history_search,
                self._history_order,
                pending,
                offset=self._history_limit - PAGE_SIZE,
                thread_hash=self._selected_thread if self._conversation_mode else None,
            )
            values.update(
                recent_tasks=page.records, task_history_has_more=page.has_more
            )
        except (OSError, sqlite3.DatabaseError) as error:
            self._storage_failed(error)
        return values

    def _schedule_conversation_names(self):
        if not self._conversation_timer.isActive():
            self._conversation_timer.start()

    def set_project_query(
        self,
        search="",
        order="recent",
        offset=0,
        custom=None,
        expected_account=None,
        expected_generation=None,
    ):
        return self.project_history.query(
            search, order, offset, custom, expected_account, expected_generation
        )

    def select_usage_project(
        self, key, expected_account=None, expected_generation=None
    ):
        return self.project_history.select(key, expected_account, expected_generation)

    def move_usage_project(
        self,
        key,
        direction=0,
        target="",
        before=True,
        expected_account=None,
        expected_generation=None,
    ):
        return self.project_history.move(
            key, direction, target, before, expected_account, expected_generation
        )

    def _refresh_conversation_names(self):
        if (
            self._conversation_mode
            and self.snapshot.account_hash
            and not self.snapshot.account_checking
        ):
            self._publish(
                _recovery=True, **self._history_values(self.snapshot.account_hash)
            )

    def set_conversation_query(
        self,
        search="",
        order="recent",
        offset=0,
        expected_account=None,
        expected_generation=None,
        project_key=None,
    ):
        if (
            self.project_history.enabled
            and project_key != self.project_history.selected
        ):
            return False
        if expected_account is not None and (
            expected_account != self.snapshot.account_hash
            or expected_generation != self.account.generation
        ):
            return False
        self._conversation_mode = True
        self._conversation_search = str(search).strip()[:200]
        self._conversation_order = "top" if order == "top" else "recent"
        self._conversation_offset = max(
            0, min(int(offset), self._conversation_offset + PAGE_SIZE)
        )
        if self.snapshot.account_checking or not self.snapshot.account_hash:
            return False
        self.conversation_catalog.start()
        self._publish(**self._history_values(self.snapshot.account_hash))
        return True

    def select_usage_conversation(
        self, thread_hash, expected_account=None, expected_generation=None
    ):
        if self.snapshot.account_checking or not self.snapshot.account_hash:
            return False
        if expected_account is not None and (
            expected_account != self.snapshot.account_hash
            or expected_generation != self.account.generation
        ):
            return False
        records = self.repository.query_conversations(
            self.snapshot.account_hash, thread_hash=str(thread_hash), limit=1
        ).records
        if not records:
            return False
        self._conversation_mode = True
        self._selected_thread = str(thread_hash)
        self._history_search, self._history_order, self._history_limit = (
            "",
            "recent",
            PAGE_SIZE,
        )
        self._publish(**self._history_values(self.snapshot.account_hash))
        return True

    def _load_history(self, account_hash, legacy=False):
        if not account_hash:
            return ()
        try:
            return (
                self.repository.load_legacy(account_hash)
                if legacy
                else self.repository.load(account_hash)
            )
        except (OSError, sqlite3.DatabaseError) as error:
            self._storage_failed(error)
            return ()

    def _storage_failed(self, error):
        self._publish(storage_error=(t("message.0384")))
