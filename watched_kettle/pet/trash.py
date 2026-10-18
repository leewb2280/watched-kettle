"""Durable, local pet package lifecycle. No UI or assistant state ownership."""

from watched_kettle.localization import t

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
from uuid import uuid4

from watched_kettle.pet.catalog import (
    discover_pets,
    discover_pets_in_roots,
    order_pet_entries,
)


class PetTrashError(ValueError):
    """An actionable lifecycle failure safe to expose to the renderer."""

    def __init__(self, message, code="pet_trash_failed"):
        super().__init__(message)
        self.code = code


def _linked(path):
    return path.is_symlink() or path.is_junction()


def _safe_tree(path):
    """Never follow links, including links inside a manually installed package."""
    path = Path(path)
    for parent in (path, *path.parents):
        if _linked(parent):
            raise PetTrashError(t("message.0163"))
    if path.is_dir():
        for folder, dirs, files in os.walk(path, followlinks=False):
            if any(_linked(Path(folder) / name) for name in (*dirs, *files)):
                raise PetTrashError(t("message.0180"))
    return path.resolve()


class PetTrashService:
    """Journal before rename; retain per-pet settings until explicit purge.

    A record and its package share a UUID directory outside discovery roots.
    Recovery is idempotent, runs before startup selection, and never deletes an
    ambiguous or unreadable record. All paths are derived here, never from IPC.
    """

    def __init__(self, user_root, roots, preferences):
        self.user_root = Path(user_root).absolute()
        self.root = self.user_root.parent / "pet-trash"
        self.roots = tuple(Path(root).absolute() for root in roots)
        self.preferences = preferences
        self.issues = []

    def _sync(self):
        settings = self.preferences.settings
        if hasattr(settings, "sync"):
            settings.sync()
            status = settings.status()
            if getattr(status, "value", status) != 0:
                raise PetTrashError(t("message.0181"))

    def _folder(self, trash_id):
        if not isinstance(trash_id, str) or not re.fullmatch(r"[0-9a-f]{32}", trash_id):
            raise PetTrashError(t("message.0164"))
        for ancestor in (self.root.parent, *self.root.parent.parents):
            if _linked(ancestor):
                raise PetTrashError(t("message.0182"))
        # Only inspect ancestors here; checking unrelated user data recursively
        # would cross this service's responsibility and make every action slow.
        if _linked(self.root):
            raise PetTrashError(t("message.0165"))
        folder = self.root / trash_id
        if folder.resolve().parent != self.root.resolve():
            raise PetTrashError(t("message.0166"))
        _safe_tree(folder)
        return folder

    def _write(self, record):
        folder = self._folder(record["trashId"])
        folder.mkdir(parents=True, exist_ok=True)
        temporary = folder / "record.tmp"
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(folder / "record.json")

    def _read(self, trash_id):
        folder = self._folder(trash_id)
        try:
            path = folder / "record.json"
            if path.stat().st_size > 256 * 1024:
                raise ValueError()
            record = json.loads(path.read_text(encoding="utf-8"))
            name = record["folder"]
            pet_id = record["petId"]
            if (
                record.get("version") != 1
                or record["trashId"] != trash_id
                or not isinstance(name, str)
                or not name
                or name in {".", ".."}
                or any(char in name for char in "/\\:")
                or name.endswith((".", " "))
                or not isinstance(pet_id, str)
                or not pet_id
                or len(pet_id) > 200
                or any(char in pet_id for char in "/\\:")
                or pet_id in {".", ".."}
                or not isinstance(record["name"], str)
                or not isinstance(record["hidden"], bool)
                or not all(
                    isinstance(record[key], list)
                    and all(isinstance(x, str) for x in record[key])
                    for key in ("before", "after")
                )
                or record["state"] not in {"moving", "trashed", "restoring", "deleting"}
            ):
                raise ValueError()
            datetime.fromisoformat(record["deletedAt"])
            return record
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise PetTrashError(t("message.0183")) from error

    def records(self):
        self.issues = []
        if not self.root.exists():
            return []
        if _linked(self.root):
            raise PetTrashError(t("message.0165"))
        rows = []
        self.issues = []
        for folder in sorted(self.root.iterdir()):
            if not folder.is_dir() or not re.fullmatch(r"[0-9a-f]{32}", folder.name):
                self.issues.append(t("message.0184"))
                continue
            try:
                record = self._read(folder.name)
                rows.append(record)
            except (OSError, PetTrashError) as error:
                self.issues.append(
                    str(error)
                    if isinstance(error, PetTrashError)
                    else t("message.0187")
                )
        return sorted(
            rows, key=lambda row: (row["deletedAt"], row["trashId"]), reverse=True
        )

    def _entries(self):
        return discover_pets_in_roots(self.roots)

    def duplicate_ids(self):
        seen, duplicates = {}, set()
        for root in self.roots:
            for entry in discover_pets(root):
                directory = entry.directory.resolve()
                if entry.id in seen and seen[entry.id] != directory:
                    duplicates.add(entry.id)
                seen[entry.id] = directory
        return duplicates

    def deletion_reason(self, entry, duplicate_ids=None):
        try:
            if entry.directory.absolute().parent != self.user_root:
                return t("message.0167")
            _safe_tree(entry.directory)
            if entry.id in (
                self.duplicate_ids() if duplicate_ids is None else duplicate_ids
            ):
                return t("message.0168")
            if (
                not entry.id
                or len(entry.id) > 200
                or any(char in entry.id for char in "/\\:")
                or entry.id in {".", ".."}
            ):
                return t("message.0169")
            return ""
        except (OSError, PetTrashError):
            return t("message.0170")

    def _original(self, record):
        destination = self.user_root / record["folder"]
        if destination.absolute().parent != self.user_root:
            raise PetTrashError(t("message.0171"))
        _safe_tree(destination)
        return destination

    def _forget(self, pet_id):
        self.preferences.save_pet_custom_order(
            [x for x in self.preferences.load_pet_custom_order() if x != pet_id]
        )
        self.preferences.save_hidden_pet_ids(
            self.preferences.load_hidden_pet_ids() - {pet_id}
        )
        self._sync()

    def _restore_preferences(self, record):
        pet_id = record["petId"]
        hidden = set(self.preferences.load_hidden_pet_ids())
        if record["hidden"]:
            hidden.add(pet_id)
        else:
            hidden.discard(pet_id)
        order = [
            entry.id
            for entry in order_pet_entries(
                self._entries(), "custom", self.preferences.load_pet_custom_order()
            )
            if entry.id != pet_id
        ]
        previous = next((x for x in reversed(record["before"]) if x in order), None)
        following = next((x for x in record["after"] if x in order), None)
        index = (
            order.index(previous) + 1
            if previous
            else order.index(following)
            if following
            else len(order)
        )
        order.insert(index, pet_id)
        self.preferences.save_pet_custom_order(order)
        self.preferences.save_hidden_pet_ids(hidden)
        self._sync()

    def _cleanup(self, record):
        folder = self._folder(record["trashId"])
        # Unknown files are never recursively discarded as metadata cleanup.
        if any(
            path.name not in {"record.json", "record.tmp"} for path in folder.iterdir()
        ):
            raise PetTrashError(t("message.0172"))
        (folder / "record.tmp").unlink(missing_ok=True)
        (folder / "record.json").unlink(missing_ok=True)
        folder.rmdir()

    def move(self, pet_id):
        entry = next((entry for entry in self._entries() if entry.id == pet_id), None)
        if entry is None:
            raise PetTrashError(t("message.0173"))
        reason = self.deletion_reason(entry)
        if reason:
            raise PetTrashError(reason)
        if pet_id == self.preferences.load_selected_pet_id():
            raise PetTrashError(t("message.0174"))
        if any(row["petId"] == pet_id for row in self.records()):
            raise PetTrashError(t("message.0175"))
        order = [
            row.id
            for row in order_pet_entries(
                self._entries(), "custom", self.preferences.load_pet_custom_order()
            )
        ]
        index = order.index(pet_id)
        record = dict(
            version=1,
            trashId=uuid4().hex,
            petId=pet_id,
            name=entry.display_name,
            folder=entry.directory.name,
            deletedAt=datetime.now(timezone.utc).isoformat(),
            hidden=pet_id in self.preferences.load_hidden_pet_ids(),
            before=order[:index],
            after=order[index + 1 :],
            state="moving",
        )
        self._write(record)
        package = self._folder(record["trashId"]) / "package"
        try:
            entry.directory.rename(package)
        except OSError:
            self._cleanup(record)
            raise
        # If saving preferences/final record fails, the durable moving record
        # remains recoverable. Never delete the only surviving package.
        try:
            self._forget(pet_id)
            record["state"] = "trashed"
            self._write(record)
        except (OSError, PetTrashError):
            # Restore the physical package first; keep journaled restore intent
            # if saving settings is still unavailable.
            if package.exists() and not entry.directory.exists():
                record["state"] = "restoring"
                self._write(record)
                package.rename(entry.directory)
                self._restore_preferences(record)
                self._cleanup(record)
            raise
        return record

    def entry(self, record):
        folder = self._folder(record["trashId"])
        return next(
            (
                entry
                for entry in discover_pets(folder)
                if entry.directory.name == "package" and entry.id == record["petId"]
            ),
            None,
        )

    def size(self, record):
        package = self._folder(record["trashId"]) / "package"
        return (
            sum(path.stat().st_size for path in package.rglob("*") if path.is_file())
            if package.exists()
            else 0
        )

    def restore(self, trash_id):
        record = self._read(trash_id)
        if record["state"] != "trashed":
            raise PetTrashError(t("message.0176"))
        destination = self._original(record)
        if destination.exists() or any(
            entry.id == record["petId"] for entry in self._entries()
        ):
            raise PetTrashError(t("message.0177"))
        if len(self._entries()) >= 256:
            raise PetTrashError(t("message.0178"))
        if self.entry(record) is None:
            raise PetTrashError(t("message.0179"))
        record["state"] = "restoring"
        self._write(record)
        package = self._folder(trash_id) / "package"
        try:
            self.user_root.mkdir(parents=True, exist_ok=True)
            package.rename(destination)
        except OSError:
            record["state"] = "trashed"
            self._write(record)
            raise
        self._restore_preferences(record)
        self._cleanup(record)
        return record

    def _finish_delete(self, record):
        # A same-ID package installed again (content pack, manual copy) owns the
        # per-pet settings now. Purge only the trashed files; refusing would
        # leave both the record and the live pet impossible to clean up.
        live = any(entry.id == record["petId"] for entry in self._entries())
        folder = self._folder(record["trashId"])
        package = folder / "package"
        if package.exists():
            # Resolve and validate the exact recursive deletion target.
            target = _safe_tree(package)
            if target.parent != folder.resolve() or target.name != "package":
                raise PetTrashError(t("message.0185"))
            shutil.rmtree(target)
        if not live:
            self.preferences.settings.remove(f"pets/{record['petId']}")
            self._forget(record["petId"])
        self._cleanup(record)

    def delete(self, trash_id):
        record = self._read(trash_id)
        if record["state"] not in {"trashed", "deleting"}:
            raise PetTrashError(t("message.0176"))
        record["state"] = "deleting"
        self._write(record)
        self._finish_delete(record)

    def recover(self, *, retry_deletes=True):
        """Converge journaled intent; ambiguous data remains with a visible issue."""
        try:
            rows = self.records()
        except (OSError, PetTrashError):
            self.issues = [t("message.0186")]
            return self.issues
        issues = list(self.issues)
        for record in rows:
            try:
                package = self._folder(record["trashId"]) / "package"
                original = self._original(record)
                if record["state"] == "moving":
                    if package.exists() and not original.exists():
                        self._forget(record["petId"])
                        record["state"] = "trashed"
                        self._write(record)
                    elif original.exists() and not package.exists():
                        self._cleanup(record)
                    else:
                        raise PetTrashError(t("message.0189"))
                elif record["state"] == "restoring":
                    if (
                        original.exists()
                        and not package.exists()
                        and any(
                            entry.id == record["petId"] and entry.directory == original
                            for entry in self._entries()
                        )
                    ):
                        self._restore_preferences(record)
                        self._cleanup(record)
                    elif package.exists() and not original.exists():
                        record["state"] = "trashed"
                        self._write(record)
                    else:
                        raise PetTrashError(t("message.0190"))
                elif record["state"] == "deleting" and retry_deletes:
                    self._finish_delete(record)
            except (OSError, PetTrashError) as error:
                issues.append(
                    str(error)
                    if isinstance(error, PetTrashError)
                    else t("message.0188")
                )
        self.issues = issues
        return issues
