"""Deterministic ID generation: G-0001, C-0001, F-0001, P-0001, EV-0001, ..."""

from __future__ import annotations

import re
from collections.abc import Iterable

GOAL_PREFIX = "G"
CONSTRAINT_PREFIX = "C"
FACT_PREFIX = "FACT"
FAILURE_PREFIX = "F"
PLAN_PREFIX = "P"
EVIDENCE_PREFIX = "EV"
HYPOTHESIS_PREFIX = "H"
INTERVENTION_PREFIX = "I"
VALIDATION_PREFIX = "V"
CLAIM_PREFIX = "CLM"
SUBTASK_PREFIX = "SUB"


def generate_id(prefix: str = CLAIM_PREFIX) -> str:
    """Generate a unique ID with prefix."""
    import uuid

    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def next_id(prefix: str, existing: Iterable[str]) -> str:
    """Return the next id for `prefix` given ids already in use.

    Non-numeric suffixes (user-supplied ids like "C-compute-budget") are
    counted for collision avoidance but do not affect the numeric sequence.
    """
    pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)$")
    highest = 0
    taken = set(existing)
    for candidate in taken:
        match = pattern.match(candidate)
        if match:
            highest = max(highest, int(match.group(1)))
    candidate_id = f"{prefix}-{highest + 1:04d}"
    while candidate_id in taken:
        highest += 1
        candidate_id = f"{prefix}-{highest + 1:04d}"
    return candidate_id

