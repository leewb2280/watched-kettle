"""Passive Windows process observation; never launches or terminates the target."""

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time

from watched_kettle.process_metrics import current_resources, process_memory
from scripts.memory_metrics import MemoryTrend


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class WindowsProcess:
    """Keep one process handle open so a recycled PID cannot change the target."""

    def __init__(self, pid, executable):
        if os.name != "nt":
            raise OSError("Windows is required")
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        signatures = {
            "OpenProcess": (
                [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD],
                wintypes.HANDLE,
            ),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
            "WaitForSingleObject": ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
            "GetProcessTimes": (
                [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4,
                wintypes.BOOL,
            ),
            "QueryFullProcessImageNameW": (
                [
                    wintypes.HANDLE,
                    wintypes.DWORD,
                    wintypes.LPWSTR,
                    ctypes.POINTER(wintypes.DWORD),
                ],
                wintypes.BOOL,
            ),
            "GetProcessHandleCount": (
                [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)],
                wintypes.BOOL,
            ),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.kernel, name)
            function.argtypes, function.restype = arguments, result
        self.user.GetGuiResources.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.user.GetGuiResources.restype = wintypes.DWORD
        self.handle = self.kernel.OpenProcess(0x100410, False, pid)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            path = ctypes.create_unicode_buffer(32768)
            length = wintypes.DWORD(len(path))
            if not self.kernel.QueryFullProcessImageNameW(
                self.handle, 0, path, ctypes.byref(length)
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            if Path(path.value).resolve() != Path(executable).resolve():
                raise ValueError("Target executable does not match the requested PID")
            self.identity = {
                "pid": pid,
                "executable": str(Path(path.value).resolve()),
                "sha256": sha256(path.value),
                "created_filetime": self.times()[0],
            }
        except BaseException:
            self.close()
            raise

    def times(self):
        values = [wintypes.FILETIME() for _ in range(4)]
        if not self.kernel.GetProcessTimes(
            self.handle, *(ctypes.byref(v) for v in values)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return tuple((v.dwHighDateTime << 32) | v.dwLowDateTime for v in values)

    def alive(self):
        result = self.kernel.WaitForSingleObject(self.handle, 0)
        if result == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
        return result == 258

    def sample(self):
        created, _, kernel, user = self.times()
        if created != self.identity["created_filetime"]:
            raise ValueError("Process identity changed")
        handles = wintypes.DWORD()
        handles_ok = self.kernel.GetProcessHandleCount(
            self.handle, ctypes.byref(handles)
        )
        result = {
            **process_memory(self.handle),
            "cpu_seconds": (kernel + user) / 10_000_000,
            "handle_count": handles.value if handles_ok else None,
        }
        for name, flag in (("gdi_objects", 0), ("user_objects", 1)):
            ctypes.set_last_error(0)
            count = self.user.GetGuiResources(self.handle, flag)
            result[name] = None if count == 0 and ctypes.get_last_error() else count
        return result

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def observe(
    target,
    report,
    duration,
    *,
    clock=time.monotonic,
    wall=time.time,
    sleep=time.sleep,
    own_reader=current_resources,
    stop_requested=None,
):
    """Return measurement validity separately from memory and manual QA verdicts."""
    if duration <= 0:
        raise ValueError("Duration must be positive")
    report = Path(report)
    samples_path = report.with_suffix(".samples.jsonl")
    metadata_path = report.with_suffix(".process.json")
    if any(path.exists() for path in (report, samples_path, metadata_path)):
        raise ValueError("Use a new report path")
    report.parent.mkdir(parents=True, exist_ok=True)
    started, wall_started = clock(), wall()
    previous, previous_wall = started, wall_started
    next_write = started
    trend, own_trend = MemoryTrend(duration), MemoryTrend(duration)
    issues = set()
    reads = 0
    largest_gap = 0.0
    alive = True
    metadata = {
        **target.identity,
        "observer_pid": os.getpid(),
        "started_at_utc": utc_now(),
        "duration_seconds": duration,
        "mode": "passive",
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    # Exclusive creation preserves prior measurements and interrupted runs.
    with samples_path.open("x", encoding="utf-8") as stream:
        try:
            while True:
                if stop_requested is not None and stop_requested():
                    issues.add("cancelled")
                    break
                now, wall_now = clock(), wall()
                elapsed = now - started
                gap = max(now - previous, wall_now - previous_wall)
                largest_gap = max(largest_gap, gap)
                if gap > 30:
                    issues.add("observation_gap")
                if abs((wall_now - previous_wall) - (now - previous)) > 30:
                    issues.add("clock_discontinuity")
                previous, previous_wall = now, wall_now
                alive = target.alive()
                if not alive:
                    issues.add("target_exited")
                    break
                resources, own = target.sample(), own_reader()
                reads += 1
                if resources.get("memory_status") != "available":
                    issues.add("memory_unavailable")
                if own.get("memory_status") != "available":
                    issues.add("observer_memory_unavailable")
                if any(
                    resources.get(key) is None
                    for key in (
                        "cpu_seconds",
                        "handle_count",
                        "gdi_objects",
                        "user_objects",
                    )
                ):
                    issues.add("counters_unavailable")
                if resources.get("private_bytes", 0) > 1024**3:
                    issues.add("memory_limit")
                if own.get("private_bytes", 0) > 256 * 1024**2:
                    issues.add("observer_memory_limit")
                if now >= next_write or elapsed >= duration:
                    trend.add(elapsed, resources)
                    own_trend.add(elapsed, own)
                    stream.write(
                        json.dumps(
                            {
                                "elapsed_seconds": elapsed,
                                "recorded_at_utc": utc_now(),
                                **resources,
                                "observer_resources": own,
                            }
                        )
                        + "\n"
                    )
                    stream.flush()
                    next_write = now + 10
                if elapsed >= duration:
                    break
                sleep(min(1.0, duration - elapsed))
        except (OSError, ValueError) as error:
            issues.add(type(error).__name__)
    elapsed = clock() - started
    if elapsed < duration:
        issues.add("duration_short")
    result = {
        **metadata,
        "finished_at_utc": utc_now(),
        "elapsed_seconds": elapsed,
        "wall_seconds": wall() - wall_started,
        "reads": reads,
        "max_observation_gap_seconds": largest_gap,
        "target_alive_at_last_check": alive,
        "status": "complete" if not issues else "needs_review",
        "issues": sorted(issues),
        "manual_qa": "not_assessed",
        "memory_trends": {"target": trend.summary(), "observer": own_trend.summary()},
    }
    report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--duration-seconds", type=int, default=3600)
    args = parser.parse_args()
    if args.pid <= 0 or args.duration_seconds <= 0:
        parser.error("PID and duration must be positive")
    target = WindowsProcess(args.pid, args.executable)
    try:
        result = observe(target, args.report, args.duration_seconds)
    finally:
        target.close()
    print(json.dumps({key: result[key] for key in ("status", "issues", "reads")}))
    return 0 if result["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
