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
from . import decision_policy, plan_validation, predictive, residuals
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

    check = predictive.posterior_check(plan, evidence)
    if (
        plan.schema_version < 2
        and plan.kind.value in ("implementation", "repair")
        and plan.predictive_contract is None
    ):
        warnings.append(
            "Legacy plan (pre-predictive-layer): no predictive contract required; "
            "new implementation/repair plans must state one."
        )

    recommended, rationale = decision_policy.recommend_next_action(
        plan, project, closure, all_plans, evidence, predictive_check=check
    )
    residual_report = residuals.compute_residuals(
        plan,
        project,
        evidence,
        blocker_codes=[b.code for b in blockers],
        recommended=recommended,
        rationale=rationale,
    )

    if not closure.hard_constraints_resolved:
        dominant = "feasibility"
    elif not closure.structurally_complete():
        dominant = "specification"
    elif check.status == "mismatch":
        dominant = "causal_model"
    elif residual_report.validation_gap > 0:
        dominant = "validation"
    elif residual_report.evidence_gap > 0:
        dominant = "evidence"
    else:
        dominant = "none"

    evaluation = PlanEvaluation(
        plan_id=plan.id,
        plan_status=status,
        executable=executable,
        closure=closure,
        blockers=blockers,
        warnings=warnings,
        residuals=residual_report,
        recommended_next_action=recommended,
        predictive_status=check.status,
        predictive=check if plan.predictive_contract is not None else None,
        dominant_residual=dominant,
        model_expansion_target=check.recommended_expansion,
    )
    evaluation.human_summary = reports.render_evaluation_summary(plan, evaluation)
    return evaluation
