"""Reopenable approval notices that expire with their owning request."""

from PySide6.QtCore import QObject

from watched_kettle.features.notifications.models import NoticeRequest


class TaskNotificationBridge(QObject):
    def __init__(self, service, notifications, router, parent=None):
        super().__init__(parent)
        self.service, self.notifications, self.router = service, notifications, router
        self.active = {}
        service.approval.connect(self.requested)
        service.changed.connect(self.refresh)

    def requested(self, request):
        key = (request.get("epoch"), request.get("id"))
        if key in self.active or not request.get("task_id"):
            return
        token = self.router.register("task", request["task_id"])
        accepted = self.notifications.submit(
            NoticeRequest(
                source="system",
                message="등록한 작업에 확인 요청이 있습니다. 작업 관리에서 확인하세요.",
                urgency="high",
                category="system",
                action_token=token,
                deduplication_key=f"task-request:{key}",
                replacement_key="task-request:" + request["task_id"],
            )
        )
        if accepted:
            self.active[key] = self.notifications.snapshot.recent[0].record_id

    def refresh(self):
        pending = {
            (r.get("epoch"), r.get("id"))
            for r in self.service.state.get("requests", ())
        }
        for key in tuple(self.active):
            if key not in pending:
                self.notifications.confirm(self.active.pop(key))
