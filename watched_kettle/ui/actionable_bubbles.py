"""Project and notification cards sharing the existing pet bubble theme."""

from dataclasses import dataclass, replace
from watched_kettle.localization import t

from watched_kettle.activity_diagnostics import (
    DiagnosticRecorder,
    diagnostic_guard,
    diagnostic_ref,
    diagnostic_thread_ref,
)

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt, QTimer
from PySide6.QtGui import QCursor, QRegion
from PySide6.QtWidgets import QApplication, QLabel, QToolTip, QWidget, QHBoxLayout

from watched_kettle.ui.project_bubble_rows import (
    ProjectBubbleRows,
    layout_project_bubble,
)
from watched_kettle.ui.wrapped_title_button import WrappedTitleButton
from watched_kettle.ui.speech_bubble_controller import PetBubbleController
from watched_kettle.ui.speech_bubble_window import (
    SpeechBubbleWindow,
    bubble_stack_positions,
)


def show_action_failure(message):
    """Say at the pointer why a click did not reach its target."""
    if message:
        QToolTip.showText(QCursor.pos(), str(message))


@dataclass(frozen=True)
class CardContent:
    key: str
    heading: str
    summary: str
    kind: str = "notification"
    rows: tuple = ()
    footer: str = ""
    token: str = ""
    footer_token: str = ""
    record_id: str = ""
    project_rows: tuple = ()
    available_width: int = 0
    # The agent source whose dot the heading shows; "" for none.
    mark: str = ""
    category: str = ""
    summary_parts: tuple = ()
    footer_parts: tuple = ()


