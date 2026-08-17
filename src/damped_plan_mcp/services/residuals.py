"""Residual computation (blueprint §12): transparent counts, no learned scores.

Hard constraints keep lexicographic priority — the scalar sum is reported but
never overrides `hard_constraint_gap > 0` blocking an implementation plan.
"""

from __future__ import annotations

from ..models import (
    EvidencePolarity,
    EvidenceRecord,
    NextAction,
    Plan,
    ProjectState,
    ResidualReport,
)
from . import plan_validation


def compute_residuals(
    plan: Plan,
    project: ProjectState,
    evidence: list[EvidenceRecord],
    blocker_codes: list[str],
    recommended: NextAction,
    rationale: list[str],
) -> ResidualReport:
    linked_goals = [g for gid in plan.goal_ids if (g := project.goal_by_id(gid))]
    goal_gap = (0 if linked_goals else 1) + sum(
        1 for g in linked_goals if not (g.metric_name and g.target)
    )

    hard_gap = len(plan_validation.unresolved_hard_constraints(plan, project))

    evidence_by_hypothesis: set[str] = set()
    for record in evidence:
        evidence_by_hypothesis.update(record.linked_hypothesis_ids)
    alternatives = (
        plan.hypothesis.alternative_hypothesis_ids if plan.hypothesis else []
    )
    evidence_gap = len(plan.unknowns) + sum(
        1 for alt in alternatives if alt not in evidence_by_hypothesis
    )

    required_steps = [s for s in plan.validation_steps if s.required]
    refuting = [
        r
        for r in evidence
        if r.linked_plan_id == plan.id and r.polarity == EvidencePolarity.REFUTES
    ]
    validation_gap = (0 if required_steps else 1) + len(refuting)

    return ResidualReport(
        goal_gap=goal_gap,
        hard_constraint_gap=hard_gap,
        evidence_gap=evidence_gap,
        validation_gap=validation_gap,
        dependency_gap=0,  # deferred to the Phase 5 dependency graph
        oscillation_risk=0,  # deferred to the Phase 5 drift analyzer
        scope_risk=0 if plan.hypothesis is not None else 1,
        blockers=blocker_codes,
        recommended_next_action=recommended,
        rationale=rationale,
    )
