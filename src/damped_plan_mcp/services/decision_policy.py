"""Deterministic decision policy (blueprint §13)."""

from __future__ import annotations

from ..models import (
    ClosureReport,
    EvidencePolarity,
    EvidenceRecord,
    NextAction,
    Plan,
    PlanStatus,
    ProjectState,
    TERMINAL_PLAN_STATUSES,
)
from . import plan_validation

# §15.2: after this many failed sibling plans without new evidence, stop
# permitting local patches.
REPEATED_FAILURE_THRESHOLD = 2


def repeated_noninformative_failure(
    plan: Plan, all_plans: list[Plan], evidence: list[EvidenceRecord]
) -> bool:
    """True when >= threshold sibling plans addressing a shared failure mode
    already failed and no new evidence has been recorded since the first
    failure — the next proposal must change the causal framing, not the code."""
    shared = set(plan.addresses_failure_ids)
    if not shared:
        return False
    failed_siblings = [
        p
        for p in all_plans
        if p.id != plan.id
        and p.status in (PlanStatus.REJECTED, PlanStatus.ROLLED_BACK)
        and shared & set(p.addresses_failure_ids)
    ]
    if len(failed_siblings) < REPEATED_FAILURE_THRESHOLD:
        return False
    first_failure_at = min(p.updated_at for p in failed_siblings)
    return not any(r.created_at > first_failure_at for r in evidence)


def recommend_next_action(
    plan: Plan,
    project: ProjectState,
    closure: ClosureReport,
    all_plans: list[Plan],
    evidence: list[EvidenceRecord],
    predictive_check=None,
) -> tuple[NextAction, list[str]]:
    rationale: list[str] = []

    if plan.status in TERMINAL_PLAN_STATUSES:
        rationale.append(f"Plan is terminal ({plan.status}); no further action.")
        return NextAction.STOP, rationale

    if plan_validation.has_critical_unsat_constraint(plan, project):
        rationale.append(
            "A CRITICAL hard constraint is UNSAT: roll back or redesign before "
            "anything else."
        )
        return NextAction.ROLLBACK, rationale

    if plan_validation.unresolved_hard_constraints(plan, project):
        if plan_validation.measurement_exception_applies(plan, project):
            rationale.append(
                "Unknown hard constraint(s) are exactly what this safe measurement "
                "plan resolves; measure first."
            )
            return NextAction.MEASURE, rationale
        unresolved = plan_validation.unresolved_hard_constraints(plan, project)
        rationale.append(
            f"Hard constraint(s) {unresolved} are not SAT and this plan does not "
            f"safely measure them. Create a measurement plan for them or escalate "
            f"to the user."
        )
        return NextAction.ESCALATE, rationale

    if not closure.structurally_complete():
        rationale.append(
            "The plan is missing required structure; repair the plan itself "
            "(see blockers), not the code."
        )
        return NextAction.REPAIR, rationale

    if repeated_noninformative_failure(plan, all_plans, evidence):
        rationale.append(
            f"At least {REPEATED_FAILURE_THRESHOLD} prior plans for the same failure "
            f"mode were rejected or rolled back with no new evidence since. Escalate: "
            f"change the causal hypothesis, representation, interface, or oracle "
            f"before another local patch."
        )
        return NextAction.ESCALATE, rationale

    if predictive_check is not None and predictive_check.status == "mismatch":
        expansion = predictive_check.recommended_expansion
        rationale.append(
            "Posterior predictive check MISMATCH: the causal model behind this "
            "plan did not produce the predicted observable pattern"
            + (f" ({predictive_check.discrepancy_summary})" if predictive_check.discrepancy_summary else "")
            + ". Escalate: expand the model"
            + (f" — start with: {expansion}." if expansion else " per the contract's disconfirming patterns.")
        )
        return NextAction.ESCALATE, rationale

    refuting = [
        r
        for r in evidence
        if r.linked_plan_id == plan.id and r.polarity == EvidencePolarity.REFUTES
    ]
    if refuting:
        rationale.append(
            f"Refuting evidence is linked to this plan ({[r.id for r in refuting]}); "
            f"repair the plan or record the outcome as rejected."
        )
        return NextAction.REPAIR, rationale

    if plan.status in (PlanStatus.APPROVED, PlanStatus.EXECUTABLE, PlanStatus.EXECUTING):
        rationale.append("All gate conditions hold and the plan is approved.")
        return NextAction.IMPLEMENT, rationale

    if plan.kind.value == "measurement":
        rationale.append(
            "Measurement plan is closed; awaiting human approval, then measure."
        )
        return NextAction.MEASURE, rationale

    rationale.append(
        "Plan is closed and READY_FOR_REVIEW; ask the human to approve_plan before "
        "implementing."
    )
    return NextAction.STOP, rationale
