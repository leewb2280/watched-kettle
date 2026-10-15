"""One-way identifiers used by privacy-limited usage records."""

from __future__ import annotations

import hashlib


def hash_identifier(value: object) -> str:
    """Return a short irreversible identifier or empty text for missing input."""
    normalized = str(value or "")
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]
