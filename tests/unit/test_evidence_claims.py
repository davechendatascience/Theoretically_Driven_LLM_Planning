"""Coverage for the deprecated EvidenceClaim passthrough.

The micro-damping engine that produced claims is gone; the model and its
normalize read path are retained because three stored records in the
robot-navigation-planning store carry `claims` (EV-0014). These tests exist to
keep that compatibility path from rotting, not to exercise any live scoring.
"""

import pytest

from damped_plan_mcp.models.evidence import EvidenceClaim
from damped_plan_mcp.models.project import ProjectState
from damped_plan_mcp.services import normalize


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

    with pytest.raises(Exception):
        EvidenceClaim(
            target_subtask_id="sub-101",
            assertion_statement="Invalid",
            source_provenance="manual",
            credibility_score=1.5,
        )


def test_normalize_evidence_preserves_stored_claims():
    """The read path that keeps pre-prune stored records loadable."""
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
    }

    record = normalize.normalize_evidence(payload, project, set())
    assert len(record.claims) == 1
    assert record.claims[0].assertion_statement == "Check passed"
    assert record.claims[0].credibility_score == 0.95
    assert not hasattr(record, "subtask_bundle")
