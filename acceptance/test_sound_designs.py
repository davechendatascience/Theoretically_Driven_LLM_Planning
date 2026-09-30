"""GOL-sound-designs: a design claim counts as proven only after falsification probes judged from
the declarations alone, and stops counting when a premise it rests on changes."""

from __future__ import annotations

from pathlib import Path

import pytest
from consistency_belief import server as design

from conftest import commit

DESIGN_YAML = """
components:
  - {id: CMP-planner, note: the grasp planner}

axioms:
  - id: AXM-reach
    domain: kinematics
    statement: A pose the arm cannot reach is never executed.
    rationale: Safety.

definitions:
  - id: DEF-reachable
    term: Reachable
    meaning: Inverse kinematics returns a solution for the pose.

branches:
  - id: BRN-planner-reachable
    subject: CMP-planner
    claim_type: contract
    statement: The planner proposes only poses for which inverse kinematics returns a solution.
    premises: [AXM-reach, DEF-reachable]
    derivation_rule: >-
      By DEF-reachable a pose is reachable exactly when inverse kinematics solves it, and by
      AXM-reach no unreachable pose is executed. evidence: CTR-planner-works
    sufficiency: {n_min: 3, min_consensus: 0.8}

policies:
  - id: POL-design-gate
    criteria:
      - {target: BRN-planner-reachable, require: proven, evidence: supported}
"""

#: One pass: the three strategies, each a real attempt written down.
ONE_PASS = [{"strategy": s, "outcome": "sound", "rationale": f"attacked the step by {s}; it held"}
            for s in ("counterexample", "entailment", "negation")]
BRANCH = "BRN-planner-reachable"


@pytest.fixture
def designed(project: Path) -> Path:
    (project / "consistency.yaml").write_text(DESIGN_YAML, encoding="utf-8")
    commit(project, "declare the design")
    return project


def badge() -> str:
    """The branch's badge in the proof tree, e.g. [PROVEN 3/3]."""
    line = next(line for line in design.status("tree").splitlines() if BRANCH in line)
    return line[line.index("["):line.index("]") + 1]


def test_an_unverified_claim_is_an_obligation_not_a_truth(designed):
    assert badge().startswith("[OBLIGATION")


def test_one_pass_of_three_probes_proves_it(designed):
    design.verify_step(BRANCH, trials=ONE_PASS)
    assert badge().startswith("[PROVEN")


def test_a_counterexample_refutes_it(designed):
    design.verify_step(BRANCH, trials=ONE_PASS)
    design.verify_step(BRANCH, strategy="counterexample", outcome="falsified",
                       rationale="every premise holds and the claim fails",
                       counterexample="IK returns a solution that violates a joint limit, so the "
                                      "pose is reachable by DEF-reachable yet the arm cannot reach it")
    assert badge() == "[REFUTED]"


def test_restating_a_premise_makes_the_claim_stale(designed):
    design.verify_step(BRANCH, trials=ONE_PASS)
    text = (designed / "consistency.yaml").read_text(encoding="utf-8")
    (designed / "consistency.yaml").write_text(
        text.replace("A pose the arm cannot reach is never executed.",
                     "A pose the arm cannot reach within its joint limits is never executed."),
        encoding="utf-8")
    commit(designed, "restate the axiom")
    assert not badge().startswith("[PROVEN")


def test_a_falsification_argued_from_the_source_is_refused(designed):
    out = design.verify_step(BRANCH, strategy="counterexample", outcome="falsified",
                             rationale="read the implementation",
                             counterexample="planner.py returns a pose without calling the IK solver")
    assert "refused" in out
    assert badge().startswith("[OBLIGATION")
