"""IFC-evidence__designs: the evidence side hands the design side the state of each contract a design
cites, and a design's release gate requires that state alongside its proof."""

from __future__ import annotations

from pathlib import Path

import pytest
from component_belief import server as evidence
from consistency_belief import server as design

from conftest import commit
from test_sound_designs import BRANCH, DESIGN_YAML, ONE_PASS


@pytest.fixture
def proven(project: Path) -> Path:
    """A design proven by one pass of three probes, citing CTR-planner-works as its evidence."""
    (project / "consistency.yaml").write_text(DESIGN_YAML, encoding="utf-8")
    commit(project, "declare the design")
    design.verify_step(BRANCH, trials=ONE_PASS)
    return project


def test_a_proven_design_over_supported_evidence_passes_the_gate(proven):
    evidence.run_test("TST-planner")
    assert design.decide("CHG-1").startswith("ADOPT")


def test_a_proven_design_with_no_evidence_does_not(proven):
    out = design.decide("CHG-2")
    assert not out.startswith("ADOPT") and "CTR-planner-works" in out


def test_a_proven_design_over_evidence_gone_stale_does_not(proven):
    evidence.run_test("TST-planner")
    (proven / "planner.py").write_text("# v2\n", encoding="utf-8")
    commit(proven, "change the planner after it was measured")
    out = design.decide("CHG-3")
    assert not out.startswith("ADOPT") and "CTR-planner-works" in out
