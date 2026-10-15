import os
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from watched_kettle.features.tasks.models import CompletionCheck, TaskSpec, TaskState
from watched_kettle.storage.database import SCHEMA_VERSION, DatabaseManager
from watched_kettle.storage.task_crypto import WindowsDataProtector, ProtectionError
from watched_kettle.storage.task_repository import QueueRepository


@unittest.skipUnless(os.name == "nt", "real current-user DPAPI")
class TaskRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "tasks.sqlite3"
        self.db = DatabaseManager(self.path)
        self.assertTrue(self.db.start().available)
        self.repo = QueueRepository(self.db, WindowsDataProtector())
        self.repo.set_account("account-A")
        self.spec = TaskSpec(
            "SECRET-TITLE",
            "SECRET-INSTRUCTION",
            "SECRET-PROJECT",
            "SECRET-THREAD",
            "C:/SECRET-PATH",
            "version",
            checks=(CompletionCheck("SECRET-CHECK"),),
        )

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_atomic_global_limit_and_withdraw_preserve_live_attempt(self):
        identities = [
            self.repo.save(
                replace(
                    self.spec,
                    project_id=f"project-{index}",
                    instruction=f"work-{index}",
                ),
                registered=True,
            )
            for index in range(3)
        ]
        batch = self.repo.create_batch(identities)
        first = self.repo.reserve(identities[0], 1, ("repo-0",))
        self.repo.reserve(identities[1], 1, ("repo-1",))
        with self.assertRaisesRegex(ValueError, "parallel_limit"):
            self.repo.reserve(identities[2], 1, ("repo-2",))
        self.repo.release_unstarted_batch(batch)
        self.assertEqual(self.repo.require(identities[0]).attempt_id, first)
        self.assertEqual(self.repo.require(identities[2]).batch_id, "")

    def test_prune_erases_only_terminal_history(self):
        first = self.repo.save(self.spec, registered=True)
        self.repo.create_batch([first])
        attempt = self.repo.reserve(first, 1, ("repo",))
        self.repo.update_attempt(attempt, TaskState.COMPLETE, terminal_verified=True)
        draft = self.repo.save(replace(self.spec, instruction="draft"))
        self.assertEqual(self.repo.prune(retained=0), 1)
        self.assertIsNone(self.repo.get(first))
        self.assertEqual(self.repo.require(draft).state, TaskState.DRAFT)

    def test_retry_requires_terminal_evidence_and_returns_to_unapproved_review(self):
        identity = self.repo.save(self.spec, registered=True)
        self.repo.create_batch([identity])
        attempt = self.repo.reserve(identity, 1, ("repo",))
        with self.assertRaises(ValueError):
            self.repo.retry_to_draft(identity)
        self.repo.update_attempt(attempt, TaskState.FAILED, terminal_verified=True)
        draft = self.repo.retry_to_draft(identity)
        self.assertEqual(self.repo.require(draft).state, TaskState.DRAFT)
        self.assertEqual(self.repo.require(draft).spec.source_version, "")
        self.assertIsNone(self.repo.require(identity).spec)
        with self.assertRaises(ValueError):
            self.repo.create_batch([draft])

    def test_draft_survives_restart_but_cannot_execute(self):
        identity = self.repo.save(self.spec)
        with self.assertRaises(ValueError):
            self.repo.create_batch([identity])
        self.db.close()
        self.db = DatabaseManager(self.path)
        self.assertTrue(self.db.start().available)
        self.repo = QueueRepository(self.db, WindowsDataProtector())
        self.repo.set_account("account-A")
        self.assertEqual(self.repo.require(identity).spec, self.spec)
        self.assertEqual(self.repo.require(identity).state, TaskState.DRAFT)

    def test_sqlite_and_wal_never_receive_sensitive_plaintext(self):
        self.repo.save(self.spec, registered=True)
        for path in Path(self.temp.name).iterdir():
            if path.is_file():
                self.assertNotIn(b"SECRET-", path.read_bytes())

    def test_completed_summary_is_encrypted_and_instruction_is_erased(self):
        identity = self.repo.save(self.spec, registered=True)
        self.repo.create_batch([identity])
        attempt = self.repo.reserve(identity, 1, ("repo",))
        self.repo.update_attempt(attempt, TaskState.COMPLETE, terminal_verified=True)
        row = self.repo.require(identity)
        self.assertIsNone(row.spec)
        self.assertEqual(row.summary["title"], self.spec.title)
        self.assertEqual(row.summary["thread_id"], self.spec.thread_id)
        self.assertNotIn("instruction", row.summary)
        for path in Path(self.temp.name).iterdir():
            if path.is_file():
                self.assertNotIn(b"SECRET-", path.read_bytes())
        self.repo.set_account("account-B")
        self.assertEqual(self.repo.list_items(), ())

    def test_candidate_link_survives_reworded_review_and_new_source_item(self):
        original = replace(
            self.spec,
            source_candidate="original candidate",
            source_refs=("turn1", "item1"),
        )
        saved = replace(
            original, title="Reviewed title", instruction="Reviewed instruction"
        )
        identity = self.repo.save(saved)
        rediscovered = replace(original, source_refs=("turn2", "item2"))
        self.assertEqual(self.repo.candidate_task(rediscovered), identity)
        with self.assertRaisesRegex(ValueError, "duplicate_task"):
            self.repo.save(rediscovered)

    def test_exclusion_is_stable_and_project_scoped_restore(self):
        first = replace(self.spec, source_candidate="first", project_id="a")
        second = replace(self.spec, source_candidate="second", project_id="b")
        self.repo.exclude(first)
        self.repo.exclude(second)
        self.assertTrue(self.repo.excluded(replace(first, source_refs=("new",))))
        self.repo.reset_exclusions("a")
        self.assertFalse(self.repo.excluded(first))
        self.assertTrue(self.repo.excluded(second))

    def test_v6_migration_preserves_draft_text_but_revokes_old_queue_authority(self):
        identity = self.repo.save(self.spec, registered=True)
        con = self.db.require_connection()
        with con:
            con.execute("DROP INDEX idx_task_origin")
            con.execute("ALTER TABLE reviewed_tasks DROP COLUMN origin_key")
            con.execute("ALTER TABLE reviewed_tasks DROP COLUMN summary_payload")
            con.execute("ALTER TABLE task_exclusions DROP COLUMN project_key")
            # A real v6 database also predates the version 8 Claude Code tables.
            for table in (
                "claude_code_turn_parts",
                "claude_code_files",
                "claude_code_state",
                "claude_code_quota_samples",
            ):
                con.execute(f"DROP TABLE {table}")
            con.execute("DELETE FROM schema_migrations WHERE version>=7")
        self.db.close()
        self.db = DatabaseManager(self.path)
        self.assertTrue(self.db.start().available)
        self.repo = QueueRepository(self.db, WindowsDataProtector())
        self.repo.set_account("account-A")
        migrated = self.repo.require(identity)
        self.assertEqual(migrated.state, TaskState.DRAFT)
        self.assertEqual(migrated.spec.instruction, self.spec.instruction)
        self.assertEqual(migrated.spec.source_version, "")
        self.assertEqual(migrated.reason, "source_version_upgrade")
        self.assertTrue(list(self.path.parent.glob(f"*.v6-to-v{SCHEMA_VERSION}.*.bak")))

    def test_retry_draft_can_be_registered_after_original_is_dismissed(self):
        identity = self.repo.save(self.spec, registered=True)
        self.repo.create_batch([identity])
        attempt = self.repo.reserve(identity, 1, ("repo",))
        self.repo.update_attempt(attempt, TaskState.FAILED, terminal_verified=True)
        draft = self.repo.retry_to_draft(identity)
        self.repo.save(self.spec, registered=True, identity=draft, expected_revision=1)
        self.assertEqual(self.repo.require(draft).state, TaskState.QUEUED)

    def test_account_switch_cannot_read_other_account(self):
        identity = self.repo.save(self.spec)
        self.repo.set_account("account-B")
        self.assertEqual(self.repo.list_items(), ())
        with self.assertRaises(ValueError):
            self.repo.require(identity)
        self.repo.set_account(None)
        with self.assertRaises(ValueError):
            self.repo.save(self.spec)
        self.repo.set_account("account-A")
        self.assertEqual(self.repo.require(identity).spec.title, "SECRET-TITLE")

    def test_stale_revision_and_locked_batch_cannot_edit(self):
        identity = self.repo.save(self.spec)
        with self.assertRaises(ValueError):
            self.repo.save(self.spec, identity=identity, expected_revision=0)
        self.repo.save(
            self.spec, registered=True, identity=identity, expected_revision=1
        )
        self.repo.create_batch([identity])
        with self.assertRaises(ValueError):
            self.repo.save(self.spec, identity=identity, expected_revision=2)

    def test_reservation_survives_restart_and_requires_terminal_evidence(self):
        identity = self.repo.save(self.spec, registered=True)
        self.repo.create_batch([identity])
        attempt = self.repo.reserve(identity, 1, ("repo-path",))
        self.repo.mark_interrupted()
        self.assertEqual(self.repo.require(identity).state, TaskState.RECONCILING)
        with self.assertRaises(ValueError):
            self.repo.reserve(identity, 1, ("repo-path",))
        with self.assertRaises(ValueError):
            self.repo.update_attempt(attempt, TaskState.COMPLETE)
        self.repo.update_attempt(
            attempt, TaskState.COMPLETE, terminal_verified=True, turn_id="turn-1"
        )
        self.assertIsNone(self.repo.require(identity).spec)
        self.assertEqual(self.repo.receipt(attempt)["turn_id"], "turn-1")
        with self.assertRaises(ValueError):
            self.repo.update_attempt(attempt, TaskState.RUNNING)

    def test_duplicate_is_explicit_and_foreign_ciphertext_fails_closed(self):
        identity = self.repo.save(self.spec)
        with self.assertRaises(ValueError):
            self.repo.save(self.spec)
        with self.db.connection:
            self.db.connection.execute(
                "UPDATE reviewed_tasks SET payload=? WHERE id=?", (b"broken", identity)
            )
        item = self.repo.require(identity)
        self.assertEqual(item.reason, "decryption_failed")
        self.assertIsNone(item.spec)

    def test_dpapi_binds_ciphertext_to_record_context(self):
        protector = WindowsDataProtector()
        data = protector.protect(b"content", b"one")
        self.assertEqual(protector.unprotect(data, b"one"), b"content")
        with self.assertRaises(ProtectionError):
            protector.unprotect(data, b"two")


if __name__ == "__main__":
    unittest.main()
