"""End-to-end tool and workflow tests for the consistency-belief MCP server."""

from __future__ import annotations

import os
from pathlib import Path
import pytest

from conftest import git
from consistency_belief.server import (
    amend,
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

    # A declared node is restated in consistency.yaml, not through a proposal
    declared_out = propose_branch(
        id="AXM-energy-budget",
        subject="CMP-cycle",
        premises=["BRN-gpu-throttling"],
        claim="Loop",
        rationale="Loop",
    )
    assert "rejected proposal 'AXM-energy-budget':" in declared_out
    assert "declared in consistency.yaml at git HEAD" in declared_out

    # Cycle attempt through staged proposals: restating BRN-x on its own dependent
    propose_branch(id="BRN-x", subject="CMP-x", premises=["BRN-gpu-throttling"], claim="x", rationale="x")
    propose_branch(id="BRN-y", subject="CMP-y", premises=["BRN-x"], claim="y", rationale="y")
    cycle_out = propose_branch(id="BRN-x", subject="CMP-x", premises=["BRN-y"], claim="x again", rationale="x")
    assert "rejected proposal 'BRN-x':" in cycle_out
    assert "cycle detected" in cycle_out


def test_verification_and_decide_flow(committed_repo: Path):
    # Initially decide fails with MORE_TESTING
    decide_init = decide("BRN-gpu-throttling", policy_id="POL-energy-gate")
    assert "MORE_TESTING" in decide_init
    assert "open proof obligation" in decide_init

    # Run verification trials on LMA-compute-cap: two strategies, so two independent trials
    v1 = verify_step("LMA-compute-cap", strategy="counterexample", outcome="sound", rationale="Math verified")
    assert "Trial TRL-0001 recorded" in v1
    v2 = verify_step("LMA-compute-cap", strategy="entailment", outcome="sound", rationale="Math verified 2")
    assert "Trial TRL-0002 recorded" in v2

    # Run verification trials on BRN-gpu-throttling
    verify_step("BRN-gpu-throttling", strategy="counterexample", outcome="sound", rationale="HW specs verified 1")
    verify_step("BRN-gpu-throttling", strategy="entailment", outcome="sound", rationale="HW specs verified 2")

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


# ---------- staged proposals and statement-bound trials ----------

def _commit_yaml(repo: Path, text: str, message: str) -> None:
    (repo / "consistency.yaml").write_text(text, encoding="utf-8")
    git(repo, "add", "consistency.yaml")
    git(repo, "commit", "-q", "-m", message)


def test_staged_branch_persists_and_can_be_verified(committed_repo: Path):
    out = propose_branch(id="BRN-fan-curve", subject="CMP-fan", premises=["LMA-compute-cap"],
                         claim="Fan curve keeps compute below 40W.", rationale="thermal headroom")
    assert "Branch BRN-fan-curve staged" in out

    # a later call, which rebuilds everything from git HEAD and the ledger, still knows it
    v = verify_step("BRN-fan-curve", strategy="counterexample", outcome="sound", rationale="checked")
    assert "Trial TRL-0001 recorded for BRN-fan-curve" in v
    assert "is staged" in v

    obligations = status("obligations")
    assert "BRN-fan-curve [OBLIGATION · STAGED]" in obligations
    assert "staged -- proposed, not yet declared at git HEAD" in status("tree")


def test_staged_branch_can_be_cited_and_cannot_support_adopt(committed_repo: Path):
    propose_branch(id="BRN-fan-curve", subject="CMP-fan", premises=["LMA-compute-cap"],
                   claim="Fan curve keeps compute below 40W.", rationale="thermal headroom")
    out = propose_branch(id="BRN-fan-alarm", subject="CMP-fan", premises=["BRN-fan-curve"],
                         claim="An alarm fires when the fan curve saturates.", rationale="follows")
    assert "Branch BRN-fan-alarm staged" in out
    assert "[GROUNDED]" in out

    for node in ("LMA-compute-cap", "BRN-fan-curve", "BRN-fan-alarm"):
        verify_step(node, outcome="sound", rationale="ok")
        verify_step(node, outcome="sound", rationale="ok again")
        verify_step(node, outcome="sound", rationale="ok thrice")
    verdict = decide("BRN-fan-alarm", policy_id="POL-energy-gate")
    assert "ADOPT" not in verdict
    assert "BRN-fan-alarm is STAGED" in verdict and "BRN-fan-curve is STAGED" in verdict


def test_trials_carry_over_when_the_same_statement_is_declared(committed_repo: Path):
    claim = "Fan curve keeps compute below 40W."
    propose_branch(id="BRN-fan-curve", subject="CMP-fan", premises=["LMA-compute-cap"], claim=claim,
                   rationale="thermal headroom")
    verify_step("BRN-fan-curve", outcome="sound", rationale="ok")
    verify_step("BRN-fan-curve", strategy="entailment", outcome="sound", rationale="ok again")

    _commit_yaml(committed_repo, SAMPLE_CONSISTENCY_YAML.replace("\npolicies:", f"""
  - id: BRN-fan-curve
    subject: CMP-fan
    claim_type: contract
    statement: {claim}
    premises: [LMA-compute-cap]
    derivation_rule: thermal headroom
    sufficiency: {{n_min: 2, min_consensus: 0.8}}

policies:"""), "declare the fan curve")
    tree = status("tree")
    assert "BRN-fan-curve [PROVEN 2/2]" in tree
    assert "staged" not in tree


def test_restating_a_declared_node_sets_its_trials_aside(committed_repo: Path):
    verify_step("BRN-gpu-throttling", outcome="sound", rationale="ok")
    verify_step("BRN-gpu-throttling", strategy="entailment", outcome="sound", rationale="ok again")
    assert "BRN-gpu-throttling [PROVEN 2/2]" in status("tree")

    _commit_yaml(committed_repo, SAMPLE_CONSISTENCY_YAML.replace(
        "Cap GPU clock to guarantee power < 35W.", "Cap GPU clock to guarantee power < 38W."), "restate")
    branches = status("branches", subject="BRN-gpu-throttling")
    assert "[OBLIGATION 0/2]" in branches
    assert "2 verified an earlier statement" in branches


def test_restating_a_premise_makes_dependents_stale(committed_repo: Path):
    verify_step("BRN-gpu-throttling", outcome="sound", rationale="ok")
    verify_step("BRN-gpu-throttling", strategy="entailment", outcome="sound", rationale="ok again")

    _commit_yaml(committed_repo, SAMPLE_CONSISTENCY_YAML.replace(
        "Compute power cannot exceed 40W.", "Compute power cannot exceed 45W."), "restate the lemma")
    branches = status("branches", subject="BRN-gpu-throttling")
    assert "[STALE]" in branches
    assert "before LMA-compute-cap was restated" in branches
    assert "BRN-gpu-throttling is STALE" in decide("BRN-gpu-throttling", policy_id="POL-energy-gate")

    verify_step("BRN-gpu-throttling", outcome="sound", rationale="re-verified")
    verify_step("BRN-gpu-throttling", strategy="entailment", outcome="sound", rationale="re-verified again")
    assert "BRN-gpu-throttling [PROVEN 2/2]" in status("tree")


def test_restating_a_staged_branch_sets_its_trials_aside(committed_repo: Path):
    propose_branch(id="BRN-fan-curve", subject="CMP-fan", premises=["LMA-compute-cap"],
                   claim="Fan curve keeps compute below 40W.", rationale="v1")
    verify_step("BRN-fan-curve", outcome="falsified", rationale="no", counterexample="fan stalls at 70C")
    assert "[REFUTED · STAGED]" in status("branches", subject="BRN-fan-curve")

    out = propose_branch(id="BRN-fan-curve", subject="CMP-fan", premises=["LMA-compute-cap"],
                         claim="Fan curve plus throttling keeps compute below 40W.", rationale="v2")
    assert "restated" in out and "no longer count" in out
    branches = status("branches", subject="BRN-fan-curve")
    assert "[OBLIGATION 0/3 · STAGED]" in branches
    assert "1 verified an earlier statement" in branches


def test_legacy_trials_without_fingerprints_still_count(committed_repo: Path):
    from consistency_belief.store import Store
    store = Store(committed_repo)
    for i, strategy in enumerate(("counterexample", "entailment")):
        store.append_trial({"target_id": "BRN-gpu-throttling", "strategy": strategy,
                            "outcome": "sound", "passed": True, "counterexample": None,
                            "reasoning": f"legacy {i}", "repro": {}, "validity": "valid"})
    assert "BRN-gpu-throttling [PROVEN 2/2]" in status("tree")


# ---------- gaps and amendments ----------

def test_a_gap_with_evidence_leaves_a_claim_unproven_not_refuted(committed_repo: Path):
    verify_step("BRN-gpu-throttling", strategy="counterexample", outcome="sound", rationale="ok")
    verify_step("BRN-gpu-throttling", strategy="entailment", outcome="gap", rationale="incomplete",
                counterexample="Missing premise: the 35W figure assumes a 25C ambient")
    branches = status("branches", subject="BRN-gpu-throttling")
    assert "[DOUBTED]" in branches
    assert "entailment gaps: Missing premise" in branches
    contradictions = status("contradictions")
    assert "Entailment Gaps -- unproven, not refuted (1):" in contradictions
    assert "Refuted Claims" not in contradictions
    verdict = decide("BRN-gpu-throttling", policy_id="POL-energy-gate")
    assert "MORE_TESTING" in verdict and "REJECT" not in verdict


def test_amend_reclassifies_without_editing(committed_repo: Path):
    out = verify_step("BRN-gpu-throttling", outcome="falsified", rationale="wrong target",
                      counterexample="this belonged to another branch")
    assert "[REFUTED]" in status("branches", subject="BRN-gpu-throttling")

    assert "reason is required" in amend("TRL-0001", validity="invalid", reason="")
    assert "unknown trial id" in amend("TRL-9999", validity="invalid", reason="typo")
    assert "validity must be one of" in amend("TRL-0001", validity="bogus", reason="x")

    amended = amend("TRL-0001", validity="invalid", reason="recorded against the wrong branch")
    assert "amended TRL-0001: validity=invalid" in amended
    assert "[OBLIGATION 0/2]" in status("branches", subject="BRN-gpu-throttling")

    from consistency_belief.store import Store
    raw = Store(committed_repo).raw_records()
    assert any(r.get("id") == "TRL-0001" and r.get("outcome") == "falsified" for r in raw)
    assert "Trial TRL-0001" in out


def test_tree_prints_each_statement_once_and_short(committed_repo: Path):
    long_claim = "Fan curve keeps compute below 40W " + "under every load profile " * 20
    propose_branch(id="BRN-fan-curve", subject="CMP-fan", premises=["LMA-compute-cap", "AXM-energy-budget"],
                   claim=long_claim, rationale="two premises, so it hangs under both")
    tree = status("tree")
    rows = [line for line in tree.splitlines() if "BRN-fan-curve" in line]
    assert len(rows) == 2 and sum("(shown above)" in r for r in rows) == 1
    assert all(len(r) < 200 for r in rows)
    assert long_claim.strip() in status("branches", subject="BRN-fan-curve")


def test_measurement_hint_points_numbers_at_component_belief():
    """A claim thick with measurements and citing no evidence id gets a note; one that cites an
    id, or that is purely logical, does not (rule 3: trials verify entailment, not measurement)."""
    from consistency_belief.server import measurement_hint

    assert "component-belief" in measurement_hint(
        "the gap was 118.7 mm, it settled in 261 steps, over 40 episodes", "claim")
    assert measurement_hint("118.7 mm and 261 steps over 40 episodes, measured in CTR-teacher-reliable",
                            "claim") == ""
    assert measurement_hint("the release is gentle exactly when DEF-gentle-placement holds", "claim") == ""


def test_verify_step_refuses_a_falsification_argued_from_source(committed_repo: Path):
    """Rule 3: a clause you cannot judge without opening a file is a gap, never a falsification.

    Thirteen refutations in the embodied_ai ledger were recorded as counterexamples citing source
    lines, and every one had to be amended. The tool refuses the shape rather than restating the
    rule in prose that gets read once.
    """
    out = verify_step(
        "LMA-compute-cap", strategy="counterexample", outcome="falsified",
        rationale="The implementation disagrees",
        counterexample="scheduler.py:482 returns the first candidate unchecked when none passes.")
    assert out.startswith("refused:")
    assert "scheduler.py:482" in out
    assert "outcome='gap'" in out
    assert "component-belief" in out
    # and nothing was recorded
    assert "TRL-" not in out
    # and no number is asserted about a ledger that holds no amended falsification
    assert "in this ledger" not in out


def test_verify_step_allows_a_gap_that_points_at_source(committed_repo: Path):
    """A gap may name a file as a pointer for the implementer; it just may not be the reason."""
    out = verify_step(
        "LMA-compute-cap", strategy="entailment", outcome="gap",
        rationale="The claim assumes the scheduler bounds its queue, which no premise states.",
        counterexample="unstated premise; see scheduler.py for where it would be enforced")
    assert not out.startswith("refused:")
    assert "Trial TRL-" in out
    assert "never the reason" in out


def test_propose_branch_warns_when_a_claim_describes_code(committed_repo: Path):
    out = propose_branch(
        id="BRN-queue-bounded", subject="CMP-scheduler", premises=["AXM-energy-budget"],
        claim="Scheduler.enqueue in scheduler.py returns False once the queue holds 64 items.",
        rationale="bounded queue")
    assert "warning:" in out
    assert "scheduler.py" in out
    assert "any implementation" in out


# ---------- the verifier's input, independence, one pass per call ----------

def test_probe_view_serves_premises_in_full_and_nothing_from_the_source(committed_repo: Path):
    """What a verifier reads: the premises with their statements, the claim, the derivation rule,
    the three strategies and the call that records them. No file name anywhere."""
    out = status("probe", subject="BRN-gpu-throttling")
    assert "PROBE BRN-gpu-throttling [BRANCH]" in out
    assert "[LEMMA LMA-compute-cap]: Compute power cannot exceed 40W." in out
    assert "Cap GPU clock to guarantee power < 35W." in out
    assert "35W margin sits safely below the 40W ceiling." in out
    assert "counterexample" in out and "entailment" in out and "negation" in out
    assert 'verify_step("BRN-gpu-throttling", trials=[' in out
    assert ".py" not in out

    every = status("probe")
    assert "2 probe(s)" in every
    assert "PROBE LMA-compute-cap" in every and "PROBE BRN-gpu-throttling" in every
    assert "unknown node" in status("probe", subject="BRN-nope")
    assert "is a root" in status("probe", subject="AXM-energy-budget")


def test_repeating_one_strategy_does_not_close_an_obligation(committed_repo: Path):
    """Rule 4.3 asks for independent trials. Three counterexample probes by one actor are one
    probe run three times: recorded, counted toward consensus, not toward n_min."""
    for i in range(3):
        out = verify_step("LMA-compute-cap", strategy="counterexample", outcome="sound", rationale=f"try {i}")
    assert "1/2 independent" in out
    assert "untried: entailment, negation" in out
    assert "LMA-compute-cap [OBLIGATION 1/2]" in status("tree")
    obligations = status("obligations")
    assert "progress: 1/2 independent trials (need 1 more; untried: entailment, negation)" in obligations
    assert "2 repeat(s) of a strategy by the same actor do not add" in obligations

    verify_step("LMA-compute-cap", strategy="entailment", outcome="sound", rationale="follows")
    assert "LMA-compute-cap [PROVEN 4/4]" in status("tree")


def test_a_different_actor_is_an_independent_trial(committed_repo: Path, monkeypatch):
    verify_step("LMA-compute-cap", strategy="counterexample", outcome="sound", rationale="first prober")
    monkeypatch.setenv("CONSISTENCY_ACTOR", "reviewer-2")
    verify_step("LMA-compute-cap", strategy="counterexample", outcome="sound", rationale="second prober")
    assert "LMA-compute-cap [PROVEN 2/2]" in status("tree")


def test_one_pass_is_one_call(committed_repo: Path):
    out = verify_step("LMA-compute-cap", trials=[
        {"strategy": "counterexample", "outcome": "sound", "rationale": "no scenario survives the 60W motor floor"},
        {"strategy": "entailment", "outcome": "sound", "rationale": "the subtraction is the whole step"},
        {"strategy": "negation", "outcome": "sound", "rationale": "NOT(cap) would need more than 100W"},
    ])
    assert out.count("recorded for LMA-compute-cap") == 3
    assert "TRL-0001" in out and "TRL-0003" in out
    assert "[PROVEN] 3/3 trials, 3/2 independent" in out


def test_a_batch_with_one_falsification_argued_from_source_records_nothing(committed_repo: Path):
    out = verify_step("LMA-compute-cap", trials=[
        {"strategy": "counterexample", "outcome": "sound", "rationale": "fine"},
        {"strategy": "entailment", "outcome": "falsified", "rationale": "power.py:12 ignores the motor",
         "counterexample": "the code adds nothing for the motor"},
    ])
    assert out.startswith("refused: trial 1 of this call")
    assert "Nothing was recorded" in out
    assert "TRL-" not in out
    assert "verification_trials×0" in status("tree")
    assert "unknown strategy 'vibes' in trial 0" in verify_step("LMA-compute-cap", trials=[{"strategy": "vibes"}])


def test_the_refusal_counts_amended_falsifications_from_its_own_ledger(committed_repo: Path):
    """The refusal used to assert a number about the ledger; now it reads it."""
    verify_step("BRN-gpu-throttling", outcome="falsified", rationale="wrong target",
                counterexample="a scenario that names no file")
    amend("TRL-0001", validity="invalid", reason="recorded against the wrong branch")
    out = verify_step("LMA-compute-cap", outcome="falsified", rationale="the implementation",
                      counterexample="power.py:12 drops the motor term")
    assert out.startswith("refused:")
    assert "1 falsification(s) in this ledger were recorded this way and had to be amended" in out


def test_audit_change_is_recorded_as_an_event(committed_repo: Path):
    from consistency_belief.store import Store

    audit_change("AXM-energy-budget", proposed_statement="bounded at 80W", reason="new battery")
    events = [e for e in Store(committed_repo).events() if e.get("tool") == "audit_change"]
    assert len(events) == 1
    assert events[0]["payload"]["target"] == "AXM-energy-budget"
    assert set(events[0]["payload"]["blast_radius"]) == {"LMA-compute-cap", "BRN-gpu-throttling"}
    assert events[0]["payload"]["reason"] == "new battery"


def test_a_decision_names_the_revision_it_was_taken_at(committed_repo: Path):
    from consistency_belief.store import Store

    head = git(committed_repo, "rev-parse", "--short", "HEAD").stdout.strip()
    out = decide("BRN-gpu-throttling", policy_id="POL-energy-gate")
    assert f"at HEAD {head}" in out
    assert Store(committed_repo).decisions()[0]["head"] == head


def test_propose_branch_warns_when_a_claim_names_a_class_or_a_call(committed_repo: Path):
    out = propose_branch(id="BRN-queue", subject="CMP-scheduler", premises=["AXM-energy-budget"],
                         claim="Scheduler.enqueue() refuses the 65th item.", rationale="bounded queue")
    assert "warning:" in out and "Scheduler.enqueue" in out
    clean = propose_branch(id="BRN-queue-2", subject="CMP-scheduler", premises=["AXM-energy-budget"],
                           claim="No more than 64 items are ever queued, whatever the load.",
                           rationale="bounded by the energy budget, cited in belief.yaml")
    assert "warning:" not in clean


# ---------- the joint gate: a design proven over a refuted measurement is proven of nothing ----------

JOINT_BELIEF = """
components:
  - id: CMP-gpu-manager
    purpose: Manage the GPU clock
    testable_capability: Keeps GPU power under the cap
    failure_modes: [{id: FM-spike, observable: power exceeds 35W}]
    remediation: Lower the clock ceiling
    code: [gpu.py]

contracts:
  - id: CTR-gpu-power
    subject: CMP-gpu-manager
    claim_type: capability
    kind: gate
    metrics: [{id: passed, unit: bool}]
    acceptance: {rule: "passed == true"}
    evaluable_by: [TST-gpu]

tests:
  - id: TST-gpu
    layer: component
    targets: [CMP-gpu-manager]
    run: "echo ok"
    metrics: [passed]
"""


def _prove(node: str) -> None:
    verify_step(node, trials=[{"strategy": "counterexample", "outcome": "sound", "rationale": "ok"},
                              {"strategy": "entailment", "outcome": "sound", "rationale": "ok"}])


@pytest.fixture
def joint_repo(committed_repo: Path) -> Path:
    yaml = SAMPLE_CONSISTENCY_YAML.replace(
        "derivation_rule: 35W margin sits safely below the 40W ceiling.",
        'derivation_rule: "35W margin sits safely below the 40W ceiling. evidence: CTR-gpu-power"',
    ).replace(
        "      - {target: BRN-gpu-throttling, require: proven}",
        "      - {target: BRN-gpu-throttling, require: proven, evidence: supported}",
    )
    (committed_repo / "consistency.yaml").write_text(yaml, encoding="utf-8")
    (committed_repo / "belief.yaml").write_text(JOINT_BELIEF, encoding="utf-8")
    (committed_repo / "gpu.py").write_text("# gpu\n", encoding="utf-8")
    git(committed_repo, "add", "-A")
    git(committed_repo, "commit", "-q", "-m", "join the ledgers")
    return committed_repo


def _measure(repo: Path, passed: bool, run_id: str) -> None:
    from component_belief.store import Store as BeliefStore

    head = git(repo, "rev-parse", "--short", "HEAD").stdout.strip()
    BeliefStore(repo).append_trials([{
        "subject": "CMP-gpu-manager", "contract_id": "CTR-gpu-power", "test_id": "TST-gpu",
        "test_ref": "TST-gpu@x", "run_id": run_id, "provenance": "measured",
        "outcome": "pass" if passed else "fail", "metrics": {"passed": passed},
        "conditions": {"raw": {}}, "repro": {"sw_revision": head},
        "validity": "valid", "artifact_uri": "a", "artifact_hash": "h",
    }])


def test_joint_gate_requires_the_cited_contract_supported(joint_repo: Path):
    _prove("LMA-compute-cap")
    _prove("BRN-gpu-throttling")
    assert "[PROVEN 2/2]" in status("branches", subject="BRN-gpu-throttling")

    unmeasured = decide("BRN-gpu-throttling", policy_id="POL-energy-gate")
    assert "MORE_TESTING" in unmeasured
    assert "rests on CTR-gpu-power, which is no evidence" in unmeasured

    _measure(joint_repo, passed=False, run_id="RUN-0001")
    refuted = decide("BRN-gpu-throttling", policy_id="POL-energy-gate")
    assert "REJECT" in refuted and "which is REFUTED" in refuted

    _measure(joint_repo, passed=True, run_id="RUN-0002")     # a gate reads its latest run
    adopt = decide("BRN-gpu-throttling", policy_id="POL-energy-gate")
    assert "ADOPT" in adopt and "NOT RECORDED" in adopt
    assert "CTR-gpu-power=supported" in adopt


def test_joint_gate_on_a_branch_citing_no_contract_is_an_obligation(committed_repo: Path):
    _commit_yaml(committed_repo, SAMPLE_CONSISTENCY_YAML.replace(
        "      - {target: BRN-gpu-throttling, require: proven}",
        "      - {target: BRN-gpu-throttling, require: proven, evidence: supported}"), "require evidence")
    _prove("LMA-compute-cap")
    _prove("BRN-gpu-throttling")
    out = decide("BRN-gpu-throttling", policy_id="POL-energy-gate")
    assert "MORE_TESTING" in out and "cites no contract" in out


def test_a_bad_evidence_criterion_is_reported(committed_repo: Path):
    from consistency_belief.declarations import load

    _commit_yaml(committed_repo, SAMPLE_CONSISTENCY_YAML.replace(
        "      - {target: BRN-gpu-throttling, require: proven}",
        "      - {target: BRN-gpu-throttling, require: proven, evidence: green}"), "bad criterion")
    assert any(i.code == "BAD_CRITERION" for i in load(committed_repo).issues)
