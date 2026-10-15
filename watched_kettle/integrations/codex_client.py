"""Small fail-open client used by short-lived Codex hook processes."""

from __future__ import annotations

import os
import sys

from watched_kettle.integrations.codex_hooks import encode_pet_event


WATCHED_KETTLE_SERVER_NAME = "watched-kettle-agent-v1"
CONNECT_TIMEOUT_MS = 500


def configured_pet_server_name():
    """Return the pipe name, honoring the isolation override used by tests."""
    return os.environ.get("WATCHED_KETTLE_SERVER_NAME") or WATCHED_KETTLE_SERVER_NAME


def send_pet_event(payload, server_name=WATCHED_KETTLE_SERVER_NAME):
    """Send one event and require an acknowledgement from the pet process."""
    encoded = encode_pet_event(payload)
    if encoded is None:
        return False
    if os.name == "nt":
        return _send_windows_named_pipe(encoded, server_name)
    return _send_qt_local_socket(encoded, server_name)


def _send_windows_named_pipe(encoded, server_name):
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    wait_named_pipe = kernel32.WaitNamedPipeW
    wait_named_pipe.argtypes = (wintypes.LPCWSTR, wintypes.DWORD)
    wait_named_pipe.restype = wintypes.BOOL
    write_file = kernel32.WriteFile
    write_file.argtypes = (
        wintypes.HANDLE,
        wintypes.LPCVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    )
    write_file.restype = wintypes.BOOL
    read_file = kernel32.ReadFile
    read_file.argtypes = (
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    )
    read_file.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL

    generic_read = 0x80000000
    generic_write = 0x40000000
    open_existing = 3
    error_pipe_busy = 231
    invalid_handle = ctypes.c_void_p(-1).value
    pipe_name = rf"\\.\pipe\{server_name}"

    handle = create_file(
        pipe_name,
        generic_read | generic_write,
        0,
        None,
        open_existing,
        0,
        None,
    )
    if handle == invalid_handle and ctypes.get_last_error() == error_pipe_busy:
        if wait_named_pipe(pipe_name, CONNECT_TIMEOUT_MS):
            handle = create_file(
                pipe_name,
                generic_read | generic_write,
                0,
                None,
                open_existing,
                0,
                None,
            )
    if handle == invalid_handle:
        if os.environ.get("WATCHED_KETTLE_DEBUG") == "1":
            error = ctypes.get_last_error()
            sys.stderr.write(f"pet-hook pipe-error={error}\n")
        return False

    try:
        written = wintypes.DWORD()
        if not write_file(
            handle,
            encoded,
            len(encoded),
            ctypes.byref(written),
            None,
        ) or written.value != len(encoded):
            return False

        response = ctypes.create_string_buffer(16)
        bytes_read = wintypes.DWORD()
        if not read_file(
            handle,
            response,
            len(response),
            ctypes.byref(bytes_read),
            None,
        ):
            return False
        return response.raw[: bytes_read.value].startswith(b"OK\n")
    finally:
        close_handle(handle)


def _send_qt_local_socket(encoded, server_name):
    from PySide6.QtNetwork import QLocalSocket

    socket = QLocalSocket()
    socket.connectToServer(server_name, QLocalSocket.OpenModeFlag.ReadWrite)
    if not socket.waitForConnected(CONNECT_TIMEOUT_MS):
        socket.abort()
        return False

    if socket.write(encoded) != len(encoded):
        socket.abort()
        return False
    socket.flush()
    if not socket.waitForReadyRead(CONNECT_TIMEOUT_MS):
        socket.abort()
        return False
    acknowledged = bytes(socket.readAll()).startswith(b"OK\n")
    socket.disconnectFromServer()
    return acknowledged
