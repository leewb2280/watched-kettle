"""Bounded process metrics for synthetic tests; no per-sample ctypes types."""

from __future__ import annotations

import os
from functools import lru_cache
from time import process_time


@lru_cache(maxsize=1)
def _windows_api():
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
            (name, ctypes.c_size_t)
            for name in (
                "peak_working_set",
                "working_set",
                "peak_paged",
                "paged",
                "peak_nonpaged",
                "nonpaged",
                "pagefile",
                "peak_pagefile",
                "private_bytes",
            )
        ]

    api = ctypes.WinDLL("psapi", use_last_error=True)
    query = api.GetProcessMemoryInfo
    query.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    query.restype = wintypes.BOOL
    return ctypes, wintypes, Counters, query


def process_memory(handle=-1):
    if os.name != "nt":
        return {"memory_status": "unsupported"}
    ctypes, wintypes, counters_type, query = _windows_api()
    counters = counters_type()
    counters.cb = ctypes.sizeof(counters)
    if not query(wintypes.HANDLE(handle), ctypes.byref(counters), counters.cb):
        return {"memory_status": "unavailable"}
    return {
        "memory_status": "available",
        "private_bytes": counters.private_bytes,
        "working_set_bytes": counters.working_set,
    }


def current_resources():
    return {"cpu_seconds": round(process_time(), 3), **process_memory()}
