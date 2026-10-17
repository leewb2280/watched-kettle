"""Replace the main icon embedded in a Windows executable with an .ico file.

The settings bundle ships Electron's electron.exe renamed, which still carries
Electron's icon; the taskbar and Explorer read that resource, not the name.
"""

from __future__ import annotations

import argparse
import ctypes
import struct
from ctypes import wintypes
from pathlib import Path


RT_ICON = 3
RT_GROUP_ICON = 14
LOAD_AS_RESOURCE = 0x00000002 | 0x00000020

_ICONDIR = struct.Struct("<HHH")
_ICONDIRENTRY = struct.Struct("<BBBBHHII")
_GRPICONDIRENTRY = struct.Struct("<BBBBHHIH")

_ENUM_NAMES = ctypes.WINFUNCTYPE(
    wintypes.BOOL, wintypes.HMODULE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
)
_ENUM_LANGUAGES = ctypes.WINFUNCTYPE(
    wintypes.BOOL,
    wintypes.HMODULE,
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.WORD,
    ctypes.c_void_p,
)


def _kernel32():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LoadLibraryExW.restype = wintypes.HMODULE
    kernel32.LoadLibraryExW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.HANDLE,
        wintypes.DWORD,
    )
    kernel32.FreeLibrary.argtypes = (wintypes.HMODULE,)
    kernel32.EnumResourceNamesW.argtypes = (
        wintypes.HMODULE,
        ctypes.c_void_p,
        _ENUM_NAMES,
        ctypes.c_void_p,
    )
    kernel32.EnumResourceLanguagesW.argtypes = (
        wintypes.HMODULE,
        ctypes.c_void_p,
        ctypes.c_void_p,
        _ENUM_LANGUAGES,
        ctypes.c_void_p,
    )
    kernel32.FindResourceExW.restype = ctypes.c_void_p
    kernel32.FindResourceExW.argtypes = (
        wintypes.HMODULE,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.WORD,
    )
    kernel32.LoadResource.restype = ctypes.c_void_p
    kernel32.LoadResource.argtypes = (wintypes.HMODULE, ctypes.c_void_p)
    kernel32.LockResource.restype = ctypes.c_void_p
    kernel32.LockResource.argtypes = (ctypes.c_void_p,)
    kernel32.SizeofResource.restype = wintypes.DWORD
    kernel32.SizeofResource.argtypes = (wintypes.HMODULE, ctypes.c_void_p)
    kernel32.BeginUpdateResourceW.restype = wintypes.HANDLE
    kernel32.BeginUpdateResourceW.argtypes = (wintypes.LPCWSTR, wintypes.BOOL)
    kernel32.UpdateResourceW.argtypes = (
        wintypes.HANDLE,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.WORD,
        ctypes.c_void_p,
        wintypes.DWORD,
    )
    kernel32.EndUpdateResourceW.argtypes = (wintypes.HANDLE, wintypes.BOOL)
    return kernel32


def _check(result, action: str):
    if not result:
        raise OSError(ctypes.get_last_error(), f"{action} failed")
    return result


def _resource_key(pointer: int | None) -> int | str:
    value = pointer or 0
    return value if value >> 16 == 0 else ctypes.wstring_at(value)


def _resource_pointer(key: int | str):
    return ctypes.c_void_p(key) if isinstance(key, int) else ctypes.c_wchar_p(key)


def read_ico(path: Path) -> list[tuple[bytes, bytes]]:
    """Return (group entry without ID, image bytes) for each .ico image."""
    data = path.read_bytes()
    reserved, kind, count = _ICONDIR.unpack_from(data)
    if reserved != 0 or kind != 1 or count == 0:
        raise ValueError(f"Not an icon file: {path}")
    images = []
    for index in range(count):
        offset = _ICONDIR.size + index * _ICONDIRENTRY.size
        *header, size, start = _ICONDIRENTRY.unpack_from(data, offset)
        image = data[start : start + size]
        if len(image) != size:
            raise ValueError(f"Truncated icon image {index} in {path}")
        images.append((struct.pack("<BBBBHHI", *header, size), image))
    return images


