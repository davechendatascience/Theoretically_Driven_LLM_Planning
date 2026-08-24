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

    # Micro-damping evidence calibration (v0.4.0)
    linked_evidence = [r for r in evidence if r.linked_plan_id == plan.id]
    all_claims = []
    bundle_variances = []
    for r in linked_evidence:
        if r.subtask_bundle:
            all_claims.extend(r.subtask_bundle.claims)
            bundle_variances.append(r.subtask_bundle.residual_variance)
        all_claims.extend(r.claims)

    if all_claims:
        agg_credibility = sum(c.credibility_score for c in all_claims) / len(all_claims)
    else:
        agg_credibility = 1.0

    # Calculate credibility-weighted empirical residual variance
    # r_i = c_i * (y_{obs, i} - y_{pred, i})
    weighted_discrepancies: list[float] = []
    if plan.predictive_contract:
        pred_map = {p.metric_id: p for p in plan.predictive_contract.predictions}
        for r in linked_evidence:
            cred = (
                (sum(c.credibility_score for c in r.claims) / len(r.claims))
                if r.claims
                else (1.0 if r.source_type != "manual_review" else 0.5)
            )
            for obs in r.observations:
                if obs.metric_id in pred_map:
                    pred = pred_map[obs.metric_id]
                    if pred.expected_range:
                        lo, hi = pred.expected_range
                        target = (lo + hi) / 2.0
                        # Credibility-weighted empirical residual
                        weighted_r = cred * (obs.value - target)
                        weighted_discrepancies.append(weighted_r)

    if weighted_discrepancies:
        mean_d = sum(weighted_discrepancies) / len(weighted_discrepancies)
        res_variance = sum((d - mean_d) ** 2 for d in weighted_discrepancies) / len(
            weighted_discrepancies
        )
    elif bundle_variances:
        res_variance = sum(bundle_variances) / len(bundle_variances)
    else:
        res_variance = 0.0

    return ResidualReport(
        goal_gap=goal_gap,
        hard_constraint_gap=hard_gap,
        evidence_gap=evidence_gap,
        validation_gap=validation_gap,
        dependency_gap=0,  # deferred to the Phase 5 dependency graph
        oscillation_risk=0,  # deferred to the Phase 5 drift analyzer
        scope_risk=0 if plan.hypothesis is not None else 1,
        residual_variance=round(res_variance, 4),
        aggregate_credibility=round(agg_credibility, 4),
        blockers=blocker_codes,
        recommended_next_action=recommended,
        rationale=rationale,
    )
