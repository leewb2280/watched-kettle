"""Acrylic behind the usage widget: where it is allowed and how it falls back."""

import ctypes
import os
from types import SimpleNamespace
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from tests.test_widget_state import claude, codex, snapshot
from watched_kettle.ui.usage_widget import backdrop
from watched_kettle.ui.usage_widget.backdrop import (
    ACCENT_DISABLED,
    ACCENT_ENABLE_ACRYLICBLURBEHIND,
    DARK_TINT,
    DWMWCP_DEFAULT,
    DWMWCP_ROUND,
    LIGHT_TINT,
    Backdrop,
    acrylic_allowed,
    acrylic_available,
)
from watched_kettle.ui.usage_widget.window import (
    GLASS_PREVIEW_DARK,
    GLASS_PREVIEW_LIGHT,
    QuickUsageWindow,
    use_software_renderer,
    widget_theme,
)


class FakeUser32:
    def __init__(self, result=1):
        self.result = result
        self.accents = []

    def SetWindowCompositionAttribute(self, hwnd, data):
        policy = ctypes.cast(
            data._obj.Data, ctypes.POINTER(backdrop._AccentPolicy)
        ).contents
        self.accents.append((hwnd, policy.AccentState, policy.GradientColor))
        return self.result


class FakeDwmapi:
    def __init__(self):
        self.corners = []

    def DwmSetWindowAttribute(self, hwnd, attribute, value, size):
        self.corners.append((hwnd, value._obj.value))
        return 0


def version(build):
    return SimpleNamespace(major=10, build=build)


class AvailabilityTests(unittest.TestCase):
    def test_only_windows_11_offers_acrylic(self):
        self.assertFalse(acrylic_available("linux", version(26000)))
        self.assertFalse(acrylic_available("win32", version(19045)))
        self.assertTrue(acrylic_available("win32", version(22000)))

    def test_transparency_off_or_high_contrast_falls_back(self):
        self.assertTrue(acrylic_allowed(True, True, False))
        self.assertFalse(acrylic_allowed(False, True, False))
        self.assertFalse(acrylic_allowed(True, False, False))
        self.assertFalse(acrylic_allowed(True, True, True))


class BackdropTests(unittest.TestCase):
    def make(self, allowed=True, result=1):
        user32, dwmapi = FakeUser32(result), FakeDwmapi()
        return Backdrop(user32, dwmapi, allowed=lambda: allowed), user32, dwmapi

    def test_acrylic_turns_on_once_and_off_again(self):
        target, user32, dwmapi = self.make()
        self.assertTrue(target.apply(7, "acrylic", dark=False))
        self.assertTrue(target.apply(7, "acrylic", dark=False))
        self.assertEqual(
            user32.accents, [(7, ACCENT_ENABLE_ACRYLICBLURBEHIND, LIGHT_TINT)]
        )
        self.assertEqual(dwmapi.corners, [(7, DWMWCP_ROUND)])

        # A theme switch re-tints the same window.
        self.assertTrue(target.apply(7, "acrylic", dark=True))
        self.assertEqual(user32.accents[-1][2], DARK_TINT)

        self.assertFalse(target.apply(7, "opaque", dark=True))
        self.assertEqual(user32.accents[-1][1], ACCENT_DISABLED)
        self.assertEqual(dwmapi.corners[-1], (7, DWMWCP_DEFAULT))
        self.assertFalse(target.active)

    def test_opaque_never_touches_windows_and_refusals_fall_back(self):
        target, user32, _dwmapi = self.make()
        self.assertFalse(target.apply(7, "opaque", dark=False))
        self.assertFalse(target.apply(0, "acrylic", dark=False))
        self.assertEqual(user32.accents, [])

        refused, user32, dwmapi = self.make(result=0)
        self.assertFalse(refused.apply(7, "acrylic", dark=False))
        self.assertEqual(dwmapi.corners, [])
        # The same refused state is not retried every minute.
        refused.apply(7, "acrylic", dark=False)
        self.assertEqual(len(user32.accents), 1)

    def test_turning_transparency_off_removes_acrylic(self):
        allowed = [True]
        user32, dwmapi = FakeUser32(), FakeDwmapi()
        target = Backdrop(user32, dwmapi, allowed=lambda: allowed[0])
        self.assertTrue(target.apply(7, "acrylic", dark=False))
        allowed[0] = False
        self.assertFalse(target.apply(7, "acrylic", dark=False))
        self.assertEqual(user32.accents[-1][1], ACCENT_DISABLED)


class GlassThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        use_software_renderer()

    def test_live_glass_keeps_text_colors_and_ignores_custom_color(self):
        theme = widget_theme("light", background="#263246", opacity=30, glass="live")
        light = widget_theme("light")
        self.assertTrue(theme["glass"])
        self.assertTrue(theme["float_surface"].startswith("#01"))
        self.assertEqual(theme["float_muted"], light["float_muted"])
        self.assertEqual(theme["float_ink"], light["float_ink"])
        self.assertFalse(theme["halo"])

    def test_preview_stands_in_with_the_measured_tone(self):
        self.assertEqual(
            widget_theme("light", glass="preview")["float_surface"].upper(),
            "#FF" + GLASS_PREVIEW_LIGHT[1:].upper(),
        )
        self.assertEqual(
            widget_theme("dark", glass="preview")["float_surface"].upper(),
            "#FF" + GLASS_PREVIEW_DARK[1:].upper(),
        )

    def test_glass_drops_the_shadow_margin_without_qml_warnings(self):
        window = QuickUsageWindow()
        warnings = []
        window.engine().warnings.connect(
            lambda items: warnings.extend(item.toString() for item in items)
        )
        self.addCleanup(window.close)
        sizes = {}
        for material in ("opaque", "acrylic"):
            context = {"layout": "rings", "material": material, "glass": "preview"}
            window.context = lambda context=context: context
            window.apply_snapshot(snapshot(codex(), claude()))
            for _ in range(5):
                self.app.processEvents()
            root = window.rootObject()
            sizes[material] = (root.width(), root.height())
        # Three one-pixel shadow rings on each side.
        self.assertEqual(sizes["opaque"][0] - sizes["acrylic"][0], 6)
        self.assertEqual(sizes["opaque"][1] - sizes["acrylic"][1], 6)
        self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()
