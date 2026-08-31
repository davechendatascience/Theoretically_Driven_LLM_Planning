"""Identifier allocation and content addressing.

Ids never encode a version, a path, or a revision (rule 1.5), so a rename or a
refactor never orphans evidence.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable


def content_hash(obj: Any, length: int = 12) -> str:
    """Stable hash over a JSON-serialisable object.

    Used for test versions (3.5) and compatibility groups: the same declaration
    always yields the same version, and any edit yields a different one without
    anyone having to remember to bump a number.
    """
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:length]


def set_hash(ids: Iterable[str], length: int = 6) -> str:
    """Hash of an exact evidence-id set — the ``set=`` citation handle.

    A range like ``EV-0112..EV-0149`` is cheaper but can lie: a slice routinely
    uses a non-contiguous subset once invalid trials and other buckets are
    dropped. This cannot misstate its contents, and lets a summary that quotes
    a belief be re-checked against a recomputation later.
    """
    ordered = sorted(set(ids))
    if not ordered:
        return "0" * length
    blob = "\n".join(ordered)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:length]


def sequential_id(prefix: str, n: int, width: int = 4) -> str:
    return f"{prefix}-{n:0{width}d}"
