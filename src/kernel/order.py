"""A total, deterministic order over open work.

v1's project-level recommendation assigned inside an unguarded loop over the
plan store, so the answer was whichever item happened to be iterated last.
Everything here sorts on an explicit key ending in `id`, which is unique, so
the order is total and invariant under store shuffling.
"""

from __future__ import annotations

from typing import Iterable

from .models import SEVERITY_RANK, STATUS_RANK, Change, Constraint


def constraint_key(c: Constraint) -> tuple[int, int, str]:
    return (SEVERITY_RANK.get(c.severity, 99), STATUS_RANK.get(c.status, 99), c.id)


def open_constraints(constraints: Iterable[Constraint]) -> list[Constraint]:
    """Unresolved constraints, worst first. Deterministic under any input order."""
    return sorted(
        (c for c in constraints if c.status in ("unsat", "unknown")),
        key=constraint_key,
    )


CHANGE_STATUS_RANK = {
    "executing": 0, "authorised": 1, "draft": 2,
    "rejected": 3, "rolled_back": 4, "adopted": 5,
}


def change_key(c: Change) -> tuple[int, str]:
    return (CHANGE_STATUS_RANK.get(c.status, 99), c.id)


def open_changes(changes: Iterable[Change]) -> list[Change]:
    return sorted(
        (c for c in changes if c.status in ("draft", "authorised", "executing")),
        key=change_key,
    )


def next_action(constraints: Iterable[Constraint], changes: Iterable[Change]) -> str:
    """Lexicographic, and derived from a total order rather than iteration order."""
    blocking = open_constraints(constraints)
    if any(c.status == "unsat" and c.severity == "critical" for c in blocking):
        return "rollback"
    if blocking:
        return "measure"
    pending = open_changes(changes)
    if not pending:
        return "stop"
    if pending[0].status == "draft":
        return "authorise"
    return "implement"
