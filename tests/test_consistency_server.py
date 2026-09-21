"""End-to-end tool and workflow tests for the consistency-belief MCP server."""

from __future__ import annotations

import os
from pathlib import Path
import pytest

from conftest import git
from consistency_belief.server import (
    audit_change,
    decide,
    note,
    propose_branch,
    status,
    verify_step,
)

SAMPLE_CONSISTENCY_YAML = """
axioms:
  - id: AXM-energy-budget
    domain: resource
    statement: Total system battery power is bounded at 100W.
    rationale: Battery physical discharge constraint.

definitions:
  - id: DEF-subsystem-power
    term: Subsystem Power
    meaning: Electrical wattage consumed by compute and actuators.

lemmas:
  - id: LMA-compute-cap
    statement: Compute power cannot exceed 40W.
    premises: [AXM-energy-budget, DEF-subsystem-power]
    derivation_rule: Worst-case motor load is 60W, leaving 40W for compute.
    sufficiency: {n_min: 2, min_consensus: 0.8}

branches:
  - id: BRN-gpu-throttling
    subject: CMP-gpu-manager
    claim_type: contract
    statement: Cap GPU clock to guarantee power < 35W.
    premises: [LMA-compute-cap]
    derivation_rule: 35W margin sits safely below the 40W ceiling.
    sufficiency: {n_min: 2, min_consensus: 0.8}

policies:
  - id: POL-energy-gate
    criteria:
      - {target: BRN-gpu-throttling, require: proven}
"""


@pytest.fixture
def committed_repo(empty_repo: Path) -> Path:
    (empty_repo / "consistency.yaml").write_text(SAMPLE_CONSISTENCY_YAML, encoding="utf-8")
    git(empty_repo, "add", "consistency.yaml")
    git(empty_repo, "commit", "-q", "-m", "add consistency declarations")
    os.environ["CONSISTENCY_PROJECT_ROOT"] = str(empty_repo)
    return empty_repo


def test_status_views(committed_repo: Path):
    # tree view
    tree_out = status("tree")
    assert "AXM-energy-budget" in tree_out
    assert "BRN-gpu-throttling" in tree_out
    assert "[OBLIGATION 0/2]" in tree_out

    # axioms view
    axioms_out = status("axioms")
    assert "AXM-energy-budget [resource]" in axioms_out
    assert "downstream dependents (2): BRN-gpu-throttling, LMA-compute-cap" in axioms_out

    # obligations view
    obl_out = status("obligations")
    assert "BRN-gpu-throttling" in obl_out
    assert "need 2 more" in obl_out

    # contradictions view (clean initially)
    contra_out = status("contradictions")
    assert "Zero contradictions" in contra_out


def test_audit_change_blast_radius(committed_repo: Path):
    audit_out = audit_change("AXM-energy-budget", proposed_statement="Total system battery power is bounded at 80W.")
    assert "Downstream blast radius (2 nodes will become STALE):" in audit_out
    assert "LMA-compute-cap" in audit_out
    assert "BRN-gpu-throttling" in audit_out


def test_propose_branch_rejects_cycle_and_unknown_premise(committed_repo: Path):
    # Unknown premise
    bad_premise_out = propose_branch(
        id="BRN-bad",
        subject="CMP-bad",
        premises=["AXM-nonexistent"],
        claim="Something",
        rationale="None",
    )
    assert "rejected proposal 'BRN-bad':" in bad_premise_out
    assert "unknown premise 'AXM-nonexistent'" in bad_premise_out

    # Cycle attempt
    cycle_out = propose_branch(
        id="AXM-energy-budget",
        subject="CMP-cycle",
        premises=["BRN-gpu-throttling"],
        claim="Loop",
        rationale="Loop",
    )
    assert "rejected proposal 'AXM-energy-budget':" in cycle_out
    assert "cycle detected" in cycle_out


def test_verification_and_decide_flow(committed_repo: Path):
    # Initially decide fails with MORE_TESTING
    decide_init = decide("BRN-gpu-throttling", policy_id="POL-energy-gate")
    assert "MORE_TESTING" in decide_init
    assert "open proof obligation" in decide_init

    # Run verification trials on LMA-compute-cap
    v1 = verify_step("LMA-compute-cap", strategy="counterexample", outcome="sound", rationale="Math verified")
    assert "Trial TRL-0001 recorded" in v1
    v2 = verify_step("LMA-compute-cap", strategy="counterexample", outcome="sound", rationale="Math verified 2")
    assert "Trial TRL-0002 recorded" in v2

    # Run verification trials on BRN-gpu-throttling
    verify_step("BRN-gpu-throttling", strategy="counterexample", outcome="sound", rationale="HW specs verified 1")
    verify_step("BRN-gpu-throttling", strategy="counterexample", outcome="sound", rationale="HW specs verified 2")

    tree_now = status("tree")
    assert "[PROVEN 2/2]" in tree_now

    # Decide requires human approver for ADOPT
    decide_no_approver = decide("BRN-gpu-throttling", policy_id="POL-energy-gate")
    assert "ADOPT — NOT RECORDED: this outcome requires a human approver" in decide_no_approver

    # With approver, records DEC
    decide_approved = decide("BRN-gpu-throttling", policy_id="POL-energy-gate", approver="Alice")
    assert "ADOPT recorded as DEC-" in decide_approved
    assert "under policy POL-energy-gate" in decide_approved


def test_counterexample_refutes_and_blocks_decide(committed_repo: Path):
    # Record a counterexample
    verify_step(
        "BRN-gpu-throttling",
        strategy="counterexample",
        outcome="falsified",
        rationale="Thermal surge transient",
        counterexample="Dynamic frequency boost spikes to 48W during first 50ms",
    )

    status_tree = status("tree")
    assert "[REFUTED]" in status_tree

    status_contra = status("contradictions")
    assert "Refuted Claims / Counterexamples (1):" in status_contra
    assert "Dynamic frequency boost" in status_contra

    # Decide now returns REJECT
    decide_rejected = decide("BRN-gpu-throttling", policy_id="POL-energy-gate")
    assert "REJECT" in decide_rejected
