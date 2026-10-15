"""Opt-in source runtime diagnostics with isolated synthetic data only.

Run with ``python -m scripts.runtime_memory_probe --report build/probe.json``.
Use --prefill to replace records at the existing history/deduplication caps.
Allocation tracing is a separate experiment, not a process-memory benchmark.
"""

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import monotonic
import tracemalloc
from unittest.mock import patch

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot

from watched_kettle.application.runtime import ApplicationRuntime
from watched_kettle import runtime_smoke


class WorkerProbe(QObject):
    requested = Signal()
    measured = Signal(str, object)

    def __init__(self, name, worker, prefill=False):
        super().__init__()
        self.name = name
        self.worker = worker
        self.prefill = prefill
        self.requested.connect(self.sample, Qt.ConnectionType.QueuedConnection)

    @Slot()
    def sample(self):
        # Traversal and service reads belong to the worker's owning thread.
        assert QThread.currentThread() == self.worker.thread()
        values = {"sampled_at_monotonic": monotonic()}
        values["qobjects"] = len(self.worker.findChildren(QObject))
        if self.name == "usage" and hasattr(self.worker, "service"):
            service = self.worker.service
            if self.prefill and service.snapshot.account_hash:
                stamp = datetime.now(timezone.utc)
                service.measurements.finished.update(
                    (("fixture", str(i)), stamp) for i in range(512)
                )
                service._expire_tasks()
                self.prefill = False
            with self.worker.lock:
                values["commands"] = len(self.worker.commands)
            values.update(
                tasks=len(service.measurements.tasks),
                finished=len(service.measurements.finished),
                requests=len(service.account.requests),
                records=len(service.snapshot.recent_tasks),
            )
        elif self.name == "logs" and self.worker.reader is not None:
            reader = self.worker.reader
            values.update(
                tracked_files=len(reader._positions),
                usage_cursors=len(reader._usage_cursors),
                event_cursors=len(reader._event_cursors),
                partial_bytes=sum(
                    len(c.partial) for c in reader._event_cursors.values()
                ),
            )
        elif self.name == "metadata":
            values.update(
                queued=len(self.worker.queue), pending=len(self.worker.pending)
            )
        self.measured.emit(self.name, values)


class RuntimeProbe(QObject):
    def __init__(self, runtime, report, *, trace=False, prefill=False):
        super().__init__(runtime)
        self.runtime = runtime
        self.report = report
        self.trace = trace
        self.started = monotonic()
        self.closed = False
        self.latest = {}
        self.workers = []
        self.trace_started = False
        for name, worker in (
            ("usage", runtime.usage_service._worker),
            ("logs", runtime.codex_log_monitor._worker),
            ("metadata", runtime.metadata_service.worker),
        ):
            probe = WorkerProbe(name, worker, prefill)
            probe.moveToThread(worker.thread())
            worker.thread().finished.connect(probe.deleteLater)
            probe.measured.connect(self.receive)
            self.workers.append(probe)

    @Slot(str, object)
    def receive(self, name, values):
        self.latest[name] = values

    def sample(self):
        if self.closed:
            return {"closed": True, "workers": dict(self.latest)}
        for probe in self.workers:
            probe.requested.emit()
        runtime = self.runtime
        values = {
            "workers": dict(self.latest),
            "center_qobjects": len(runtime.center.findChildren(QObject)),
            "pet_qobjects": len(runtime.pet.findChildren(QObject)),
            "renderer_cache": runtime.pet.renderer.cache_size,
            "project_seen": len(runtime.projects._seen),
            "project_retired": len(runtime.projects._retired),
            "project_metadata": len(runtime.projects.metadata),
            "project_activities": len(runtime.projects.activities),
            "action_targets": len(runtime.action_router.targets),
        }
        if self.trace:
            values["traced_bytes"] = tracemalloc.get_traced_memory()[0]
            if not self.trace_started and monotonic() - self.started >= 10:
                self.dump("warmup")
                self.trace_started = True
        return values

    def dump(self, suffix):
        self.report.parent.mkdir(parents=True, exist_ok=True)
        snapshot = tracemalloc.take_snapshot()
        snapshot.dump(str(self.report.with_suffix(f".alloc-{suffix}")))
        # Never retain snapshots between samples: that changes the measurement.

    def close(self):
        if not self.closed:
            if self.trace:
                self.dump("final")
            self.closed = True


def seed_history(path):
    from watched_kettle.storage.database import DatabaseManager
    from watched_kettle.storage.usage_repository import SqliteUsageRepository
    from watched_kettle.usage.identifiers import hash_identifier
    from watched_kettle.usage.models import TaskUsageRecord

    database = DatabaseManager(path)
    try:
        if not database.start().available:
            raise RuntimeError("fixture_database_unavailable")
        repository = SqliteUsageRepository(database)
        stamp = datetime.now(timezone.utc)
        for i in range(repository.maximum_records):
            repository.append(
                TaskUsageRecord(
                    stamp - timedelta(seconds=1000 - i),
                    hash_identifier("synthetic-smoke-account"),
                    hash_identifier("fixture-thread"),
                    "done",
                    total_tokens=10,
                    turn_hash=hash_identifier(f"fixture-{i}"),
                )
            )
    finally:
        database.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration-seconds", type=int, default=60)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--trace-allocations", action="store_true")
    parser.add_argument("--prefill", action="store_true")
    args = parser.parse_args()
    probe = None

    class DiagnosticRuntime(ApplicationRuntime):
        def __init__(self, app, pet, preferences, paths, **kwargs):
            if args.prefill:
                seed_history(paths.database)
            super().__init__(app, pet, preferences, paths, **kwargs)
            if args.prefill:
                now = monotonic()
                self.projects._seen.update(
                    (("fixture", str(i), "done", ""), now) for i in range(4096)
                )
                self.projects._retired.update(
                    (("fixture", str(i)), None) for i in range(4096)
                )

        def start(self):
            nonlocal probe
            super().start()
            probe = RuntimeProbe(
                self, args.report, trace=args.trace_allocations, prefill=args.prefill
            )

        def close(self):
            if probe is not None:
                probe.close()
            super().close()

    original_resources = runtime_smoke._resources

    def resources():
        return {
            **original_resources(),
            "memory_diagnostics": probe.sample() if probe is not None else {},
            "allocation_tracing": args.trace_allocations,
            "prefilled": args.prefill,
        }

    if args.trace_allocations:
        tracemalloc.start(8)
    try:
        with (
            patch(
                "watched_kettle.application.runtime.ApplicationRuntime",
                DiagnosticRuntime,
            ),
            patch.object(runtime_smoke, "_resources", resources),
        ):
            return runtime_smoke.run_runtime_smoke(
                [
                    "--require-tray",
                    "--duration-seconds",
                    str(args.duration_seconds),
                    "--report",
                    str(args.report),
                ]
            )
    finally:
        if args.trace_allocations:
            tracemalloc.stop()


if __name__ == "__main__":
    raise SystemExit(main())
