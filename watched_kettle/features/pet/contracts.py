"""Decoration data and registry contract; no UI module dependency."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Any


@dataclass(frozen=True)
class BubbleElement:
    id: str
    name: str
    kind: str
    image_path: Path

    @property
    def reference(self):
        return f"user:{self.id}"


class BubbleElementRegistry(Protocol):
    root: Path

    @property
    def elements(self) -> tuple[BubbleElement, ...]: ...
    def elements_for(self, kind: str) -> tuple[BubbleElement, ...]: ...
    def get(self, reference: str) -> BubbleElement | None: ...
    def pixmap(self, reference: str) -> Any: ...
    def refresh(self) -> None: ...
    def import_image(self, source_path, kind, name=None) -> BubbleElement: ...
    def delete(self, reference: str) -> bool: ...