class ActionableBubbleWindow(SpeechBubbleWindow):
    def __init__(self, *args, router, notifications, projects=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.router = router
        self.notifications = notifications
        self.content = None
        self.compact = False
        self._content_signature = None
        self.content_layout.removeWidget(self.category_label)
        self.header = QWidget(self)
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.addWidget(self.category_label)
        self.summary_label = QLabel(self.header)
        self.summary_label.setTextFormat(Qt.TextFormat.PlainText)
        self.summary_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        header_layout.addWidget(self.summary_label)
        self.content_layout.insertWidget(0, self.header)
        self.summary_label.installEventFilter(self)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.project_rows = ProjectBubbleRows(
            router,
            projects.dismiss_rows if projects is not None else lambda _ids: None,
            self,
        )
        self.project_rows.hide()
        self.content_layout.addWidget(self.project_rows)
        self.buttons = []
        for _index in range(4):
            button = WrappedTitleButton(self)
            button.setFlat(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setStyleSheet("QPushButton { text-align: left; padding: 3px; }")
            button.hide()
            button.action_connected = False
            self.content_layout.addWidget(button)
            self.buttons.append(button)
        self.label.installEventFilter(self)
        self.category_label.installEventFilter(self)

    def eventFilter(self, obj, event):
        if (
            event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self.activate()
            return True
        return super().eventFilter(obj, event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.activate()
        super().mouseReleaseEvent(event)

    def activate(self, token=""):
        primary = bool(self.content and (not token or token == self.content.token))
        if self.content and self.router.open(token or self.content.token):
            if primary and self.content.record_id:
                self.notifications.confirm(self.content.record_id)

    def set_content(self, content, compact=False):
        signature = (
            content,
            compact,
            self.theme,
            self.scale_percent,
            self._decorations_enabled,
        )
        if signature == self._content_signature:
            return
        self._content_signature = signature
        self.content = content
        self.compact = compact
        self.set_message(content.summary, content.kind, "")
        # set_message marks only notices; a card names its own source.
        self._mark_source = content.mark
        project = content.key.startswith("project:")
        if project:
            layout_project_bubble(self, content, compact)
            return
        self.project_rows.hide()
        self.summary_label.setTextFormat(Qt.TextFormat.PlainText)
        self.summary_label.setWordWrap(False)
        has_summary = project and bool(content.summary)
        spacing = self._scaled(6) if has_summary else 0
        self.header.layout().setSpacing(spacing)

        rows = [] if compact else list(content.rows[:2])
        if not project:
            rows.append(
                (
                    t("message.0200")
                    if content.category == "usage"
                    else t("message.0201"),
                    content.token,
                )
            )
        if content.footer:
            rows.append((content.footer, content.footer_token))

        # Clear the previous fixed constraint before measuring the full heading.
        self.category_label.setMinimumWidth(0)
        self.category_label.setMaximumWidth(16_777_215)
        self._update_category_label(content.heading)
        if not content.mark:
            self.category_label.setToolTip(content.heading)
        self.summary_label.setFont(self.label.font())
        self.summary_label.setStyleSheet(f"color: {self.theme.text};")
        self.summary_label.setToolTip(content.summary)
        self.summary_label.setAccessibleName(content.summary)
        self.summary_label.setText(content.summary if has_summary else "")
        self.summary_label.setVisible(has_summary)
        self.label.setVisible(not project)
        self.category_label.ensurePolished()
        self.summary_label.ensurePolished()

        heading_text_width = self.category_label.fontMetrics().horizontalAdvance(
            content.heading
        )
        heading_natural_width = self.category_label.sizeHint().width()
        heading_chrome_width = max(0, heading_natural_width - heading_text_width)
        summary_natural_width = (
            self.summary_label.sizeHint().width() if has_summary else 0
        )
        header_natural_width = heading_natural_width + spacing + summary_natural_width
        natural_widths = [header_natural_width]
        if not project and content.summary:
            natural_widths.append(
                max(
                    self.label.fontMetrics().horizontalAdvance(line)
                    for line in content.summary.splitlines() or [""]
                )
            )
        for label, _token in rows:
            natural_widths.append(
                self.label.fontMetrics().horizontalAdvance(label) + self._scaled(8)
            )
        minimum_width = max(
            1,
            self._scaled(self.theme.minimum_width - self.theme.horizontal_padding),
        )
        maximum_width = max(
            minimum_width,
            self._scaled(self.theme.maximum_width - self.theme.horizontal_padding),
        )
        if content.available_width:
            margins = self.content_layout.contentsMargins()
            maximum_width = max(
                1,
                min(
                    maximum_width,
                    content.available_width - margins.left() - margins.right(),
                ),
            )
            minimum_width = min(minimum_width, maximum_width)
        width = min(max(max(natural_widths), minimum_width), maximum_width)
        self.label.setFixedWidth(width)
        self.header.setFixedWidth(width)
        if has_summary:
            # Keep the status readable and give the project the remaining space.
            available = max(1, width - spacing)
            summary_width = min(
                summary_natural_width,
                max(1, available - self._scaled(56)),
            )
            heading_width = max(1, available - summary_width)
            self.summary_label.setFixedWidth(summary_width)
            if summary_width >= summary_natural_width:
                self.summary_label.setText(content.summary)
            else:
                self.summary_label.setText(
                    self.summary_label.fontMetrics().elidedText(
                        content.summary, Qt.TextElideMode.ElideRight, summary_width
                    )
                )
        else:
            heading_width = width
            self.summary_label.clear()
            self.summary_label.setFixedWidth(0)
            self.label.setText(content.summary)
        category_width = min(heading_width, heading_natural_width)
        self.category_label.setFixedWidth(category_width)
        if heading_width >= heading_natural_width:
            self.category_label.setText(content.heading)
        else:
            self.category_label.setText(
                self.category_label.fontMetrics().elidedText(
                    content.heading,
                    Qt.TextElideMode.ElideRight,
                    max(1, category_width - heading_chrome_width),
                )
            )
        self.category_label.show()
        self.setWindowTitle(t("message.0199", value0=content.heading))
        for index, button in enumerate(self.buttons):
            if index >= len(rows):
                if not button.isHidden():
                    button.hide()
                continue
            label, token = rows[index]
            button.setFont(self.label.font())
            button.setStyleSheet(
                f"QPushButton {{ text-align: left; padding: 3px; color: {self.theme.text}; }} QPushButton:hover {{ background: rgba(100,140,180,25); }}"
            )
            button.set_title(
                label,
                width,
                self._scaled(8),
                2 if project and index < len(content.rows) else 1,
            )
            button.setAccessibleName(label)
            button.setToolTip(label)
            if getattr(button, "action_token", None) != token:
                if button.action_connected:
                    button.clicked.disconnect()
                button.clicked.connect(
                    lambda checked=False, value=token: self.activate(value)
                )
                button.action_connected = True
                button.action_token = token
            if button.isHidden():
                button.show()
        self.setAccessibleName(
            " · ".join(filter(None, (content.heading, content.summary)))
        )
        self.content_layout.activate()
        self.adjustSize()

    def nativeEvent(self, event_type, message):
        # HTTRANSPARENT prevents transparent frame margins from intercepting
        # mouse input without clipping the theme's decorative artwork.
        import sys

        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0084:  # WM_NCHITTEST
                x = ctypes.c_short(msg.lParam & 0xFFFF).value
                y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
                ratio = self.devicePixelRatioF()
                # ScreenToClient uses native pixel coordinates (mixed DPI safe).
                point = wintypes.POINT(x, y)
                ctypes.windll.user32.ScreenToClient(
                    wintypes.HWND(int(self.winId())), ctypes.byref(point)
                )
                local = QPoint(round(point.x / ratio), round(point.y / ratio))
                body = getattr(self, "_input_path", None)
                if body is None or not body.contains(QPointF(local)):
                    return True, -1
        return super().nativeEvent(event_type, message)


class ActionableBubbleController(PetBubbleController):
    def __init__(self, pet, projects, notifications, router, **kwargs):
        self.projects = projects
        self.notifications = notifications
        self.router = router
        self.card_windows = {}
        self.activity_diagnostics = DiagnosticRecorder()
        self._diagnostic_rows = {}
        self._diagnostic_cards = {}
        self._diagnostic_reason = "initial"
        self._rendering = False
        self._closed = False
        self._last_layout = None
        self._plan_key = None
        self._plan = ()
        self._measurer = None
        self._project_generation = projects.generation
        super().__init__(pet, **kwargs)
        self.notifications.managed_delivery = True
        projects.changed.connect(self._render)
        notifications.snapshot_changed.connect(self._render)
        self.tick = QTimer(self)
        self.tick.setInterval(200)
        self.tick.timeout.connect(self._tick)
        self.tick.start()

    def _tick(self):
        self.projects.expire()
        self._render()

    def apply(self, _presentation):
        # Animation presentations stay owned by the existing state controller.
        self._render()

    def set_duration_seconds(self, seconds):
        super().set_duration_seconds(seconds)
        self.projects.duration = self.duration_seconds

    def set_duration_policy(self, policy):
        super().set_duration_policy(policy)
        self.projects.duration = policy.seconds("result")
        self.projects.completion_duration = policy.seconds("completion")
        self.notifications.duration_policy = policy

    @property
    def visible_windows(self):
        return (
            tuple(
                sorted(
                    (w for w in self.card_windows.values() if w.isVisible()),
                    key=lambda w: w.y(),
                    reverse=True,
                )
            )
            or super().visible_windows
        )

    def _contents(self):
        cards = self.projects.bubble_cards
        self._diagnose_membership(cards)
        all_token = self.router.register("projects")
        contents = []
        retained = {all_token}
        for index, card in enumerate(cards):
            tokens = [
                (row, self.router.register("thread", row.thread_id))
                for row in card.rows
            ]
            retained.update(t for _, t in tokens)
            if index >= 3:
                continue
            footer = []
            if index == min(2, len(cards) - 1) and len(cards) > 3:
                hidden = cards[3:]
                footer.append(
                    (
                        "overflow",
                        t(
                            "bubble.more_projects"
                            if all(c.kind == "project" for c in hidden)
                            else "bubble.more_items",
                            count=len(hidden),
                        ),
                    )
                )
            contents.append(
                CardContent(
                    "project:" + card.key,
                    card.label,
                    card.summary,
                    "waiting"
                    if card.waiting
                    else "error"
                    if any(r.state == "failed" for r in card.rows)
                    else "start",
                    tuple((row.title, token) for row, token in tokens),
                    " · ".join(text for _, text in footer),
                    tokens[0][1],
                    all_token,
                    project_rows=card.rows,
                    summary_parts=card.summary_parts,
                    footer_parts=tuple(footer),
                    mark=card.source if self.source_marks_shown else "",
                )
            )
        for record in self.projects.recent:
            retained.add(self.router.register("thread", record.thread_id))
        for record in self.projects.completions:
            retained.add(self.router.register("thread", record.thread_id))
        for record in self.projects.visible_completions:
            retained.add(self.router.register("thread", record.thread_id))
        selected = {r.record_id for r in self.notifications.candidates()}
        for record in self.notifications.snapshot.recent:
            kind = "usage" if record.category == "usage" else "notice"
            token = (
                record.action_token
                if record.action_token in self.router.targets
                else self.router.register(kind, record.record_id)
            )
            retained.add(token)
            if record.record_id not in selected:
                continue
            footer_token = self.router.register("history", record.category)
            retained.add(footer_token)
            pending = self.notifications.pending_count(record.category) - (
                record.delivery == "queued"
            )
            contents.append(
                CardContent(
                    record.record_id,
                    {
                        "usage": t("message.0204"),
                        "system": t("message.0202"),
                        "schedule": t("message.0205"),
                    }.get(record.category, t("message.0202")),
                    record.message,
                    "notification",
                    (),
                    t("message.0203", value0=pending) if pending else "",
                    token,
                    footer_token,
                    record.record_id,
                    category=record.category,
                )
            )
        # Notifications are appended in lane order, regardless of history order.
        projects = sorted(
            [c for c in contents if not c.record_id],
            key=lambda c: 0 if c.kind in {"waiting", "error"} else 1,
        )
        notices = sorted(
            (c for c in contents if c.record_id), key=lambda c: c.category == "schedule"
        )
        self.router.retain(retained)
        return projects + notices

    def _new_card_window(self):
        return ActionableBubbleWindow(
            self.pet,
            router=self.router,
            notifications=self.notifications,
            projects=self.projects,
            scale_percent=self.scale_percent,
            theme=self.theme,
            element_registry=self.element_registry,
            source_marks_shown=self.source_marks_shown,
        )

    def _layout_plan(self, contents, bounds, ratio):
        # Pet coordinates/height do not affect card capacity. Measure only when
        # content, work area or appearance changes, using a never-shown widget.
        key = (
            tuple(contents),
            bounds.size(),
            ratio,
            self.theme,
            self.scale_percent,
            len(self.projects.bubble_cards),
        )
        if key == self._plan_key:
            return self._plan
        if self._measurer is None:
            self._measurer = self._new_card_window()
        sizes = {}
        gap = max(1, round(6 * self.scale_percent / 100))

        def measured(content, compact, decorated):
            key = (content, compact, decorated)
            if key not in sizes:
                probe = self._measurer
                probe.set_scale_percent(self.scale_percent)
                probe.set_theme(self.theme)
                probe.set_tail_side(None)
                probe.set_decorations_enabled(decorated)
                probe.set_content(content, compact)
                sizes[key] = probe.size()
            return sizes[key]

        entries = [(c, False, i == 0) for i, c in enumerate(contents)]

        def height():
            return sum(measured(*entry).height() for entry in entries) + gap * max(
                0, len(entries) - 1
            )

        for index in reversed(range(len(entries))):
            if height() <= bounds.height() - 16:
                break
            content, _, decorated = entries[index]
            if content.key.startswith("project:"):
                entries[index] = (content, True, decorated)

        def fits():
            return not entries or (
                height() <= bounds.height() - 16
                and max(measured(*e).width() for e in entries) <= bounds.width() - 16
            )

        while entries and not fits():
            entries.pop()
        # If capacity hid projects, replace only the project-overflow portion;
        # retain conversation/hidden-wait summaries. Recheck footer height.
        while entries:
            count = len(self.projects.bubble_cards) - sum(
                e[0].key.startswith("project:") for e in entries
            )
            if count > max(
                0,
                len(self.projects.bubble_cards)
                - sum(c.key.startswith("project:") for c in contents),
            ):
                index = next(
                    (
                        i
                        for i, e in enumerate(entries)
                        if e[0].key.startswith("project:")
                    ),
                    0,
                )
                for i, (content, compact, decorated) in enumerate(entries):
                    if not content.key.startswith("project:"):
                        continue
                    parts = [
                        part
                        for kind, part in (
                            content.footer_parts or (("other", content.footer),)
                        )
                        if part and kind != "overflow"
                    ]
                    if i == index:
                        parts.append(t("bubble.more_projects", count=count))
                    entries[i] = (
                        replace(
                            content,
                            footer=" · ".join(parts),
                            footer_parts=tuple(
                                (
                                    "overflow"
                                    if i == index and n == len(parts) - 1
                                    else "other",
                                    part,
                                )
                                for n, part in enumerate(parts)
                            ),
                            footer_token=self.router.register("projects")
                            if i == index
                            else content.footer_token,
                        ),
                        compact,
                        decorated,
                    )
            if fits():
                break
            entries.pop()
        self._plan = tuple(
            (c, compact, decorated, measured(c, compact, decorated))
            for c, compact, decorated in entries
        )
        self._plan_key = key
        return self._plan

    def _render(self, *_args):
        if self._rendering or self._closed:
            return
        self._rendering = True
        try:
            if self._project_generation != self.projects.generation:
                self._project_generation = self.projects.generation
                self._plan_key = None
                self._plan = ()
                if self._measurer is not None:
                    self._measurer.close()
                    self._measurer.deleteLater()
                    self._measurer = None
                for window in self.card_windows.values():
                    window.close()
                    window.deleteLater()
                self.card_windows.clear()
            enabled = self.enabled and not self.is_snoozed and self.pet.isVisible()
            self.notifications.set_delivery_enabled(enabled)
            if self._entries or not enabled:
                self._diagnostic_reason = (
                    "preview"
                    if self._entries
                    else "disabled"
                    if not self.enabled
                    else "snoozed"
                    if self.is_snoozed
                    else "pet_hidden"
                )
                self._last_layout = None
                for window in self.card_windows.values():
                    if window.isVisible():
                        window.hide()
                if self._entries:
                    super()._render()
                else:
                    self._contents()
                return
            contents = self._contents()
            self._diagnostic_reason = "space"
            screen = (
                QApplication.screenAt(self.pet.frameGeometry().center())
                or self.pet.screen()
            )
            if screen is None:
                self._diagnostic_reason = "no_screen"
                return
            bounds = screen.availableGeometry()
            pet_rect = self.pet.frameGeometry()
            companion = self.pet.findChild(QWidget, "usageCompanion")
            obstacles = [pet_rect]
            if companion is not None and companion.isVisible():
                obstacles.append(companion.frameGeometry())
            contents = [
                replace(c, available_width=max(1, bounds.width() - 16))
                for c in contents
            ]
            ratio = (
                screen.devicePixelRatio() if hasattr(screen, "devicePixelRatio") else 1
            )
            signature = (
                contents,
                self.pet.frameGeometry(),
                bounds,
                ratio,
                self.scale_percent,
                self.theme,
                tuple(obstacles),
            )
            if signature == self._last_layout:
                return
            plan = self._layout_plan(contents, bounds, ratio)
            desired = {c.key for c in contents}
            for key in set(self.card_windows) - desired:
                window = self.card_windows.pop(key)
                window.close()
                window.deleteLater()
            visible = {entry[0].key for entry in plan}
            for key, window in self.card_windows.items():
                if key not in visible and window.isVisible():
                    window.hide()
            positions = bubble_stack_positions(
                self.pet.frameGeometry(),
                [entry[3] for entry in plan],
                bounds,
                gap=round(10 * self.scale_percent / 100),
                stack_gap=max(1, round(6 * self.scale_percent / 100)),
                alignment=self.theme.stack_alignment,
            )
            positions = self._avoid_pet_overlap(
                positions, [entry[3] for entry in plan], bounds, obstacles
            )
            for (content, compact, decorated, _), position in zip(plan, positions):
                if content.key not in self.card_windows:
                    self.card_windows[content.key] = self._new_card_window()
                window = self.card_windows[content.key]
                changed = (
                    window.content != content
                    or window.compact != compact
                    or window.scale_percent != self.scale_percent
                    or window.theme != self.theme
                    or window._decorations_enabled != decorated
                )
                if changed:
                    window.set_scale_percent(self.scale_percent)
                    window.set_theme(self.theme)
                    window.set_tail_side(None)
                    window.set_decorations_enabled(decorated)
                    window.set_content(content, compact)
                if window.pos() != position:
                    window.move(position)
                overlap = window.frameGeometry().intersected(self.pet.frameGeometry())
                mask = QRegion()
                if not overlap.isEmpty():
                    local = QRect(overlap)
                    local.translate(-window.x(), -window.y())
                    mask = QRegion(window.rect()).subtracted(QRegion(local))
                    if mask.isEmpty():
                        mask = QRegion(-1, -1, 1, 1)
                if window.mask() != mask:
                    if mask.isEmpty():
                        window.clearMask()
                    else:
                        window.setMask(mask)
                if not window.isVisible():
                    window.show()
                    if content.record_id:
                        self.notifications.shown(content.record_id)
                for row in content.project_rows:
                    self.projects.mark_latency(row.thread_id, "shown")
                    metadata = self.projects.metadata.get(row.thread_id)
                    if (
                        metadata
                        and metadata.project_id is not None
                        and bool(metadata.title)
                    ):
                        self.projects.mark_latency(row.thread_id, "named")
            # The mask preserves pet pixels and dragging without repeated raises.
            self._last_layout = signature
        finally:
            self._diagnose_visibility()
            self._rendering = False

    @diagnostic_guard
    def _diagnose_membership(self, cards):
        recorder = self.activity_diagnostics
        if recorder.callback is None:
            return
        rows = {}
        observed_cards = {}
        truncated = False
        for index, card in enumerate(cards):
            if len(observed_cards) >= 512:
                truncated = True
                break
            card_ref = diagnostic_ref("project:" + card.key)
            observed_cards[card_ref] = dict(
                card_ref=card_ref,
                project_ref=diagnostic_ref(card.key),
                source=card.source,
                project_kind=card.kind,
                reason="project_limit" if index >= 3 else "space",
            )
            for row in card.rows:
                if len(rows) >= 512:
                    truncated = True
                    break
                ref = diagnostic_thread_ref(row.source, row.thread_id)
                fields = dict(
                    thread_ref=ref,
                    card_ref=card_ref,
                    project_ref=diagnostic_ref(card.key),
                    source=row.source,
                    project_kind=card.kind,
                    state=row.state,
                    uncertain=row.uncertain,
                    generation=self.projects.generation,
                )
                previous = self._diagnostic_rows.get(ref)
                if previous != fields:
                    result = (
                        "attached"
                        if previous is None
                        else "moved"
                        if previous["card_ref"] != card_ref
                        else "updated"
                    )
                    recorder.emit("bubble_row_membership", result=result, **fields)
                rows[ref] = fields
        if not truncated:
            for ref, previous in self._diagnostic_rows.items():
                if ref not in rows:
                    recorder.emit(
                        "bubble_row_membership",
                        result="removed",
                        reason="no_longer_in_cards",
                        **previous,
                    )
            for ref, previous in self._diagnostic_cards.items():
                if ref not in observed_cards:
                    recorder.emit(
                        "bubble_card_removed",
                        card_ref=ref,
                        source=previous["source"],
                        reason="no_longer_in_cards",
                        generation=self.projects.generation,
                    )
                    recorder.forget("bubble_card_visibility", ref)
        self._diagnostic_rows = rows
        self._diagnostic_cards = observed_cards

    @diagnostic_guard
    def _diagnose_visibility(self):
        visible = {
            diagnostic_ref(key)
            for key, window in self.card_windows.items()
            if window.isVisible()
        }
        for ref, card in self._diagnostic_cards.items():
            shown = ref in visible
            reason = (
                "shown"
                if shown
                else card["reason"]
                if self._diagnostic_reason == "space"
                else self._diagnostic_reason
            )
            self.activity_diagnostics.record(
                "bubble_card_visibility",
                ref,
                **dict(
                    card,
                    visible=shown,
                    reason=reason,
                    generation=self.projects.generation,
                ),
            )

    def _avoid_pet_overlap(self, positions, sizes, bounds, obstacles):
        rects = [QRect(point, size) for point, size in zip(positions, sizes)]
        if not any(rect.intersects(obstacles[0]) for rect in rects):
            return positions
        # At the top edge the clamped stack can cover the pet. Preserve the full
        # title/header by translating the column into free space before masking.
        area = bounds.adjusted(8, 8, -8, -8)
        column = QRect()
        for rect in rects:
            column = column.united(rect)
        gap = max(1, round(10 * self.scale_percent / 100))
        candidates = []
        for obstacle in obstacles:
            candidates.extend(
                (
                    QPoint(obstacle.right() + 1 + gap - column.left(), 0),
                    QPoint(obstacle.left() - gap - column.right() - 1, 0),
                )
            )
        candidates.sort(key=lambda point: abs(point.x()))
        # If neither side fits on a narrow screen, use the space below the pet.
        candidates.append(
            QPoint(0, max(rect.bottom() for rect in obstacles) + gap + 1 - column.top())
        )
        for delta in candidates:
            moved = [rect.translated(delta) for rect in rects]
            if all(area.contains(rect) for rect in moved) and not any(
                rect.intersects(obstacle) for rect in moved for obstacle in obstacles
            ):
                return tuple(point + delta for point in positions)
        return positions

    def reposition(self):
        if self._entries:
            return super().reposition()
        self._render()

    def owner_hidden(self):
        if self._closed:
            return
        super().owner_hidden()
        self.notifications.set_delivery_enabled(False)
        for window in self.card_windows.values():
            window.hide()
        self._diagnostic_reason = "pet_hidden"
        self._diagnose_visibility()

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.tick.stop()
        if self._measurer is not None:
            self._measurer.close()
            self._measurer.deleteLater()
        for window in self.card_windows.values():
            window.close()
            window.deleteLater()
        self.card_windows.clear()
        self._diagnostic_reason = "closed"
        self._diagnose_visibility()
        super().close()

    @staticmethod
    def _tail_side_for(primary_rect, pet_rect):
        return "bottom" if primary_rect.bottom() < pet_rect.top() else None

    def sync_always_on_top(self, enabled):
        for window in self.card_windows.values():
            window.sync_always_on_top(enabled)
        super().sync_always_on_top(enabled)
