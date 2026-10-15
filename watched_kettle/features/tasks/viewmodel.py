"""Stable selection, project pages and contextual actions for the task views."""

from PySide6.QtCore import QObject, Signal

from watched_kettle.features.tasks.presentation import item_spec


class TasksViewModel(QObject):
    changed = Signal()

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.state = {}
        self.project = None
        self.page = 0
        self.thread_id = ""
        self.task_ids = []
        self.filter = "all"
        self.show_reported = False
        self._browse_context = None
        service.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        state = self.service.state
        if state.get("epoch") != self.state.get("epoch"):
            self.thread_id = ""
            self.task_ids = []
            self._browse_context = None
        self.state = state
        projects = {p["id"] for p in state.get("projects", ())} | {""}
        selected_thread = next(
            (t for t in state.get("threads", ()) if t["id"] == self.thread_id), None
        )
        if selected_thread and (selected_thread.get("projectId") or "") in projects:
            self.project = selected_thread.get("projectId") or ""
        if self.project is None or self.project not in projects:
            self.project = next((p["id"] for p in state.get("projects", ())), "")
            self.page = 0
        self.page = min(self.page, max(0, (len(self.project_threads()) - 1) // 10))
        for index, thread in enumerate(self.project_threads()):
            if thread["id"] == self.thread_id:
                self.page = index // 10
                break
        if self.thread_id not in {t["id"] for t in self.thread_rows()}:
            self.thread_id = ""
        existing = {i["id"] for i in state.get("items", ())}
        self.task_ids = [i for i in self.task_ids if i in existing]
        self.changed.emit()
        self.browse()

    def project_threads(self):
        return sorted(
            (
                t
                for t in self.state.get("threads", ())
                if not t.get("parentThreadId")
                and (t.get("projectId") or "") == self.project
            ),
            key=lambda t: (t.get("updatedAt") or 0, t["id"]),
            reverse=True,
        )

    def thread_rows(self):
        return self.project_threads()[self.page * 10 : (self.page + 1) * 10]

    def browse(self):
        history = (
            tuple(t["id"] for t in self.thread_rows())
            if self.page or self.state.get("archived")
            else ()
        )
        context = (self.project, history)
        if context != self._browse_context:
            self._browse_context = context
            self.service.send("browse", {"project": self.project, "history": history})

    def set_project(self, identity):
        if identity != self.project:
            self.project, self.page, self.thread_id = identity, 0, ""
            self.changed.emit()
            self.browse()

    def set_page(self, page):
        self.page = max(0, min(page, max(0, (len(self.project_threads()) - 1) // 10)))
        self.thread_id = ""
        self.changed.emit()
        self.browse()

    def select_thread(self, identity):
        self.thread_id = identity
        self.changed.emit()
        if (
            identity
            and identity not in self.state.get("versions", {})
            and self.project not in self.state.get("excluded_projects", ())
        ):
            self.service.send("read", identity)

    def candidate_rows(self):
        return [
            c
            for c in self.state.get("candidates", ())
            if c["spec"]["thread_id"] == self.thread_id
            and not c.get("task_id")
            and (self.show_reported or not c.get("reported_complete"))
        ]

    def task_rows(self):
        filters = {
            "draft": {"draft"},
            "queued": {"queued"},
            "running": {"starting", "running", "reconciling"},
            "attention": {"needs_review", "failed", "stopped"},
            "complete": {"complete"},
        }
        return [
            i
            for i in self.state.get("items", ())
            if i.get("reason") != "dismissed_by_user"
            and (self.filter == "all" or i["state"] in filters.get(self.filter, set()))
        ]

    def select_tasks(self, identities):
        existing = {i["id"] for i in self.task_rows()}
        self.task_ids = [i for i in identities if i in existing]

    def task(self):
        return next(
            (
                i
                for i in self.task_rows()
                if self.task_ids and i["id"] == self.task_ids[0]
            ),
            None,
        )

    def actions(self):
        row = self.task()
        if row is None:
            return set()
        actions = {"open"} if item_spec(row).get("thread_id") else set()
        state = row["state"]
        if row.get("spec") and state in {"draft", "queued"} and not row.get("batch_id"):
            actions.update({"review", "remove", "compare"})
            if state == "queued":
                actions.update({"up", "down"})
        if state == "queued" and row.get("batch_id"):
            actions.add("withdraw_batch")
        if state in {"failed", "stopped"} and row.get("spec"):
            actions.update({"retry_review", "dismiss"})
        if row.get("attempt_id") and state in {
            "starting",
            "running",
            "reconciling",
            "needs_review",
        }:
            actions.add("reconcile")
            if self.state.get("capabilities", {}).get("interrupts_owned"):
                actions.add("interrupt")
            if row.get("reason") == "manual_confirmation_required":
                actions.add("confirm_result")
        if any(r.get("task_id") == row["id"] for r in self.state.get("requests", ())):
            actions.add("approval")
        if (
            self.state.get("execution_available")
            and state == "queued"
            and row.get("batch_id")
        ):
            actions.add("resume_project")
        return actions

    def can_start(self):
        rows = [i for i in self.task_rows() if i["id"] in self.task_ids]
        return bool(
            self.state.get("execution_available")
            and rows
            and all(i["state"] == "queued" and not i.get("batch_id") for i in rows)
        )

    def move_task(self, offset):
        row = self.task()
        if row is None:
            return False
        # Reorder the full eligible queue, never just the visible filtered subset.
        identities = [
            i["id"]
            for i in self.state.get("items", ())
            if i["state"] == "queued" and not i.get("batch_id")
        ]
        if row["id"] not in identities:
            return False
        index = identities.index(row["id"])
        destination = index + offset
        if not 0 <= destination < len(identities):
            return False
        identities[index], identities[destination] = (
            identities[destination],
            identities[index],
        )
        self.service.send("reorder", identities)
        return True
