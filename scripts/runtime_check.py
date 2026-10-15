"""External runtime verdict: child observation is not proof of process exit."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import sysconfig
import time
from typing import Any
from watched_kettle.process_metrics import current_resources
from scripts.memory_metrics import MemoryTrend


def source_command(source_root, arguments, *, diagnostics=False):
    """Bypass Windows venv redirectors so Popen owns the measured interpreter."""
    module = "scripts.runtime_memory_probe" if diagnostics else "watched_kettle"
    bootstrap = (
        "import sys,site,runpy; "
        f"site.addsitedir({sysconfig.get_path('purelib')!r}); "
        f"sys.path.insert(0, {str(Path(source_root).resolve())!r}); "
        f"runpy.run_module({module!r}, run_name='__main__')"
    )
    return [
        getattr(sys, "_base_executable", sys.executable),
        "-c",
        bootstrap,
        *arguments,
    ]


def process_memory(process):
    from watched_kettle.process_metrics import process_memory as query

    return query(int(process._handle)) if os.name == "nt" else query()


def read_report(path):
    try:
        if path.stat().st_size > 1024 * 1024:
            return {}
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def read_observation(path):
    timeline = path.with_suffix(".samples.jsonl")
    if not timeline.exists():
        return read_report(path)
    try:
        with timeline.open("rb") as stream:
            size = os.fstat(stream.fileno()).st_size
            start = max(0, size - 1024 * 1024)
            stream.seek(start)
            lines = stream.read(size - start).split(b"\n")
        # Ignore the partial leading/trailing record while the child appends.
        for line in reversed(lines[1:-1] if start else lines[:-1]):
            try:
                value = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            if isinstance(value, dict):
                return value
    except OSError:
        pass
    return {}


def assess(observation, exit_code, duration):
    issues = []
    if observation.get("status") != "observation_complete":
        issues.append("observation_incomplete")
    if exit_code != 0:
        issues.append("process_exit_failed")
    elapsed = observation.get("elapsed_seconds", 0)
    if elapsed < duration:
        issues.append("duration_short")
    if elapsed <= 0 or observation.get("ticks", 0) / (elapsed / 0.1) < 0.9:
        issues.append("tick_coverage_low")
    if observation.get("max_event_loop_gap_seconds", 0) >= 5:
        issues.append("event_loop_gap")
    for field in (
        "tray_required",
        "tray_created",
        "tray_initial_checked",
        "tray_checked",
        "tray_closed",
        "storage_available",
    ):
        if not observation.get(field):
            issues.append(field + "_missing")
    if observation.get("lifecycle_errors") or observation.get("initialization_error"):
        issues.append("lifecycle_error")
    return issues


def supervise(
    command,
    report,
    duration,
    *,
    startup_timeout=30,
    exit_timeout=10,
    memory_limit=1024**3,
    resource_reader=process_memory,
    supervisor_resource_reader=current_resources,
):
    report = Path(report)
    if report.exists():
        raise ValueError("Use a new report path for each run")
    report.parent.mkdir(parents=True, exist_ok=True)
    executable = Path(command[0]).resolve()
    metadata = {
        "executable": str(executable),
        "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": duration,
    }
    started = time.monotonic()
    startup = complete = None
    observation: dict[str, Any] = {}
    failure = None
    child_memory = MemoryTrend(duration)
    supervisor_memory = MemoryTrend(duration)
    next_sample = 0.0
    next_memory = 0.0
    observation_identity = None
    resources = {}
    own_resources = {}
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
    )
    metadata["pid"] = process.pid
    report.with_suffix(".process.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    try:
        while process.poll() is None:
            now = time.monotonic()
            timeline = report.with_suffix(".samples.jsonl")
            candidate = timeline if timeline.exists() else report
            try:
                stat = candidate.stat()
                identity = (str(candidate), stat.st_size, stat.st_mtime_ns)
            except OSError:
                identity = None
            if identity != observation_identity:
                observation = read_observation(report) or observation
                observation_identity = identity
            if observation and startup is None:
                startup = now
            if (
                observation.get("status") in ("observation_complete", "failed")
                and complete is None
            ):
                complete = now
            if now >= next_memory:
                resources = resource_reader(process)
                own_resources = supervisor_resource_reader()
                next_memory = now + 1.0
            if now >= next_sample:
                sample = {
                    "elapsed_seconds": now - started,
                    **resources,
                    "supervisor_resources": own_resources,
                    "child_cpu_seconds": observation.get("latest_resources", {}).get(
                        "cpu_seconds"
                    ),
                    "ticks": observation.get("ticks"),
                    "tray_objects": observation.get("tray_objects"),
                }
                child_memory.add(sample["elapsed_seconds"], resources)
                supervisor_memory.add(sample["elapsed_seconds"], own_resources)
                with report.with_suffix(".supervisor.jsonl").open(
                    "a", encoding="utf-8"
                ) as stream:
                    stream.write(json.dumps(sample) + "\n")
                next_sample = now + 10
            if resources.get("private_bytes", 0) > memory_limit:
                failure = "memory_limit"
            elif own_resources.get("private_bytes", 0) > 256 * 1024**2:
                failure = "supervisor_memory_limit"
            elif startup is None and now - started > startup_timeout:
                failure = "startup_timeout"
            elif complete is not None and now - complete > exit_timeout:
                failure = "exit_timeout"
            elif startup is not None and now - startup > duration + exit_timeout:
                failure = "runtime_timeout"
            observed_pid = observation.get("latest_resources", {}).get("process_id")
            if observed_pid is not None and observed_pid != process.pid:
                failure = "process_identity_mismatch"
            if failure:
                process.kill()
                break
            time.sleep(0.05)
        process.wait(timeout=10)
    except Exception as error:
        failure = "supervisor_" + type(error).__name__
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
    observation = read_report(report) or observation
    issues = assess(observation, process.returncode, duration)
    if failure:
        issues.append(failure)
    memory_growth = None
    if duration >= 600:
        late = child_memory.after_warmup
        if late.samples < 2 or late.missing:
            issues.append("memory_samples_missing")
        else:
            memory_growth = late.growth_bytes
            if memory_growth > 32 * 1024**2:
                issues.append("memory_growth")
    own_growth = None
    if duration >= 600:
        own_late = supervisor_memory.after_warmup
        if own_late.samples < 2 or own_late.missing:
            issues.append("supervisor_memory_samples_missing")
        else:
            own_growth = own_late.growth_bytes
            if own_growth > 32 * 1024**2:
                issues.append("supervisor_memory_growth")
    finished_at = datetime.now(timezone.utc)
    cleanup_seconds = time.monotonic() - complete if complete is not None else None
    if cleanup_seconds is None and observation.get("observation_finished_at_utc"):
        try:
            cleanup_seconds = max(
                0.0,
                (
                    finished_at
                    - datetime.fromisoformat(observation["observation_finished_at_utc"])
                ).total_seconds(),
            )
        except (ValueError, TypeError):
            issues.append("cleanup_timestamp_invalid")
    if cleanup_seconds is not None and cleanup_seconds > exit_timeout:
        if "exit_timeout" not in issues:
            issues.append("exit_timeout")
    result = {
        **metadata,
        "app_version": observation.get("app_version"),
        "status": "failed" if issues else "passed",
        "issues": issues,
        "exit_code": process.returncode,
        "process_exited": True,
        "wall_seconds": time.monotonic() - started,
        "cleanup_seconds": cleanup_seconds,
        "finished_at_utc": finished_at.isoformat(),
        "late_private_growth_bytes": memory_growth,
        "supervisor_late_private_growth_bytes": own_growth,
        "memory_trends": {
            "child": child_memory.summary(),
            "supervisor": supervisor_memory.summary(),
        },
        "observation": observation,
    }
    report.with_suffix(".verdict.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    return result


def main():
    parser = argparse.ArgumentParser()
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--executable", type=Path)
    target.add_argument("--source", action="store_true")
    parser.add_argument(
        "--source-root", type=Path, default=Path(__file__).resolve().parent.parent
    )
    parser.add_argument("--memory-diagnostics", action="store_true")
    parser.add_argument("--prefill", action="store_true")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--duration-seconds", type=int, default=5)
    args = parser.parse_args()
    if (args.memory_diagnostics or args.prefill) and not args.source:
        parser.error("Memory diagnostics require --source")
    diagnostics = args.memory_diagnostics or args.prefill
    arguments = [
        "--duration-seconds",
        str(args.duration_seconds),
        "--report",
        str(args.report.resolve()),
    ]
    if not diagnostics:
        arguments += ["--runtime-smoke-test", "--require-tray"]
    elif args.prefill:
        arguments += ["--prefill"]
    command = (
        source_command(args.source_root, arguments, diagnostics=diagnostics)
        if args.source
        else [str(args.executable.resolve()), *arguments]
    )
    result = supervise(
        command,
        args.report,
        args.duration_seconds,
    )
    print(
        json.dumps(
            {k: result[k] for k in ("status", "issues", "exit_code", "wall_seconds")},
            indent=2,
        )
    )
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
