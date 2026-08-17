"""Top-level plan evaluation: closure + blockers + residuals + decision."""

from __future__ import annotations

from ..models import (
    ConstraintKind,
    ConstraintStatus,
    EvidenceRecord,
    Plan,
    PlanEvaluation,
    PlanStatus,
    ProjectState,
)
from . import decision_policy, plan_validation, residuals
from ..render import reports


def evaluate_plan(
    plan: Plan,
    project: ProjectState,
    all_plans: list[Plan],
    evidence: list[EvidenceRecord],
) -> PlanEvaluation:
    closure = plan_validation.compute_closure(plan, project)
    status, executable = plan_validation.derive_status(plan, project, closure)

    blockers = plan_validation.structural_blockers(plan, closure)
    if status == PlanStatus.BLOCKED or not closure.hard_constraints_resolved:
        blockers.extend(plan_validation.hard_constraint_blockers(plan, project))

    warnings: list[str] = []
    linked, via_failure = plan_validation.failure_linked(plan, project)
    if linked and not via_failure:
        warnings.append(
            "No registered failure mode is linked; the plan is justified only by an "
            "unmet goal. Consider registering the failure this addresses."
        )
    for constraint in project.constraints:
        if (
            constraint.kind == ConstraintKind.SOFT
            and constraint.status == ConstraintStatus.UNSAT
        ):
            warnings.append(
                f"Soft constraint {constraint.id} is UNSAT ({constraint.statement}); "
                f"not blocking, but note the trade-off."
            )
    if plan.kind.value == "measurement":
        targets = plan_validation.measurement_targets(plan, project)
        if len(targets) > 1:
            warnings.append(
                f"This measurement plan targets {len(targets)} unknowns ({targets}); "
                f"prefer one discriminative measurement per plan."
            )

    recommended, rationale = decision_policy.recommend_next_action(
        plan, project, closure, all_plans, evidence
    )
    residual_report = residuals.compute_residuals(
        plan,
        project,
        evidence,
        blocker_codes=[b.code for b in blockers],
        recommended=recommended,
        rationale=rationale,
    )

    evaluation = PlanEvaluation(
        plan_id=plan.id,
        plan_status=status,
        executable=executable,
        closure=closure,
        blockers=blockers,
        warnings=warnings,
        residuals=residual_report,
        recommended_next_action=recommended,
    )
    evaluation.human_summary = reports.render_evaluation_summary(plan, evaluation)
    return evaluation
