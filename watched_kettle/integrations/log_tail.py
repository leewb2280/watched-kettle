"""Bounded incremental byte reader shared by lifecycle and usage parsing."""

from dataclasses import dataclass, field
from time import monotonic


@dataclass
class TailCursor:
    offset: int = 0
    identity: tuple | None = None
    partial: bytearray = field(default_factory=bytearray)
    line_start: int = 0
    discarding: bool = False
    replaced: bool = False
    record_ordinal: int = 0
    line_ordinals: tuple[int, ...] = ()

    def read(
        self,
        path,
        byte_budget,
        record_budget,
        deadline,
        line_limit,
        clock=monotonic,
        end_offset=None,
    ):
        stat = path.stat()
        identity = (stat.st_dev, stat.st_ino)
        self.replaced = stat.st_size < self.offset or (
            self.identity is not None and self.identity != identity
        )
        if self.replaced:
            self.offset = 0
            self.partial.clear()
            self.discarding = False
            self.record_ordinal = 0
        self.identity = identity
        found = []
        ordinals = []
        consumed_bytes = consumed_records = 0
        with path.open("rb") as stream:
            stream.seek(self.offset)
            while (
                consumed_bytes < byte_budget
                and consumed_records < record_budget
                and clock() < deadline
                and (end_offset is None or self.offset < end_offset)
            ):
                if not self.partial and not self.discarding:
                    self.line_start = self.offset
                remaining = byte_budget - consumed_bytes
                if end_offset is not None:
                    remaining = min(remaining, end_offset - self.offset)
                chunk = stream.readline(min(65536, remaining))
                if not chunk:
                    break
                consumed_bytes += len(chunk)
                self.offset = stream.tell()
                if not self.discarding:
                    if len(self.partial) + len(chunk) > line_limit:
                        self.partial.clear()
                        self.discarding = True
                    else:
                        self.partial.extend(chunk)
                if chunk.endswith(b"\n"):
                    consumed_records += 1
                    if not self.discarding:
                        found.append((self.line_start, bytes(self.partial)))
                        ordinals.append(self.record_ordinal)
                    self.record_ordinal += 1
                    self.partial.clear()
                    self.discarding = False
        self.line_ordinals = tuple(ordinals)
        return tuple(found), consumed_bytes, consumed_records