def read_icon_groups(executable: Path) -> dict[int | str, dict[int, list[int]]]:
    """Return {group name: {language: [RT_ICON IDs]}} in resource order."""
    kernel32 = _kernel32()
    module = _check(
        kernel32.LoadLibraryExW(str(executable), None, LOAD_AS_RESOURCE),
        "LoadLibraryExW",
    )
    try:
        names: list[int | str] = []

        @_ENUM_NAMES
        def collect_name(_module, _kind, name, _param):
            names.append(_resource_key(name))
            return True

        kernel32.EnumResourceNamesW(module, RT_GROUP_ICON, collect_name, None)
        groups: dict[int | str, dict[int, list[int]]] = {}
        for name in names:
            languages: list[int] = []

            @_ENUM_LANGUAGES
            def collect_language(_module, _kind, _name, language, _param):
                languages.append(language)
                return True

            pointer = _resource_pointer(name)
            kernel32.EnumResourceLanguagesW(
                module, RT_GROUP_ICON, pointer, collect_language, None
            )
            groups[name] = {}
            for language in languages:
                found = _check(
                    kernel32.FindResourceExW(module, RT_GROUP_ICON, pointer, language),
                    "FindResourceExW",
                )
                size = kernel32.SizeofResource(module, found)
                address = kernel32.LockResource(kernel32.LoadResource(module, found))
                data = ctypes.string_at(address, size)
                count = _ICONDIR.unpack_from(data)[2]
                groups[name][language] = [
                    _GRPICONDIRENTRY.unpack_from(
                        data, _ICONDIR.size + index * _GRPICONDIRENTRY.size
                    )[-1]
                    for index in range(count)
                ]
        return groups
    finally:
        kernel32.FreeLibrary(module)


def read_icon_ids(executable: Path) -> list[int]:
    """Return every numeric RT_ICON ID in the executable."""
    kernel32 = _kernel32()
    module = _check(
        kernel32.LoadLibraryExW(str(executable), None, LOAD_AS_RESOURCE),
        "LoadLibraryExW",
    )
    try:
        ids: list[int] = []

        @_ENUM_NAMES
        def collect(_module, _kind, name, _param):
            key = _resource_key(name)
            if isinstance(key, int):
                ids.append(key)
            return True

        kernel32.EnumResourceNamesW(module, RT_ICON, collect, None)
        return ids
    finally:
        kernel32.FreeLibrary(module)


def set_exe_icon(executable: Path, icon: Path) -> None:
    """Replace the first icon group, which Windows shows for the file."""
    images = read_ico(icon)
    groups = read_icon_groups(executable)
    if not groups:
        raise ValueError(f"Executable has no icon group to replace: {executable}")
    name, languages = next(iter(groups.items()))
    next_id = max(read_icon_ids(executable), default=0) + 1
    kernel32 = _kernel32()
    handle = _check(
        kernel32.BeginUpdateResourceW(str(executable), False), "BeginUpdateResourceW"
    )
    try:
        for language, old_ids in languages.items():
            for old_id in old_ids:
                _check(
                    kernel32.UpdateResourceW(
                        handle, RT_ICON, old_id, language, None, 0
                    ),
                    "UpdateResourceW (remove icon)",
                )
            new_ids = old_ids[: len(images)]
            while len(new_ids) < len(images):
                new_ids.append(next_id)
                next_id += 1
            group = _ICONDIR.pack(0, 1, len(images))
            for icon_id, (entry, image) in zip(new_ids, images, strict=True):
                buffer = ctypes.create_string_buffer(image, len(image))
                _check(
                    kernel32.UpdateResourceW(
                        handle, RT_ICON, icon_id, language, buffer, len(image)
                    ),
                    "UpdateResourceW (icon)",
                )
                group += entry + struct.pack("<H", icon_id)
            buffer = ctypes.create_string_buffer(group, len(group))
            _check(
                kernel32.UpdateResourceW(
                    handle,
                    RT_GROUP_ICON,
                    _resource_pointer(name),
                    language,
                    buffer,
                    len(group),
                ),
                "UpdateResourceW (icon group)",
            )
    except BaseException:
        kernel32.EndUpdateResourceW(handle, True)
        raise
    _check(kernel32.EndUpdateResourceW(handle, False), "EndUpdateResourceW")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("icon", type=Path)
    args = parser.parse_args()
    set_exe_icon(args.executable, args.icon)
    print(f"Icon replaced: {args.executable}")


if __name__ == "__main__":
    main()
