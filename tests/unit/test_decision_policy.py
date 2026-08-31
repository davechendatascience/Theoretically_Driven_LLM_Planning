from __future__ import annotations

from datetime import UTC, datetime, timedelta

from conftest import make_evidence, make_plan, make_project

from plan_auto.models import EvidencePolarity, NextAction, PlanStatus
from plan_auto.services.evaluation import evaluate_plan


def test_refuting_evidence_recommends_repair():
    project = make_project()
    plan = make_plan()
    refutation = make_evidence(
        "EV-0200", polarity=EvidencePolarity.REFUTES, linked_plan_id=plan.id
    )
    result = evaluate_plan(plan, project, [plan], [refutation])
    assert result.recommended_next_action == NextAction.REPAIR
    assert result.residuals.validation_gap >= 1


def test_repeated_noninformative_failure_escalates():
    project = make_project()
    failed_at = datetime.now(UTC) - timedelta(hours=2)
    prior_one = make_plan(plan_id="P-0001", status=PlanStatus.REJECTED)
    prior_two = make_plan(plan_id="P-0002", status=PlanStatus.ROLLED_BACK)
    prior_one.updated_at = failed_at
    prior_two.updated_at = failed_at
    current = make_plan(plan_id="P-0003")
    # No evidence recorded since the failures -> local patching must stop.
    result = evaluate_plan(current, project, [prior_one, prior_two, current], [])
    assert result.recommended_next_action == NextAction.ESCALATE


def test_new_evidence_resets_escalation():
    project = make_project()
    failed_at = datetime.now(UTC) - timedelta(hours=2)
    prior_one = make_plan(plan_id="P-0001", status=PlanStatus.REJECTED)
    prior_two = make_plan(plan_id="P-0002", status=PlanStatus.ROLLED_BACK)
    prior_one.updated_at = failed_at
    prior_two.updated_at = failed_at
    current = make_plan(plan_id="P-0003")
    fresh = make_evidence("EV-0300", created_at=datetime.now(UTC))
    result = evaluate_plan(current, project, [prior_one, prior_two, current], [fresh])
    assert result.recommended_next_action != NextAction.ESCALATE


def test_ready_for_review_awaits_human():
    project = make_project()
    plan = make_plan()
    result = evaluate_plan(plan, project, [plan], [])
    assert result.plan_status == PlanStatus.READY_FOR_REVIEW
    assert result.recommended_next_action == NextAction.STOP
    assert any("approve" in r.lower() for r in result.residuals.rationale)
