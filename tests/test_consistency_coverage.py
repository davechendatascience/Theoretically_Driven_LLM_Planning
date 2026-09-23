"""The join between the two ledgers: a branch's subject names a component in belief.yaml.

What the design ledger needs from the component ledger is which components exist and which are
built. A component with code and no declared branch is the prune-or-declare case; a component
with a branch and no code is a design that precedes its implementation, and is allowed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from component_belief.declarations import load as load_components_declarations
from consistency_belief.declarations import load
from consistency_belief.views import Context, view_coverage
from conftest import git

BELIEF = """
components:
  - id: CMP-motion
    purpose: Plan motion
    testable_capability: Produces a trajectory that clears obstacles
    failure_modes: [{id: FM-clip, observable: trajectory clips an obstacle}]
    remediation: Retune the clearance margin
    code: [motion.py]
  - id: CMP-gripper
    purpose: Close the jaws
    testable_capability: Holds an object through a carry
    failure_modes: [{id: FM-drop, observable: object leaves the jaws}]
    remediation: Raise the squeeze
    code: [gripper.py]
  - id: CMP-planner
    purpose: Choose the next skill
    testable_capability: Selects an applicable skill at every state
    failure_modes: [{id: FM-stuck, observable: no skill applies}]
    remediation: Widen the contract set

contracts:
  - id: CTR-motion-clear
    subject: CMP-motion
    claim_type: capability
    metrics: [{id: clearance, unit: m}]
    acceptance: {rule: "clearance > 0.5"}
    evaluable_by: []
"""

CONSISTENCY = """
components:
  - {id: CMP-motion, note: what the gate below governs}
  - CMP-planner

axioms:
  - id: AXM-safety
    domain: safety
    statement: The robot must not collide.
    rationale: Core physical safety invariant.

branches:
  - id: BRN-motion-gate
    subject: CMP-motion
    claim_type: contract
    statement: Abort the trajectory below 0.5 m of clearance.
    premises: [AXM-safety]
    derivation_rule: "motion.py, evidence: CTR-motion-clear"

  - id: BRN-planner-regression
    subject: CMP-planner
    claim_type: contract
    statement: The planner regresses over declared contracts.
    premises: [AXM-safety]
    derivation_rule: "planner.py, not written yet"

  - id: BRN-orphan
    subject: the teacher, described in prose
    claim_type: contract
    statement: Something true of a component nobody declared.
    premises: [AXM-safety]
    derivation_rule: "evidence: CTR-nowhere"

  - id: BRN-left-behind
    subject: CMP-deleted
    claim_type: contract
    statement: Something true of a component that was removed.
    premises: [AXM-safety]
    derivation_rule: "deleted.py"
