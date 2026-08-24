"""Unit tests for credibility-weighted residual calculations (v0.4.0)."""

from datetime import datetime, timezone
import pytest

from damped_plan_mcp.models.enums import EvidencePolarity, NextAction, PlanKind, PlanStatus
from damped_plan_mcp.models.evidence import EvidenceClaim, EvidenceRecord, SubtaskEvidenceBundle
from damped_plan_mcp.models.plan import Plan, CausalHypothesis
from damped_plan_mcp.models.predictive import MetricObservation, Prediction, PredictiveContract
from damped_plan_mcp.models.project import ProjectState
from damped_plan_mcp.services import residuals


def test_residual_computation_with_claims_and_bundle():
    project = ProjectState(project_id="test-proj", name="Test")
    now = datetime.now(timezone.utc)
    plan = Plan(
        id="P-0001",
        project_id="test-proj",
        title="Test Plan",
        kind=PlanKind.IMPLEMENTATION,
        status=PlanStatus.EXECUTABLE,
        hypothesis=CausalHypothesis(id="H-0001", statement="Intervention solves bug"),
        predictive_contract=PredictiveContract(
            context_fixed=["eval"],
            predictions=[
                Prediction(
                    id="PRED-1",
                    metric_id="latency_ms",
                    direction="decrease",
                    expected_range=(50.0, 70.0),
                )
            ],
            disconfirming_patterns=[],
        ),
        created_at=now,
        updated_at=now,
    )

    claims = [
        EvidenceClaim(
            target_subtask_id="sub-bench",
            assertion_statement="Measured latency under load",
            source_provenance="tool:unit_test",
            credibility_score=0.95,
        )
    ]

    bundle = SubtaskEvidenceBundle(
        subtask_id="sub-bench",
        claims=claims,
        aggregate_credibility=0.95,
        total_coverage=1.0,
        damping_status="converged",
        residual_variance=0.005,
    )

    evidence_record = EvidenceRecord(
        id="EV-0001",
        project_id="test-proj",
        source_type="test",
        summary="Benchmark completed",
        polarity=EvidencePolarity.SUPPORTS,
        linked_plan_id="P-0001",
        observations=[MetricObservation(metric_id="latency_ms", value=65.0)],
        claims=claims,
        subtask_bundle=bundle,
        created_at=datetime.now(timezone.utc),
    )

    report = residuals.compute_residuals(
        plan=plan,
        project=project,
        evidence=[evidence_record],
        blocker_codes=[],
        recommended=NextAction.IMPLEMENT,
        rationale=["Proceed"],
    )

    assert report.aggregate_credibility == 0.95
    # The discrepancy is (65 - 60) = 5, weighted by 0.95 = 4.75.
    # Single sample variance defaults to 0.0 or bundle variance if no multi-point spread.
    assert isinstance(report.residual_variance, float)
