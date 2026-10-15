"""Generation-scoped account requests; no GUI or network ownership."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RequestContext:
    generation: int
    kind: str
    task_key: tuple[str, str] | None = None
    refresh_id: int = 0


class AccountSession:
    def __init__(self):
        self.generation = 0
        self.requests: dict[int, RequestContext] = {}

    def invalidate(self):
        self.generation += 1
        self.requests.clear()

    def consume(self, request_id):
        context = self.requests.pop(request_id, None)
        return (
            context
            if context is not None and context.generation == self.generation
            else None
        )
