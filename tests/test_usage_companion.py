"""Usage widget placement, preferences wiring and pointer behavior."""

import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QSize, Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QFrame

from watched_kettle.ui.usage_companion import (
    UsageCompanionController,
    usage_companion_position,
)
from watched_kettle.usage.models import (
    RateLimitBucket,
    UsageAvailability,
    UsageSnapshot,
    UsageWindow,
)


class FakePet(QFrame):
    usage_widget_visibility_requested = Signal(bool)
    usage_widget_shape_requested = Signal(str)
    usage_widget_tasks_visibility_requested = Signal(bool)
    usage_widget_today_visibility_requested = Signal(bool)
    usage_widget_settings_requested = Signal()
    usage_widget_position_reset_requested = Signal()

    def __init__(self):
        super().__init__()
        self.always_on_top = False
        self.setFixedSize(224, 224)


class FakePetViewModel(QObject):
    snapshot_changed = Signal(object)


class FakeUsageViewModel(QObject):
    snapshot_changed = Signal(object)

    def __init__(self, snapshot):
        super().__init__()
        self.snapshot = snapshot
        self.enabled = True
        self.widget_visible = True
        self.widget_shape = "rings"
        self.widget_emphasis = "auto"
        self.widget_tasks_visible = True
        self.widget_today_visible = False
        self.widget_theme_mode = "app"
        self.widget_background_color = "#263246"
        self.widget_background_opacity = 93
        self.widget_scale_percent = 100
        self.widget_hour_range = (0, 24)
        self.widget_legacy_offset = None
        self.widget_detached = False
        self.widget_placement = None
        self.claude_code_snapshot = None

    def _publish(self):
        self.snapshot_changed.emit(self.snapshot)

    def set_widget_visible(self, visible):
        self.widget_visible = bool(visible)
        self._publish()

    def set_widget_shape(self, shape):
        self.widget_shape = shape
        self._publish()

    def set_widget_tasks_visible(self, visible):
        self.widget_tasks_visible = bool(visible)
        self._publish()

    def set_widget_today_visible(self, visible):
        self.widget_today_visible = bool(visible)
        self._publish()

    def detach_widget(self, placement):
        self.widget_placement = placement
        self.widget_detached = True
        self.widget_legacy_offset = None
        self._publish()
        return placement

    def reset_widget_position(self):
        self.widget_legacy_offset = None
        self.widget_detached = False
        self.widget_placement = None
        self._publish()


def snapshot():
    now = datetime.now(timezone.utc)
    return UsageSnapshot(
        availability=UsageAvailability("available", "연결됨"),
        buckets=(
            RateLimitBucket(
                "codex",
                limit_name="Codex",
                primary=UsageWindow(25, 75, 300, now + timedelta(hours=2)),
                secondary=UsageWindow(90, 10, 10080, now + timedelta(days=2)),
            ),
        ),
        account_hash="account",
        last_updated_at=now,
    )


class UsageCompanionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def controller(self, usage_vm=None, **kwargs):
        pet = FakePet()
        pet.move(160, 140)
        pet.show()
        usage_vm = usage_vm or FakeUsageViewModel(snapshot())
        opened = []
        controller = UsageCompanionController(
            pet, FakePetViewModel(), usage_vm, lambda: opened.append(True), **kwargs
        )
        self.addCleanup(pet.close)
        self.addCleanup(controller.close)
        self.app.processEvents()
        return controller, pet, usage_vm, opened

    def test_preview_draws_offscreen_and_falls_back_to_example_values(self):
        controller, _pet, usage_vm, _opened = self.controller()
        image, sample = controller.preview()
        self.assertFalse(sample)
        # One Codex ring cell; example values add the Claude Code cell.
        self.assertGreater(image.width(), 100)
        self.assertGreater(image.height(), 40)
        # The preview never shows a window or moves the real widget.
        self.assertFalse(controller._preview_window.isVisible())
        self.assertIsNot(controller._preview_window, controller.window)

        usage_vm.snapshot = UsageSnapshot()
        _image, sample = controller.preview()
        self.assertTrue(sample)
        both, sample = controller.preview(sample=True)
        self.assertTrue(sample)
        self.assertGreater(both.width(), image.width())

        usage_vm.widget_shape = "chips"
        folded, _ = controller.preview(sample=True)
        unfolded, _ = controller.preview(sample=True, expanded=True)
        self.assertGreater(unfolded.height(), folded.height())

        controller._release_preview()
        self.assertIsNone(controller._preview_window)

    def mouse(self, window, kind, point, buttons):
        local = QPointF(point - window.position())
        event = QMouseEvent(
            kind,
            local,
            QPointF(point),
            Qt.MouseButton.LeftButton,
            buttons,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(window, event)

    def test_position_uses_roomier_side_and_clamps_to_work_area(self):
        bounds = QRect(0, 0, 1000, 700)
        right = usage_companion_position(
            QRect(100, 300, 200, 200), QSize(250, 120), bounds
        )
        self.assertEqual(right, QPoint(308, 339))
        left = usage_companion_position(
            QRect(700, 300, 200, 200), QSize(250, 120), bounds
        )
        self.assertEqual(left, QPoint(442, 339))
        clamped = usage_companion_position(
            QRect(700, 650, 200, 200), QSize(250, 120), bounds
        )
        self.assertEqual(clamped.y(), 580)

    def test_widget_follows_pet_visibility_and_settings(self):
        controller, pet, usage_vm, _ = self.controller()
        self.assertTrue(controller.window.isVisible())
        usage_vm.set_widget_visible(False)
        self.assertFalse(controller.window.isVisible())
        usage_vm.set_widget_visible(True)
        pet.hide()
        self.app.processEvents()
        self.assertFalse(controller.window.isVisible())

    def test_refresh_timer_runs_only_while_the_widget_is_shown(self):
        controller, pet, usage_vm, _ = self.controller()
        self.assertTrue(controller._tick.isActive())
        usage_vm.set_widget_visible(False)
        self.assertFalse(controller._tick.isActive())
        usage_vm.set_widget_visible(True)
        self.assertTrue(controller._tick.isActive())
        pet.hide()
        self.app.processEvents()
        self.assertFalse(controller._tick.isActive())

    def test_widget_stays_visible_with_claude_only_and_hides_when_both_are_off(self):
        controller, _pet, usage_vm, _ = self.controller()
        usage_vm.enabled = False
        usage_vm.claude_code_enabled = True
        usage_vm.any_enabled = True
        usage_vm.snapshot = UsageSnapshot(
            availability=UsageAvailability("disabled", "Codex 사용량이 꺼져 있습니다."),
            buckets=(RateLimitBucket("claude_code", primary=UsageWindow(30, 70, 300)),),
        )
        usage_vm._publish()
        self.assertTrue(controller.window.isVisible())
        self.assertTrue(controller._tick.isActive())
        self.assertTrue(controller.pet.usage_widget_available)
        usage_vm.claude_code_enabled = False
        usage_vm.any_enabled = False
        usage_vm._publish()
        self.assertFalse(controller.window.isVisible())
        self.assertFalse(controller._tick.isActive())
        self.assertFalse(controller.pet.usage_widget_available)

    def test_pet_menu_signals_reach_the_view_model_and_menu_state(self):
        controller, pet, usage_vm, opened = self.controller()
        pet.usage_widget_shape_requested.emit("chips")
        pet.usage_widget_tasks_visibility_requested.emit(False)
        pet.usage_widget_today_visibility_requested.emit(True)
        pet.usage_widget_settings_requested.emit()
        self.assertEqual(
            (usage_vm.widget_shape, usage_vm.widget_tasks_visible),
            ("chips", False),
        )
        self.assertTrue(usage_vm.widget_today_visible)
        self.assertEqual(opened, [True])
        controller._sync_menu_state()
        self.assertEqual(pet.usage_widget_shape, "chips")
        self.assertFalse(pet.usage_widget_tasks_visible)

    def test_context_carries_shape_theme_and_hides_tasks_on_request(self):
        controller, _pet, usage_vm, _ = self.controller(
            app_theme=lambda: "dark",
            activity=lambda: {"codex": {"running": 2}},
        )
        context = controller._widget_context()
        self.assertEqual((context["layout"], context["theme"]), ("rings", "dark"))
        self.assertEqual(context["activity"], {"codex": {"running": 2}})
        self.assertIsNone(context["background"])
        usage_vm.widget_tasks_visible = False
        usage_vm.widget_theme_mode = "custom"
        context = controller._widget_context()
        self.assertIsNone(context["activity"])
        self.assertEqual(context["background"], "#263246")
        controller.refresh()
        self.assertEqual(controller.window.model.layout, "rings")

    def test_live_and_sample_preview_keep_the_task_switch(self):
        controller, _pet, usage_vm, _ = self.controller(
            activity=lambda: {"codex": {"running": 2}},
        )
        usage_vm.widget_shape = "chips"
        for visible in (True, False, True):
            usage_vm.set_widget_tasks_visible(visible)
            self.assertEqual(controller._widget_context()["tasks_visible"], visible)
            self.assertEqual(controller.window.model.state["tasksVisible"], visible)
            for sample in (False, True):
                with self.subTest(visible=visible, sample=sample):
                    image, used_sample = controller.preview(
                        sample=sample, expanded=True
                    )
                    self.assertFalse(image.isNull())
                    self.assertEqual(used_sample, sample)
                    state = controller._preview_window.model.state
                    self.assertEqual(state["tasksVisible"], visible)
                    rows = state["providers"]
                    expected = [(1, 0), (0, 1)] if sample else [(2, 0)]
                    self.assertEqual(
                        [(p["running"], p["attention"]) for p in rows],
                        expected if visible else [(0, 0)] * len(rows),
                    )

    def test_enabled_claude_without_observed_limits_does_not_add_a_widget_row(self):
        usage_vm = FakeUsageViewModel(snapshot())
        usage_vm.claude_code_enabled = True
        controller, _pet, _vm, _opened = self.controller(usage_vm)
        self.assertIsNone(controller._widget_context()["claude_code_enabled"])
        self.assertEqual(
            [row["key"] for row in controller.window.model.state["providers"]],
            ["codex"],
        )

    def test_short_click_opens_usage_and_drag_detaches(self):
        controller, _pet, usage_vm, opened = self.controller()
        window = controller.window
        start = window.position() + QPoint(20, 20)
        self.mouse(
            window, QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton
        )
        self.mouse(
            window, QEvent.Type.MouseButtonRelease, start, Qt.MouseButton.NoButton
        )
        self.assertEqual(opened, [True])
        self.assertFalse(usage_vm.widget_detached)

        self.mouse(
            window, QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton
        )
        target = start + QPoint(-60, 40)
        self.mouse(window, QEvent.Type.MouseMove, target, Qt.MouseButton.LeftButton)
        self.mouse(
            window, QEvent.Type.MouseButtonRelease, target, Qt.MouseButton.NoButton
        )
        self.assertEqual(opened, [True])
        self.assertTrue(usage_vm.widget_detached)
        self.assertEqual(
            (usage_vm.widget_placement.x, usage_vm.widget_placement.y),
            (window.position().x(), window.position().y()),
        )

    def start_drag(self, window, offset=QPoint(-60, 40)):
        start = window.position() + QPoint(20, 20)
        self.mouse(
            window, QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton
        )
        target = start + offset
        self.mouse(window, QEvent.Type.MouseMove, target, Qt.MouseButton.LeftButton)
        self.assertTrue(window.dragging)
        return target

    def test_updates_during_a_drag_do_not_pull_the_widget_back(self):
        controller, pet, usage_vm, _ = self.controller()
        window = controller.window
        before = window.position()
        target = self.start_drag(window)
        dragged = window.position()
        self.assertNotEqual(dragged, before)

        # A bubble change refreshes the pet snapshot; usage, size and pet
        # moves all ask for a new placement too.
        controller.pet_viewmodel.snapshot_changed.emit(
            SimpleNamespace(always_on_top=False)
        )
        usage_vm._publish()
        window.size_changed.emit()
        pet.move(200, 180)
        self.app.processEvents()
        controller.reposition()
        self.assertEqual(window.position(), dragged)

        # Releasing without another move keeps the dragged spot.
        self.mouse(
            window, QEvent.Type.MouseButtonRelease, target, Qt.MouseButton.NoButton
        )
        self.assertFalse(window.dragging)
        self.assertTrue(usage_vm.widget_detached)
        self.assertEqual(
            (usage_vm.widget_placement.x, usage_vm.widget_placement.y),
            (dragged.x(), dragged.y()),
        )
        self.assertEqual(window.position(), dragged)

    def test_a_detached_widget_is_not_pulled_back_to_its_saved_spot(self):
        controller, _pet, usage_vm, _ = self.controller()
        window = controller.window
        target = self.start_drag(window)
        self.mouse(
            window, QEvent.Type.MouseButtonRelease, target, Qt.MouseButton.NoButton
        )
        saved = window.position()

        self.start_drag(window, QPoint(50, 30))
        dragged = window.position()
        self.assertNotEqual(dragged, saved)
        usage_vm._publish()
        self.assertEqual(window.position(), dragged)

    def test_a_lost_release_does_not_leave_the_widget_stuck(self):
        controller, pet, usage_vm, _ = self.controller()
        window = controller.window
        self.start_drag(window)
        # Hidden mid-drag: no release arrives, and nothing is saved.
        usage_vm.set_widget_visible(False)
        self.assertFalse(window.dragging)
        usage_vm.set_widget_visible(True)
        self.assertFalse(usage_vm.widget_detached)
        self.assertEqual(window.position(), controller._placement()[0])
        pet.move(220, 200)
        self.app.processEvents()
        self.assertEqual(window.position(), controller._placement()[0])

        # A move without the button means the release went elsewhere.
        target = self.start_drag(window)
        self.mouse(window, QEvent.Type.MouseMove, target, Qt.MouseButton.NoButton)
        self.assertFalse(window.dragging)
        controller.reposition()
        self.assertEqual(window.position(), controller._placement()[0])

    def test_legacy_offset_migrates_to_a_restorable_detached_position(self):
        usage_vm = FakeUsageViewModel(snapshot())
        usage_vm.widget_legacy_offset = (35, -18)
        controller, pet, _, _ = self.controller(usage_vm)
        migrated_position = controller.window.pos()
        self.assertTrue(usage_vm.widget_detached)
        self.assertEqual(
            (usage_vm.widget_placement.x, usage_vm.widget_placement.y),
            (migrated_position.x(), migrated_position.y()),
        )
        pet.move(300, 260)
        self.app.processEvents()
        self.assertEqual(controller.window.pos(), migrated_position)

        restored_vm = FakeUsageViewModel(snapshot())
        restored_vm.widget_detached = True
        restored_vm.widget_placement = usage_vm.widget_placement
        restored, _, _, _ = self.controller(restored_vm)
        self.assertEqual(restored.window.pos(), migrated_position)


if __name__ == "__main__":
    unittest.main()
