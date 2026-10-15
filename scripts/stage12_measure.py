"""Stage 12 performance harness for packaged bundles.

Targets and results are summarized in docs/decisions/0004-stage12-performance.md.
Every launch uses a temporary profile and private IPC names, so the user's
running pet, settings, Codex hooks and startup registration stay untouched.
Reports keep only timings and process counters.

    python -m scripts.stage12_measure startup --executable EXE --edition pet-only --out DIR
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

from watched_kettle.process_metrics import process_memory

MIB = 1024 * 1024
PROBE_FLAG = "--performance-probe"
SAMPLE_INTERVAL_SECONDS = 5.0
LONG_SAMPLE_INTERVAL_SECONDS = 10.0
WINDOW_TIMEOUT_SECONDS = 30.0
SEED_SECONDS = {"pet-only": 15.0, "pet-assistant": 45.0}


def utc_now():
    return datetime.now(timezone.utc)


def nearest_rank(values, percentile):
    ordered = sorted(values)
    if not ordered:
        return None
    return ordered[max(0, math.ceil(percentile / 100 * len(ordered)) - 1)]


def distribution(values):
    values = [value for value in values if value is not None]
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "median": statistics.median(values),
        "p95": nearest_rank(values, 95),
        "min": min(values),
        "max": max(values),
    }


def window_median(samples, start, end, key="total_private_bytes"):
    """Median of samples whose ``t`` lies in [start, end]."""
    values = [
        sample[key]
        for sample in samples
        if start <= sample["t"] <= end and sample.get(key) is not None
    ]
    return statistics.median(values) if values else None


def descendants(root, table):
    """Return root and every descendant pid from a {pid: (parent, name)} table."""
    children = {}
    for pid, (parent, _name) in table.items():
        children.setdefault(parent, []).append(pid)
    found, pending = [], [root]
    while pending:
        pid = pending.pop()
        if pid in found or pid not in table:
            continue
        found.append(pid)
        pending.extend(child for child in children.get(pid, ()) if child != pid)
    return found


def isolated_environment(root, *, server_name=None):
    """Point every user-scoped path and IPC name at the measurement root."""
    suffix = uuid4().hex
    environment = dict(os.environ)
    environment.update(
        LOCALAPPDATA=str(Path(root) / "LocalAppData"),
        WATCHED_KETTLE_INSTANCE_SERVER_NAME=f"watched-kettle-stage12-instance-{suffix}",
        WATCHED_KETTLE_SERVER_NAME=server_name
        or f"watched-kettle-stage12-agent-{suffix}",
        WATCHED_KETTLE_SPOOL_DIRECTORY=str(Path(root) / "spool"),
        WATCHED_KETTLE_HOOK_HEALTH_PATH=str(Path(root) / "hook-health.json"),
    )
    return environment


def read_timeline(path):
    path = Path(path)
    if not path.is_file():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entry = json.loads(line)
            entry["t"] = datetime.fromisoformat(entry["at_utc"]).timestamp()
            events.append(entry)
    return events


def first_event(events, name):
    return next((event for event in events if event["event"] == name), None)


class Windows:
    """Minimal Win32 access for process trees and visible windows."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        self.ctypes, self.wintypes = ctypes, wintypes
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.user = ctypes.WinDLL("user32", use_last_error=True)

        class Entry(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_wchar * 260),
            ]

        self.Entry = Entry
        self.kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD] * 2
        self.kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        for name in ("Process32FirstW", "Process32NextW"):
            function = getattr(self.kernel, name)
            function.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
            function.restype = wintypes.BOOL
        self.kernel.OpenProcess.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.callback_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )
        self.user.EnumWindows.argtypes = [self.callback_type, wintypes.LPARAM]
        self.user.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.user.IsWindowVisible.argtypes = [wintypes.HWND]
        self.user.GetWindowRect.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.RECT),
        ]

    def process_table(self):
        snapshot = self.kernel.CreateToolhelp32Snapshot(0x2, 0)
        if not snapshot or snapshot == self.ctypes.c_void_p(-1).value:
            raise self.ctypes.WinError(self.ctypes.get_last_error())
        table = {}
        try:
            entry = self.Entry()
            entry.dwSize = self.ctypes.sizeof(entry)
            ok = self.kernel.Process32FirstW(snapshot, self.ctypes.byref(entry))
            while ok:
                table[entry.th32ProcessID] = (
                    entry.th32ParentProcessID,
                    entry.szExeFile,
                )
                ok = self.kernel.Process32NextW(snapshot, self.ctypes.byref(entry))
        finally:
            self.kernel.CloseHandle(snapshot)
        return table

    def tree_memory(self, root):
        table = self.process_table()
        processes = []
        for pid in descendants(root, table):
            handle = self.kernel.OpenProcess(0x1000, False, pid)
            if not handle:
                processes.append(
                    {"pid": pid, "name": table[pid][1], "memory_status": "unavailable"}
                )
                continue
            try:
                memory = process_memory(handle)
            finally:
                self.kernel.CloseHandle(handle)
            processes.append({"pid": pid, "name": table[pid][1], **memory})
        available = [p for p in processes if p.get("memory_status") == "available"]
        return {
            "total_private_bytes": sum(p["private_bytes"] for p in available)
            if available
            else None,
            "total_working_set_bytes": sum(p["working_set_bytes"] for p in available)
            if available
            else None,
            "process_count": len(processes),
            "missing": len(processes) - len(available),
            "processes": processes,
        }

    def visible_window_pids(self):
        ctypes, wintypes = self.ctypes, self.wintypes
        found = set()

        def visit(hwnd, _parameter):
            if self.user.IsWindowVisible(hwnd):
                rect = wintypes.RECT()
                self.user.GetWindowRect(hwnd, ctypes.byref(rect))
                if rect.right > rect.left and rect.bottom > rect.top:
                    pid = wintypes.DWORD()
                    self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    found.add(pid.value)
            return True

        self.user.EnumWindows(self.callback_type(visit), 0)
        return found


