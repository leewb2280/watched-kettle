"""Windows 11 acrylic behind the usage widget, with an opaque fallback.

A see-through card only lets the desktop show through: a light card at 48%
over a dark wallpaper turns dark gray. Acrylic blurs what is behind and keeps
the card's light or dark tone (stage 14 prototype: light stayed at 223, dark
at 34 over a dark editor). It is drawn by DWM through
``SetWindowCompositionAttribute`` with ``ACCENT_ENABLE_ACRYLICBLURBEHIND``.
The documented ``DWMWA_SYSTEMBACKDROP_TYPE`` was not used: DWM removes it
when a window loses focus, and the widget never takes focus.

The accent API is undocumented, so every failure falls back to the opaque
card. Its tint alpha is ignored by DWM; only the tint color's brightness
picks the light or dark result.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys

from watched_kettle.application.logging import log_event

OPAQUE = "opaque"
ACRYLIC = "acrylic"
# Windows 11 starts at build 22000; acrylic was checked there only.
MIN_ACRYLIC_BUILD = 22000

WCA_ACCENT_POLICY = 19
ACCENT_DISABLED = 0
ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
# Tells DWM to use GradientColor as the tint.
ACCENT_FLAG_GRADIENT = 2
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_DEFAULT = 0
DWMWCP_ROUND = 2
SPI_GETHIGHCONTRAST = 0x0042
HCF_HIGHCONTRASTON = 0x00000001
_PERSONALIZE = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"

# Card tints (AABBGGRR); DWM ignores the alpha.
LIGHT_TINT = 0xFFF3F8F7
DARK_TINT = 0xFF21251D


class _AccentPolicy(ctypes.Structure):
    _fields_ = [
        ("AccentState", ctypes.c_int),
        ("AccentFlags", ctypes.c_int),
        ("GradientColor", ctypes.c_uint),
        ("AnimationId", ctypes.c_int),
    ]


class _CompositionData(ctypes.Structure):
    _fields_ = [
        ("Attribute", ctypes.c_int),
        ("Data", ctypes.c_void_p),
        ("SizeOfData", ctypes.c_size_t),
    ]


class _HighContrast(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("dwFlags", ctypes.c_uint),
        ("lpszDefaultScheme", ctypes.c_wchar_p),
    ]


def acrylic_available(platform=sys.platform, version=None):
    """Whether this Windows can draw acrylic behind the widget at all."""
    if platform != "win32":
        return False
    try:
        version = version or sys.getwindowsversion()
    except AttributeError:
        return False
    return version.major >= 10 and version.build >= MIN_ACRYLIC_BUILD


def transparency_enabled():
    """Windows Settings > Personalization > Colors > Transparency effects."""
    if os.name != "nt":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _PERSONALIZE) as key:
            value, _kind = winreg.QueryValueEx(key, "EnableTransparency")
        return bool(value)
    except OSError:
        # Missing on some installs; Windows treats that as enabled.
        return True


def high_contrast():
    if os.name != "nt":
        return False
    try:
        info = _HighContrast(ctypes.sizeof(_HighContrast), 0, None)
        ok = ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETHIGHCONTRAST, ctypes.sizeof(info), ctypes.byref(info), 0
        )
        return bool(ok) and bool(info.dwFlags & HCF_HIGHCONTRASTON)
    except (AttributeError, OSError):
        return False


def acrylic_allowed(available=None, transparency=None, contrast=None):
    """Acrylic only where supported, with transparency on and no high contrast."""
    available = acrylic_available() if available is None else available
    if not available:
        return False
    transparency = transparency_enabled() if transparency is None else transparency
    contrast = high_contrast() if contrast is None else contrast
    return bool(transparency) and not contrast


def _set_accent(user32, hwnd, state, tint):
    policy = _AccentPolicy(
        state, ACCENT_FLAG_GRADIENT if state != ACCENT_DISABLED else 0, tint, 0
    )
    data = _CompositionData(
        WCA_ACCENT_POLICY,
        ctypes.cast(ctypes.pointer(policy), ctypes.c_void_p),
        ctypes.sizeof(policy),
    )
    return bool(user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data)))


def _set_corners(dwmapi, hwnd, preference):
    value = ctypes.c_int(preference)
    return (
        dwmapi.DwmSetWindowAttribute(
            hwnd,
            DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(value),
            ctypes.sizeof(value),
        )
        == 0
    )


class Backdrop:
    """Apply one window's material and remember what DWM now draws.

    ``user32`` and ``dwmapi`` are injectable for tests. ``active`` is true
    only while acrylic is really on, so the widget knows whether to drop its
    own card fill, border and shadow.
    """

    def __init__(self, user32=None, dwmapi=None, allowed=acrylic_allowed):
        self._user32 = user32
        self._dwmapi = dwmapi
        self._allowed = allowed
        self._applied = None
        self.active = False

    def _libraries(self):
        if self._user32 is None:
            self._user32 = ctypes.windll.user32
            self._dwmapi = ctypes.windll.dwmapi
        return self._user32, self._dwmapi

    def apply(self, hwnd, material, dark):
        """Turn acrylic on or off; return whether acrylic is now drawn."""
        want = material == ACRYLIC and bool(hwnd) and self._allowed()
        state = (int(hwnd or 0), want, bool(dark))
        if state == self._applied:
            return self.active
        if not want and not self.active:
            self._applied = state
            return False
        try:
            user32, dwmapi = self._libraries()
            if want:
                tint = DARK_TINT if dark else LIGHT_TINT
                ok = _set_accent(user32, hwnd, ACCENT_ENABLE_ACRYLICBLURBEHIND, tint)
                if ok:
                    _set_corners(dwmapi, hwnd, DWMWCP_ROUND)
            else:
                _set_accent(user32, hwnd, ACCENT_DISABLED, 0)
                _set_corners(dwmapi, hwnd, DWMWCP_DEFAULT)
                ok = False
        except (AttributeError, OSError, ValueError) as error:
            ok = False
            log_event(
                "usage.widget",
                "backdrop_fallback",
                logging.WARNING,
                reason=type(error).__name__,
            )
        else:
            if want and not ok:
                log_event(
                    "usage.widget",
                    "backdrop_fallback",
                    logging.WARNING,
                    reason="accent_refused",
                )
        self._applied = state
        self.active = bool(want and ok)
        return self.active
