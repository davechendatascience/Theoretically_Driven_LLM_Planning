"""Deterministic plan-closure validation (blueprint §10–§11).

The closure predicate and status ladder:

- structural gap                          -> UNDER_SPECIFIED (+ repair instructions)
- complete impl/repair, hard not all SAT  -> BLOCKED (+ escape route per constraint)
- measurement targeting the unknown(s)    -> READY_FOR_REVIEW, recommend MEASURE
- complete, all hard SAT                  -> READY_FOR_REVIEW, executable=True
- approve_plan then promotes              -> EXECUTABLE

Effective constraint status is the conservative merge of the project's
evidence-gated status and the plan's audit claim: UNSAT from either side wins;
an audit may scope a constraint out with NOT_APPLICABLE; SAT can only come
from the project record (no plan self-certification, §10.3).
"""

from __future__ import annotations

from ..models import (
    Blocker,
    ClosureReport,
    Constraint,
    ConstraintKind,
    ConstraintStatus,
    PlanConstraintAudit,
    Plan,
    PlanKind,
    PlanStatus,
    ProjectState,
    Severity,
    TERMINAL_PLAN_STATUSES,
)


def effective_constraint_status(
    constraint: Constraint, audit_entry: PlanConstraintAudit | None
) -> ConstraintStatus:
    audit_status = audit_entry.status if audit_entry else None
    if constraint.status == ConstraintStatus.UNSAT or audit_status == ConstraintStatus.UNSAT:
        return ConstraintStatus.UNSAT
    if audit_status == ConstraintStatus.NOT_APPLICABLE:
        return ConstraintStatus.NOT_APPLICABLE
    if constraint.status in (ConstraintStatus.SAT, ConstraintStatus.NOT_APPLICABLE):
        return constraint.status
    return ConstraintStatus.UNKNOWN


def hard_constraint_statuses(
    plan: Plan, project: ProjectState
) -> dict[str, ConstraintStatus]:
    audit = plan.audit_by_constraint()
    return {
        c.id: effective_constraint_status(c, audit.get(c.id))
        for c in project.hard_constraints()
    }


def unresolved_hard_constraints(plan: Plan, project: ProjectState) -> list[str]:
    return [
        cid
        for cid, status in hard_constraint_statuses(plan, project).items()
        if status not in (ConstraintStatus.SAT, ConstraintStatus.NOT_APPLICABLE)
    ]


def unsat_hard_constraints(plan: Plan, project: ProjectState) -> list[str]:
    return [
        cid
        for cid, status in hard_constraint_statuses(plan, project).items()
        if status == ConstraintStatus.UNSAT
    ]


def has_critical_unsat_constraint(plan: Plan, project: ProjectState) -> bool:
    return any(
        project.constraint_by_id(cid) is not None
        and project.constraint_by_id(cid).severity == Severity.CRITICAL
        for cid in unsat_hard_constraints(plan, project)
    )


def failure_linked(plan: Plan, project: ProjectState) -> tuple[bool, bool]:
    """Returns (linked, via_failure_mode).

    Relaxed rule: a plan is linked if it addresses a registered failure mode
    OR targets a goal whose metric is not yet met (goal-gap).
    """
    known_failures = {f.id for f in project.failure_modes}
    via_failure = bool(set(plan.addresses_failure_ids) & known_failures)
    if via_failure:
        return True, True
    via_goal_gap = any(
        (goal := project.goal_by_id(gid)) is not None and not goal.met
        for gid in plan.goal_ids
    )
    return via_goal_gap, False


def hypothesis_is_testable(plan: Plan) -> bool:
    return (
        plan.hypothesis is not None
        and bool(plan.validation_steps)
        and any(step.required for step in plan.validation_steps)
    )


def has_decision_rule(plan: Plan) -> bool:
    return bool(
        plan.decision_rule
        and plan.decision_rule.adopt_if
        and plan.decision_rule.reject_if
    )


def has_safe_rollback(plan: Plan) -> bool:
    if plan.kind == PlanKind.MEASUREMENT:
        return True
    return bool(plan.rollback_description) or (
        plan.intervention is not None and plan.intervention.reversible
    )


def measurement_targets(plan: Plan, project: ProjectState) -> list[str]:
    """Unknown hard constraints this measurement plan claims to resolve.

    The deterministic proxy for "directly measures the unknown": the plan's
    audit entry for that constraint is UNKNOWN and carries a non-empty
    evidence/rationale text explaining that this plan measures it.
    """
    audit = plan.audit_by_constraint()
    targets = []
    for cid, status in hard_constraint_statuses(plan, project).items():
        if status != ConstraintStatus.UNKNOWN:
            continue
        entry = audit.get(cid)
        if entry is not None and entry.evidence and entry.evidence.strip():
            targets.append(cid)
    return targets


def measurement_exception_applies(plan: Plan, project: ProjectState) -> bool:
    """Blueprint §10.1: a safe measurement-only plan may proceed with UNKNOWN
    hard constraints iff it targets every one of them, is reversible, has a
    required validation step, and nothing is UNSAT."""
    if plan.kind != PlanKind.MEASUREMENT:
        return False
    if unsat_hard_constraints(plan, project):
        return False
    unresolved = set(unresolved_hard_constraints(plan, project))
    if not unresolved:
        return True
    targets = set(measurement_targets(plan, project))
    if not unresolved.issubset(targets):
        return False
    reversible = plan.intervention is None or plan.intervention.reversible
    return reversible and any(step.required for step in plan.validation_steps)


