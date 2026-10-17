"""Compact application-owned system tray."""

from PySide6.QtCore import QObject, QRectF, Qt, QTimer, SIGNAL
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from watched_kettle.application.routes import RouteId
from watched_kettle.ui import design_tokens
from watched_kettle.ui.bubble_models import source_mark_color
from watched_kettle.ui.pet_controls import tray_status_text
from watched_kettle.ui.pet_tray import update_action_text

TRAY_ICON_SIZES = (16, 20, 24, 32, 48)


def connection_action_text(alerts):
    """One tray line for the connection watch (features/integrations/watch.py)."""
    broken = [a.label for a in alerts if a.kind == "broken"]
    found = [a.label for a in alerts if a.kind == "found"]
    parts = []
    if broken:
        parts.append(f"{'·'.join(broken)} 다시 연결 필요")
    if found:
        parts.append(f"{'·'.join(found)} 연결 가능")
    return " · ".join(parts)


# Pet states that put a colored dot on the tray icon, by design token.
BADGE_TOKENS = {
    "running": "status-running",
    "review": "status-running",
    "waiting": "status-attention",
    "failed": "status-failed",
}


def badged_icon(pixmap, state):
    """The pet's face for every tray size, with a dot for work or attention."""
    icon = QIcon()
    if pixmap is None or pixmap.isNull():
        return icon
    # The top of the idle frame is the face; it reads better at 16px.
    side = min(pixmap.width(), pixmap.height())
    face = pixmap.copy(int((pixmap.width() - side) / 2), 0, side, side)
    token = BADGE_TOKENS.get(state)
    for size in TRAY_ICON_SIZES:
        canvas = QPixmap(size, size)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawPixmap(QRectF(0, 0, size, size), face, QRectF(face.rect()))
        if token:
            dot = max(5.0, size * 0.42)
            rect = QRectF(size - dot, size - dot, dot, dot).adjusted(
                0.5, 0.5, -0.5, -0.5
            )
            painter.setPen(QColor("#ffffff"))
            painter.setBrush(QColor(design_tokens.LIGHT_THEME[token]))
            painter.drawEllipse(rect)
        painter.end()
        icon.addPixmap(canvas)
    return icon


def source_dot_icon(source):
    """A small dot in the source's color for a menu entry, or an empty icon."""
    color = source_mark_color(source)
    if not color:
        return QIcon()
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(QRectF(4, 4, 8, 8))
    painter.end()
    return QIcon(pixmap)


