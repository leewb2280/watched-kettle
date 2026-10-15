"""Constant-space summaries for process memory; raw samples stay in JSONL."""

from dataclasses import asdict, dataclass, field


@dataclass(slots=True)
class MemoryWindow:
    samples: int = 0
    missing: int = 0
    first_bytes: int | None = None
    peak_bytes: int | None = None
    last_bytes: int | None = None
    first_seconds: float | None = None
    last_seconds: float | None = None

    def add(self, elapsed, resources):
        value = resources.get("private_bytes")
        if (
            resources.get("memory_status", "available") != "available"
            or type(value) is not int
            or value < 0
        ):
            self.missing += 1
            return
        if self.first_bytes is None:
            self.first_bytes = self.peak_bytes = value
            self.first_seconds = elapsed
        self.samples += 1
        self.peak_bytes = max(self.peak_bytes or 0, value)
        self.last_bytes = value
        self.last_seconds = elapsed

    @property
    def growth_bytes(self):
        if self.samples < 2 or self.peak_bytes is None or self.first_bytes is None:
            return None
        return self.peak_bytes - self.first_bytes

    def summary(self):
        return {
            **asdict(self),
            "peak_growth_bytes": self.growth_bytes,
            "net_growth_bytes": (
                self.last_bytes - self.first_bytes
                if self.samples >= 2
                and self.last_bytes is not None
                and self.first_bytes is not None
                else None
            ),
        }


@dataclass(slots=True)
class MemoryTrend:
    duration: float
    overall: MemoryWindow = field(default_factory=MemoryWindow)
    after_warmup: MemoryWindow = field(default_factory=MemoryWindow)
    final_ten_minutes: MemoryWindow = field(default_factory=MemoryWindow)
    segments: tuple[MemoryWindow, ...] = field(
        default_factory=lambda: tuple(MemoryWindow() for _ in range(6))
    )

    def add(self, elapsed, resources):
        self.overall.add(elapsed, resources)
        if elapsed >= 300:
            self.after_warmup.add(elapsed, resources)
        if elapsed >= max(0, self.duration - 600):
            self.final_ten_minutes.add(elapsed, resources)
        index = min(5, max(0, int(elapsed * 6 / max(1, self.duration))))
        self.segments[index].add(elapsed, resources)

    def summary(self):
        return {
            "overall": self.overall.summary(),
            "after_warmup": self.after_warmup.summary(),
            "final_ten_minutes": self.final_ten_minutes.summary(),
            "segments": [window.summary() for window in self.segments],
        }
