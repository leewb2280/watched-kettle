"""Task measurements require complete, matching local rollout evidence."""

import json
import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from watched_kettle.storage.database import DatabaseManager
from watched_kettle.storage.usage_repository import SqliteUsageRepository
from watched_kettle.usage.identifiers import hash_identifier
from watched_kettle.usage.log_recovery import LocalTurnRecovery
from watched_kettle.usage.models import TaskUsageRecord
from watched_kettle.usage.turn_log import TurnLogParser


SESSION = "5a6f0c5b-93eb-4ad4-8c29-8f4c96283d5e"
STAMP = "2026-10-01T05:00:00Z"
COMPLETED = datetime(2026, 10, 1, 5, 0, 0, tzinfo=timezone.utc)


def record(kind, payload):
    return {"timestamp": STAMP, "type": kind, "payload": payload}


def token(total, input_tokens, cached, output):
    return record(
        "event_msg",
        {
            "type": "token_count",
            "info": {
                "total_token_usage": {
                    "total_tokens": total,
                    "input_tokens": input_tokens,
                    "cached_input_tokens": cached,
                    "output_tokens": output,
                }
            },
        },
    )


def rollout(*, inherited=False, second_token=True, total=15):
    header = {"id": SESSION, "source": "cli"}
    if inherited:
        header["parent_thread_id"] = "parent"
    rows = [
        record("session_meta", header),
        record("event_msg", {"type": "task_started", "turn_id": "turn-one"}),
        record(
            "turn_context",
            {"turn_id": "turn-one", "model": "gpt-6-sol", "effort": "medium"},
        ),
        token(10, 7, 2, 3),
    ]
    if second_token:
        rows.append(token(total, 10, 3, 5))
    rows.append(
        record(
            "event_msg",
            {"type": "task_complete", "turn_id": "turn-one", "completed_at": STAMP},
        )
    )
    return rows


def write_log(root, file_id, rows, ordinal=0):
    path = root / f"rollout-2026-10-01T14-00-00-{file_id}.jsonl"
    path.write_bytes(
        b"".join(
            (json.dumps(dict(row, ordinal=index)) + "\n").encode()
            for index, row in enumerate(rows, ordinal)
        )
    )
    return path


def continuation(base, file_id, ordinal, rows, **overrides):
    header = {
        "id": SESSION,
        "session_id": SESSION,
        "source": "cli",
        "history_base": {
            "thread_id": base.stem[-36:],
            "end_byte_offset": base.stat().st_size,
            "end_ordinal_exclusive": ordinal,
        },
    }
    header["history_base"].update(overrides)
    return write_log(
        base.parent, file_id, [record("session_meta", header), *rows], ordinal
    )


def next_turn(turn="turn-two", total=20):
    return [
        record("event_msg", {"type": "task_started", "turn_id": turn}),
        record("turn_context", {"turn_id": turn, "model": "gpt-6-sol"}),
        token(total, total - 5, 3, 5),
        record("event_msg", {"type": "task_complete", "turn_id": turn}),
    ]


class TurnLogParserTests(unittest.TestCase):
    def parse(self, rows):
        parser = TurnLogParser(SESSION)
        return [e for row in rows if (e := parser.feed(row)) is not None]

    def test_multiple_cumulative_events_yield_one_turn_measurement(self):
        (evidence,) = self.parse(rollout())
        self.assertEqual(
            (
                evidence.total_tokens,
                evidence.input_tokens,
                evidence.cached_input_tokens,
                evidence.output_tokens,
            ),
            (15, 10, 3, 5),
        )
        self.assertEqual(evidence.model, "gpt-6-sol")
        self.assertFalse(evidence.partial)

    def test_explicit_zero_is_distinct_from_no_token_event(self):
        rows = rollout(second_token=False)
        rows[3] = token(0, 0, 0, 0)
        self.assertEqual(self.parse(rows)[0].total_tokens, 0)
        self.assertEqual(self.parse([row for row in rows if row is not rows[3]]), [])

    def test_regression_and_inherited_file_are_not_attributed(self):
        self.assertEqual(self.parse(rollout(total=5)), [])
        self.assertEqual(self.parse(rollout(inherited=True)), [])

    def test_duplicate_start_does_not_reset_token_baseline(self):
        rows = rollout()
        rows.insert(4, rows[1])
        self.assertEqual(self.parse(rows)[0].total_tokens, 15)

    def test_prompt_content_is_not_carried_into_usage_evidence(self):
        rows = rollout()
        rows.insert(
            3, record("response_item", {"type": "message", "content": "PRIVATE PROMPT"})
        )
        self.assertNotIn("PRIVATE PROMPT", repr(self.parse(rows)[0]))

    def test_missing_start_or_wrong_completion_id_is_not_attributed(self):
        rows = rollout()
        self.assertEqual(self.parse([row for row in rows if row is not rows[1]]), [])
        rows[-1]["payload"]["turn_id"] = "other"
        self.assertEqual(self.parse(rows), [])

    def test_regression_invalidates_only_affected_turn(self):
        evidence = self.parse(rollout(total=5) + next_turn(total=20))
        self.assertEqual(
            [(e.turn_id, e.total_tokens) for e in evidence], [("turn-two", 15)]
        )

    def test_missing_counter_requires_new_baseline_then_new_turn(self):
        rows = rollout()
        rows.insert(4, record("event_msg", {"type": "token_count", "info": None}))
        evidence = self.parse(rows + next_turn(total=20))
        self.assertEqual(
            [(e.turn_id, e.total_tokens) for e in evidence], [("turn-two", 5)]
        )

    def test_partial_requires_known_total_for_whole_turn(self):
        rows = rollout(second_token=False)
        rows[3] = token(10, None, None, None)
        evidence = self.parse(rows)[0]
        self.assertTrue(evidence.partial)
        self.assertEqual(evidence.total_tokens, 10)
        rows[0]["payload"]["history_base"] = {"thread_id": "missing"}
        self.assertEqual(self.parse(rows), [])


class LocalRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def scan(self, root):
        found = []
        worker = LocalTurnRecovery(found.append, roots=(root,))
        self.addCleanup(worker.clear)
        worker.add_targets((hash_identifier(SESSION),))
        for _ in worker._round():
            pass
        return worker, {e.turn_id: e for e in found}

    def test_multilevel_prefix_excludes_old_suffix_and_carries_baseline(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = write_log(root, SESSION, rollout())
            first = continuation(
                base, "11111111-1111-1111-1111-111111111111", 6, next_turn()
            )
            continuation(
                first,
                "22222222-2222-2222-2222-222222222222",
                11,
                next_turn("turn-three", 24),
            )
            # Later abandoned suffix must not become the child's baseline.
            with base.open("ab") as stream:
                stream.write(
                    (json.dumps(dict(token(100, 90, 3, 10), ordinal=6)) + "\n").encode()
                )
            _, found = self.scan(root)
            self.assertEqual(
                {k: e.total_tokens for k, e in found.items()},
                {"turn-one": 15, "turn-two": 5, "turn-three": 4},
            )

    def test_unchanged_and_unrelated_logs_do_not_reparse_or_repeat_status(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_log(root, SESSION, rollout())
            other_id = "99999999-9999-9999-9999-999999999999"
            other = write_log(
                root,
                other_id,
                [record("session_meta", {"id": other_id, "source": "cli"})],
            )
            worker = LocalTurnRecovery(lambda e: None, roots=(root,))
            self.addCleanup(worker.clear)
            events = []
            worker.on_state = lambda *args: events.append(args)
            worker.turns.add((hash_identifier(SESSION), hash_identifier("absent")))
            worker.add_targets((hash_identifier(SESSION),))
            list(worker._round())
            events.clear()
            with patch.object(
                worker, "_parse_uncached", wraps=worker._parse_uncached
            ) as parse:
                list(worker._round())
                with other.open("ab") as stream:
                    stream.write((json.dumps(token(1, 1, 0, 0)) + "\n").encode())
                list(worker._round())
                parse.assert_not_called()
            self.assertEqual(events, [])
            self.assertNotIn(other, worker.watched)

    def test_growing_file_reads_only_new_suffix(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write_log(root, SESSION, rollout())
            worker, _ = self.scan(root)
            offset = path.stat().st_size
            with path.open("ab") as stream:
                for i, row in enumerate(next_turn(), 6):
                    stream.write((json.dumps(dict(row, ordinal=i)) + "\n").encode())
            positions = []
            original = worker._line

            def track(stream, limit):
                positions.append(stream.tell())
                return (yield from original(stream, limit))

            with patch.object(worker, "_line", side_effect=track):
                list(worker._round())
            self.assertTrue(positions)
            self.assertGreaterEqual(min(positions), offset)
            self.assertEqual(
                worker.evidence_cache[
                    (hash_identifier(SESSION), hash_identifier("turn-two"))
                ].total_tokens,
                5,
            )

    def test_changed_parent_invalidates_unchanged_child_checkpoint(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = write_log(root, SESSION, rollout())
            continuation(base, "11111111-1111-1111-1111-111111111111", 6, next_turn())
            worker, _ = self.scan(root)
            write_log(root, SESSION, rollout(total=18))
            list(worker._round())
            self.assertEqual(
                worker.evidence_cache[
                    (hash_identifier(SESSION), hash_identifier("turn-two"))
                ].total_tokens,
                2,
            )

    def test_manual_retry_checks_again_but_automatic_retry_keeps_verdict(self):
        with TemporaryDirectory() as tmp:
            missing = TaskUsageRecord(
                COMPLETED,
                "a",
                hash_identifier(SESSION),
                "done",
                turn_hash=hash_identifier("missing"),
                data_quality="unavailable",
            )
            events = []
            worker = LocalTurnRecovery(
                lambda e: None,
                roots=(Path(tmp),),
                on_state=lambda *args: events.append(args[2]),
            )
            self.addCleanup(worker.clear)
            worker.add_records((missing,))
            list(worker._round())
            events.clear()
            list(worker._round())
            self.assertEqual(events, [])
            worker.add_records((missing,), manual=True)
            list(worker._round())
            self.assertEqual(events, ["checking", "unavailable"])

    def test_acknowledged_task_is_removed_from_recovery_targets(self):
        with TemporaryDirectory() as tmp:
            row = TaskUsageRecord(
                COMPLETED,
                "a",
                hash_identifier(SESSION),
                "done",
                turn_hash=hash_identifier("turn-one"),
                data_quality="unavailable",
            )
            worker = LocalTurnRecovery(lambda e: None, roots=(Path(tmp),))
            worker.add_records((row,))
            worker.acknowledge({(row.thread_hash, row.turn_hash)})
            self.assertFalse(worker.turns)
            self.assertFalse(worker.targets)
            self.assertFalse(worker.timer.isActive())
            worker.clear()

    def test_turn_can_start_in_previous_file(self):
        with TemporaryDirectory() as tmp:
            base = write_log(Path(tmp), SESSION, rollout()[:-1])
            continuation(
                base,
                "11111111-1111-1111-1111-111111111111",
                5,
                [token(20, 15, 3, 5), rollout()[-1]],
            )
            _, found = self.scan(Path(tmp))
            self.assertEqual(found["turn-one"].total_tokens, 20)

    def test_invalid_link_never_uses_zero_for_inherited_total(self):
        for override in (
            {"end_byte_offset": 1},
            {"end_ordinal_exclusive": 100},
            {"thread_id": "missing"},
        ):
            with self.subTest(override=override), TemporaryDirectory() as tmp:
                base = write_log(Path(tmp), SESSION, rollout())
                continuation(
                    base,
                    "11111111-1111-1111-1111-111111111111",
                    6,
                    next_turn(total=1000) + next_turn("turn-three", 1005),
                    **override,
                )
                _, found = self.scan(Path(tmp))
                self.assertNotIn("turn-two", found)
                self.assertEqual(found["turn-three"].total_tokens, 5)

    def test_cycle_and_wrong_owner_rejected(self):
        for mode in ("cycle", "owner"):
            with self.subTest(mode=mode), TemporaryDirectory() as tmp:
                rows = rollout()
                if mode == "owner":
                    rows[0]["payload"]["id"] = "other-owner"
                base = write_log(Path(tmp), SESSION, rows)
                child_id = "11111111-1111-1111-1111-111111111111"
                overrides = {"thread_id": child_id} if mode == "cycle" else {}
                continuation(base, child_id, 6, next_turn(), **overrides)
                _, found = self.scan(Path(tmp))
                self.assertNotIn("turn-two", found)

    def test_partial_line_late_append_and_replacement_are_rechecked(self):
        with TemporaryDirectory() as tmp:
            base = write_log(Path(tmp), SESSION, rollout()[:-1])
            worker, found = self.scan(Path(tmp))
            self.assertFalse(found)
            last = (json.dumps(dict(rollout()[-1], ordinal=5)) + "\n").encode()
            with base.open("ab") as stream:
                stream.write(last[:-1])
            list(worker._round())
            self.assertFalse(worker.evidence_cache)
            with base.open("ab") as stream:
                stream.write(b"\n")
            list(worker._round())
            self.assertEqual(
                next(iter(worker.evidence_cache.values())).total_tokens, 15
            )
            write_log(Path(tmp), SESSION, rollout(second_token=False, total=10))
            list(worker._round())
            self.assertEqual(
                next(iter(worker.evidence_cache.values())).total_tokens, 10
            )

    def test_append_during_scan_does_not_invalidate_complete_prefix(self):
        with TemporaryDirectory() as tmp:
            base = write_log(Path(tmp), SESSION, rollout())
            worker = LocalTurnRecovery(lambda e: None, roots=(Path(tmp),))
            self.addCleanup(worker.clear)
            job = worker._parse(base, (), base.stat().st_size, allow_tail=True)
            next(job)
            with base.open("ab") as stream:
                stream.write(
                    (json.dumps(dict(token(20, 15, 3, 5), ordinal=6)) + "\n").encode()
                )
            try:
                while True:
                    next(job)
            except StopIteration as end:
                evidence = end.value[2]
            self.assertEqual(evidence[0].total_tokens, 15)

    def test_scan_not_discarded_when_waiting_deadline_passes_and_clear_cancels(self):
        worker = LocalTurnRecovery(lambda e: None, roots=())
        self.addCleanup(worker.clear)
        worker.targets.add("target")
        worker.idle_until = 0
        worker.work = iter([None] * 1000)
        with patch("watched_kettle.usage.log_recovery.monotonic", return_value=1000):
            worker._tick()
        self.assertIsNotNone(worker.work)
        # A real scan generator can be closed while suspended in a read.
        worker.work = (None for _ in range(1000))
        worker.clear()
        self.assertFalse(worker.targets)
        self.assertIsNone(worker.work)

    def test_backfill_updates_only_exact_unavailable_row_and_is_idempotent(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            session_root = root / "sessions"
            session_root.mkdir()
            path = session_root / f"rollout-2026-10-01T14-00-00-{SESSION}.jsonl"
            path.write_text(
                "".join(json.dumps(row) + "\n" for row in rollout()), encoding="utf-8"
            )
            database = DatabaseManager(root / "usage.db")
            self.assertTrue(database.start().available)
            try:
                repository = SqliteUsageRepository(database, retention_days=36500)
                missing = TaskUsageRecord(
                    COMPLETED,
                    "account-one",
                    hash_identifier(SESSION),
                    "done",
                    turn_hash=hash_identifier("turn-one"),
                    data_quality="unavailable",
                    quality_reason="invalid_usage_response",
                )
                repository.append(missing)
                repository.append(
                    TaskUsageRecord(
                        COMPLETED,
                        "account-two",
                        hash_identifier(SESSION),
                        "done",
                        turn_hash=hash_identifier("other-turn"),
                        data_quality="unavailable",
                    )
                )
                recovery = LocalTurnRecovery(
                    lambda evidence: repository.enrich_unavailable(
                        "account-one", evidence
                    ),
                    roots=(session_root,),
                )
                recovery.add_targets((hash_identifier(SESSION),))
                for _ in range(30):
                    recovery._tick()
                    if repository.load("account-one")[0].total_tokens is not None:
                        break
                record_one = repository.load("account-one")[0]
                self.assertEqual(record_one.total_tokens, 15)
                self.assertEqual(record_one.net_new_input_tokens, 7)
                self.assertEqual(record_one.model, "gpt-6-sol")
                self.assertIsNone(record_one.estimated_usd_micros)
                self.assertIsNone(repository.load("account-two")[0].total_tokens)
                recovery.add_targets((hash_identifier(SESSION),))
                self.assertEqual(len(repository.load("account-one")), 1)
                recovery.clear()
            finally:
                database.close()

    def test_same_turn_recorded_under_two_accounts_stays_unavailable(self):
        with TemporaryDirectory() as temporary:
            database = DatabaseManager(Path(temporary) / "usage.db")
            self.assertTrue(database.start().available)
            try:
                repository = SqliteUsageRepository(database, retention_days=36500)
                for account in ("one", "two"):
                    repository.append(
                        TaskUsageRecord(
                            COMPLETED,
                            account,
                            hash_identifier(SESSION),
                            "done",
                            turn_hash=hash_identifier("turn-one"),
                            data_quality="unavailable",
                        )
                    )
                parser = TurnLogParser(SESSION)
                evidence = next(
                    item for row in rollout() if (item := parser.feed(row)) is not None
                )
                self.assertFalse(repository.enrich_unavailable("one", evidence))
                self.assertFalse(repository.enrich_unavailable("two", evidence))
            finally:
                database.close()

    def test_batch_commits_once_and_identical_reasons_do_not_write(self):
        with TemporaryDirectory() as tmp:
            database = DatabaseManager(Path(tmp) / "usage.db")
            database.start()
            try:
                repo = SqliteUsageRepository(database, retention_days=36500)
                for turn in ("one", "two"):
                    repo.append(
                        TaskUsageRecord(
                            COMPLETED,
                            "account",
                            hash_identifier(SESSION),
                            "done",
                            turn_hash=hash_identifier(turn),
                            data_quality="unavailable",
                        )
                    )
                statements = []
                repo.connection.set_trace_callback(statements.append)
                reasons = tuple(
                    (
                        hash_identifier(SESSION),
                        hash_identifier(turn),
                        "turn_boundary_missing",
                    )
                    for turn in ("one", "two")
                )
                self.assertTrue(repo.apply_recovery_batch("account", (), reasons))
                self.assertEqual(sum(s == "COMMIT" for s in statements), 1)
                statements.clear()
                self.assertFalse(repo.apply_recovery_batch("account", (), reasons))
                self.assertFalse(any(s.startswith("UPDATE ") for s in statements))
            finally:
                database.close()
