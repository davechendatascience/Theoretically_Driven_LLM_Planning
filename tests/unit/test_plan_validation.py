"""Blueprint Phase 1 required test cases (§20) for the closure kernel."""

from __future__ import annotations

from conftest import make_plan, make_project

from damped_plan_mcp.models import (
    ConstraintStatus,
    NextAction,
    PlanConstraintAudit,
    PlanKind,
    PlanStatus,
)
from damped_plan_mcp.services import plan_validation
from damped_plan_mcp.services.evaluation import evaluate_plan


def test_valid_implementation_plan_is_executable():
    project = make_project()
    plan = make_plan()
    result = evaluate_plan(plan, project, [plan], [])
    assert result.plan_status == PlanStatus.READY_FOR_REVIEW
    assert result.executable is True
    assert result.closure.complete()
    assert result.blockers == []


def test_approved_valid_plan_promotes_to_executable():
    project = make_project()
    plan = make_plan(status=PlanStatus.APPROVED)
    result = evaluate_plan(plan, project, [plan], [])
    assert result.plan_status == PlanStatus.EXECUTABLE
    assert result.executable is True
    assert result.recommended_next_action == NextAction.IMPLEMENT


def test_unknown_hard_constraint_blocks_implementation():
    project = make_project(compute_status=ConstraintStatus.UNKNOWN)
    plan = make_plan()
    result = evaluate_plan(plan, project, [plan], [])
    assert result.plan_status == PlanStatus.BLOCKED
    assert result.executable is False
    codes = {b.code for b in result.blockers}
    assert "UNRESOLVED_HARD_CONSTRAINT" in codes
    blocked_ids = {b.constraint_id for b in result.blockers if b.constraint_id}
    assert "C-compute" in blocked_ids
    assert result.recommended_next_action == NextAction.ESCALATE


def test_safe_measurement_plan_permitted_with_unknown_target():
    project = make_project(compute_status=ConstraintStatus.UNKNOWN)
    plan = make_plan(
        kind=PlanKind.MEASUREMENT,
        constraint_audit=[
            PlanConstraintAudit(
                constraint_id="C-compute",
                status=ConstraintStatus.UNKNOWN,
                evidence="This plan exists to measure peak VRAM.",
            )
        ],
    )
    result = evaluate_plan(plan, project, [plan], [])
    assert result.plan_status == PlanStatus.READY_FOR_REVIEW
    assert result.recommended_next_action == NextAction.MEASURE
    assert result.executable is True


def test_measurement_plan_without_target_claim_is_not_exempt():
    # UNKNOWN constraint but no audit entry claiming to measure it.
    project = make_project(compute_status=ConstraintStatus.UNKNOWN)
    plan = make_plan(kind=PlanKind.MEASUREMENT)
    result = evaluate_plan(plan, project, [plan], [])
    assert result.plan_status == PlanStatus.BLOCKED
    assert result.recommended_next_action == NextAction.ESCALATE


def test_measurement_with_unrelated_unknown_prerequisite_blocked():
    project = make_project(
        compute_status=ConstraintStatus.UNKNOWN,
        safety_status=ConstraintStatus.UNKNOWN,
    )
    plan = make_plan(
        kind=PlanKind.MEASUREMENT,
        constraint_audit=[
            PlanConstraintAudit(
                constraint_id="C-compute",
                status=ConstraintStatus.UNKNOWN,
                evidence="This plan measures peak VRAM.",
            )
        ],
    )
    result = evaluate_plan(plan, project, [plan], [])
    assert result.plan_status == PlanStatus.BLOCKED


def test_missing_metric_is_under_specified():
    project = make_project(with_metric=False)
    plan = make_plan()
    result = evaluate_plan(plan, project, [plan], [])
    assert result.plan_status == PlanStatus.UNDER_SPECIFIED
    assert any(b.code == "MISSING_METRIC" for b in result.blockers)
    assert result.recommended_next_action == NextAction.REPAIR


def test_orphan_intervention_is_under_specified():
    # No failure link AND the only goal is already met -> orphan.
    project = make_project(goal_met=True)
    plan = make_plan(addresses_failure_ids=[])
    result = evaluate_plan(plan, project, [plan], [])
    assert result.plan_status == PlanStatus.UNDER_SPECIFIED
    assert any(b.code == "ORPHAN_INTERVENTION" for b in result.blockers)


def test_goal_gap_alone_satisfies_failure_linkage():
    # Relaxed rule: unmet goal justifies the plan; soft warning is surfaced.
    project = make_project()
    plan = make_plan(addresses_failure_ids=[])
    result = evaluate_plan(plan, project, [plan], [])
    assert result.plan_status == PlanStatus.READY_FOR_REVIEW
    assert any("failure mode" in w for w in result.warnings)


def test_hypothesis_without_validation_is_under_specified():
    project = make_project()
    plan = make_plan(with_validation=False)
    result = evaluate_plan(plan, project, [plan], [])
    assert result.plan_status == PlanStatus.UNDER_SPECIFIED
    assert any(b.code == "MISSING_VALIDATION" for b in result.blockers)


def test_missing_decision_rule_is_under_specified():
    project = make_project()
    plan = make_plan(with_decision_rule=False)
    result = evaluate_plan(plan, project, [plan], [])
    assert result.plan_status == PlanStatus.UNDER_SPECIFIED
    assert any(b.code == "MISSING_DECISION_RULE" for b in result.blockers)


def test_irreversible_plan_without_rollback_is_under_specified():
    project = make_project()
    plan = make_plan(reversible=False)
    plan.rollback_description = None
    result = evaluate_plan(plan, project, [plan], [])
    assert result.plan_status == PlanStatus.UNDER_SPECIFIED
    assert any(b.code == "MISSING_ROLLBACK" for b in result.blockers)


def test_critical_unsat_recommends_rollback():
    project = make_project(safety_status=ConstraintStatus.UNSAT)
    plan = make_plan()
    result = evaluate_plan(plan, project, [plan], [])
    assert result.plan_status == PlanStatus.BLOCKED
    assert result.recommended_next_action == NextAction.ROLLBACK


def test_audit_cannot_self_certify_sat():
    # Plan claims SAT in its audit; project records UNKNOWN -> still unresolved.
    project = make_project(compute_status=ConstraintStatus.UNKNOWN)
    plan = make_plan(
        constraint_audit=[
            PlanConstraintAudit(
                constraint_id="C-compute",
                status=ConstraintStatus.SAT,
                evidence="trust me",
            )
        ]
    )
    assert plan_validation.unresolved_hard_constraints(plan, project) == ["C-compute"]


def test_audit_not_applicable_scopes_constraint_out():
    project = make_project(compute_status=ConstraintStatus.UNKNOWN)
    plan = make_plan(
        constraint_audit=[
            PlanConstraintAudit(
                constraint_id="C-compute",
                status=ConstraintStatus.NOT_APPLICABLE,
                evidence="Doc-only change; no training run involved.",
            )
        ]
    )
    assert plan_validation.unresolved_hard_constraints(plan, project) == []


def test_terminal_status_never_changes():
    project = make_project(compute_status=ConstraintStatus.UNKNOWN)
    plan = make_plan(status=PlanStatus.VALIDATED)
    result = evaluate_plan(plan, project, [plan], [])
    assert result.plan_status == PlanStatus.VALIDATED
    assert result.recommended_next_action == NextAction.STOP