def compute_closure(plan: Plan, project: ProjectState) -> ClosureReport:
    linked_goals = [g for gid in plan.goal_ids if (g := project.goal_by_id(gid))]
    linked, _ = failure_linked(plan, project)
    hard_ok = not unresolved_hard_constraints(plan, project) or (
        measurement_exception_applies(plan, project)
        and not unsat_hard_constraints(plan, project)
    )
    return ClosureReport(
        goal_defined=bool(linked_goals),
        metric_defined=any(g.metric_name and g.target for g in linked_goals),
        hard_constraints_resolved=hard_ok,
        failure_linked=linked,
        hypothesis_testable=hypothesis_is_testable(plan),
        intervention_defined=plan.intervention is not None,
        validation_defined=any(step.required for step in plan.validation_steps),
        decision_rule_defined=has_decision_rule(plan),
        rollback_defined=has_safe_rollback(plan),
    )


def structural_blockers(plan: Plan, closure: ClosureReport) -> list[Blocker]:
    """Repair instructions for each missing structural item."""
    blockers: list[Blocker] = []

    def add(code: str, message: str) -> None:
        blockers.append(Blocker(code=code, message=message))

    if not closure.goal_defined:
        add(
            "MISSING_GOAL",
            "Link at least one registered goal: set plan.goal_ids to ids from the "
            "project state (register goals via register_project if none exist).",
        )
    elif not closure.metric_defined:
        add(
            "MISSING_METRIC",
            "None of the linked goals has a metric and target. Re-register the goal "
            "with metric_name and target so success is measurable.",
        )
    if not closure.failure_linked:
        add(
            "ORPHAN_INTERVENTION",
            "The plan addresses no registered failure mode and no unmet goal. Either "
            "set addresses_failure_ids to a registered failure mode, or link a goal "
            "whose metric is not yet met.",
        )
    if plan.hypothesis is None:
        add(
            "MISSING_HYPOTHESIS",
            'Add a causal hypothesis: {"hypothesis": {"statement": "<why the failure '
            'happens / why this change should reach the goal>"}}.',
        )
    if not closure.intervention_defined:
        add(
            "MISSING_INTERVENTION",
            'Add a scoped intervention: {"intervention": {"description": "...", '
            '"allowed_files": ["path/one.py", ...], "reversible": true}}.',
        )
    if not closure.validation_defined:
        add(
            "MISSING_VALIDATION",
            "Add at least one required validation step stating how the outcome will "
            "be checked (test, benchmark, simulation, or manual check).",
        )
    elif not closure.hypothesis_testable and plan.hypothesis is not None:
        add(
            "HYPOTHESIS_UNTESTABLE",
            "The hypothesis has no required validation step that could refute it. "
            "Mark at least one validation step required.",
        )
    if not closure.decision_rule_defined:
        add(
            "MISSING_DECISION_RULE",
            'Add decision_rule with both sides: "adopt_if" (conditions to keep the '
            'change) and "reject_if" (conditions under which you abandon it).',
        )
    if not closure.rollback_defined:
        add(
            "MISSING_ROLLBACK",
            "State rollback_description, or mark the intervention reversible, so the "
            "change can be undone.",
        )
    return blockers


def hard_constraint_blockers(plan: Plan, project: ProjectState) -> list[Blocker]:
    blockers: list[Blocker] = []
    statuses = hard_constraint_statuses(plan, project)
    for cid in unsat_hard_constraints(plan, project):
        constraint = project.constraint_by_id(cid)
        blockers.append(
            Blocker(
                code="UNSAT_HARD_CONSTRAINT",
                constraint_id=cid,
                message=(
                    f"Hard constraint {cid} is UNSAT ({constraint.statement}). This "
                    f"plan cannot proceed; redesign it or roll back the violating "
                    f"change."
                ),
            )
        )
    for cid, status in statuses.items():
        if status != ConstraintStatus.UNKNOWN:
            continue
        constraint = project.constraint_by_id(cid)
        blockers.append(
            Blocker(
                code="UNRESOLVED_HARD_CONSTRAINT",
                constraint_id=cid,
                message=(
                    f"Hard constraint {cid} is UNKNOWN ({constraint.statement}). "
                    f"Either create a measurement plan whose constraint_audit entry "
                    f"for {cid} explains how it measures this, or record_evidence "
                    f"and update_constraint_status({cid}, sat)."
                ),
            )
        )
    return blockers


def derive_status(
    plan: Plan, project: ProjectState, closure: ClosureReport
) -> tuple[PlanStatus, bool]:
    """Returns (status, executable). Terminal statuses are never changed.

    `executable` means "meets every gate condition; becomes EXECUTABLE upon
    human approval" (or is already approved/executable).
    """
    if plan.status in TERMINAL_PLAN_STATUSES:
        return plan.status, False

    if not closure.structurally_complete():
        return PlanStatus.UNDER_SPECIFIED, False

    if not closure.hard_constraints_resolved:
        return PlanStatus.BLOCKED, False

    # Structurally complete and constraint-acceptable for this plan kind.
    if plan.status in (PlanStatus.APPROVED, PlanStatus.EXECUTABLE, PlanStatus.EXECUTING):
        promoted = (
            PlanStatus.EXECUTABLE if plan.status == PlanStatus.APPROVED else plan.status
        )
        return promoted, True
    return PlanStatus.READY_FOR_REVIEW, True
