"""Predictive layer: contract closure, grandfathering, posterior checks."""

from __future__ import annotations

from conftest import make_evidence, make_plan, make_project

from plan_auto.models import (
    MetricObservation,
    NextAction,
    PlanKind,
    PlanStatus,
    PredictiveContract,
    Prediction,
    DisconfirmingPattern,
)
from plan_auto.services import predictive
from plan_auto.services.evaluation import evaluate_plan
from plan_auto.services.normalize import normalize_plan


CONTRACT = PredictiveContract(
    context_fixed=["frozen eval protocol", "pinned scenes"],
    context_varied=["policy architecture"],
    predictions=[
        Prediction(id="PR-1", metric_id="robustness", direction="increase",
                   expected_range=(0.47, 0.60)),
        Prediction(id="PR-2", metric_id="feasibility", direction="no_change",
                   expected_range=(0.90, 1.00)),
    ],
    disconfirming_patterns=[
        DisconfirmingPattern(
            id="D-1",
            description="Gain disappears on held-out split",
            suggested_model_expansion="test visual ambiguity with oracle state",
        )
    ],
)


def contract_plan(**kwargs):
    plan = make_plan(**kwargs)
    plan.predictive_contract = CONTRACT
    plan.schema_version = 2
    return plan


# -- closure and grandfathering ---------------------------------------------


def test_v2_implementation_without_contract_is_under_specified():
    project = make_project()
    plan = make_plan()
    plan.schema_version = 2
    result = evaluate_plan(plan, project, [plan], [])
    assert result.plan_status == PlanStatus.UNDER_SPECIFIED
    assert any(b.code == "MISSING_PREDICTIVE_CONTRACT" for b in result.blockers)


def test_v1_legacy_plan_unaffected_but_warned():
    project = make_project()
    plan = make_plan()  # schema_version defaults to 1
    result = evaluate_plan(plan, project, [plan], [])
    assert result.plan_status == PlanStatus.READY_FOR_REVIEW
    assert result.executable is True
    assert any("Legacy plan" in w for w in result.warnings)


def test_v2_measurement_plan_needs_no_contract():
    project = make_project()
    plan = make_plan(kind=PlanKind.MEASUREMENT)
    plan.schema_version = 2
    result = evaluate_plan(plan, project, [plan], [])
    assert result.plan_status == PlanStatus.READY_FOR_REVIEW


def test_incomplete_contract_lists_gaps():
    project = make_project()
    plan = make_plan()
    plan.schema_version = 2
    plan.predictive_contract = PredictiveContract(
        predictions=[Prediction(metric_id="m", direction="increase")]
    )
    result = evaluate_plan(plan, project, [plan], [])
    codes = [b.code for b in result.blockers]
    assert "INCOMPLETE_PREDICTIVE_CONTRACT" in codes
    messages = " ".join(b.message for b in result.blockers)
    assert "context_fixed" in messages
    assert "disconfirming_patterns" in messages


def test_complete_contract_closes():
    project = make_project()
    plan = contract_plan()
    result = evaluate_plan(plan, project, [plan], [])
    assert result.plan_status == PlanStatus.READY_FOR_REVIEW
    assert result.closure.predictive_contract_ok is True


def test_normalize_stamps_new_plans_v2_and_preserves_v1_on_upsert():
    project = make_project()
    fresh, _ = normalize_plan({"title": "x", "kind": "measurement"}, project, set())
    assert fresh.schema_version == 2
    legacy = make_plan()  # v1
    edited, _ = normalize_plan(
        {"id": legacy.id, "title": "x", "kind": "implementation"},
        project, {legacy.id}, existing_plan=legacy,
    )
    assert edited.schema_version == 1


def test_normalize_parses_contract():
    project = make_project()
    plan, _ = normalize_plan(
        {
            "title": "x", "kind": "implementation",
            "predictive_contract": {
                "context_fixed": ["frozen eval"],
                "predictions": [
                    {"metric": "robustness", "direction": "Increase",
                     "expected_range": [0.47, 0.6]}
                ],
                "disconfirming_patterns": [
                    "gain disappears on held-out split"
                ],
                "next_expansions": ["oracle-state test"],
            },
        },
        project, set(),
    )
    contract = plan.predictive_contract
    assert contract is not None
    assert contract.predictions[0].metric_id == "robustness"
    assert contract.predictions[0].expected_range == (0.47, 0.6)
    assert contract.disconfirming_patterns[0].id == "D-001"
    assert predictive.contract_structural_gaps(contract) == []


# -- posterior checks --------------------------------------------------------


def obs_evidence(evidence_id, plan_id, **metrics):
    record = make_evidence(evidence_id, linked_plan_id=plan_id)
    record.observations = [
        MetricObservation(metric_id=k, value=v) for k, v in metrics.items()
    ]
    return record


def test_posterior_not_ready_without_evidence():
    plan = contract_plan()
    check = predictive.posterior_check(plan, [])
    assert check.status == "not_ready"


def test_posterior_consistent_in_range():
    plan = contract_plan()
    ev = obs_evidence("EV-1", plan.id, robustness=0.51, feasibility=0.95)
    check = predictive.posterior_check(plan, [ev])
    assert check.status == "consistent"
    assert set(check.matched_prediction_ids) == {"PR-1", "PR-2"}


def test_posterior_mismatch_out_of_range_recommends_expansion():
    plan = contract_plan()
    ev = obs_evidence("EV-1", plan.id, robustness=0.43, feasibility=0.95)
    check = predictive.posterior_check(plan, [ev])
    assert check.status == "mismatch"
    assert check.violated_prediction_ids == ["PR-1"]
    assert check.recommended_expansion is None or isinstance(
        check.recommended_expansion, str
    )


def test_posterior_declared_pattern_is_mismatch():
    plan = contract_plan()
    ev = make_evidence("EV-1", linked_plan_id=plan.id)
    ev.observed_pattern_ids = ["D-1"]
    check = predictive.posterior_check(plan, [ev])
    assert check.status == "mismatch"
    assert check.observed_pattern_ids == ["D-1"]
    assert check.recommended_expansion == "test visual ambiguity with oracle state"


def test_posterior_inconclusive_without_structured_observations():
    plan = contract_plan()
    ev = make_evidence("EV-1", linked_plan_id=plan.id)  # narration only
    check = predictive.posterior_check(plan, [ev])
    assert check.status == "inconclusive"


def test_mismatch_drives_escalate_and_dominant_residual():
    project = make_project()
    plan = contract_plan(status=PlanStatus.EXECUTING)
    ev = obs_evidence("EV-1", plan.id, robustness=0.43)
    result = evaluate_plan(plan, project, [plan], [ev])
    assert result.predictive_status == "mismatch"
    assert result.dominant_residual == "causal_model"
    assert result.recommended_next_action == NextAction.ESCALATE
    assert "Posterior predictive check MISMATCH" in " ".join(
        result.residuals.rationale
    )
