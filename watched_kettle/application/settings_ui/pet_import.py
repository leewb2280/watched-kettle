"""One cancellable preparation worker; results enter Qt only through status reads."""

import base64
import threading
from uuid import uuid4

from watched_kettle.localization import t
from watched_kettle.pet.importer import PetImporter, PetImportError, PreparedPet
from watched_kettle.pet.import_package import PackageError
from watched_kettle.pet.import_sources import (
    Fetcher,
    InstalledPets,
    SourceError,
    online_pet,
)
from watched_kettle import settings_protocol as wire


THEME_WARNING = "bubbleTheme."


def preparation(prepared) -> wire.PetPreparation:
    # Unused package fields are listed by name; another installation's
    # decoration references are explained once instead.
    return dict(
        token=prepared.token,
        name=prepared.name,
        thumbnail="data:image/png;base64,"
        + base64.b64encode(prepared.thumbnail).decode("ascii"),
        spriteVersion=prepared.version,
        description=prepared.extras.get("description", ""),
        source=prepared.source,
        warnings=[w for w in prepared.warnings if not w.startswith(THEME_WARNING)],
        omittedThemeReferences=any(
            w.startswith(THEME_WARNING) for w in prepared.warnings
        ),
    )


class PetImportJob:
    """One preparation's state; a cancelled worker only ever writes its own."""

    def __init__(self, job_id=None):
        self.id = uuid4().hex if job_id is None else job_id
        self.stop = threading.Event()
        self.worker: threading.Thread | None = None
        self.result: PreparedPet | None = None
        self.error = ""
        self.received = self.total = 0
        self.cancelled = False


class PetImportController:
    def __init__(self, adapter):
        self.adapter = adapter
        self.installed = InstalledPets()
        self.job = PetImportJob(job_id="")

    @property
    def job_id(self):
        return self.job.id

    @property
    def worker(self):
        return self.job.worker

    def start(self, *, path=None, command=None):
        # A cancelled download may still wait on the network for a few
        # seconds; it no longer blocks a new attempt.
        if self.worker and self.worker.is_alive() and not self.job.stop.is_set():
            raise PetImportError(t("pet.import.busy"))
        self.adapter.cancel_pet_import()
        job = self.job = PetImportJob()

        def progress(received, total):
            job.received, job.total = received, total

        def run():
            importer = PetImporter(self.adapter.pet_importer.root)
            try:
                result = (
                    online_pet(command, importer, Fetcher(job.stop, progress))
                    if command is not None
                    else importer.prepare(path)
                )
                if not job.stop.is_set():
                    job.result = result
            except Exception as error:
                job.error = (
                    str(error)
                    if isinstance(error, (PetImportError, SourceError, PackageError))
                    and str(error)
                    else t("pet.import.invalid_package")
                )

        job.worker = threading.Thread(target=run, daemon=True, name="pet-import")
        job.worker.start()
        return self.status(job.id)

    def cancel(self, key=None):
        if key is None or key == self.job.id:
            self.job.stop.set()
            self.job.result = None
            self.job.cancelled = True

    def status(self, key):
        job = self.job
        if key != job.id:
            raise PetImportError(t("pet.import.cancelled"))
        result: wire.PetImportJob = dict(
            jobId=key,
            state="preparing",
            received=job.received,
            total=job.total,
            error="",
        )
        if job.cancelled:
            result["state"] = "cancelled"
        elif job.worker and job.worker.is_alive():
            pass
        elif job.error:
            result["state"] = "error"
            result["error"] = job.error
        elif job.result:
            result["state"] = "ready"
            if self.adapter.pet_importer.prepared is not job.result:
                self.adapter.pet_importer.prepared = job.result
                self.adapter.import_timer.start(600000)
            result["prepared"] = preparation(job.result)
        else:
            result["state"] = "cancelled"
        return result
