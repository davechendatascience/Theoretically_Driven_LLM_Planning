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
