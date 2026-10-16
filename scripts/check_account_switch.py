"""Check real App Server auth caching with isolated synthetic credentials.

Only initialize/account/read use the real transport. The quota RPC is stubbed
so the synthetic token never reaches a usage endpoint or changes a real login.
Run with: python -m scripts.check_account_switch
"""

import base64
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from watched_kettle.integrations.account_monitor import AccountMonitor
from watched_kettle.integrations.codex_app_server import (
    CodexAppServerClient,
    find_codex_program,
)


class SettledTemporaryDirectory(TemporaryDirectory):
    """Allow a CLI-owned background file handle to close before cleanup."""

    def cleanup(self):
        deadline = time.monotonic() + 10
        while True:
            try:
                super().cleanup()
                return
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                QTest.qWait(100)


def _token(identity):
    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

    return ".".join(
        (
            encode({"alg": "none"}),
            encode(
                {
                    "email": identity + "@example.invalid",
                    "exp": int(time.time()) + 3600,
                    "https://api.openai.com/auth": {
                        "chatgpt_account_id": identity,
                        "chatgpt_plan_type": "plus",
                    },
                }
            ),
            "synthetic",
        )
    )


def _write_auth(root, identity):
    token = _token(identity)
    (root / "auth.json").write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "OPENAI_API_KEY": None,
                "tokens": {
                    "id_token": token,
                    "access_token": token,
                    "refresh_token": "synthetic",
                    "account_id": identity,
                },
                "last_refresh": datetime.now(timezone.utc).isoformat(),
            }
        ),
        encoding="utf-8",
    )


def _wait(predicate):
    deadline = time.monotonic() + 20
    while not predicate():
        if time.monotonic() >= deadline:
            raise TimeoutError("Isolated account check did not complete")
        QTest.qWait(20)


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    program = find_codex_program()
    if not program:
        raise RuntimeError("Codex CLI is required for this optional transport check")
    with SettledTemporaryDirectory(prefix="pet-account-switch-") as directory:
        root = Path(directory)
        (root / "config.toml").write_text(
            'cli_auth_credentials_store = "file"\n', encoding="utf-8"
        )

        def process_factory(parent):
            process = QProcess(parent)
            environment = QProcessEnvironment.systemEnvironment()
            environment.insert("CODEX_HOME", str(root))
            for name in ("CODEX_ACCESS_TOKEN", "OPENAI_API_KEY", "CODEX_API_KEY"):
                environment.remove(name)
            process.setProcessEnvironment(environment)
            return process

        class OfflineClient(CodexAppServerClient):
            def __init__(self, parent=None):
                super().__init__(
                    parent, program=program, process_factory=process_factory
                )

            def request(self, method, params=None, timeout_ms=10_000):
                if method == "account/rateLimits/read":
                    rid = 1_000_000
                    QTimer.singleShot(
                        0,
                        lambda: self.response_received.emit(
                            rid, method, params, {}, None
                        ),
                    )
                    return rid
                return super().request(method, params, timeout_ms)

        _write_auth(root, "alice")
        cached = OfflineClient()
        responses = []
        cached.response_received.connect(
            lambda rid, method, params, result, error: responses.append(
                (method, result)
            )
        )
        try:
            cached.start()
            _wait(lambda: cached.ready)

            def read_email():
                responses.clear()
                cached.request("account/read", {"refreshToken": False})
                _wait(lambda: any(method == "account/read" for method, _ in responses))
                response = next(
                    result for method, result in responses if method == "account/read"
                )
                return response["account"]["email"]

            assert read_email() == "alice@example.invalid"
            _write_auth(root, "bob")
            assert read_email() == "alice@example.invalid", (
                "Installed CLI caching behavior changed; re-evaluate monitor necessity"
            )
            print("PASS: running App Server retains old synthetic identity")
        finally:
            cached.close()

        _write_auth(root, "alice")
        monitor = AccountMonitor(OfflineClient, auth_path=root / "auth.json")
        checks = []
        monitor.checked.connect(checks.append)
        try:
            monitor.start()
            _wait(lambda: len(checks) == 1)
            assert checks[-1].email_label == "a***@example.invalid"
            _write_auth(root, "bob")
            monitor.poll_file()
            _wait(lambda: len(checks) == 2)
            assert checks[-1].email_label == "b***@example.invalid"
            print("PASS: fresh-process monitor detects synthetic A -> B")
            (root / "auth.json").unlink()
            monitor.poll_file()
            _wait(lambda: len(checks) == 3)
            assert checks[-1].state == "signed_out"
            print("PASS: fresh-process monitor detects removed credentials")
        finally:
            monitor.close()
            app.processEvents()


if __name__ == "__main__":
    main()
