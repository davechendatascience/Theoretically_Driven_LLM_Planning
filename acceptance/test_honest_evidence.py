"""GOL-honest-evidence: a number the harness reports was measured -- by a test it ran or an
artifact it hashed -- and stops counting the moment what it measured changes."""

from __future__ import annotations

from component_belief import server

from conftest import commit


def belief(subject: str | None = None) -> str:
    return server.status(view="belief", subject=subject)


def test_a_measured_run_counts(project):
    server.run_test("TST-planner")
    assert "CTR-planner-works [unbucketed] supported gate 1/1" in belief()


def test_a_statement_moves_no_belief(project):
    server.note("CMP-planner", "it works, trust me")
    assert "no belief-eligible evidence" in belief("CMP-planner")


def test_a_fabricated_import_is_refused_and_cannot_be_adopted(project):
    out = server.ingest(records=[{"contract_id": "CTR-planner-works", "test_id": "TST-made-up",
                                  "outcome": "pass", "metrics": {"passed": True}, "repro": {}}],
                        source="CI", artifact_uri="nowhere/results.json")
    assert out.startswith("rejected")
    assert "no belief-eligible evidence" in belief("CMP-planner")
    assert not server.decide("CHG-1", approver="me").startswith("ADOPT")


def test_sparse_data_is_insufficient_not_a_verdict(project):
    server.run_test("TST-planner")
    assert "CTR-planner-rate [unbucketed] insufficient n=1" in belief()


def test_evidence_stops_counting_when_the_code_it_measured_changes(project):
    server.run_test("TST-planner")
    (project / "planner.py").write_text("# v2\n", encoding="utf-8")
    commit(project, "change the planner")
    line = belief("CTR-planner-works")
    assert "stale" in line and "planner.py" in line
    assert not server.decide("CHG-2", approver="me").startswith("ADOPT")


def test_evidence_stops_counting_when_a_checkpoint_it_read_changes(project):
    server.run_test("TST-planner")
    (project / "ckpt" / "model.pt").write_bytes(b"weights-v2-retrained")
    line = belief("CTR-planner-works")
    assert "stale" in line and "ckpt/model.pt" in line
    (project / "ckpt" / "model.pt").write_bytes(b"weights-v1")
    assert "supported gate" in belief("CTR-planner-works")
