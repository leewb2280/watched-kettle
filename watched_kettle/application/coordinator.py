"""Explicit cross-feature signal wiring."""

from __future__ import annotations

from watched_kettle.localization import t

from watched_kettle.features.notifications.models import NoticeRequest
from watched_kettle.state.events import normalize_agent_source


class AppCoordinator:
    def __init__(
        self,
        codex_server,
        activity_service,
        usage_service,
        notification_service,
        pet_vm,
        center,
        tray,
    ):
        self.codex_server = codex_server
        self.activity_service = activity_service
        self.usage_service = usage_service
        self.notification_service = notification_service
        self.pet_vm = pet_vm
        self.center = center
        self.tray = tray
        codex_server.payload_received.connect(self.observe_agent_payload)
        usage_service.notice_requested.connect(notification_service.submit)
        notification_service.payload_ready.connect(activity_service.observe)
        activity_service.snapshot_changed.connect(self._state_changed)
        usage_service.snapshot_changed.connect(self._usage_changed)
        notification_service.snapshot_changed.connect(self._notice_changed)
        pet_vm.pet.center_requested.connect(center.open_route)
        pet_vm.snapshot_changed.connect(self._pet_changed)

    def observe_agent_payload(self, payload):
        source = (
            normalize_agent_source(payload.get("source"))
            if isinstance(payload, dict)
            else ""
        )
        if source == "schedule" and isinstance(payload, dict):
            self.notification_service.submit(
                NoticeRequest(
                    source="schedule",
                    message=str(payload.get("message") or t("message.0034")),
                    urgency=str(payload.get("urgency") or "normal"),
                    session_id=str(payload.get("session_id") or "schedule"),
                    category="schedule",
                    deduplication_key=str(
                        payload.get("event_id") or payload.get("session_id") or ""
                    ),
                )
            )
        else:
            self.activity_service.observe(payload)
        self.usage_service.observe_agent_payload(payload)
        self.pet_vm.refresh()
        self.tray.request_refresh()

    def show_notice(self, payload):
        self.notification_service.submit(
            NoticeRequest(
                source=str(payload.get("source") or "system"),
                message=str(payload.get("message") or ""),
                urgency=str(payload.get("urgency") or "normal"),
                session_id=str(payload.get("session_id") or "system"),
                category=str(payload.get("category") or "system"),
                deduplication_key=str(payload.get("session_id") or ""),
            )
        )

    def _state_changed(self, _snapshot):
        self.pet_vm.refresh()
        self.tray.request_refresh()

    def _usage_changed(self, _snapshot):
        self.tray.request_refresh()

    def _notice_changed(self, _snapshot):
        self.tray.request_refresh()

    def _pet_changed(self, _snapshot):
        self.tray.set_icon(self.pet_vm.pet.frames["idle"][0])
        self.tray.request_refresh()
