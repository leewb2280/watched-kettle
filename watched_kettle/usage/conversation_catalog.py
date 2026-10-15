"""Read-only, generation-scoped display names on the usage worker thread."""

from time import monotonic

from PySide6.QtCore import QObject, QTimer, Signal

from watched_kettle.features.project_activity.metadata import (
    _read_desktop_project_index,
    _normalized_project_path,
)
from watched_kettle.features.project_activity.service import (
    conversation_title,
    safe_label,
)
from watched_kettle.integrations.codex_paths import codex_home
from watched_kettle.usage.identifiers import hash_identifier


class UsageConversationCatalog(QObject):
    changed = Signal()

    def __init__(self, service):
        super().__init__(service)
        self.service = service
        self.client = service.client
        self.client.response_received.connect(self.response)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(35000)
        self.timer.timeout.connect(self.timeout)
        self.clear()

    def clear(self):
        self.timer.stop()
        self.scope = None
        self.pending = {}
        self.cursors = set()
        self.projects = {}
        self.assignments, self.projectless, self.desktop_projects, self.roots = (
            {},
            set(),
            {},
            {},
        )
        self.pages = 0
        self.last_started = 0.0
        self.status = ""

    def start(self, force=False):
        scope = (self.service.snapshot.account_hash, self.service.account.generation)
        if not scope[0] or not self.client.ready:
            return
        if scope == self.scope and (
            self.pending or (not force and monotonic() - self.last_started < 60)
        ):
            return
        self.clear()
        self.scope = scope
        self.last_started = monotonic()
        self.assignments, self.projectless, self.desktop_projects, self.roots = (
            _read_desktop_project_index(codex_home() / ".codex-global-state.json")
        )
        self.status = "대화 제목·프로젝트 확인 중"
        self.request("project/list", {})

    def request(self, method, params):
        rid = self.client.request(method, params, timeout_ms=30000)
        if rid is None:
            self.timeout()
            return
        self.pending[rid] = (method, params, self.scope)
        self.timer.start()

    def timeout(self):
        self.pending.clear()
        self.status = "일부 이름 확인 불가 · 기록은 계속 표시합니다"
        self.changed.emit()

    def thread_request(self, archived=False, cursor=None):
        params = dict(
            limit=100, archived=archived, sortKey="updated_at", sortDirection="desc"
        )
        if cursor:
            params["cursor"] = cursor
        self.request("thread/list", params)

    def label(self, row):
        raw_id = row["id"]
        project = row.get("projectId")
        if not isinstance(project, str):
            project = self.assignments.get(raw_id)
        if project is None and raw_id in self.projectless:
            project = ""
        if project is None:
            cwd = _normalized_project_path(row.get("cwd"))
            matches = [
                root
                for root in self.roots
                if cwd == root or cwd.startswith(root.rstrip("\\") + "\\")
            ]
            if matches:
                owners = self.roots[max(matches, key=len)]
                project = next(iter(owners)) if len(owners) == 1 else None
        thread = hash_identifier(raw_id)
        raw_name = row.get("name")
        title = (
            conversation_title(raw_name)[:512]
            if isinstance(raw_name, str) and raw_name.strip()
            else f"제목 확인 불가 · {thread[:8]}"
        )
        key = (
            "unknown"
            if project is None
            else "none"
            if project == ""
            else "project:" + hash_identifier(project)
        )
        name = (
            "프로젝트 확인 불가"
            if project is None
            else "프로젝트 없음"
            if project == ""
            else self.projects.get(project)
            or self.desktop_projects.get(project)
            or "프로젝트 이름 확인 불가"
        )
        return thread, (title, key, name)

    def response(self, rid, method, params, result, error):
        request = self.pending.pop(rid, None)
        if request is None:
            return
        self.timer.stop()
        requested, params, scope = request
        if (
            scope
            != (self.service.snapshot.account_hash, self.service.account.generation)
            or scope != self.scope
        ):
            return
        if error or not isinstance(result, dict):
            if requested == "project/list":
                self.thread_request()
            else:
                self.timeout()
            return
        rows = result.get("data", result.get("projects", []))
        if not isinstance(rows, list) or len(rows) > (
            1000 if requested == "project/list" else 100
        ):
            self.timeout()
            return
        self.pages += 1
        if requested == "project/list":
            for row in rows:
                if isinstance(row, dict) and isinstance(row.get("id"), str):
                    self.projects[row["id"]] = safe_label(
                        row.get("name"), "프로젝트 이름 확인 불가"
                    )
        else:
            labels = {}
            for row in rows:
                if (
                    isinstance(row, dict)
                    and isinstance(row.get("id"), str)
                    and row["id"]
                ):
                    thread, label = self.label(row)
                    labels[thread] = label
            if self.service.repository.set_thread_labels(scope[0], labels):
                self.changed.emit()
        cursor = result.get("nextCursor")
        marker = (requested, bool(params.get("archived")), cursor)
        if cursor and (
            not isinstance(cursor, str)
            or self.pages >= 100
            or (requested == "project/list" and len(self.projects) >= 1000)
        ):
            self.status = "이름 조회 범위 초과 · 확인된 이름만 표시합니다"
            self.changed.emit()
            return
        if cursor:
            if marker in self.cursors:
                self.timeout()
                return
            self.cursors.add(marker)
            self.request(requested, dict(params, cursor=cursor))
        elif requested == "project/list":
            self.thread_request()
        elif not params.get("archived"):
            self.thread_request(archived=True)
        else:
            self.status = "이 기기 로그 기준 · 제목은 Codex에서 확인"
            self.changed.emit()
