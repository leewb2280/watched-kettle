"""Explicit local execution targets and redacted transport diagnostics."""

from dataclasses import dataclass
import os
from pathlib import Path
import re


@dataclass(frozen=True)
class ConnectionTarget:
    program: str
    endpoint: str
    transport: str = "local_proxy"
    cli_version: str = ""

    @property
    def arguments(self):
        return ("app-server", "proxy", "--sock", self.endpoint)

    @property
    def exists(self):
        return Path(self.endpoint).exists()


@dataclass(frozen=True)
class ConnectionStatus:
    phase: str = "idle"
    code: str = ""
    exit_code: int | None = None
    os_error: int | None = None


CONNECTION_LABELS = {
    "endpoint_missing": "Codex 앱의 공유 연결 주소가 없습니다. 현재 앱의 연결 방식 확인이 필요합니다.",
    "socket_unavailable": "Codex 공유 연결 소켓을 사용할 수 없습니다.",
    "access_denied": "Codex 공유 연결에 접근할 수 없습니다.",
    "process_start_failed": "Codex 연결 프로그램을 시작하지 못했습니다.",
    "process_exited": "Codex 연결 프로그램이 종료되었습니다.",
    "initialization_failed": "Codex 공유 연결 초기화에 실패했습니다.",
    "initialization_timeout": "Codex 공유 연결 초기화 응답이 없습니다.",
    "closed": "Codex 공유 연결이 종료되었습니다.",
}


def connection_target(program, *, endpoint=None, home=None):
    root = Path(home or os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    path = (
        Path(endpoint)
        if endpoint
        else root / "app-server-control/app-server-control.sock"
    )
    if not path.is_absolute():
        raise ValueError("absolute_connection_endpoint_required")
    return ConnectionTarget(str(program or ""), str(path))


def transport_failure(data: bytes, *, endpoint_exists=True):
    """Classify a bounded stderr tail; never return command text or credentials."""
    message = data[-8192:].decode("utf-8", "replace").lower()
    match = re.search(r"os error (\d+)", message)
    number = int(match[1]) if match else None
    if "failed to connect" not in message and number is None:
        return None
    code = (
        "endpoint_missing"
        if not endpoint_exists
        else "access_denied"
        if number in {5, 13, 10013}
        else "socket_unavailable"
    )
    return ConnectionStatus("transport", code, os_error=number)