class AssistantSystemTray(QObject):
    def __init__(
        self,
        pet_vm,
        usage_vm,
        notifications,
        open_route,
        icon_pixmap,
        parent=None,
        updates=None,
        connections=None,
    ):
        super().__init__(parent)
        self.pet_vm = pet_vm
        self.connections = connections
        self.usage_vm = usage_vm
        self.notifications = notifications
        self.open_route = open_route
        self._closed = False
        self._refreshing = False
        self._menu_open = False
        self._project_menus = {}
        self._rows = {}
        self._bindings = {}
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self.refresh)
        self.tray = QSystemTrayIcon(badged_icon(icon_pixmap, None), self)
        self.tray.setToolTip("Watched Kettle")
        self.menu = QMenu()
        self._icon_pixmap = icon_pixmap
        self._icon_state = None
        # Agent source dots on project entries; on when both are in use.
        self.source_marks_shown = False
        # Stays while the watch reports a tool to (re)connect.
        self.connection_action = self.menu.addAction("")
        self.connection_action.setVisible(False)
        self.connection_action.triggered.connect(
            lambda: open_route(RouteId.INTEGRATIONS)
        )
        self.status_action = self.menu.addAction("현재 상태: 대기 중")
        self.status_action.setEnabled(False)
        self.usage_status_action = self.menu.addAction("Codex 사용량: 확인 불가")
        self.usage_status_action.setEnabled(False)
        self.claude_usage_action = self.menu.addAction("Claude Code 사용량: 확인 불가")
        self.claude_usage_action.setEnabled(False)
        self.claude_usage_action.setVisible(False)
        self.menu.addSeparator()
        self.projects_menu = self.menu.addMenu("진행 중 프로젝트")
        self.recent_menu = self.menu.addMenu("최근 알림")
        self.menu.addSeparator()
        home = self.menu.addAction("홈 열기")
        home.triggered.connect(lambda: open_route(RouteId.OVERVIEW))
        usage = self.menu.addAction("사용량 보기")
        usage.triggered.connect(lambda: open_route(RouteId.USAGE))
        self.menu.addSeparator()
        self._categories = {
            name: self.recent_menu.addMenu(label)
            for name, label in (
                ("usage", "사용량"),
                ("system", "시스템"),
                ("schedule", "일정"),
                ("events", "프로젝트 이벤트"),
            )
        }
        self.focus_menu = self.menu.addMenu("알림 잠시 쉬기")
        for label, minutes in (("15분", 15), ("30분", 30), ("1시간", 60)):
            action = self.focus_menu.addAction(label)
            action.triggered.connect(
                lambda checked=False, minutes=minutes: pet_vm.snooze_bubbles(
                    minutes * 60 * 1000
                )
            )
        resume = self.focus_menu.addAction("다시 표시")
        resume.triggered.connect(pet_vm.resume_bubbles)
        self.visibility_action = self.menu.addAction("펫 숨기기")
        self.visibility_action.triggered.connect(pet_vm.toggle_visibility)
        settings = self.menu.addAction("설정")
        settings.triggered.connect(lambda: open_route(RouteId.PET_SETTINGS))
        self.update_action = self.menu.addAction(update_action_text(updates))
        self.update_action.triggered.connect(self._check_updates)
        if updates is not None:
            updates.changed.connect(
                lambda: self.update_action.setText(update_action_text(updates))
            )
        self.menu.addSeparator()
        quit_action = self.menu.addAction("종료")
        quit_action.triggered.connect(QApplication.quit)
        self.menu.aboutToShow.connect(self._opening)
        self.menu.aboutToHide.connect(self._closing)
        self.tray.activated.connect(self._activated)
        self.tray.setContextMenu(self.menu)
        if connections is not None:
            connections.changed.connect(self.request_refresh)
        self.refresh()
        self.tray.show()

    def _check_updates(self):
        self.open_route(RouteId.APP_STARTUP)

    def request_refresh(self):
        if not self._closed and not self._refresh_timer.isActive():
            self._refresh_timer.start(0)

    def _opening(self):
        self.refresh()
        self._menu_open = True

    def _closing(self):
        self._menu_open = False
        self.request_refresh()

    @staticmethod
    def _set_text(action, text):
        if action.text() != text:
            action.setText(text)

    def _desired(self):
        from watched_kettle.features.project_activity.service import (
            row_status_label,
            state_label,
            thread_source,
        )

        projects = getattr(self.notifications, "projects", None)
        router = getattr(self.notifications, "router", None)
        snapshot = getattr(self.usage_vm, "snapshot", None)
        generation = (
            getattr(projects, "generation", 0),
            getattr(snapshot, "account_hash", ""),
        )
        groups = {}
        bindings = {}

        def row(key, label, kind, identifier):
            key = repr(key)
            bindings[key] = (kind, identifier, generation)
            return key, label

        if projects is not None and router is not None:
            for card in projects.cards:
                key = card.key
                rows = [
                    row(
                        ("thread", key, r.thread_id),
                        f"{r.title} · {row_status_label(r)} · {router.label('thread', r.thread_id)}",
                        "thread",
                        r.thread_id,
                    )
                    for r in card.rows
                ]
                groups[key] = (
                    " · ".join(filter(None, (card.label, card.summary))),
                    rows,
                    card.source if self.source_marks_shown else "",
                )
        categories: dict[str, list[tuple[str, str]]] = {
            name: [] for name in self._categories
        }
        if projects is not None and router is not None:
            for record in self.notifications.snapshot.recent:
                if record.category in categories and record.category != "events":
                    categories[record.category].append(
                        row(
                            ("notice", record.record_id),
                            ("" if record.confirmed else "● ") + record.message,
                            "usage" if record.category == "usage" else "notice",
                            record.record_id,
                        )
                    )
            for record in reversed(projects.recent):
                categories["events"].append(
                    row(
                        ("event", record.thread_id, record.state, record.occurred_at),
                        f"{self._conversation_title(projects, record.thread_id)}"
                        f" · {state_label(record.state, thread_source(record.thread_id))}",
                        "thread",
                        record.thread_id,
                    )
                )
        return groups, categories, bindings

    def _claude_code_usage(self):
        """Claude Code line only once limits were seen and usage is on."""
        if not getattr(self.usage_vm, "claude_code_enabled", True):
            return ""
        snapshot = getattr(self.usage_vm, "claude_code_snapshot", None)
        if not getattr(snapshot, "buckets", ()):
            return ""
        return self.usage_vm.claude_code_tray_summary()

    @staticmethod
    def _conversation_title(projects, thread_id):
        from watched_kettle.features.project_activity.service import (
            DEFAULT_TITLES,
            thread_source,
        )

        metadata = getattr(projects, "metadata", {}).get(thread_id)
        title = getattr(metadata, "title", "")
        return title or DEFAULT_TITLES[thread_source(thread_id)]

    def _open_dynamic(self, _checked=False):
        if self._closed:
            return
        action = self.sender()
        if not isinstance(action, QAction):
            return
        key = action.data()
        binding = self._bindings.get(key)
        current = self._desired()[2].get(key)
        if binding is None or binding != current:
            action.setEnabled(False)
            return
        router = getattr(self.notifications, "router", None)
        if router is not None:
            kind, identifier, _generation = binding
            router.open(router.register(kind, identifier))

    @staticmethod
    def _order(menu, actions):
        if menu.actions() == actions:
            return
        for action in menu.actions():
            menu.removeAction(action)
        for action in actions:
            menu.addAction(action)

    def _sync_rows(self, menu, rows):
        cache = self._rows.setdefault(menu, {})
        desired = {key for key, _ in rows}
        retired = [cache.pop(key) for key in tuple(cache) if key not in desired]
        ordered = []
        for key, label in rows:
            action = cache.get(key)
            if action is None:
                if retired:
                    action = retired.pop()
                else:
                    action = QAction(menu)
                    action.triggered.connect(self._open_dynamic)
                cache[key] = action
                action.setData(key)
            self._set_text(action, label)
            if not action.isEnabled():
                action.setEnabled(True)
            ordered.append(action)
        for action in retired:
            menu.removeAction(action)
            action.triggered.disconnect(self._open_dynamic)
            action.deleteLater()
        self._order(menu, ordered)

    def _dispose_menu(self, menu):
        self._sync_rows(menu, [])
        self._rows.pop(menu, None)
        self.projects_menu.removeAction(menu.menuAction())
        menu.deleteLater()

    def _sync_structure(self, groups, categories, bindings):
        retired = [
            self._project_menus.pop(key)
            for key in tuple(self._project_menus)
            if key not in groups
        ]
        ordered = []
        for key, (title, rows, mark) in groups.items():
            menu = self._project_menus.get(key)
            if menu is None:
                menu = retired.pop() if retired else QMenu(self.projects_menu)
                self._project_menus[key] = menu
            if menu.title() != title:
                menu.setTitle(title)
            if menu.property("sourceMark") != mark:
                menu.setProperty("sourceMark", mark)
                menu.setIcon(source_dot_icon(mark))
            self._sync_rows(menu, rows)
            ordered.append(menu.menuAction())
        for menu in retired:
            self._dispose_menu(menu)
        self._order(self.projects_menu, ordered)
        for name, rows in categories.items():
            self._sync_rows(self._categories[name], rows)
        self._bindings = bindings

    def refresh(self):
        if self._closed or self._refreshing:
            return
        self._refresh_timer.stop()
        self._refreshing = True
        try:
            pet = self.pet_vm.refresh()
            state = tray_status_text(
                None, pet.visual_state, getattr(pet, "working_sources", ())
            )
            # A tool switched off has no line at all.
            codex = bool(self.usage_vm.enabled)
            usage = self.usage_vm.tray_summary() if codex else ""
            active = f" · 활성 작업 {pet.active_count}개" if pet.active_count else ""
            self._set_text(self.status_action, f"현재 상태: {state}{active}")
            self._update_icon(pet.visual_state)
            if self.usage_status_action.isVisible() != codex:
                self.usage_status_action.setVisible(codex)
            if codex:
                self._set_text(self.usage_status_action, f"Codex 사용량: {usage}")
            claude_usage = self._claude_code_usage()
            if self.claude_usage_action.isVisible() != bool(claude_usage):
                self.claude_usage_action.setVisible(bool(claude_usage))
            if claude_usage:
                self._set_text(
                    self.claude_usage_action, f"Claude Code 사용량: {claude_usage}"
                )
            self._set_text(
                self.visibility_action, "펫 숨기기" if pet.visible else "펫 표시"
            )
            connection = connection_action_text(
                self.connections.snapshot if self.connections is not None else ()
            )
            if self.connection_action.isVisible() != bool(connection):
                self.connection_action.setVisible(bool(connection))
            if connection:
                self._set_text(self.connection_action, connection)
            groups, categories, bindings = self._desired()
            if self._menu_open:
                for cache in self._rows.values():
                    for key, action in cache.items():
                        valid = (
                            self._bindings.get(key) == bindings.get(key)
                            and key in bindings
                        )
                        if action.isEnabled() != valid:
                            action.setEnabled(valid)
            else:
                self._sync_structure(groups, categories, bindings)
            notice = self.notifications.snapshot.last_message
            tooltip = (
                f"Watched Kettle\n{state}"
                + (f"\n{connection}" if connection else "")
                + (f" · 활성 작업 {pet.active_count}개" if pet.active_count else "")
                + (f"\nCodex 사용량: {usage}" if codex else "")
                + (f"\nClaude Code 사용량: {claude_usage}" if claude_usage else "")
                + (f"\n{notice}" if notice else "")
            )
            if self.tray.toolTip() != tooltip:
                self.tray.setToolTip(tooltip)
        finally:
            self._refreshing = False

    def set_source_marks_shown(self, shown):
        shown = bool(shown)
        if shown != self.source_marks_shown:
            self.source_marks_shown = shown
            self.request_refresh()

    def set_icon(self, pixmap):
        if not self._closed:
            self._icon_pixmap = pixmap
            self._icon_state = None
            self._update_icon(self.pet_vm.refresh().visual_state)

    def _update_icon(self, state):
        badge = state if state in BADGE_TOKENS else None
        if self._closed or badge == self._icon_state:
            return
        self._icon_state = badge
        self.tray.setIcon(badged_icon(self._icon_pixmap, badge))

    def _activated(self, reason):
        if not self._closed and reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.pet_vm.toggle_visibility()

    def hide(self):
        self.tray.hide()

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._refresh_timer.stop()
        self.menu.aboutToShow.disconnect(self._opening)
        self.menu.aboutToHide.disconnect(self._closing)
        self.menu.close()
        self.tray.hide()
        self.tray.setContextMenu(None)  # type: ignore[arg-type]  # Qt null detaches the menu.
        self.tray.activated.disconnect(self._activated)
        for action in self.menu.findChildren(QAction):
            if not action.receivers(SIGNAL("triggered(bool)")):
                continue
            try:
                action.triggered.disconnect()
            except RuntimeError:
                pass
        self._bindings.clear()
        self._rows.clear()
        self._project_menus.clear()
        self._categories.clear()
        self.menu.deleteLater()
