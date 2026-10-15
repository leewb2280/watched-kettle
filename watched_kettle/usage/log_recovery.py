"""Bounded, content-free recovery through verified rollout prefix links."""

from __future__ import annotations

import json
from collections import OrderedDict
from copy import deepcopy
from pathlib import Path
from time import monotonic

from PySide6.QtCore import QObject, QTimer

from watched_kettle.integrations.codex_log import rollout_session_id
from watched_kettle.integrations.codex_paths import codex_home
from watched_kettle.usage.identifiers import hash_identifier
from watched_kettle.usage.turn_log import TurnLogParser, TurnUsageEvidence

MAX_LINE_BYTES = 4 * 1024 * 1024
MAX_FILES = 50000
MAX_CHAIN = 64


class LinkError(ValueError):
    pass


def signature(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def same_prefix(before, after):
    """Appending is normal; replacement, truncation and same-size edits are not."""
    return before[:2] == after[:2] and (
        after[2] > before[2] or (after[2] == before[2] and after[3] == before[3])
    )


class LocalTurnRecovery(QObject):
    """Scan cooperatively; callbacks carry hashes, never conversation content."""

    def __init__(self, on_evidence, parent=None, roots=None, on_state=None):
        super().__init__(parent)
        self.on_evidence = on_evidence
        self.on_state = on_state or (lambda *args: None)
        home = codex_home()
        self.roots = tuple(
            Path(root)
            for root in (roots or (home / "sessions", home / "archived_sessions"))
        )
        self.timer = QTimer(self)
        self.timer.setInterval(25)
        self.timer.timeout.connect(self._tick)
        self.targets = set()
        self.turns = set()
        self.evidence_cache = {}
        self.statuses = {}
        self.index = {}
        self.watched = {}
        self.work = None
        self.rediscover = False
        self.idle_until = None
        self.next_poll = 0.0
        self.next_discovery = 0.0
        self.headers = {}
        self.file_signatures = {}
        self.checkpoints = OrderedDict()
        self._dependency_stack = []
        self._versions = {}
        self._requested = set()
        self._forced = set()
        self._record_targets = False
        self._tick_bytes = 0

    def clear(self):
        self.timer.stop()
        if self.work is not None:
            self.work.close()
        self.work = None
        self.targets.clear()
        self.turns.clear()
        self.evidence_cache.clear()
        self.statuses.clear()
        self.index.clear()
        self.watched.clear()
        self.rediscover = False
        self.idle_until = None
        self.headers.clear()
        self.file_signatures.clear()
        self.checkpoints.clear()
        self._dependency_stack.clear()
        self._versions.clear()
        self._requested.clear()
        self._forced.clear()

    def replay_cached(self):
        # Service owns the bounded queue of updates deferred during account checks.
        return

    def acknowledge(self, keys):
        for key in keys:
            self.turns.discard(key)
            self._requested.discard(key)
            self.statuses.pop(key, None)
            self.evidence_cache.pop(key, None)
        if self._record_targets:
            self.targets = {k[0] for k in self.turns}
            if not self.targets:
                self.timer.stop()
                if self.work is not None:
                    self.work.close()
                    self.work = None
                self.rediscover = False

    def _state(self, key, state, reason=""):
        value = (state, reason)
        if self.statuses.get(key) != value:
            self.statuses[key] = value
            self.on_state(*key, state, reason)

    def add_records(self, records, *, manual=False, resume=False):
        self._record_targets = True
        keys = {
            (r.thread_hash, r.turn_hash)
            for r in records
            if r.source_version == 3 and r.data_quality == "unavailable" and r.turn_hash
        }
        restored = set()
        if resume and not manual:
            for record in records:
                key = (record.thread_hash, record.turn_hash)
                if record.quality_reason.startswith("recovery:"):
                    reason = record.quality_reason.removeprefix("recovery:").split(
                        "|original:", 1
                    )[0]
                    self.statuses.setdefault(key, ("unavailable", reason))
                    restored.add(key)
        self._requested.update(keys if manual else keys - self.turns - restored)
        self.turns.update(keys)
        if len(self.turns) > 1024:
            self.turns = keys
            self.statuses = {k: v for k, v in self.statuses.items() if k in keys}
        self.add_targets({key[0] for key in keys}, discover=False)

    def add_targets(self, thread_hashes, *, discover=True):
        thread_hashes = tuple(thread_hashes)
        self.targets.update(key for key in thread_hashes if key)
        if discover:
            self._forced.update(thread_hashes)
        if self.targets:
            self.rediscover = True
            self.idle_until = None
            self.timer.start()

    def add_live_target(self, thread_id, started_at):
        self.add_targets((hash_identifier(thread_id),))

    def _all_paths(self):
        for root in self.roots:
            if root.is_dir():
                yield from root.rglob("rollout-*.jsonl")

    def _tick(self):
        if not self.targets:
            return
        if self.work is None and self.rediscover:
            self.rediscover = False
            self.work = self._round()
        deadline = monotonic() + 0.008
        self._tick_bytes = 0
        for _ in range(200):
            if (
                self.work is None
                or monotonic() >= deadline
                or self._tick_bytes >= 1024 * 1024
            ):
                break
            try:
                next(self.work)
            except StopIteration:
                self.work = None
                if self.idle_until is None:
                    self.idle_until = monotonic() + 300
                self.next_discovery = monotonic() + 30
        if self.work is not None or self.rediscover:
            return
        now = monotonic()
        if self.idle_until is not None and now >= self.idle_until:
            # Keep cache/status until the service clears the account generation.
            self.timer.stop()
            return
        if now >= self.next_poll:
            self.next_poll = now + 2
            for path, before in self.watched.items():
                try:
                    changed = signature(path) != before
                except OSError:
                    changed = True
                if changed:
                    self.rediscover = True
                    break
        if now >= self.next_discovery:
            self.rediscover = True

    def _closure(self, paths):
        found = set(paths)
        todo = list(paths)
        for _ in range(MAX_FILES):
            if not todo:
                break
            path = todo.pop()
            base = self.headers.get(path, {}).get("base")
            for parent in self.index.get(base, ()):
                if parent not in found:
                    found.add(parent)
                    todo.append(parent)
        return found

    def _round(self):
        index: dict[str, list[Path]] = {}
        signatures = {}
        headers = {}
        limited = False
        for count, path in enumerate(self._all_paths()):
            if count >= MAX_FILES:
                limited = True
                break
            try:
                current = signature(path)
                old = self.file_signatures.get(path)
                header = (
                    self.headers.get(path)
                    if old and same_prefix(old, current)
                    else None
                )
                if header is None:
                    with path.open("rb") as stream:
                        line = yield from self._line(stream, MAX_LINE_BYTES + 1)
                    if len(line) > MAX_LINE_BYTES or not line.endswith(b"\n"):
                        yield
                        continue
                    record = json.loads(line)
                    payload = record.get("payload")
                    if record.get("type") != "session_meta" or not isinstance(
                        payload, dict
                    ):
                        yield
                        continue
                    base = payload.get("history_base")
                    reference = (
                        base.get("thread_id") if isinstance(base, dict) else None
                    )
                    header = {
                        "id": payload.get("id"),
                        "base": reference if isinstance(reference, str) else None,
                    }
                headers[path] = header
                signatures[path] = current
                index.setdefault(rollout_session_id(path), []).append(path)
            except (OSError, ValueError, AttributeError):
                pass
            yield
        self.index, self.headers, self.file_signatures = index, headers, signatures
        self.watched = {}
        forced, self._forced = self._forced, set()
        for owner in tuple(self.targets):
            keys = {k for k in self.turns if k[0] == owner}
            paths = [
                p for p, h in headers.items() if hash_identifier(h.get("id")) == owner
            ]
            dependencies = self._closure(paths)
            version = tuple(sorted((str(p), signatures.get(p)) for p in dependencies))
            self.watched.update(
                {p: signatures[p] for p in dependencies if p in signatures}
            )
            requested = keys & self._requested
            self._requested.difference_update(requested)
            if (
                self._versions.get(owner) == version
                and not requested
                and owner not in forced
            ):
                continue
            for key in keys:
                if key in requested or key not in self.statuses:
                    self._state(key, "checking")
            yield
            failures = {}
            candidates: dict[tuple[str, str], TurnUsageEvidence] = {}
            conflicts = set()
            retry = False
            for path in paths:
                try:
                    parser, _count, evidence, problem = yield from self._parse(
                        path, (), signatures[path][2], allow_tail=True
                    )
                    if not same_prefix(signatures[path], signature(path)):
                        raise LinkError("log_changed")
                    for turn, reason in parser.failures.items():
                        failures[(owner, hash_identifier(turn))] = (
                            problem
                            if problem and reason == "token_baseline_missing"
                            else reason
                        )
                    if problem:
                        for key in keys:
                            failures.setdefault(key, problem)
                    for item in evidence:
                        key = (
                            hash_identifier(item.thread_id),
                            hash_identifier(item.turn_id),
                        )
                        if self._record_targets and key not in keys:
                            continue
                        if key in candidates and candidates[key] != item:
                            conflicts.add(key)
                        candidates[key] = item
                        while len(candidates) > 1024:
                            candidates.pop(next(iter(candidates)))
                except (OSError, LinkError) as error:
                    reason = (
                        str(error)
                        if isinstance(error, LinkError)
                        else "linked_log_missing"
                    )
                    retry |= reason == "log_changed"
                    for key in keys:
                        failures.setdefault(key, reason)
                yield
            for key, item in candidates.items():
                if key in conflicts:
                    failures[key] = "conflicting_evidence"
                    continue
                if self.evidence_cache.get(key) != item:
                    self.evidence_cache[key] = item
                    while len(self.evidence_cache) > 1024:
                        self.evidence_cache.pop(next(iter(self.evidence_cache)))
                    self.on_evidence(item)
                self._state(key, "measured")
                yield
            for key in keys:
                if key not in candidates or key in conflicts:
                    reason = failures.get(key) or (
                        "scan_limit"
                        if limited
                        else "turn_boundary_missing"
                        if paths
                        else "local_log_missing"
                    )
                    self._state(key, "unavailable", reason)
                    yield
            if not retry:
                self._versions[owner] = version
            else:
                self._forced.add(owner)
                self.rediscover = True

    def _line(self, stream, limit):
        chunks = []
        remaining = limit
        while remaining > 0:
            part = stream.readline(min(remaining, 64 * 1024))
            self._tick_bytes += len(part)
            chunks.append(part)
            remaining -= len(part)
            if self._tick_bytes >= 1024 * 1024:
                yield
            if not part or part.endswith(b"\n"):
                break
        return b"".join(chunks)

    def _valid_checkpoint(self, entry):
        try:
            return all(
                same_prefix(sig, signature(p))
                and (
                    not self.headers.get(p, {}).get("base")
                    or len(self.index.get(self.headers[p]["base"], ())) == 1
                )
                for p, sig in entry[0].items()
            )
        except OSError:
            return False

    def _parse(self, path, stack, boundary=None, allow_tail=False):
        if path in stack or len(stack) >= MAX_CHAIN:
            raise LinkError("link_cycle" if path in stack else "scan_limit")
        if boundary is None:
            boundary = signature(path)[2]
        key = (path, boundary)
        cached = self.checkpoints.get(key)
        if (
            cached
            and self._valid_checkpoint(cached)
            and (allow_tail or cached[1][0]._file_offset == boundary)
        ):
            self.checkpoints.move_to_end(key)
            if self._dependency_stack:
                self._dependency_stack[-1].update(cached[0])
            return deepcopy(cached[1])
        resume = None
        if boundary is not None:
            for (known_path, end), entry in reversed(self.checkpoints.items()):
                if (
                    known_path == path
                    and end is not None
                    and end < boundary
                    and self._valid_checkpoint(entry)
                ):
                    resume = entry
                    break
        deps = {path: signature(path)}
        if resume:
            deps.update(resume[0])
            deps[path] = signature(path)
        self._dependency_stack.append(deps)
        try:
            result = yield from self._parse_uncached(
                path,
                stack,
                boundary,
                allow_tail,
                deepcopy(resume[1]) if resume else None,
            )
        finally:
            self._dependency_stack.pop()
        if not result[3]:
            self.checkpoints[key] = (deps, deepcopy(result))
            self.checkpoints.move_to_end(key)
            while len(self.checkpoints) > 1024:
                self.checkpoints.popitem(last=False)
        if self._dependency_stack:
            self._dependency_stack[-1].update(deps)
        return result

    def _parse_uncached(
        self, path, stack, boundary=None, allow_tail=False, resume=None
    ):
        if path in stack or len(stack) >= MAX_CHAIN:
            raise LinkError("link_cycle" if path in stack else "scan_limit")
        before = signature(path)
        parser = TurnLogParser(rollout_session_id(path))
        evidence = []
        problem = ""
        with path.open("rb") as stream:
            if resume:
                parser, ordinal, evidence, problem = resume
                stream.seek(parser._file_offset)
            else:
                line = yield from self._line(stream, MAX_LINE_BYTES + 1)
                try:
                    head = json.loads(line)
                    meta = head["payload"]
                except (ValueError, KeyError, TypeError):
                    raise LinkError("log_damaged") from None
                parser.feed(head)
                if not parser.trusted:
                    raise LinkError("owner_mismatch")
                base = meta.get("history_base")
                ordinal = 0
                if base:
                    try:
                        if not isinstance(base, dict):
                            raise LinkError("link_boundary_invalid")
                        if not isinstance(base.get("thread_id"), str):
                            raise LinkError("link_boundary_invalid")
                        candidates = self.index.get(base.get("thread_id"), ())
                        if len(candidates) != 1:
                            raise LinkError(
                                "linked_log_missing"
                                if not candidates
                                else "link_ambiguous"
                            )
                        end = base.get("end_byte_offset")
                        expected = base.get("end_ordinal_exclusive")
                        if (
                            type(end) is not int
                            or end <= 0
                            or type(expected) is not int
                            or expected <= 0
                        ):
                            raise LinkError("link_boundary_invalid")
                        previous, ordinal, _ignored, _problem = yield from self._parse(
                            candidates[0], (*stack, path), end
                        )
                        if ordinal != expected:
                            raise LinkError("link_boundary_invalid")
                        if previous.thread_id != parser.thread_id:
                            raise LinkError("owner_mismatch")
                        parser.inherit(previous)
                        problem = _problem
                    except (LinkError, OSError) as error:
                        problem = (
                            str(error)
                            if isinstance(error, LinkError)
                            else "linked_log_missing"
                        )
                        # Unknown inherited baseline is never replaced with zero.
                        ordinal = head.get("ordinal", 0)
                        if type(ordinal) is not int:
                            raise LinkError("link_boundary_invalid") from None
                        if problem in {
                            "owner_mismatch",
                            "link_cycle",
                            "link_ambiguous",
                        }:
                            raise LinkError(problem) from None
                if head.get("ordinal", ordinal) != ordinal:
                    raise LinkError("link_boundary_invalid")
                ordinal += 1
                yield
            while boundary is None or stream.tell() < boundary:
                start = stream.tell()
                remaining = (
                    MAX_LINE_BYTES + 1
                    if boundary is None
                    else min(MAX_LINE_BYTES + 1, boundary - start)
                )
                line = yield from self._line(stream, remaining)
                if not line:
                    break
                if boundary is not None and stream.tell() > boundary:
                    raise LinkError("link_boundary_invalid")
                if not line.endswith(b"\n"):
                    if len(line) <= MAX_LINE_BYTES:
                        stream.seek(start)
                        break
                    parser.invalidate()
                    while line and not line.endswith(b"\n"):
                        yield
                        line = yield from self._line(stream, MAX_LINE_BYTES + 1)
                    ordinal += 1
                    yield
                    continue
                try:
                    row = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    parser.invalidate()
                else:
                    if (
                        not isinstance(row, dict)
                        or row.get("ordinal", ordinal) != ordinal
                    ):
                        raise LinkError("link_boundary_invalid")
                    item = parser.feed(row)
                    if item is not None:
                        evidence.append(item)
                        if len(evidence) > 1024:
                            evidence.pop(0)
                ordinal += 1
                yield
            if boundary is not None and stream.tell() != boundary and not allow_tail:
                raise LinkError("link_boundary_invalid")
            parser._file_offset = stream.tell()
        if not same_prefix(before, signature(path)):
            raise LinkError("log_changed")
        return parser, ordinal, evidence, problem
