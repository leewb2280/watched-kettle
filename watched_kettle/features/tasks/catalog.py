"""Bounded paginated project/thread catalog, independent of active bubbles."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from watched_kettle.features.tasks.models import source_version
from watched_kettle.features.tasks.history import HistoryReader


class ConversationCatalog(QObject):
    changed = Signal()
    thread_read = Signal(object)
    account_changed = Signal(object)
    failed = Signal(str)

    def __init__(self, client, parent=None):
        super().__init__(parent)
        self.client = client
        self.projects = {}
        self.threads = {}
        self.pending = {}
        self.cursors = set()
        self.generation = 0
        self.account = None
        self.enabled = False
        self.stale = True
        self.status = "읽기 기능 꺼짐"
        self._staging = {}
        self._complete = set()
        self.excluded_projects = set()
        self.archived = False
        self.reader = HistoryReader(client, self)
        self.reader.completed.connect(self.thread_read)
        self.account_changed.connect(lambda _account: self.reader.cancel())
        client.ready_changed.connect(self.ready)
        client.response_received.connect(self.response)
        client.notification_received.connect(self.notification)

    def enable(self, enabled: bool):
        self.enabled = enabled
        if enabled:
            if self.client.ready:
                self.refresh()
            else:
                self.status = "Codex 연결 중"
                self.client.start()
        else:
            self.generation += 1
            self.pending.clear()
            self.projects.clear()
            self.threads.clear()
            self._staging.clear()
            self.account = None
            self.status = "읽기 기능 꺼짐"
            self.account_changed.emit(None)
            self.client.close()
        self.changed.emit()

    def ready(self, ready: bool):
        self.generation += 1
        self.pending.clear()
        self.stale = True
        if ready and self.enabled:
            self.refresh()
        elif self.enabled:
            self.status = "연결 끊김 — 이전 목록"
            self.account = None
            self.account_changed.emit(None)
            self.changed.emit()

    def notification(self, method, _params):
        if method in {"account/updated", "account/login/completed"}:
            self.projects.clear()
            self.threads.clear()
            self.account = None
            self.account_changed.emit(None)
            self.refresh()

    def request(self, method: str, params: dict):
        rid = self.client.request(method, params)
        if rid is None:
            self._fail("request_unavailable")
        else:
            self.pending[rid] = (self.generation, method)

    def refresh(self):
        if not self.enabled or not self.client.ready:
            return
        self.generation += 1
        self.pending.clear()
        self.cursors.clear()
        self._staging = {"project/list": {}, "thread/list": {}}
        self._complete.clear()
        self.stale = True
        self.status = "계정 확인 중"
        self.request("account/read", {})
        self.changed.emit()

    def read_thread(self, identity: str):
        thread = self.threads.get(identity)
        if (
            not self.enabled
            or not self.account
            or not thread
            or (thread.get("projectId") or "") in self.excluded_projects
        ):
            self._fail("thread_read_unavailable")
            return
        if not self.reader.identity:
            self.reader.start(identity)

    def _fail(self, reason: str):
        self.stale = True
        self.status = "조회 실패 — 이전 목록 유지"
        self.failed.emit(reason)
        self.changed.emit()

    def response(self, rid, method, params, result, error):
        pending = self.pending.pop(rid, None)
        if pending is None or pending[0] != self.generation:
            return
        if error or not isinstance(result, dict):
            self._fail("catalog_read_failed")
            return
        if method == "account/read":
            previous_account = self.account
            account = result.get("account")
            if not isinstance(account, dict):
                self.account = None
            else:
                self.account = account.get("accountId") or account.get("id")
                # Match the established account identity contract, without displaying it.
                if not self.account:
                    self.account = account.get("email")
                if not isinstance(self.account, str) or len(self.account) > 512:
                    self.account = None
            if previous_account != self.account:
                self.projects.clear()
                self.threads.clear()
            if previous_account != self.account:
                self.account_changed.emit(self.account)
            if not self.account:
                self.projects.clear()
                self.threads.clear()
                self.status = "로그인 계정을 확인할 수 없습니다"
                self.changed.emit()
                return
            self.status = "프로젝트와 대화 목록 읽는 중"
            self.request("project/list", {})
            self.request(
                "thread/list",
                {
                    "limit": 100,
                    "archived": self.archived,
                    "sortKey": "updated_at",
                    "sortDirection": "desc",
                },
            )
        elif method in {"project/list", "thread/list"}:
            rows = result.get("data")
            if not isinstance(rows, list) or len(rows) > 10_000:
                self._fail("catalog_schema_changed")
                return
            staging = self._staging[method]
            for row in rows:
                if isinstance(row, dict) and isinstance(row.get("id"), str):
                    # Never retain source previews or raw turn bodies in the catalog.
                    fields = (
                        ("id", "name", "roots")
                        if method == "project/list"
                        else (
                            "id",
                            "name",
                            "projectId",
                            "cwd",
                            "parentThreadId",
                            "updatedAt",
                            "status",
                            "canAcceptDirectInput",
                        )
                    )
                    staging[row["id"]] = {key: row.get(key) for key in fields}
                    if method == "thread/list":
                        staging[row["id"]]["status"] = (
                            row.get("status")
                            if isinstance(row.get("status"), dict)
                            else {}
                        )
                        staging[row["id"]]["updatedAt"] = (
                            row.get("updatedAt")
                            if isinstance(row.get("updatedAt"), (float, int))
                            else 0
                        )
            if len(staging) > 10_000:
                self._fail("catalog_pagination_limit")
                return
            cursor = result.get("nextCursor")
            if cursor:
                marker = (method, str(cursor))
                if (
                    marker in self.cursors
                    or len(self.cursors) >= 200
                    or not isinstance(cursor, str)
                ):
                    self._fail("catalog_pagination_limit")
                    return
                self.cursors.add(marker)
                next_params = dict(params)
                next_params["cursor"] = cursor
                self.request(method, next_params)
            else:
                self._complete.add(method)
            if len(self._complete) == 2:
                self.projects = self._staging["project/list"]
                self.threads = self._staging["thread/list"]
                self.stale = False
                self.status = (
                    f"프로젝트 {len(self.projects)}개 · 대화 {len(self.threads)}개"
                )
            self.changed.emit()
        elif method == "thread/read":
            thread = result.get("thread")
            if not isinstance(thread, dict) or thread.get("id") != params.get(
                "threadId"
            ):
                self._fail("thread_identity_changed")
                return
            if (thread.get("projectId") or "") in self.excluded_projects:
                return
            if not isinstance(thread.get("turns"), list) or any(
                not isinstance(t, dict) for t in thread["turns"]
            ):
                self._fail("thread_schema_changed")
                return
            thread["sourceVersion"] = source_version(thread.get("turns", []))
            self.thread_read.emit(thread)
