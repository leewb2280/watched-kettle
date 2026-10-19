"""Account-scoped project cache and bounded, read-only display metadata queries."""

import sqlite3
from dataclasses import dataclass, field
from time import monotonic

from PySide6.QtCore import QObject, QTimer, Signal

from watched_kettle.localization import t
from watched_kettle.features.project_activity.metadata import (
    _read_desktop_project_index,
    _normalized_project_path,
)
from watched_kettle.features.project_activity.service import (
    conversation_title,
    safe_label,
)
from watched_kettle.integrations.codex_paths import codex_home
from watched_kettle.usage.conversation_models import ThreadProjectRelation
from watched_kettle.usage.identifiers import hash_identifier


REFRESH_SECONDS = 300
MAX_THREAD_PAGES = 100
MAX_PROJECTS = 1000


@dataclass
class _DiscoveryPage:
    cursor: str | None = None
    done: bool = False
    cursors: set[str] = field(default_factory=set)


class UsageConversationCatalog(QObject):
    changed = Signal()

    def __init__(self, service):
        super().__init__(service)
        self.service = service
        self.client = service.client
        self.client.response_received.connect(self.response)
        self.clock = monotonic
        self.desktop_path = codex_home() / ".codex-global-state.json"
        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.tick)
        self.clear()

    def clear(self):
        self.timer.stop()
        self.scope = None
        self.pending = {}
        self.projects = {}
        self.assignments, self.projectless, self.desktop_projects, self.roots = (
            {},
            set(),
            {},
            {},
        )
        self.retained = set()
        self.known = {}
        self.rows = {}
        self.due = {}
        self.failures = {}
        self.retries = {}
        self.desktop_stamp = 0
        self.relation_versions = {}
        self.file_stamp = None
        self.desktop_read = False
        self.project_due = 0.0
        self.project_cursor = None
        self.project_cursors = set()
        self.project_cycle = False
        self.project_failed = False
        self.project_pages = 0
        self.read_supported = True
        self.listed = set()
        self.fallback_due = 0.0
        self.limited = False
        self.discovery = {archived: _DiscoveryPage() for archived in (False, True)}
        self.next_archived = False
        self.pages = 0
        self.status = ""

    def valid(self):
        return bool(
            self.scope
            and self.service.enabled
            and not self.service.snapshot.account_checking
            and self.scope
            == (self.service.snapshot.account_hash, self.service.account.generation)
        )

    def start(self, force=False):
        scope = (self.service.snapshot.account_hash, self.service.account.generation)
        if (
            not scope[0]
            or self.service.snapshot.account_checking
            or not self.service.enabled
        ):
            return
        if scope != self.scope:
            self.clear()
            self.scope = scope
        self.sync_retained()
        self.refresh_desktop()
        if force:
            active = {p[1].get("threadId") for p in self.pending.values()}
            for raw in self.known.values():
                if raw not in active:
                    self.due[raw] = 0
                    self.retries.pop(raw, None)
            if not any(p[0] == "project/list" for p in self.pending.values()):
                self.project_due = 0
                self.retries.pop("project/list", None)
            if (
                not any(p[0] == "thread/list" for p in self.pending.values())
                and self.retained - self.known.keys()
            ):
                self.discovery = {
                    archived: _DiscoveryPage() for archived in (False, True)
                }
                self.pages = 0
                for archived in (False, True):
                    self.retries.pop("list:" + str(archived), None)
            if not self.read_supported and not any(
                p[0] == "thread/list" for p in self.pending.values()
            ):
                self.listed.clear()
                self.discovery = {
                    archived: _DiscoveryPage() for archived in (False, True)
                }
                self.pages = 0
                self.limited = False
                self.fallback_due = self.clock() + REFRESH_SECONDS
        self.timer.start()
        self.pump()

    def sync_retained(self):
        if self.scope is None:
            return
        try:
            self.service.repository.load_thread_projects(self.scope[0])
            retained = set(self.service.repository.retained_threads(self.scope[0]))
        except (OSError, sqlite3.DatabaseError) as error:
            self.service._storage_failed(error)
            return
        added = retained - self.retained
        self.retained = retained
        for thread, raw in tuple(self.known.items()):
            if thread not in retained:
                self.known.pop(thread, None)
                self.rows.pop(raw, None)
                self.due.pop(raw, None)
                self.retries.pop(raw, None)
                self.failures.pop(raw, None)
                self.relation_versions.pop(raw, None)
        local_rows = []
        if added:
            for raw in self.assignments.keys() | self.projectless:
                if hash_identifier(raw) in added:
                    self.known[hash_identifier(raw)] = raw
                    self.due.setdefault(raw, 0)
                    local_rows.append({"id": raw})
        self.apply_rows(local_rows, local=True)
        if (
            added
            and self.pages
            and all(state.done for state in self.discovery.values())
        ):
            self.discovery = {archived: _DiscoveryPage() for archived in (False, True)}
            self.pages = 0

    def observe(self, raw):
        """Remember a known ID from this usage service, never from bubble state."""
        scope = (self.service.snapshot.account_hash, self.service.account.generation)
        if (
            not scope[0]
            or self.service.snapshot.account_checking
            or not self.service.enabled
            or not isinstance(raw, str)
            or not raw
        ):
            return
        if scope != self.scope:
            self.clear()
            self.scope = scope
        self.sync_retained()
        thread = hash_identifier(raw)
        if thread in self.retained:
            self.known = {thread: raw, **self.known}
            self.due.setdefault(raw, 0)
            if self.service._conversation_mode:
                self.timer.start()
                self.refresh_desktop()
                self.pump()

    def tick(self):
        if not self.valid():
            return
        self.sync_retained()
        self.refresh_desktop()
        self.pump()

    def refresh_desktop(self):
        if self.scope is None:
            return
        try:
            stat = self.desktop_path.stat()
            stamp = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            stamp = None
        if self.desktop_read and stamp == self.file_stamp:
            return
        changed = self.desktop_read
        self.desktop_read = True
        self.file_stamp = stamp
        index = _read_desktop_project_index(self.desktop_path)
        if changed and index == (
            self.assignments,
            self.projectless,
            self.desktop_projects,
            self.roots,
        ):
            return
        self.desktop_stamp += 1
        previous_assignments = self.assignments
        previous_projectless = self.projectless
        previous_roots = self.roots
        self.assignments, self.projectless, self.desktop_projects, self.roots = index
        names = {
            "project:" + hash_identifier(raw): name
            for raw, name in self.desktop_projects.items()
        }
        if self.service.repository.set_project_names(self.scope[0], names):
            self.changed.emit()
        for raw in self.assignments.keys() | self.projectless:
            if hash_identifier(raw) in self.retained:
                self.known[hash_identifier(raw)] = raw
                self.due.setdefault(raw, 0)
        updates = []
        for raw in tuple(self.known.values()):
            row = dict(self.rows.get(raw, {}), id=raw)
            affected = changed and (
                previous_assignments.get(raw) != self.assignments.get(raw)
                or (raw in previous_projectless) != (raw in self.projectless)
                or (previous_roots != self.roots and bool(row.get("cwd")))
            )
            if affected:
                # A previous API assignment must not mask a later desktop move.
                row.pop("projectId", None)
                self.relation_versions[raw] = self.desktop_stamp
                self.due[raw] = 0
                self.retries.pop(raw, None)
            updates.append(row)
        self.apply_rows(updates, local=True)

    def resolve(self, row):
        raw = row["id"]
        project = row.get("projectId")
        if isinstance(project, str):
            return project, "api"
        if raw in self.assignments:
            return self.assignments[raw], "desktop_assignment"
        if raw in self.projectless:
            return "", "explicit_projectless"
        cwd = _normalized_project_path(row.get("cwd"))
        matches = [
            root
            for root in self.roots
            if cwd == root or cwd.startswith(root.rstrip("\\") + "\\")
        ]
        if matches:
            owners = self.roots[max(matches, key=len)]
            if len(owners) == 1:
                return next(iter(owners)), "cwd_match"
        return None, "unresolved"

    def apply_rows(self, rows, local=False):
        if self.scope is None:
            return
        rows = [
            row
            for row in rows
            if isinstance(row.get("id"), str)
            and hash_identifier(row["id"]) in self.retained
        ]
        if not rows:
            return
        account = self.scope[0]
        try:
            relations = self.service.repository.load_thread_projects(account)
        except (OSError, sqlite3.DatabaseError) as error:
            self.service._storage_failed(error)
            relations = {}
        updates: dict[str, ThreadProjectRelation] = {}
        labels = {}
        for row in rows:
            raw = row["id"]
            thread = hash_identifier(raw)
            self.known[thread] = raw
            previous = self.rows.get(raw, {})
            # Never retain preview, turns or message bodies.
            clean = {"id": raw}
            if isinstance(row.get("name"), str):
                clean["name"] = conversation_title(row["name"])[:512]
            if isinstance(row.get("cwd"), str) and len(row["cwd"]) <= 32767:
                clean["cwd"] = _normalized_project_path(row["cwd"])
            if isinstance(row.get("projectId"), str):
                clean["projectId"] = row["projectId"]
            if "name" not in clean and "name" in previous:
                clean["name"] = previous["name"]
            self.rows[raw] = clean
            project, evidence = self.resolve(clean)
            saved = updates.get(thread, relations.get(thread))
            key = (
                "none"
                if project == ""
                else "project:" + hash_identifier(project)
                if project is not None
                else saved.project_key
                if saved
                else "unknown"
            )
            if project is not None and (
                not local
                or saved is None
                or (saved.project_key, saved.evidence) != (key, evidence)
            ):
                updates[thread] = ThreadProjectRelation(
                    key, evidence, self.service._now()
                )
            raw_name = clean.get("name")
            title = (
                raw_name
                if isinstance(raw_name, str) and raw_name.strip()
                else t("message.0349", value0=thread[:8])
            )
            name = (
                t("message.0352")
                if key == "none"
                else t("message.0350")
                if key == "unknown"
                else self.projects.get(project)
                or self.desktop_projects.get(project)
                or t("message.0353")
            )
            labels[thread] = (title, key, name)
        if updates:
            try:
                self.service.repository.save_thread_projects(account, updates)
            except (OSError, sqlite3.DatabaseError) as error:
                self.service._storage_failed(error)
        if self.service.repository.set_thread_labels(account, labels):
            self.changed.emit()

    def request(self, method, params):
        rid = self.client.request(method, params, timeout_ms=10000)
        if rid is None:
            self.failed(method, params)
            return
        self.pending[rid] = (
            method,
            params,
            self.scope,
            self.clock(),
            self.desktop_stamp,
        )
        self.set_status(t("message.0347"))

    def failed(self, method, params):
        key = (
            params.get("threadId")
            if method == "thread/read"
            else "list:" + str(bool(params.get("archived")))
            if method == "thread/list"
            else "project/list"
        )
        count = min(5, self.failures.get(key, 0) + 1)
        self.failures[key] = count
        self.retries[key] = self.clock() + min(300, 30 * 2 ** (count - 1))
        self.set_status(t("message.0348"))

    def timeout(self):
        for rid, (method, params, _, started, _) in tuple(self.pending.items()):
            if self.clock() - started >= 10:
                self.pending.pop(rid)
                self.failed(method, params)

    def pump(self):
        if not self.valid() or not self.client.ready:
            return
        self.timeout()
        now = self.clock()
        if (
            not self.read_supported
            and now >= self.fallback_due
            and not any(p[0] == "thread/list" for p in self.pending.values())
        ):
            self.listed.clear()
            self.discovery = {archived: _DiscoveryPage() for archived in (False, True)}
            self.pages = 0
            self.fallback_due = now + REFRESH_SECONDS
        methods = [p[0] for p in self.pending.values()]
        active = {
            p[1].get("threadId") for p in self.pending.values() if p[0] == "thread/read"
        }
        for raw in self.known.values() if self.read_supported else ():
            if len(active) >= 2:
                break
            if raw not in active and now >= max(
                self.due.get(raw, 0), self.retries.get(raw, 0)
            ):
                self.request("thread/read", {"threadId": raw, "includeTurns": False})
                active.add(raw)
        if (
            self.retained
            and "project/list" not in methods
            and now >= max(self.project_due, self.retries.get("project/list", 0))
        ):
            if not self.project_cycle:
                self.project_cycle = True
                self.project_cursor = None
                self.project_cursors.clear()
                self.project_pages = 0
            self.request(
                "project/list",
                {"cursor": self.project_cursor} if self.project_cursor else {},
            )
        missing = self.retained - (
            self.known.keys() if self.read_supported else self.listed
        )
        if missing and "thread/list" not in methods and self.pages < MAX_THREAD_PAGES:
            for archived in (self.next_archived, not self.next_archived):
                page = self.discovery[archived]
                if not page.done and now >= self.retries.get(
                    "list:" + str(archived), 0
                ):
                    params = dict(
                        limit=100,
                        archived=archived,
                        sortKey="updated_at",
                        sortDirection="desc",
                    )
                    if page.cursor:
                        params["cursor"] = page.cursor
                    self.request("thread/list", params)
                    self.next_archived = not archived
                    break
        if not self.pending:
            if self.limited or (missing and self.pages >= MAX_THREAD_PAGES):
                self.set_status(t("message.0351"))
            elif missing and all(state.done for state in self.discovery.values()):
                self.set_status(t("message.0348"))
            elif not self.retries and not self.project_failed:
                self.set_status(t("message.0354"))
            else:
                self.set_status(t("message.0348"))

    def set_status(self, status):
        if status != self.status:
            self.status = status
            self.changed.emit()

    def response(self, rid, method, params, result, error):
        request = self.pending.pop(rid, None)
        if request is None or not self.valid() or request[2] != self.scope:
            return
        requested, params, _, _, desktop_stamp = request
        self.sync_retained()
        self.refresh_desktop()
        if self.clock() - request[3] >= 10:
            self.failed(requested, params)
            return
        if error or not isinstance(result, dict):
            if (
                requested == "thread/read"
                and isinstance(error, dict)
                and error.get("code") in (-32601, "unsupported", "method_not_found")
            ):
                self.read_supported = False
            if requested == "project/list":
                self.project_failed = True
                if isinstance(error, dict) and error.get("code") in (
                    -32601,
                    "unsupported",
                    "method_not_found",
                ):
                    self.project_cycle = False
                    self.project_due = self.clock() + REFRESH_SECONDS
            self.failed(requested, params)
            self.pump()
            return
        if requested == "thread/read":
            row = result.get("thread")
            if not isinstance(row, dict) or row.get("id") != params["threadId"]:
                self.failed(requested, params)
            elif self.relation_versions.get(params["threadId"], 0) > desktop_stamp:
                self.due[params["threadId"]] = 0
            else:
                self.apply_rows([row])
                raw = params["threadId"]
                self.due[raw] = self.clock() + REFRESH_SECONDS
                self.retries.pop(raw, None)
                self.failures.pop(raw, None)
        else:
            self.list_response(requested, params, result, desktop_stamp)
        self.pump()

    def list_response(self, method, params, result, desktop_stamp=None):
        if self.scope is None:
            return
        rows = result.get("data", result.get("projects", []))
        if not isinstance(rows, list) or len(rows) > (
            MAX_PROJECTS if method == "project/list" else 100
        ):
            self.failed(method, params)
            return
        cursor = result.get("nextCursor")
        if cursor is not None and (not isinstance(cursor, str) or not cursor):
            self.failed(method, params)
            return
        if method == "project/list":
            self.project_pages += 1
            for row in rows:
                if (
                    isinstance(row, dict)
                    and isinstance(row.get("id"), str)
                    and row["id"]
                ):
                    if (
                        len(self.projects) >= MAX_PROJECTS
                        and row["id"] not in self.projects
                    ):
                        break
                    self.projects[row["id"]] = safe_label(
                        row.get("name"), t("message.0353")
                    )
            names = {
                "project:" + hash_identifier(raw): name
                for raw, name in self.projects.items()
            }
            if self.service.repository.set_project_names(self.scope[0], names):
                self.changed.emit()
            if cursor and (
                cursor in self.project_cursors
                or len(self.projects) >= MAX_PROJECTS
                or self.project_pages >= MAX_THREAD_PAGES
            ):
                self.project_due = self.clock() + REFRESH_SECONDS
                self.project_cycle = False
                self.limited = True
                self.set_status(t("message.0351"))
                return
            self.retries.pop("project/list", None)
            self.failures.pop("project/list", None)
            self.project_failed = False
            self.project_cursor = cursor
            if cursor:
                self.project_cursors.add(cursor)
            else:
                self.project_cycle = False
                self.project_due = self.clock() + REFRESH_SECONDS
        else:
            archived = bool(params.get("archived"))
            state = self.discovery[archived]
            if cursor and cursor in state.cursors:
                state.done = True
                self.failed(method, params)
                return
            self.pages += 1
            updates = []
            for row in rows:
                if isinstance(row, dict):
                    raw_id = row.get("id")
                    if isinstance(raw_id, str) and self.relation_versions.get(
                        raw_id, 0
                    ) > (desktop_stamp or 0):
                        row = dict(row)
                        row.pop("projectId", None)
                    updates.append(row)
                    raw = row.get("id")
                    if isinstance(raw, str) and hash_identifier(raw) in self.retained:
                        self.listed.add(hash_identifier(raw))
                        self.retries.pop(raw, None)
                        self.failures.pop(raw, None)
                        self.due[raw] = self.clock() + REFRESH_SECONDS
            self.apply_rows(updates)
            state.cursor, state.done = cursor, not cursor
            if cursor:
                state.cursors.add(cursor)
            key = "list:" + str(archived)
            self.retries.pop(key, None)
            self.failures.pop(key, None)
