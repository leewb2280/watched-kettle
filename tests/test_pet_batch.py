"""Batch lifecycle through the real adapter, isolated Qt/settings and packages."""

import unittest
from unittest.mock import patch
from uuid import uuid4

from PySide6.QtTest import QTest

from tests import test_settings_bridge as bridge
from watched_kettle.application.settings_ui.contracts import CommandError
from watched_kettle.pet.trash import PetTrashError


class PetBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        bridge.SettingsBridgeTests.setUpClass()

    def setUp(self):
        self.case = bridge.SettingsBridgeTests()
        self.case.setUp()
        self.addCleanup(self.case.tearDown)
        self.core = self.case.core
        self.vm = self.case.vm
        self.batch = self.core.pet_batch
        for pet_id in ("a", "b", "c"):
            self.case.install_user_pet(pet_id)

    def start(self, action="move", ids=None, **extra):
        args = self.case.context(
            action=action, ids=ids or ["a", "b", "c"], operationKey=uuid4().hex
        )
        args.update(extra)
        result = self.core.execute("pet.trash.batch.start", args)
        self.batch.timer.stop()
        return result, args

    def step(self):
        self.batch.timer.stop()
        self.batch._step()
        self.batch.timer.stop()

    def drain(self):
        for _ in range(260):
            if not self.batch.running:
                return self.batch.last
            self.step()
        self.fail("batch did not finish")

    def test_move_and_reverse_group_undo_preserve_order_settings_and_current(self):
        order = ["a", "b", "c", "mori-bot"]
        self.vm.save_catalog_preferences("custom", order, ["b"])
        self.case.settings.setValue("pets/a/width", 224)
        started, _ = self.start()
        self.assertEqual(started["job"]["processed"], 0)
        job = self.drain()
        self.assertEqual([row["status"] for row in job["results"]], ["succeeded"] * 3)
        ids = [row["trashId"] for row in reversed(job["results"])]
        self.start("restore", ids)
        self.drain()
        self.assertEqual(list(self.case.preferences.load_pet_custom_order()), order)
        self.assertIn("b", self.case.preferences.load_hidden_pet_ids())
        self.assertEqual(self.case.settings.value("pets/a/width"), 224)
        self.assertEqual(self.vm.snapshot.pet_id, "mori-bot")

    def test_partial_file_failure_continues_and_reports_safe_item_results(self):
        self.start()
        original = self.vm.packages.move

        def move(pet_id):
            if pet_id == "b":
                raise PermissionError("must not expose a source path")
            return original(pet_id)

        with patch.object(self.vm.packages, "move", side_effect=move):
            self.drain()
        result = self.batch.status(dict(epoch=0))["job"]
        self.assertEqual((result["succeeded"], result["failed"]), (2, 1))
        self.assertEqual(result["results"][1]["code"], "file_access")
        self.assertNotIn("source path", str(result))
        self.assertTrue((self.case.root / "pets" / "b").exists())

    def test_cancel_keeps_completed_and_does_not_start_remaining(self):
        result, _ = self.start()
        self.step()
        result = self.core.execute(
            "pet.trash.batch.cancel", dict(epoch=0, jobId=result["job"]["jobId"])
        )
        self.assertEqual(result["job"]["state"], "cancelled")
        self.assertEqual(
            [row["status"] for row in result["job"]["results"]],
            ["succeeded", "notStarted", "notStarted"],
        )
        self.assertFalse(self.batch.timer.isActive())
        self.assertTrue((self.case.root / "pets" / "b").exists())

    def test_retries_return_same_job_before_and_after_completion(self):
        result, args = self.start()
        job_id = result["job"]["jobId"]
        self.step()
        retry = self.core.execute("pet.trash.batch.start", args)
        self.assertEqual(retry["job"]["jobId"], job_id)
        with self.assertRaises(CommandError):
            self.core.execute("pet.trash.batch.start", {**args, "ids": ["a"]})
        self.drain()
        retry = self.core.execute("pet.trash.batch.start", args)
        self.assertEqual(retry["job"]["jobId"], job_id)
        self.assertEqual(len(self.vm.packages.records()), 3)

    def test_concurrent_job_and_other_pet_mutations_are_rejected(self):
        self.start()
        with self.assertRaises(CommandError):
            self.start(ids=["a"])
        with self.assertRaises(CommandError):
            self.core.execute("pet.select", self.case.context(id="a"))
        with self.assertRaises(CommandError):
            self.core.prepare_pet_import(self.case.root / "unused.png")
        self.assertEqual(len(self.vm.packages.records()), 0)

    def test_stale_or_invalid_requests_do_not_start_any_file_operation(self):
        for extra in (
            {"epoch": -1},
            {"revision": -1},
            {"petId": "other"},
            {"ids": ["a", "a"]},
            {"ids": ["a", "mori-bot"]},
            {"ids": ["a", "missing"]},
            {"ids": ["a"] * 257},
        ):
            with self.assertRaises(CommandError):
                self.start(**extra)
        self.assertFalse(self.batch.running)
        self.assertEqual(self.vm.packages.records(), [])

    def test_current_pet_is_first_and_replacement_failure_stops_entire_job(self):
        self.vm.change_pet("b")
        self.start(ids=["a", "b", "c"], replacementId="mori-bot")
        with patch.object(self.vm, "change_pet", return_value=False):
            self.step()
        self.assertEqual(self.batch.last["state"], "failed")
        self.assertEqual(self.batch.last["results"][0]["id"], "b")
        self.assertEqual(self.batch.last["results"][0]["code"], "replacement_failed")
        self.assertEqual(len(self.vm.packages.records()), 0)
        self.assertEqual(self.vm.snapshot.pet_id, "b")

    def test_current_move_file_failure_rolls_back_and_other_items_continue(self):
        self.vm.change_pet("b")
        self.start(ids=["a", "b"], replacementId="mori-bot")
        original = self.vm.packages.move

        def move(pet_id):
            if pet_id == "b":
                raise PermissionError()
            return original(pet_id)

        with patch.object(self.vm.packages, "move", side_effect=move):
            self.drain()
        self.assertEqual(self.vm.snapshot.pet_id, "b")
        self.assertEqual(
            [row["status"] for row in self.batch.last["results"]],
            ["failed", "succeeded"],
        )

    def test_selected_replacement_is_rejected_before_mutation(self):
        self.vm.change_pet("b")
        with self.assertRaises(CommandError):
            self.start(ids=["a", "b"], replacementId="a")
        self.assertEqual(self.vm.snapshot.pet_id, "b")

    def test_external_pet_change_and_revision_change_stop_remaining(self):
        self.start()
        self.step()
        self.vm.change_pet("b")
        self.step()
        self.assertEqual(self.batch.last["state"], "cancelled")
        self.assertTrue((self.case.root / "pets" / "b").exists())
        self.start(ids=["c"])
        self.core.revision += 1
        self.step()
        self.assertEqual(self.batch.last["results"][0]["status"], "notStarted")

    def test_account_change_cancels_and_hides_previous_results(self):
        self.start()
        self.core.account_epoch += 1
        self.step()
        self.assertEqual(self.batch.last["state"], "cancelled")
        self.assertIsNone(self.batch.status(dict(epoch=1))["job"])
        with self.assertRaises(CommandError):
            self.batch.status(dict(epoch=0))

    def test_restore_conflict_and_capacity_failures_keep_other_successes(self):
        self.start(ids=["a", "b"])
        job = self.drain()
        self.case.install_user_pet("a")
        self.start("restore", [row["trashId"] for row in job["results"]])
        self.drain()
        self.assertEqual(
            [row["status"] for row in self.batch.last["results"]],
            ["failed", "succeeded"],
        )
        self.start("restore", [self.vm.packages.records()[0]["trashId"]])
        with patch.object(
            self.vm.packages, "restore", side_effect=PetTrashError("등록 상한")
        ):
            self.drain()
        self.assertEqual(self.batch.last["results"][0]["status"], "failed")

    def test_partial_permanent_delete_retains_failed_records_and_settings(self):
        self.start(ids=["a", "b"])
        job = self.drain()
        ids = [row["trashId"] for row in job["results"]]
        self.case.settings.setValue("pets/a/width", 224)
        self.case.settings.setValue("pets/b/width", 224)
        original = self.vm.packages.delete

        def delete(trash_id):
            if trash_id == ids[0]:
                raise PermissionError()
            return original(trash_id)

        self.start("delete", ids)
        with patch.object(self.vm.packages, "delete", side_effect=delete):
            self.drain()
        self.assertEqual(len(self.vm.packages.records()), 1)
        self.assertEqual(self.case.settings.value("pets/a/width"), 224)
        self.assertIsNone(self.case.settings.value("pets/b/width"))

    def test_hide_and_disconnect_keep_job_and_shutdown_stops_unstarted_items(self):
        result, _ = self.start()
        self.case.host.hide()
        self.case.host._disconnect()
        self.assertTrue(self.batch.running)
        self.assertEqual(
            self.batch.status(dict(epoch=0))["job"]["jobId"], result["job"]["jobId"]
        )
        self.step()
        self.case.host.shutdown()
        self.assertFalse(self.batch.running)
        self.assertEqual(len(self.vm.packages.records()), 1)
        self.vm.packages.recover()
        self.assertTrue((self.case.root / "pets" / "b").exists())

    def test_qt_event_loop_processes_items_and_retains_only_last_completed(self):
        self.start(ids=["a"])
        self.batch.timer.start(0)
        for _ in range(100):
            if not self.batch.running:
                break
            QTest.qWait(5)
        self.assertFalse(self.batch.running)
        self.start(ids=["b"])
        self.drain()
        self.assertEqual(self.batch.last["total"], 1)
        self.assertEqual(self.batch.last["results"][0]["id"], "b")

    def test_old_move_result_offers_undo_only_for_packages_still_in_trash(self):
        self.start(ids=["a", "b"])
        self.drain()
        moved = self.batch.status(dict(epoch=0))["job"]
        self.vm.packages.restore(moved["results"][0]["trashId"])
        updated = self.batch.status(dict(epoch=0))["job"]
        self.assertEqual(updated["undoIds"], [moved["results"][1]["trashId"]])
        updated["results"][0]["name"] = "must not mutate controller"
        self.assertNotEqual(
            self.batch.last["results"][0]["name"], "must not mutate controller"
        )

    def test_deleting_records_allow_delete_retry_but_not_batch_restore(self):
        record = self.vm.packages.move("a")
        with patch(
            "watched_kettle.pet.trash.shutil.rmtree", side_effect=PermissionError()
        ):
            with self.assertRaises(PermissionError):
                self.vm.packages.delete(record["trashId"])
        with self.assertRaises(CommandError):
            self.start("restore", [record["trashId"]])
        self.start("delete", [record["trashId"]])
        self.drain()
        self.assertEqual(self.batch.last["results"][0]["status"], "succeeded")
