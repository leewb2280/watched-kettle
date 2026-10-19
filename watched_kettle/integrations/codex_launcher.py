"""Activate the registered Codex GUI without navigating or resuming a thread."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID
import xml.etree.ElementTree as ET

from watched_kettle.integrations.windows_apps import (
    AppInstallation,
    WindowsApps,
    open_app,
)


CODEX_PACKAGE_FAMILY = "OpenAI.Codex_2p2nqsd0c76g0"


def open_codex(backend=None):
    return open_app("Codex", WindowsCodexLauncher, backend)


class WindowsCodexLauncher(WindowsApps):
    """The packaged app first, then a classic install's registered handler."""

    def __init__(self):
        super().__init__()
        wintypes, ctypes = self.w, self.ctypes
        self.kernel.GetPackagesByPackageFamily.argtypes = (
            wintypes.LPCWSTR,
            ctypes.POINTER(wintypes.UINT),
            ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(wintypes.UINT),
            wintypes.LPWSTR,
        )
        self.kernel.GetPackagesByPackageFamily.restype = wintypes.LONG
        self.kernel.GetPackagePathByFullName.argtypes = (
            wintypes.LPCWSTR,
            ctypes.POINTER(wintypes.UINT),
            wintypes.LPWSTR,
        )
        self.kernel.GetPackagePathByFullName.restype = wintypes.LONG

    def installations(self):
        found = list(self._packages())
        # A classic install must explicitly register the Codex URI handler.
        executable = self.registered_executable("codex")
        if executable and not any(executable == item.executable for item in found):
            found.append(AppInstallation(executable))
        return tuple(found)

    def _packages(self):
        c, w = self.ctypes, self.w
        count, size = w.UINT(), w.UINT()
        result = self.kernel.GetPackagesByPackageFamily(
            CODEX_PACKAGE_FAMILY, c.byref(count), None, c.byref(size), None
        )
        if result != 122 or not 0 < count.value <= 32 or not 0 < size.value <= 65536:
            return
        names, buffer = (w.LPWSTR * count.value)(), c.create_unicode_buffer(size.value)
        if self.kernel.GetPackagesByPackageFamily(
            CODEX_PACKAGE_FAMILY, c.byref(count), names, c.byref(size), buffer
        ):
            return
        for name in names:
            length = w.UINT()
            if (
                self.kernel.GetPackagePathByFullName(name, c.byref(length), None) != 122
                or not 0 < length.value <= 32768
            ):
                continue
            path = c.create_unicode_buffer(length.value)
            if self.kernel.GetPackagePathByFullName(name, c.byref(length), path):
                continue
            root = Path(path.value)
            try:
                manifest = ET.parse(root / "AppxManifest.xml")
                for app in manifest.iter():
                    if app.tag.rsplit("}", 1)[-1] != "Application":
                        continue
                    if not any(
                        node.tag.rsplit("}", 1)[-1] == "Protocol"
                        and node.get("Name") == "codex"
                        for node in app.iter()
                    ):
                        continue
                    executable = (root / app.attrib["Executable"]).resolve()
                    if executable.is_relative_to(root) and executable.is_file():
                        yield AppInstallation(
                            executable, CODEX_PACKAGE_FAMILY + "!" + app.attrib["Id"]
                        )
            except (OSError, ET.ParseError, KeyError):
                continue

    def start(self, installation):
        if not installation.aumid:
            return super().start(installation)
        # Use Windows.Launch, not a protocol activation that changes the page.
        from ctypes import Structure

        c, w = self.ctypes, self.w
        ole = c.OleDLL("ole32")

        class GUID(Structure):
            _fields_ = [("bytes", c.c_ubyte * 16)]

        def guid(value):
            return GUID((c.c_ubyte * 16).from_buffer_copy(UUID(value).bytes_le))

        ole.CoInitializeEx.argtypes = (c.c_void_p, w.DWORD)
        ole.CoInitializeEx.restype = c.c_long
        ole.CoUninitialize.argtypes = ()
        ole.CoCreateInstance.argtypes = (
            c.POINTER(GUID),
            c.c_void_p,
            w.DWORD,
            c.POINTER(GUID),
            c.POINTER(c.c_void_p),
        )
        initialized = ole.CoInitializeEx(None, 2)
        if initialized not in (0, 1, -2147417850):
            return False
        instance = c.c_void_p()
        try:
            clsid = guid("45ba127d-10a8-46ea-8ab7-56ea9078943c")
            iid = guid("2e941141-7f97-4756-ba1d-9decde894a3d")
            ole.CoCreateInstance(
                c.byref(clsid), None, 1, c.byref(iid), c.byref(instance)
            )
            table = c.cast(instance, c.POINTER(c.POINTER(c.c_void_p))).contents
            release = c.WINFUNCTYPE(w.ULONG, c.c_void_p)(table[2])
            try:
                activate = c.WINFUNCTYPE(
                    c.c_long,
                    c.c_void_p,
                    w.LPCWSTR,
                    w.LPCWSTR,
                    w.DWORD,
                    c.POINTER(w.DWORD),
                )(table[3])
                pid = w.DWORD()
                return (
                    activate(instance, installation.aumid, None, 2, c.byref(pid)) == 0
                )
            finally:
                release(instance)
        finally:
            if initialized in (0, 1):
                ole.CoUninitialize()
