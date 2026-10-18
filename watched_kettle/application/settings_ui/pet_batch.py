"""Bounded pet batch jobs on the Qt event loop, outside assistant state."""

from watched_kettle.localization import t

from copy import deepcopy
import json
import re
from uuid import uuid4

from PySide6.QtCore import QObject, QTimer

from watched_kettle.application.settings_ui.contracts import (
    CommandError,
    choice,
    require,
    text,
)
from watched_kettle.pet.trash import PetTrashError


class PetBatchController(QObject):
    def __init__(self, adapter):
        super().__init__(adapter)
        self.adapter = adapter
        self.job = None
        self.last = None
        self.delay_ms = 0
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._step)

    @property
    def running(self):
        return self.job is not None

    def _epoch(self, args):
        require(
            args.get("epoch") == self.adapter.account_epoch,
            t("message.0514"),
            "stale_context",
        )

    def _public(self, job):
        if job is None:
            return None
        result = {key: value for key, value in job.items() if not key.startswith("_")}
        result["processed"] = sum(
            row["status"] in {"succeeded", "failed"} for row in job["results"]
        )
        result["succeeded"] = sum(
            row["status"] == "succeeded" for row in job["results"]
        )
        result["failed"] = sum(row["status"] == "failed" for row in job["results"])
        result["undoIds"] = []
        if job["action"] == "move" and job["state"] != "running":
            try:
                available = {
                    row["trashId"]
                    for row in self.adapter.pet_vm.packages.records()
                    if row["state"] == "trashed"
                }
                result["undoIds"] = [
                    row["trashId"]
                    for row in reversed(job["results"])
                    if row["status"] == "succeeded" and row.get("trashId") in available
                ]
            except (OSError, PetTrashError):
                pass
        return deepcopy(result)

    def status(self, args):
        self._epoch(args)
        job_id = text(args.get("jobId", ""), 32)
        job = next(
            (
                job
                for job in (self.job, self.last)
                if job
                and job["_epoch"] == self.adapter.account_epoch
                and (not job_id or job["jobId"] == job_id)
            ),
            None,
        )
        require(
            not job_id or job is not None,
            t("message.0579"),
            "batch_missing",
        )
        return dict(job=self._public(job), snapshot=self.adapter.snapshot())

    def start(self, args):
        self._epoch(args)
        action = choice(args.get("action"), ("move", "restore", "delete"))
        ids = args.get("ids")
        require(isinstance(ids, list) and 1 <= len(ids) <= 256)
        require(all(isinstance(value, str) and 0 < len(value) <= 200 for value in ids))
        require(len(set(ids)) == len(ids))
        key = text(args.get("operationKey"), 80)
        require(re.fullmatch(r"[A-Za-z0-9_-]{8,80}", key) is not None)
        replacement = text(args.get("replacementId", ""), 200)
        fingerprint = json.dumps([action, ids, replacement], ensure_ascii=False)
        for prior in (self.job, self.last):
            if (
                prior
                and prior["operationKey"] == key
                and prior["_epoch"] == self.adapter.account_epoch
            ):
                require(
                    prior["_fingerprint"] == fingerprint,
                    t("message.0584"),
                    "duplicate_operation",
                )
                return dict(
                    accepted=True,
                    job=self._public(prior),
                    snapshot=self.adapter.snapshot(),
                )
        require(
            not self.running,
            t("message.0533"),
            "batch_busy",
        )
        self.adapter._context(args)
        vm = self.adapter.pet_vm
        service = vm.packages
        if action == "move":
            entries = {entry.id: entry for entry in vm.all_pets()}
            duplicates = service.duplicate_ids()
            require(
                all(value in entries for value in ids),
                t("message.0173"),
                "conflict",
            )
            for value in ids:
                reason = service.deletion_reason(entries[value], duplicates)
                require(not reason, reason or t("message.0587"))
            current = vm.snapshot.pet_id
            if current in ids:
                require(
                    replacement in entries and replacement not in ids,
                    t("message.0585"),
                )
                ids = [current, *(value for value in ids if value != current)]
            names = {value: entries[value].display_name for value in ids}
        else:
            records = {row["trashId"]: row for row in service.records()}
            require(
                all(value in records for value in ids),
                t("message.0581"),
                "conflict",
            )
            states = {"trashed"} if action == "restore" else {"trashed", "deleting"}
            require(
                all(records[value]["state"] in states for value in ids),
                t("message.0582"),
            )
            names = {value: records[value]["name"] for value in ids}
        self.job = dict(
            jobId=uuid4().hex,
            operationKey=key,
            action=action,
            state="running",
            total=len(ids),
            results=[
                dict(id=value, name=names[value], status="pending", code="", message="")
                for value in ids
            ],
            message="",
            code="",
            _epoch=self.adapter.account_epoch,
            _revision=self.adapter.revision,
            _petId=vm.snapshot.pet_id,
            _replacement=replacement,
            _fingerprint=fingerprint,
        )
        self.timer.start(self.delay_ms)
        return dict(
            accepted=True, job=self._public(self.job), snapshot=self.adapter.snapshot()
        )

    def _finish(self, state, code="", message=""):
        job = self.job
        if job is None:
            return
        self.timer.stop()
        for row in job["results"]:
            if row["status"] == "pending":
                row.update(status="notStarted", code=code, message=message)
        job.update(state=state, code=code, message=message)
        self.last, self.job = job, None
        self.adapter.changed.emit("settings")

    def cancel(self, args):
        self._epoch(args)
        job_id = text(args.get("jobId"), 32)
        if self.job and self.job["jobId"] == job_id:
            require(
                self.job["_epoch"] == self.adapter.account_epoch, code="stale_context"
            )
            self._finish(
                "cancelled",
                "cancelled",
                t("message.0583"),
            )
        return self.status(dict(epoch=args["epoch"], jobId=job_id))

    def shutdown(self):
        self._finish("cancelled", "app_closed", t("message.0580"))

    def _step(self):
        job = self.job
        if job is None:
            return
        try:
            self.adapter._context(
                dict(
                    epoch=job["_epoch"], revision=job["_revision"], petId=job["_petId"]
                )
            )
        except CommandError as error:
            self._finish(
                "cancelled",
                error.code,
                t("message.0586"),
            )
            return
        row = next((row for row in job["results"] if row["status"] == "pending"), None)
        if row is None:
            self._finish("completed")
            return
        vm = self.adapter.pet_vm
        try:
            if job["action"] == "move":
                record = vm.trash_pet(row["id"], job["_replacement"])
                row["trashId"] = record["trashId"]
            elif job["action"] == "restore":
                vm.packages.restore(row["id"])
            else:
                vm.packages.delete(row["id"])
            row["status"] = "succeeded"
        except (PetTrashError, OSError) as error:
            code = error.code if isinstance(error, PetTrashError) else "file_access"
            row.update(
                status="failed",
                code=code,
                message=str(error)
                if isinstance(error, PetTrashError)
                else t("message.0588"),
            )
            if code == "replacement_failed":
                self._finish("failed", code, row["message"])
                return
        finally:
            vm.refresh()
            self.adapter.revision += 1
            job["_revision"] = self.adapter.revision
            job["_petId"] = vm.snapshot.pet_id
            self.adapter.changed.emit("settings")
        if all(row["status"] != "pending" for row in job["results"]):
            self._finish("completed")
        else:
            self.timer.start(self.delay_ms)
