"""Ownership, bounded input and measurement regressions for the v5 boundary."""

import ctypes
import gc
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

from watched_kettle.process_metrics import process_memory, _windows_api
from watched_kettle.storage.database import DatabaseManager
from watched_kettle.storage.usage_repository import SqliteUsageRepository
from watched_kettle.usage.device import parse_device_batch, nonnegative, utc_timestamp
from watched_kettle.usage.account_session import AccountSession, RequestContext
from watched_kettle.integrations.log_tail import TailCursor
from watched_kettle.integrations.usage_log_parser import UsageLogParser


class Boundary154Tests(unittest.TestCase):
    def test_meter_reuses_types_and_remains_bounded(self):
        if os.name != "nt":
            self.skipTest("Windows process counters")
        process_memory()
        misses = _windows_api.cache_info().misses
        # Python 3.14 replaced ctypes._pointer_type_cache with an unsized
        # mapping, so count pointer-type requests instead of the cache size.
        with patch("ctypes.POINTER", wraps=ctypes.POINTER) as pointer:
            for i in range(10000):
                resource = process_memory()
                if i == 4999:
                    gc.collect()
                    warm = process_memory()["private_bytes"]
        gc.collect()
        self.assertEqual(pointer.call_count, 0)
        self.assertEqual(_windows_api.cache_info().misses, misses)
        self.assertLessEqual(process_memory()["private_bytes"] - warm, 2 * 1024**2)
        self.assertEqual(resource["memory_status"], "available")
        with patch("watched_kettle.process_metrics.os.name", "posix"):
            self.assertEqual(process_memory(), {"memory_status": "unsupported"})
        api = _windows_api()
        with patch(
            "watched_kettle.process_metrics._windows_api",
            return_value=(*api[:3], lambda *args: False),
        ):
            self.assertEqual(process_memory(), {"memory_status": "unavailable"})

    def test_number_and_timestamp_boundary(self):
        for value in (None, True, "bad", float("inf"), float("nan"), -1, 2**100):
            self.assertIsNone(nonnegative(value, float))
        self.assertEqual(nonnegative("12"), 12)
        for value in (None, "", "bad", "2026-09-07T12:00:00"):
            self.assertIsNone(utc_timestamp(value))
        self.assertEqual(utc_timestamp("2026-09-07T12:00:00Z").tzinfo, timezone.utc)

    def test_batch_contains_no_account_and_discards_malformed_records(self):
        now = datetime.now(timezone.utc).isoformat()
        records = [
            None,
            {},
            {"event_key": "x", "occurred_at": "bad"},
            {
                "event_key": "bad",
                "occurred_at": now,
                "kind": "token",
                "delta_tokens": True,
            },
            {
                "event_key": "badq",
                "occurred_at": now,
                "kind": "quota",
                "used_percent": "nan",
            },
            {
                "event_key": "t",
                "occurred_at": now,
                "kind": "token",
                "delta_tokens": 7,
                "session_id": "secret",
            },
            {"event_key": "q", "occurred_at": now, "kind": "quota", "used_percent": 23},
            {"event_key": "unknown", "occurred_at": now, "kind": "unknown"},
        ]
        tokens, quotas = parse_device_batch(records)
        self.assertEqual(len(tokens), 1)
        self.assertEqual(len(quotas), 1)
        self.assertFalse(hasattr(tokens[0], "account_hash"))
        self.assertNotIn("secret", repr(tokens))

    def test_account_requests_cannot_cross_generation(self):
        account = AccountSession()
        account.requests[1] = RequestContext(0, "limits")
        self.assertEqual(account.consume(1).kind, "limits")
        self.assertIsNone(account.consume(1))
        account.requests[2] = RequestContext(-1, "limits")
        self.assertIsNone(account.consume(2))
        account.requests[3] = RequestContext(0, "limits")
        account.invalidate()
        self.assertIsNone(account.consume(3))

    def test_shared_tail_yields_partial_oversize_and_replaced_files(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "log"
            path.write_bytes(b"a" * 30 + b"\nok\npart")
            cursor = TailCursor()
            found = []
            for _ in range(20):
                lines, used, count = cursor.read(path, 5, 1, 1, 10, clock=lambda: 0)
                self.assertLessEqual(used, 5)
                self.assertLessEqual(count, 1)
                found.extend(lines)
            self.assertEqual([x[1] for x in found], [b"ok\n"])
            with path.open("ab") as stream:
                stream.write(b"ial\n")
            self.assertEqual(
                cursor.read(path, 100, 20, 1, 10, clock=lambda: 0)[0][0][1],
                b"partial\n",
            )
            self.assertEqual(cursor.read(path, 100, 20, 0, 10, clock=lambda: 1)[1], 0)
            path.write_bytes(b"new\n")
            self.assertEqual(
                cursor.read(path, 100, 20, 1, 10, clock=lambda: 0)[0][0][1], b"new\n"
            )
            self.assertTrue(cursor.replaced)

    def test_usage_regression_keeps_high_water(self):
        now = datetime.now(timezone.utc)
        parser = UsageLogParser(lambda: now, lambda path: "file", lambda r: now)
        parser.extract("f", {"type": "session_meta", "payload": {"id": "s"}}, 0)
        observed = []
        for i, total in enumerate((100, 50, 110, 110)):
            result = parser.extract(
                "f",
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {"total_token_usage": {"total_tokens": total}},
                    },
                },
                i,
            )
            observed.append(
                sum(x["delta_tokens"] for x in result if x["kind"] == "token")
            )
        self.assertEqual(observed, [100, 0, 10, 0])
        self.assertEqual(parser.usage_regression_count, 1)

    def test_v4_history_is_quarantined_and_device_clear_is_independent(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "db.sqlite"
            db = DatabaseManager(path)
            now = datetime.now(timezone.utc)
            old = now - timedelta(minutes=1)
            con = sqlite3.connect(path)
            db._migrate(con, target_version=4)
            con.execute(
                "INSERT INTO usage_local_token_events VALUES (?,?,?,?,?,4)",
                ("old", "wrong-account", "s", old.isoformat(), 70),
            )
            con.execute(
                "INSERT INTO usage_quota_samples VALUES (?,?,?,?,?,?,?,?,4)",
                (
                    "oldq",
                    "wrong-account",
                    "x",
                    "primary",
                    old.isoformat(),
                    50,
                    None,
                    None,
                ),
            )
            con.execute(
                "INSERT INTO usage_import_state VALUES (?,?)", ("a", old.isoformat())
            )
            con.commit()
            con.close()
            self.assertTrue(db.start().available)
            try:
                repo = SqliteUsageRepository(db)
                self.assertEqual(repo.device.tokens(), ())
                self.assertEqual(repo.load_quota_samples("wrong-account"), ())
                self.assertEqual(len(repo.device.legacy()), 2)
                tokens, quotas = parse_device_batch(
                    [
                        {
                            "event_key": "new",
                            "kind": "token",
                            "occurred_at": now.isoformat(),
                            "delta_tokens": 5,
                        }
                    ]
                )
                repo.device.append(tokens, quotas)
                repo.device.append(tokens, quotas)
                self.assertEqual(len(repo.device.tokens()), 1)
                repo.clear("a")
                self.assertEqual(len(repo.device.tokens()), 1)
                repo.device.clear(now + timedelta(seconds=1))
                repo.device.append(tokens, quotas)
                self.assertEqual(repo.device.tokens(), ())
                from watched_kettle.storage.database import SCHEMA_VERSION

                self.assertTrue(
                    tuple(path.parent.glob(f"*.v4-to-v{SCHEMA_VERSION}.*.bak"))
                )
                self.assertNotIn(
                    "account_hash",
                    [
                        x[1]
                        for x in db.connection.execute(
                            "PRAGMA table_info(device_token_events)"
                        )
                    ],
                )
            finally:
                db.close()

    def test_device_events_do_not_wait_for_login_or_move_accounts(self):
        from tests.test_usage_service import UsageServiceTests

        UsageServiceTests.setUpClass()
        fixture = UsageServiceTests()
        fixture.setUp()
        try:
            service = fixture.service
            records = [
                {
                    "kind": "token",
                    "event_key": "test-device",
                    "session_id": "local",
                    "occurred_at": fixture.now.isoformat(),
                    "delta_tokens": 123,
                }
            ]
            service.observe_local_usage_batch(records)
            self.assertEqual(service.snapshot.observed_today_tokens, 123)
            service._reset_account("signed_out")
            fixture._ready_and_account()
            self.assertEqual(service.snapshot.observed_today_tokens, 123)
            self.assertEqual(
                service.repository.load_local_token_events(
                    service.snapshot.account_hash
                ),
                (),
            )
            service.clear_device_history()
            service.observe_local_usage_batch(records)
            self.assertIsNone(service.snapshot.observed_today_tokens)
        finally:
            fixture.tearDown()

    def test_parser_rejects_invalid_counters_dates_and_limits(self):
        now = datetime.now(timezone.utc)
        parser = UsageLogParser(
            lambda: now.replace(tzinfo=None), lambda p: "f", lambda r: r.get("stamp")
        )
        self.assertEqual(parser.extract("f", None, 0), ())
        self.assertEqual(
            parser.extract(
                "f", {"type": "event_msg", "payload": {"type": "token_count"}}, 0
            ),
            (),
        )
        base = {
            "type": "event_msg",
            "stamp": now,
            "payload": {
                "type": "token_count",
                "info": {"total_token_usage": {"total_tokens": True}},
            },
        }
        self.assertEqual(parser.extract("f", base, 0), ())
        base["payload"]["info"]["total_token_usage"]["total_tokens"] = 100
        base["payload"]["info"]["last_token_usage"] = {"total_tokens": 2}
        base["payload"]["rate_limits"] = {
            "primary": {"used_percent": "nan"},
            "secondary": {"used_percent": 1, "resets_at": 2**62},
        }
        rows = parser.extract("f", base, 0)
        self.assertEqual(rows[0]["delta_tokens"], 2)
        self.assertIsNone(rows[1]["resets_at"])
        base["stamp"] = now - timedelta(days=1)
        self.assertEqual(parser.extract("f", base, 0), ())
        base["payload"]["info"]["total_token_usage"]["total_tokens"] = 0
        self.assertEqual(parser.extract("f", base, 0), ())
        self.assertEqual(parser.usage_regression_count, 0)

    def test_log_worker_restart_discards_old_generation(self):
        from PySide6.QtWidgets import QApplication
        from watched_kettle.integrations.codex_log_worker import ThreadedCodexLogMonitor
        from watched_kettle.usage.device import DeviceBatch

        app = QApplication.instance() or QApplication([])
        with TemporaryDirectory() as directory:
            monitor = ThreadedCodexLogMonitor(
                sessions_root=Path(directory),
                archived_root=Path(directory) / "archived",
            )
            delivered = []
            monitor.usage_detected.connect(delivered.append)
            try:
                for _ in range(3):
                    monitor.start()
                    app.processEvents()
                    old = monitor._generation - 1
                    monitor._receive_usage(DeviceBatch(old, (), ()))
                    monitor._receive_payload((old, {"event": "done"}))
                    monitor._receive((old, {"active": True}, {"old": "main"}))
                    self.assertEqual(monitor.session_scope("old"), "unknown")
                    monitor.close()
                    app.processEvents()
                    self.assertFalse(monitor.is_active)
                self.assertEqual(delivered, [])
            finally:
                monitor.close()
                monitor.deleteLater()
