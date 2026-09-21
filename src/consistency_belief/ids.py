"""Identifier allocation and content addressing for consistency-belief."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable


def content_hash(obj: Any, length: int = 12) -> str:
    """Stable hash over a JSON-serialisable object."""
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:length]


def set_hash(ids: Iterable[str], length: int = 6) -> str:
    """Hash of an exact evidence or premise id set."""
    ordered = sorted(set(ids))
    if not ordered:
        return "0" * length
    blob = "\n".join(ordered)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:length]


def sequential_id(prefix: str, n: int, width: int = 4) -> str:
    return f"{prefix}-{n:0{width}d}"
