"""Fresh-process, read-only authentication checks shared by application features."""

import logging
from uuid import uuid4
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from watched_kettle.application.logging import log_event
from watched_kettle.integrations.codex_paths import codex_home
from watched_kettle.usage.identifiers import hash_identifier


def masked_email(value):
    value = str(value or "")
    local, separator, domain = value.partition("@")
    return (
        f"{local[:1]}***@{domain}"
        if local and separator and domain
        else "이메일 정보 없음"
    )


@dataclass(frozen=True)
class AccountCheck:
    refresh_id: int = 0
    state: str = "error"
    auth_type: str = ""
    email_fingerprint: str = ""
    account_hash: str = ""
    email_label: str = "이메일 정보 없음"
    plan: str = ""
    error_code: str = ""
    reason: str = "periodic"
    auth_generation: int = 0
    operation_id: str = ""

    @property
    def identity(self):
        return self.auth_type, self.email_fingerprint, self.account_hash


class AccountMonitor(QObject):
    checking = Signal(bool)
    checked = Signal(object)

    def __init__(self, client_factory, parent=None, auth_path=None):
        super().__init__(parent)
        self.factory = client_factory
        self.auth_path = Path(auth_path or codex_home() / "auth.json")
        self.client = None
        self.running = False
        self.refresh_id = 0
        self.reason = "periodic"
        self.auth_generation = 0
        self.operation_id = ""
        self.pending = {}
        self.account = {}
        self.signature = self._signature()
        self.probe_signature = self.signature
        self.periodic = QTimer(self)
        self.periodic.setInterval(60_000)
        self.periodic.timeout.connect(self.check)
        self.file_timer = QTimer(self)
        self.file_timer.setInterval(2_000)
        self.file_timer.timeout.connect(self.poll_file)
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(500)
        self.debounce.timeout.connect(self._after_change)
        self.deadline = QTimer(self)
        self.deadline.setSingleShot(True)
        self.deadline.setInterval(30_000)
        self.deadline.timeout.connect(lambda: self._finish(error_code="timeout"))

    def _signature(self):
        try:
            stat = self.auth_path.stat()
            return stat.st_mtime_ns, stat.st_size, stat.st_ino
        except OSError:
            return None

    def start(self):
        if self.running:
            return
        self.running = True
        self.periodic.start()
        self.file_timer.start()
        self.check()

    def poll_file(self):
        signature = self._signature()
        if signature != self.signature:
            self.signature = signature
            self.auth_generation += 1
            log_event(
                "integrations.account_monitor",
                "auth_file_changed",
                refresh_id=0,
            )
            self.checking.emit(True)
            self._dispose()
            self.debounce.start()

    def _after_change(self):
        self.debounce.stop()
        self.check(self.refresh_id, suspicious=True, reason="auth_file_changed")

    def check(self, refresh_id=0, suspicious=False, *, reason=None):
        if not self.running:
            return False
        reason = reason or (
            "manual"
            if refresh_id
            else "identity_mismatch"
            if suspicious
            else "periodic"
        )
        # Ordinary notifications join the active verification, including a manual
        # refresh. Do not discard its request ID or extend its deadline.
        if reason == "account_notification" and (
            self.client is not None or self.debounce.isActive()
        ):
            return True
        if self.debounce.isActive() and not refresh_id:
            return True
        if self.client is not None and not refresh_id and not suspicious:
            return True
        self.debounce.stop()
        self._dispose()
        self.refresh_id = int(refresh_id or 0)
        self.reason = reason
        self.operation_id = uuid4().hex
        self.account = {}
        self.probe_signature = self._signature()
        if self.probe_signature != self.signature:
            self.signature = self.probe_signature
            self.auth_generation += 1
            suspicious = True
        log_event(
            "integrations.account_monitor",
            "probe_started",
            refresh_id=self.refresh_id,
            phase=self.reason,
            operation_id=self.operation_id,
        )
        self.checking.emit(bool(suspicious))
        client = self.factory(parent=self)
        self.client = client
        client.ready_changed.connect(lambda ready, c=client: self._ready(c, ready))
        client.response_received.connect(
            lambda rid, method, params, result, error, c=client: self._response(
                c, rid, result, error
            )
        )
        client.error_changed.connect(lambda message, c=client: self._error(c, message))
        self.deadline.start()
        client.start()
        return True

    def _ready(self, client, ready):
        if client is not self.client:
            return
        if ready:
            self._request("account/read", {"refreshToken": False})
        else:
            self._finish(error_code="connection_closed")

    def _request(self, method, params=None):
        client = self.client
        if client is None:
            return
        rid = client.request(method, params)
        if rid is None:
            log_event(
                "integrations.account_monitor",
                "probe_request_rejected",
                logging.WARNING,
                operation=method,
                refresh_id=self.refresh_id,
                operation_id=self.operation_id,
                error_code="request_rejected",
            )
            self._finish(error_code="request_rejected")
        else:
            self.pending[rid] = method

    def _error(self, client, message):
        if client is self.client and message:
            log_event(
                "integrations.account_monitor",
                "probe_connection_failed",
                logging.WARNING,
                refresh_id=self.refresh_id,
                operation_id=self.operation_id,
                error_code="connection_failed",
            )
            self._finish(error_code="connection_failed")

    def _response(self, client, rid, result, error):
        if client is not self.client:
            return
        method = self.pending.pop(rid, None)
        if method is None:
            return
        if error is not None:
            error_code = (
                str(error.get("code") or "request_failed")
                if isinstance(error, dict)
                else "request_failed"
            )
            log_event(
                "integrations.account_monitor",
                "probe_request_failed",
                logging.WARNING,
                operation=method,
                refresh_id=self.refresh_id,
                operation_id=self.operation_id,
                error_code=error_code,
            )
            # A valid account response still detects sign-in/email changes even
            # when the quota endpoint is temporarily unavailable.
            self._finish(
                state="available" if self.account else "error",
                error_code="request_failed",
            )
            return
        if not isinstance(result, dict):
            log_event(
                "integrations.account_monitor",
                "probe_invalid_response",
                logging.WARNING,
                operation=method,
                refresh_id=self.refresh_id,
                operation_id=self.operation_id,
                error_code="invalid_response",
            )
            self._finish(error_code="invalid_response")
            return
        if method == "account/read":
            if "account" not in result:
                self._finish(error_code="invalid_response")
                return
            account = result["account"]
            if account is None:
                self._finish(state="signed_out")
            elif not isinstance(account, dict) or not account.get("type"):
                self._finish(error_code="invalid_response")
            else:
                self.account = account
                if account["type"] == "chatgpt":
                    self._request("account/rateLimits/read")
                else:
                    self._finish(state="unsupported_auth")
        else:
            value = result.get("accountId")
            self._finish(
                state="available",
                account_hash=hash_identifier(value)
                if isinstance(value, str) and value
                else "",
            )

    def _finish(self, state="error", account_hash="", error_code=""):
        if self.client is None:
            return
        if self._signature() != self.probe_signature:
            log_event(
                "integrations.account_monitor",
                "auth_file_changed_during_probe",
                logging.WARNING,
                refresh_id=self.refresh_id,
                operation_id=self.operation_id,
                error_code="stale_probe",
            )
            self.signature = self._signature()
            self.auth_generation += 1
            self.checking.emit(True)
            self._dispose()
            self.debounce.start()
            return
        email = str(self.account.get("email") or "")
        result = AccountCheck(
            refresh_id=self.refresh_id,
            state=state,
            auth_type=str(self.account.get("type") or ""),
            email_fingerprint=hash_identifier(email) if email else "",
            account_hash=account_hash,
            email_label=masked_email(email),
            plan=str(self.account.get("planType") or ""),
            error_code=error_code,
            reason=self.reason,
            auth_generation=self.auth_generation,
            operation_id=self.operation_id,
        )
        self._dispose()
        self.refresh_id = 0
        self.account = {}
        log_event(
            "integrations.account_monitor",
            "probe_finished",
            logging.WARNING if error_code else logging.INFO,
            refresh_id=result.refresh_id,
            operation_id=result.operation_id,
            phase=result.reason,
            state=state,
            error_code=error_code or None,
        )
        self.checked.emit(result)

    def _dispose(self):
        self.deadline.stop()
        self.pending.clear()
        client, self.client = self.client, None
        if client is not None:
            client.close()
            client.deleteLater()

    def cancel(self, refresh_id):
        if refresh_id and refresh_id == self.refresh_id:
            self._dispose()
            self.refresh_id = 0

    def close(self):
        self.running = False
        for timer in (self.periodic, self.file_timer, self.debounce):
            timer.stop()
        self._dispose()