"""


@pytest.fixture
def linked(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    (tmp_path / "belief.yaml").write_text(BELIEF, encoding="utf-8")
    (tmp_path / "consistency.yaml").write_text(CONSISTENCY, encoding="utf-8")
    (tmp_path / "motion.py").write_text("# motion\n", encoding="utf-8")
    (tmp_path / "gripper.py").write_text("# gripper\n", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "declare both ledgers")
    return tmp_path


def test_components_load_from_the_component_ledger(linked: Path):
    decl = load(linked)
    assert decl.components_source == "git-HEAD"
    assert set(decl.components) == {"CMP-motion", "CMP-gripper", "CMP-planner"}
    assert decl.components["CMP-motion"].implemented
    assert decl.components["CMP-motion"].contracts == ["CTR-motion-clear"]
    assert not decl.components["CMP-planner"].implemented, "no code: declares a planned component"


def test_prose_subject_is_reported_but_not_fatal(linked: Path):
    decl = load(linked)
    unattached = {i.subject for i in decl.issues if i.code == "UNATTACHED_SUBJECT"}
    assert unattached == {"BRN-orphan"}
    assert decl.is_valid_node("BRN-orphan"), "a design keeps its place in the proof DAG"


def test_a_removed_component_leaves_its_design_broken(linked: Path):
    decl = load(linked)
    removed = [i for i in decl.issues if i.code == "REMOVED_SUBJECT"]
    assert [i.subject for i in removed] == ["BRN-left-behind"]
    assert "removed or renamed" in removed[0].message
    assert decl.is_valid_node("BRN-left-behind"), "the proof stands; only its subject is gone"

    text = view_coverage(Context.build(linked))
    broken = text.split("BROKEN")[1].split("unattached --")[0]
    assert "CMP-deleted" in broken and "BRN-left-behind" in broken
    assert "BRN-orphan" not in broken, "prose and a deleted component are different faults"
    assert "repoint or prune" in text


def test_unknown_evidence_id_is_reported(linked: Path):
    decl = load(linked)
    evidence = [i for i in decl.issues if i.code == "UNKNOWN_EVIDENCE"]
    assert [i.subject for i in evidence] == ["BRN-orphan"]
    assert "CTR-nowhere" in evidence[0].message
    assert not [i for i in decl.issues if i.code == "UNKNOWN_EVIDENCE" and i.subject == "BRN-motion-gate"]


def test_coverage_sorts_components_by_code_and_design(linked: Path):
    text = view_coverage(Context.build(linked))
    assert "governed" in text and "CMP-motion" in text
    undeclared = text.split("undeclared design")[1].split("planned --")[0]
    assert "CMP-gripper" in undeclared, "code with no declared branch is the prune-or-declare case"
    planned = text.split("planned --")[1]
    assert "CMP-planner" in planned, "a design may precede its implementation"
    assert "BRN-orphan" in text.split("unattached --")[1]


def test_coverage_without_a_component_ledger_explains_itself(tmp_path: Path):
    git(tmp_path, "init", "-q")
    (tmp_path / "consistency.yaml").write_text(CONSISTENCY, encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "design only")

    decl = load(tmp_path)
    assert decl.components_source == "none"
    assert not [i for i in decl.issues
                if i.code in ("REMOVED_SUBJECT", "UNATTACHED_SUBJECT", "UNKNOWN_EVIDENCE")], \
        "no component ledger means subjects go unchecked, not wrong"
    assert "belief.yaml" in view_coverage(Context.build(tmp_path))


def test_code_paths_are_checked_against_the_repository(linked: Path):
    (linked / "belief.yaml").write_text(BELIEF.replace("code: [gripper.py]", "code: [gone.py]"), encoding="utf-8")
    git(linked, "commit", "-qam", "claim a path that does not exist")

    decl = load_components_declarations(linked)
    missing = [i for i in decl.issues if i.code == "MISSING_CODE_PATH"]
    assert [i.subject for i in missing] == ["CMP-gripper"]
    assert decl.components_for_path("motion.py") == ["CMP-motion"]


# --- withdrawing a staged proposal ------------------------------------------------------------

def test_withdraw_retires_a_staged_proposal_and_keeps_the_record(linked: Path, monkeypatch):
    from consistency_belief import server

    monkeypatch.setenv("CONSISTENCY_PROJECT_ROOT", str(linked))
    server.propose_branch(id="BRN-doomed", subject="CMP-motion", premises=["AXM-safety"],
                          claim="A design nobody will build.", rationale="staged for the test")
    assert "BRN-doomed" in Context.build(linked).dag.nodes

    out = server.withdraw(id="BRN-doomed", reason="the approach was abandoned")
    assert "withdrawn" in out
    ctx = Context.build(linked)
    assert "BRN-doomed" not in ctx.dag.nodes
    assert ctx.store.withdrawn() == {"BRN-doomed": "the approach was abandoned"}
    assert any(e.get("tool") == "propose_branch" and e["payload"]["id"] == "BRN-doomed"
               for e in ctx.store.events()), "the ledger keeps what was proposed"

    server.propose_branch(id="BRN-doomed", subject="CMP-motion", premises=["AXM-safety"],
                          claim="A design nobody will build.", rationale="revived")
    assert "BRN-doomed" in Context.build(linked).dag.nodes


def test_withdraw_refuses_a_declaration_and_an_empty_reason(linked: Path, monkeypatch):
    from consistency_belief import server

    monkeypatch.setenv("CONSISTENCY_PROJECT_ROOT", str(linked))
    refused = server.withdraw(id="BRN-motion-gate", reason="not wanted")
    assert "rejected" in refused and "consistency.yaml" in refused

    server.propose_branch(id="BRN-staged", subject="CMP-motion", premises=["AXM-safety"],
                          claim="Staged.", rationale="r")
    assert "reason is empty" in server.withdraw(id="BRN-staged", reason="  ")
    assert "unknown proposal" in server.withdraw(id="BRN-nothing", reason="r")


# --- the components a design file governs ------------------------------------------------------

def test_consistency_yaml_lists_the_components_it_governs(linked: Path):
    decl = load(linked)
    assert set(decl.governs) == {"CMP-motion", "CMP-planner"}
    assert decl.governs["CMP-motion"].note == "what the gate below governs"
    assert "consistency.yaml governs (2): CMP-motion, CMP-planner" in view_coverage(Context.build(linked))


def test_a_listed_component_that_belief_yaml_dropped_is_reported(linked: Path):
    (linked / "consistency.yaml").write_text(
        CONSISTENCY.replace("  - CMP-planner", "  - CMP-planner\n  - CMP-deleted"), encoding="utf-8")
    git(linked, "commit", "-qam", "list a component belief.yaml does not declare")

    removed = [i for i in load(linked).issues if i.code == "REMOVED_COMPONENT"]
    assert [i.subject for i in removed] == ["CMP-deleted"]
    assert "removed or renamed" in removed[0].message


def test_a_subject_missing_from_the_list_is_reported(linked: Path):
    (linked / "consistency.yaml").write_text(
        CONSISTENCY.replace("  - CMP-planner\n", ""), encoding="utf-8")
    git(linked, "commit", "-qam", "drop a component from the list while a branch still governs it")

    unlisted = [i for i in load(linked).issues if i.code == "UNLISTED_SUBJECT"]
    assert [i.subject for i in unlisted] == ["BRN-planner-regression"]


# --- a claim cites the measurement behind it ---------------------------------------------------

def test_a_branch_naming_no_contract_is_reported(linked: Path):
    decl = load(linked)
    missing = {i.subject for i in decl.issues if i.code == "MISSING_EVIDENCE"}
    assert missing == {"BRN-planner-regression", "BRN-left-behind"}, \
        "a branch citing a contract is not reported, even when that contract is unknown"


def test_coverage_prints_the_contract_and_its_belief_state(linked: Path):
    text = view_coverage(Context.build(linked))
    assert "CTR-motion-clear [no evidence]" in text, "a cited contract with no trials says so"
    assert "evidence: none cited" in text
