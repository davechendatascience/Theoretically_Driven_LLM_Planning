from __future__ import annotations

from datetime import UTC, datetime

import pytest

from plan_auto.models import (
    CausalHypothesis,
    Constraint,
    ConstraintKind,
    ConstraintStatus,
    DecisionRule,
    EvidenceRecord,
    EvidencePolarity,
    FailureMode,
    Goal,
    Intervention,
    Plan,
    PlanKind,
    PlanStatus,
    ProjectState,
    Severity,
    ValidationStep,
    ValidatorKind,
)


def ts() -> datetime:
    return datetime.now(UTC)


def make_project(
    compute_status: ConstraintStatus = ConstraintStatus.SAT,
    safety_status: ConstraintStatus = ConstraintStatus.SAT,
    safety_severity: Severity = Severity.CRITICAL,
    goal_met: bool = False,
    with_metric: bool = True,
) -> ProjectState:
    return ProjectState(
        project_id="lehome",
        name="LeHome",
        goals=[
            Goal(
                id="G-0001",
                statement="Robust placement under perturbation",
                metric_name="placement_success_rate" if with_metric else "",
                target=">= 0.8 on frozen eval" if with_metric else "",
                met=goal_met,
            )
        ],
        constraints=[
            Constraint(
                id="C-compute",
                statement="Peak VRAM below 20 GB per GPU",
                kind=ConstraintKind.HARD,
                status=compute_status,
                evidence_ids=["EV-0001"] if compute_status == ConstraintStatus.SAT else [],
            ),
            Constraint(
                id="C-safety",
                statement="No physical robot actuation",
                kind=ConstraintKind.HARD,
                severity=safety_severity,
                status=safety_status,
                evidence_ids=["EV-0002"] if safety_status == ConstraintStatus.SAT else [],
            ),
        ],
        failure_modes=[
            FailureMode(
                id="F-placement",
                symptom="Placement fails under initial-state perturbation",
                severity=Severity.HIGH,
            )
        ],
    )


def make_plan(
    kind: PlanKind = PlanKind.IMPLEMENTATION,
    status: PlanStatus = PlanStatus.DRAFT,
    goal_ids: list[str] | None = None,
    addresses_failure_ids: list[str] | None = None,
    with_hypothesis: bool = True,
    with_intervention: bool = True,
    with_validation: bool = True,
    with_decision_rule: bool = True,
    reversible: bool = True,
    constraint_audit: list | None = None,
    plan_id: str = "P-0001",
) -> Plan:
    stamp = ts()
    return Plan(
        id=plan_id,
        project_id="lehome",
        title="Add pick-conditioned placement head",
        status=status,
        kind=kind,
        goal_ids=goal_ids if goal_ids is not None else ["G-0001"],
        addresses_failure_ids=(
            addresses_failure_ids if addresses_failure_ids is not None else ["F-placement"]
        ),
        hypothesis=(
            CausalHypothesis(
                id="H-0001",
                statement="Placement lacks dependence on the selected pick point",
                linked_failure_ids=["F-placement"],
            )
            if with_hypothesis
            else None
        ),
        intervention=(
            Intervention(
                id="I-0001",
                description="Condition the placement head on pick coordinates",
                kind=kind,
                allowed_files=["src/policy/placement_head.py", "tests/test_head.py"],
                reversible=reversible,
            )
            if with_intervention
            else None
        ),
        constraint_audit=constraint_audit or [],
        validation_steps=(
            [
                ValidationStep(
                    id="V-0001",
                    description="Run frozen eval",
                    kind=ValidatorKind.COMMAND,
                    command="frozen_eval",
                    expected_result="metrics artifact",
                    required=True,
                )
            ]
            if with_validation
            else []
        ),
        decision_rule=(
            DecisionRule(
                adopt_if=["success rate improves >= 5pp"],
                reject_if=["no improvement under matched initial states"],
            )
            if with_decision_rule
            else None
        ),
        rollback_description="Disable via config, keep baseline checkpoint",
        created_at=stamp,
        updated_at=stamp,
    )


def make_evidence(
    evidence_id: str = "EV-0100",
    polarity: EvidencePolarity = EvidencePolarity.SUPPORTS,
    linked_plan_id: str | None = None,
    created_at: datetime | None = None,
) -> EvidenceRecord:
    return EvidenceRecord(
        id=evidence_id,
        project_id="lehome",
        source_type="test",
        summary="observation",
        polarity=polarity,
        linked_plan_id=linked_plan_id,
        created_at=created_at or ts(),
    )


@pytest.fixture
def project() -> ProjectState:
    return make_project()
