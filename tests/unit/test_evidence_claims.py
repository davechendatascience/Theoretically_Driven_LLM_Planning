"""Unit tests for EvidenceClaim, SubtaskEvidenceBundle, and normalization (v0.4.0)."""

from pathlib import Path
import pytest

from damped_plan_mcp.models.evidence import (
    EvidenceClaim,
    EvidenceRecord,
    SubtaskEvidenceBundle,
)
from damped_plan_mcp.models.project import ProjectState
from damped_plan_mcp.services import normalize
from damped_plan_mcp.workspace import Workspace


def test_evidence_claim_validation():
    claim = EvidenceClaim(
        target_subtask_id="sub-101",
        assertion_statement="Function signatures match",
        observed_payload={"sig_ok": True},
        source_provenance="tool:ast_parser",
        credibility_score=0.95,
        coverage_ratio=0.8,
        step_index=1,
    )
    assert claim.claim_id.startswith("CLM-")
    assert claim.credibility_score == 0.95
    assert claim.coverage_ratio == 0.8
    assert claim.is_terminal is False

    # Out-of-bounds score should raise validation error
    with pytest.raises(Exception):
        EvidenceClaim(
            target_subtask_id="sub-101",
            assertion_statement="Invalid",
            source_provenance="manual",
            credibility_score=1.5,
        )


def test_subtask_evidence_bundle_serialization():
    bundle = SubtaskEvidenceBundle(
        subtask_id="sub-101",
        claims=[
            EvidenceClaim(
                target_subtask_id="sub-101",
                assertion_statement="Resolved",
                source_provenance="tool:unit_test",
                credibility_score=0.95,
            )
        ],
        aggregate_credibility=0.95,
        total_coverage=1.0,
        damping_status="converged",
        residual_variance=0.012,
    )
    dumped = bundle.model_dump(mode="json")
    assert dumped["damping_status"] == "converged"
    assert len(dumped["claims"]) == 1
    assert dumped["residual_variance"] == 0.012

    restored = SubtaskEvidenceBundle.model_validate(dumped)
    assert restored.subtask_id == "sub-101"
    assert restored.aggregate_credibility == 0.95


def test_normalize_evidence_with_claims_and_bundle():
    project = ProjectState(project_id="test-proj", name="Test")
    payload = {
        "summary": "Diagnostic probe completed",
        "source_type": "test",
        "claims": [
            {
                "target_subtask_id": "sub-test",
                "assertion_statement": "Check passed",
                "source_provenance": "tool:unit_test",
                "credibility_score": 0.95,
                "coverage_ratio": 0.5,
                "observed_payload": {"passed": True},
            }
        ],
        "subtask_bundle": {
            "subtask_id": "sub-test",
            "aggregate_credibility": 0.95,
            "total_coverage": 0.5,
            "damping_status": "converged",
            "residual_variance": 0.0,
        },
    }

    record = normalize.normalize_evidence(payload, project, set())
    assert len(record.claims) == 1
    assert record.claims[0].assertion_statement == "Check passed"
    assert record.claims[0].credibility_score == 0.95
    assert record.subtask_bundle is not None
    assert record.subtask_bundle.damping_status == "converged"


def test_workspace_record_evidence_bundle(tmp_path: Path):
    ws = Workspace(tmp_path)
    ws.register_project({"name": "Test Micro Damping"})

    claims_data = [
        {
            "target_subtask_id": "sub-verify",
            "assertion_statement": "Verified imports",
            "source_provenance": "tool:ast_parser",
            "credibility_score": 1.0,
            "coverage_ratio": 0.5,
            "observed_payload": {"imports_ok": True},
            "step_index": 1,
        },
        {
            "target_subtask_id": "sub-verify",
            "assertion_statement": "Verified types",
            "source_provenance": "tool:type_checker",
            "credibility_score": 0.95,
            "coverage_ratio": 1.0,
            "observed_payload": {"types_ok": True},
            "step_index": 2,
            "is_terminal": True,
        },
    ]

    res = ws.record_evidence_bundle(
        subtask_id="sub-verify",
        claims=claims_data,
        required_attributes=["imports_ok", "types_ok"],
        max_steps=5,
    )

    assert "evidence" in res
    assert "subtask_bundle" in res
    assert res["subtask_bundle"]["damping_status"] == "converged"
    assert res["subtask_bundle"]["total_coverage"] == 1.0
    assert len(res["evidence"]["claims"]) == 2
