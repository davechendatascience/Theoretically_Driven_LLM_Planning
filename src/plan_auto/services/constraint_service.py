"""Constraint status transitions (blueprint §10.3).

UNKNOWN is never coerced to SAT: marking a hard constraint SAT requires at
least one existing evidence record and a rationale. Every transition is the
caller's responsibility to event-log.
"""

from __future__ import annotations

from ..models import Constraint, ConstraintKind, ConstraintStatus, ProjectState


class ConstraintUpdateError(ValueError):
    """Rejected transition; the message tells the caller how to proceed."""


def apply_constraint_update(
    project: ProjectState,
    constraint_id: str,
    status: str,
    rationale: str,
    evidence_ids: list[str],
    known_evidence_ids: set[str],
) -> tuple[Constraint, ConstraintStatus]:
    constraint = project.constraint_by_id(constraint_id)
    if constraint is None:
        registered = [c.id for c in project.constraints]
        raise ConstraintUpdateError(
            f"No constraint {constraint_id!r} is registered. Registered constraints: "
            f"{registered}. Add it via register_project first."
        )

    try:
        new_status = ConstraintStatus(str(status).strip().lower())
    except ValueError as exc:
        raise ConstraintUpdateError(
            f"status must be one of sat|unsat|unknown|not_applicable, got {status!r}."
        ) from exc

    if not rationale or not rationale.strip():
        raise ConstraintUpdateError(
            "A rationale is required for every constraint status change: state what "
            "was observed and why it justifies the new status."
        )

    if new_status == ConstraintStatus.SAT and constraint.kind == ConstraintKind.HARD:
        if not evidence_ids:
            raise ConstraintUpdateError(
                f"Marking hard constraint {constraint_id} SAT requires evidence. "
                f"First call record_evidence with what was measured/observed, then "
                f"retry with its id in evidence_ids."
            )
        missing = [eid for eid in evidence_ids if eid not in known_evidence_ids]
        if missing:
            raise ConstraintUpdateError(
                f"Evidence id(s) {missing} do not exist. Call record_evidence first; "
                f"known evidence ids: {sorted(known_evidence_ids)}."
            )

    old_status = constraint.status
    constraint.status = new_status
    constraint.rationale = rationale.strip()
    for eid in evidence_ids:
        if eid not in constraint.evidence_ids:
            constraint.evidence_ids.append(eid)
    return constraint, old_status
