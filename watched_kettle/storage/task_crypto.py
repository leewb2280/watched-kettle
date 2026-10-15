"""Windows current-user DPAPI protection; never falls back to plaintext."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from typing import Protocol


class ProtectionError(ValueError):
    """A content-free error safe to surface in diagnostics."""


class Protector(Protocol):
    def protect(self, value: bytes, context: bytes) -> bytes: ...

    def unprotect(self, value: bytes, context: bytes) -> bytes: ...


class _Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


class WindowsDataProtector:
    def __init__(self):
        if os.name != "nt":
            raise ProtectionError("windows_protection_unavailable")
        self._crypt = ctypes.WinDLL("crypt32", use_last_error=True)
        self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel.LocalFree.argtypes = [ctypes.c_void_p]
        self._kernel.LocalFree.restype = ctypes.c_void_p
        blob = ctypes.POINTER(_Blob)
        self._crypt.CryptProtectData.argtypes = [
            blob,
            wintypes.LPCWSTR,
            blob,
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            blob,
        ]
        self._crypt.CryptUnprotectData.argtypes = [
            blob,
            ctypes.c_void_p,
            blob,
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            blob,
        ]
        self._crypt.CryptProtectData.restype = wintypes.BOOL
        self._crypt.CryptUnprotectData.restype = wintypes.BOOL

    def _transform(self, value: bytes, context: bytes, *, decrypt: bool) -> bytes:
        if not value or len(value) > 1024 * 1024:
            raise ProtectionError("protected_data_invalid")
        source_buffer = ctypes.create_string_buffer(value)
        entropy_buffer = ctypes.create_string_buffer(context)
        source = _Blob(
            len(value), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte))
        )
        entropy = _Blob(
            len(context), ctypes.cast(entropy_buffer, ctypes.POINTER(ctypes.c_ubyte))
        )
        result = _Blob()
        function = (
            self._crypt.CryptUnprotectData if decrypt else self._crypt.CryptProtectData
        )
        # CRYPTPROTECT_UI_FORBIDDEN; never machine-wide protection.
        success = function(
            ctypes.byref(source),
            None,
            ctypes.byref(entropy),
            None,
            None,
            1,
            ctypes.byref(result),
        )
        try:
            if not success:
                raise ProtectionError("protected_data_unavailable")
            return ctypes.string_at(result.data, result.size)
        finally:
            if result.data:
                self._kernel.LocalFree(ctypes.cast(result.data, ctypes.c_void_p))

    def protect(self, value: bytes, context: bytes) -> bytes:
        return self._transform(value, context, decrypt=False)

    def unprotect(self, value: bytes, context: bytes) -> bytes:
        return self._transform(value, context, decrypt=True)