def kill_tree(pid):
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


class Session:
    """One measurement run: isolated profiles in TEMP, reports under ``out``."""

    def __init__(self, executable, edition, out):
        self.executable = Path(executable).resolve()
        self.edition = edition
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.temp = Path(tempfile.mkdtemp(prefix=f"watched-kettle-stage12-{edition}-"))
        self.windows = Windows()
        self.seed = None

    def close(self):
        # Profiles may hold usage records read from the real Codex logs.
        shutil.rmtree(self.temp, ignore_errors=True)

    def write(self, name, payload):
        path = self.out / f"{name}-{self.edition}.json"
        with path.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, ensure_ascii=False)
        return path

    def describe(self):
        return {
            "edition": self.edition,
            "executable": str(self.executable),
            "sha256": sha256(self.executable),
            "started_at_utc": utc_now().isoformat(),
            "host": host_description(),
        }

    def root(self, name, *, from_seed=True):
        root = self.temp / name
        if from_seed:
            shutil.copytree(self.prepare_seed(), root / "LocalAppData")
        else:
            (root / "LocalAppData").mkdir(parents=True)
        return root

    def prepare_seed(self):
        if self.seed is None:
            root = self.root("seed", from_seed=False)
            process, _ = self.launch(
                root,
                [
                    "--scenario",
                    "idle",
                    "--duration-seconds",
                    str(SEED_SECONDS[self.edition]),
                ],
            )
            if not self.wait_exit(process, SEED_SECONDS[self.edition] + 60):
                raise RuntimeError("seed run did not quit gracefully")
            self.seed = root / "LocalAppData"
        return self.seed

    def launch(self, root, probe_arguments, *, environment=None):
        timeline = Path(root) / f"timeline-{uuid4().hex}.jsonl"
        command = [
            str(self.executable),
            PROBE_FLAG,
            "--report",
            str(timeline),
            *probe_arguments,
        ]
        process = subprocess.Popen(
            command,
            env=environment or isolated_environment(root),
            cwd=str(self.executable.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return process, timeline

    def wait_window(self, process, started):
        while time.perf_counter() - started < WINDOW_TIMEOUT_SECONDS:
            if process.poll() is not None:
                return None
            if process.pid in self.windows.visible_window_pids():
                return time.perf_counter() - started
            time.sleep(0.01)
        return None

    def wait_exit(self, process, timeout):
        try:
            process.wait(timeout=timeout)
            return process.returncode == 0
        except subprocess.TimeoutExpired:
            kill_tree(process.pid)
            process.wait(timeout=10)
            return False

    def sample_until_exit(self, process, timeout, interval, samples_path):
        samples = []
        started = time.perf_counter()
        deadline = started + timeout
        with Path(samples_path).open("x", encoding="utf-8") as stream:
            while process.poll() is None and time.perf_counter() < deadline:
                sample = self.windows.tree_memory(process.pid)
                sample["t"] = utc_now().timestamp()
                sample["elapsed_seconds"] = round(time.perf_counter() - started, 3)
                samples.append(sample)
                stream.write(json.dumps(sample) + "\n")
                stream.flush()
                time.sleep(interval)
        graceful = self.wait_exit(process, 0 if process.poll() is None else 10)
        return samples, graceful


def sha256(path):
    import hashlib

    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def host_description():
    import platform

    return {
        "windows": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
    }


def mib(value):
    return None if value is None else round(value / MIB, 1)


def measure_startup(session, runs):
    results = []
    for index in range(runs):
        root = session.root(f"startup-{index + 1}")
        started = time.perf_counter()
        process, _ = session.launch(
            root, ["--scenario", "idle", "--duration-seconds", "8"]
        )
        shown = session.wait_window(process, started)
        graceful = session.wait_exit(process, 60)
        results.append(
            {"run": index + 1, "window_seconds": shown, "graceful_exit": graceful}
        )
    return {
        "scenario": "S2",
        "runs": results,
        "window_seconds": distribution([r["window_seconds"] for r in results]),
        "cold_start": "not_measured",
    }


def measure_cycle(session, runs, timing):
    results = []
    for index in range(runs):
        root = session.root(f"cycle-{index + 1}")
        process, timeline_path = session.launch(
            root,
            ["--scenario", "settings-cycle", *timing.arguments()],
        )
        samples, graceful = session.sample_until_exit(
            process,
            timing.cycle_total() + 120,
            SAMPLE_INTERVAL_SECONDS,
            session.out / f"cycle-{session.edition}-{index + 1}.samples.jsonl",
        )
        events = read_timeline(timeline_path)
        results.append(
            {
                "run": index + 1,
                "graceful_exit": graceful,
                **cycle_metrics(events, samples, timing),
            }
        )
    return {
        "scenario": "S3",
        "timing": vars(timing),
        "runs": results,
        "idle_private_mib": distribution([r["idle_private_mib"] for r in results]),
        "open_private_mib": distribution([r["open_private_mib"] for r in results]),
        "hidden_private_mib": distribution([r["hidden_private_mib"] for r in results]),
        "first_open_ms": distribution([r["first_open_ms"] for r in results]),
        "reopen_ms": distribution([r["reopen_ms"] for r in results]),
    }


class CycleTiming:
    def __init__(self, warmup=120.0, idle=300.0, open_=120.0, hidden=330.0):
        self.warmup, self.idle, self.open, self.hidden = warmup, idle, open_, hidden

    def arguments(self):
        return [
            "--warmup-seconds", str(self.warmup),
            "--idle-seconds", str(self.idle),
            "--open-seconds", str(self.open),
            "--hidden-seconds", str(self.hidden),
        ]  # fmt: skip

    def cycle_total(self):
        return self.warmup + self.idle + self.open + self.hidden + 60


def cycle_metrics(events, samples, timing):
    def at(name):
        event = first_event(events, name)
        return None if event is None else event

    idle_start, idle_end = at("idle_window_start"), at("idle_window_end")
    opened, hidden = at("settings_open_ready"), at("settings_hidden")
    reopen_requested, reopened = (
        at("settings_reopen_requested"),
        at("settings_reopen_ready"),
    )
    issues = [
        name
        for name, event in (
            ("idle_window_start", idle_start),
            ("settings_open_ready", opened),
            ("settings_hidden", hidden),
            ("settings_reopen_ready", reopened),
        )
        if event is None
    ]
    return {
        "issues": issues,
        "idle_private_mib": mib(window_median(samples, idle_start["t"], idle_end["t"]))
        if idle_start and idle_end
        else None,
        "open_private_mib": mib(window_median(samples, opened["t"], hidden["t"]))
        if opened and hidden
        else None,
        "hidden_private_mib": mib(
            window_median(samples, hidden["t"] + 300, reopen_requested["t"])
        )
        if hidden and reopen_requested
        else None,
        "first_open_ms": opened.get("duration_ms") if opened else None,
        "reopen_ms": reopened.get("duration_ms") if reopened else None,
        "processes_while_hidden": process_names(samples, hidden, reopen_requested),
    }


def process_names(samples, start, end):
    if not start or not end:
        return []
    names = set()
    for sample in samples:
        if start["t"] + 300 <= sample["t"] <= end["t"]:
            names.update(process["name"] for process in sample["processes"])
    return sorted(names)


def measure_long(session, scenario, duration):
    root = session.root(f"long-{scenario}")
    process, timeline_path = session.launch(
        root, ["--scenario", scenario, "--duration-seconds", str(duration)]
    )
    started = utc_now().timestamp()
    samples, graceful = session.sample_until_exit(
        process,
        duration + 120,
        LONG_SAMPLE_INTERVAL_SECONDS,
        session.out / f"long-{scenario}-{session.edition}.samples.jsonl",
    )
    early = window_median(
        samples, started + duration * 25 / 60, started + duration * 30 / 60
    )
    late = window_median(samples, started + duration * 55 / 60, started + duration)
    events = read_timeline(timeline_path)
    return {
        "scenario": "S4",
        "probe_scenario": scenario,
        "duration_seconds": duration,
        "graceful_exit": graceful,
        "samples": len(samples),
        "early_private_mib": mib(early),
        "late_private_mib": mib(late),
        "growth_mib": mib(late - early)
        if early is not None and late is not None
        else None,
        "open_ms": distribution(
            [
                e.get("duration_ms")
                for e in events
                if e["event"] == "settings_open_ready"
            ]
        ),
        "timeouts": [e["event"] for e in events if e["event"].endswith("_timeout")],
    }


def measure_recovery(session, runs):
    settings_runs, app_runs = [], []
    for index in range(runs):
        root = session.root(f"recovery-settings-{index + 1}")
        process, timeline_path = session.launch(
            root, ["--scenario", "settings-recovery", "--warmup-seconds", "20"]
        )
        graceful = session.wait_exit(process, 120)
        events = read_timeline(timeline_path)
        recovered = first_event(events, "settings_recovered_ready")
        settings_runs.append(
            {
                "run": index + 1,
                "graceful_exit": graceful,
                "recovered_ms": recovered.get("duration_ms") if recovered else None,
            }
        )
    for index in range(runs):
        root = session.root(f"recovery-app-{index + 1}")
        process, _ = session.launch(
            root, ["--scenario", "idle", "--duration-seconds", "120"]
        )
        session.wait_window(process, time.perf_counter())
        time.sleep(10)
        kill_tree(process.pid)
        process.wait(timeout=10)
        started = time.perf_counter()
        process, _ = session.launch(
            root, ["--scenario", "idle", "--duration-seconds", "8"]
        )
        shown = session.wait_window(process, started)
        graceful = session.wait_exit(process, 60)
        app_runs.append(
            {"run": index + 1, "window_seconds": shown, "graceful_exit": graceful}
        )
    return {
        "scenario": "S6",
        "settings_child_killed": settings_runs,
        "settings_recovered_ms": distribution(
            [r["recovered_ms"] for r in settings_runs]
        ),
        "app_killed": app_runs,
        "app_restart_window_seconds": distribution(
            [r["window_seconds"] for r in app_runs]
        ),
    }


def measure_hook(session, runs, warmup):
    root = session.root("hook", from_seed=False)
    payloads = [
        json.dumps(
            {"hook_event_name": "PreToolUse", "session_id": f"stage12-{index}"}
        ).encode()
        for index in range(warmup + runs)
    ]
    server_name = f"watched-kettle-stage12-hook-{uuid4().hex}"
    receiver = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "scripts.stage12_measure",
            "receiver",
            "--name",
            server_name,
            "--root",
            str(root / "receiver"),
        ],
        cwd=str(Path(__file__).resolve().parents[1]),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    ready = root / "receiver" / "ready"
    deadline = time.perf_counter() + 30
    while not ready.exists() and time.perf_counter() < deadline:
        time.sleep(0.05)
    try:
        if not ready.exists():
            raise RuntimeError("hook receiver did not start")
        delivered_env = isolated_environment(
            root / "delivered", server_name=server_name
        )
        delivered = time_commands(
            [str(session.executable), "--codex-hook-bridge"], payloads, delivered_env
        )
        received = wait_count(root / "receiver" / "count", len(payloads))
    finally:
        receiver.terminate()
        receiver.wait(timeout=10)
    queued_env = isolated_environment(root / "queued")
    queued = time_commands(
        [str(session.executable), "--codex-hook-bridge"], payloads, queued_env
    )
    floor = time_commands(
        ["cmd.exe", "/c", "exit"], [b""] * len(payloads), dict(os.environ)
    )
    return {
        "scenario": "S5",
        "runs": runs,
        "warmup": warmup,
        "delivered_ms": distribution(delivered[warmup:]),
        "delivered_received": received,
        "delivered_expected": len(payloads),
        "delivered_health": read_health(root / "delivered" / "hook-health.json"),
        "queued_ms": distribution(queued[warmup:]),
        "queued_health": read_health(root / "queued" / "hook-health.json"),
        "queued_files": len(list((root / "queued" / "spool").glob("*"))),
        "floor_ms": distribution(floor[warmup:]),
    }


def time_commands(command, inputs, environment):
    durations = []
    for payload in inputs:
        started = time.perf_counter()
        subprocess.run(
            command,
            input=payload,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
        durations.append(round((time.perf_counter() - started) * 1000, 2))
    return durations


def wait_count(path, expected, timeout=5.0):
    deadline = time.perf_counter() + timeout
    count = 0
    while time.perf_counter() < deadline:
        if path.exists():
            count = int(path.read_text(encoding="utf-8") or 0)
            if count >= expected:
                break
        time.sleep(0.05)
    return count


def read_health(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")).get("outcome")
    except (OSError, ValueError):
        return None


def run_receiver(name, root):
    """Real hook server in an isolated root; counts payloads for the harness."""
    from PySide6.QtCore import QCoreApplication

    from watched_kettle.integrations.codex_ipc import CodexHookServer

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    app = QCoreApplication([])
    server = CodexHookServer(
        server_name=name,
        spool_directory=root / "spool",
        hook_config_path=root / "absent-hooks.json",
        global_hook_config_path=root / "absent-global-hooks.json",
        codex_config_path=root / "absent-config.toml",
        hook_health_path=root / "health.json",
        managed_spool_directory=None,
        managed_hook_health_path=None,
    )
    count = 0

    def received(_payload):
        nonlocal count
        count += 1
        (root / "count").write_text(str(count), encoding="utf-8")

    server.payload_received.connect(received)
    if not server.start():
        return 1
    (root / "ready").write_text("ready", encoding="utf-8")
    return app.exec()


def measure_size(bundle, archive):
    bundle = Path(bundle)

    def tree_size(path):
        files = [item for item in Path(path).rglob("*") if item.is_file()]
        return sum(item.stat().st_size for item in files), len(files)

    total, files = tree_size(bundle)
    electron, electron_files = tree_size(bundle / "settings-ui")
    return {
        "scenario": "S1",
        "bundle_mib": mib(total),
        "bundle_files": files,
        "electron_mib": mib(electron),
        "electron_files": electron_files,
        "other_mib": mib(total - electron),
        "zip_mib": mib(Path(archive).stat().st_size) if archive else None,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    receiver = commands.add_parser("receiver")
    receiver.add_argument("--name", required=True)
    receiver.add_argument("--root", type=Path, required=True)
    size = commands.add_parser("size")
    size.add_argument("--bundle", type=Path, required=True)
    size.add_argument("--zip", type=Path)
    size.add_argument("--edition", required=True)
    size.add_argument("--out", type=Path, required=True)
    for name in ("startup", "cycle", "long", "hook", "recovery"):
        command = commands.add_parser(name)
        command.add_argument("--executable", type=Path, required=True)
        command.add_argument("--edition", choices=tuple(SEED_SECONDS), required=True)
        command.add_argument("--out", type=Path, required=True)
        command.add_argument(
            "--runs", type=int, default={"startup": 5, "hook": 100}.get(name, 3)
        )
    commands.choices["hook"].add_argument("--warmup", type=int, default=5)
    commands.choices["long"].add_argument(
        "--scenario", choices=("idle", "long-mixed"), required=True
    )
    commands.choices["long"].add_argument(
        "--duration-seconds", type=float, default=3600
    )
    args = parser.parse_args(argv)

    if args.command == "receiver":
        return run_receiver(args.name, args.root)
    if args.command == "size":
        args.out.mkdir(parents=True, exist_ok=True)
        path = args.out / f"size-{args.edition}.json"
        result = measure_size(args.bundle, args.zip)
        with path.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2)
        print(json.dumps(result, indent=2))
        return 0

    session = Session(args.executable, args.edition, args.out)
    try:
        description = session.describe()
        if args.command == "startup":
            result = measure_startup(session, args.runs)
        elif args.command == "cycle":
            result = measure_cycle(session, args.runs, CycleTiming())
        elif args.command == "long":
            result = measure_long(session, args.scenario, args.duration_seconds)
        elif args.command == "hook":
            result = measure_hook(session, args.runs, args.warmup)
        else:
            result = measure_recovery(session, args.runs)
        name = args.command + (f"-{args.scenario}" if args.command == "long" else "")
        result = {**description, "finished_at_utc": utc_now().isoformat(), **result}
        session.write(name, result)
        summary = {k: v for k, v in result.items() if k not in {"runs", "host"}}
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
