"""Integration tests: one class per interface belief.yaml declares between components.

A component test checks one side of a hand-over. These run the producer's actual output through
the consumer and assert what the interface declares: each producer guarantee holds of what the
producer hands over, and the consumer behaves as its assumption says when it receives it --
including the malformed input the guarantee is there to stop.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import BASE_YAML, git, trial


# ---------- IFC-declarations__model: CMP-declarations -> CMP-belief-model ----------

class TestDeclarationsToModel:
    """Guarantees: contracts reaching the model are scorable; condition predicates parse under the
    whitelist."""

    YAML = BASE_YAML.replace("\ntests:", """
  - id: CTR-unparsable
    subject: CMP-grasp
    claim_type: capability
    metrics: [{id: ik_success, unit: bool}]
    acceptance: {rule: "ik_success ==", target_rate: 0.8}
    evaluable_by: [TST-grasp-ik]
  - id: CTR-bad-bucket
    subject: CMP-grasp
    claim_type: capability
    metrics: [{id: ik_success, unit: bool}]
    acceptance: {rule: "ik_success == true", target_rate: 0.8}
    conditions:
      - {id: sneaky, when: "__import__('os').system('true')"}
    evaluable_by: [TST-grasp-ik]

tests:""")

    @pytest.fixture
    def declared(self, repo: Path) -> Path:
        (repo / "belief.yaml").write_text(self.YAML, encoding="utf-8")
        git(repo, "add", "belief.yaml")
        git(repo, "commit", "-q", "-m", "an unparsable rule and a predicate outside the whitelist")
        return repo

    def test_an_unscorable_contract_never_reaches_a_belief(self, declared: Path):
        from component_belief.declarations import load
        from component_belief.model import compute_slices

        decl = load(declared)
        assert not decl.is_scorable("CTR-unparsable"), "the producer marks it"
        trials = [trial(contract=c) for c in ("CTR-grasp-reachable", "CTR-unparsable") for _ in range(10)]
        slices = compute_slices(decl, trials)
        assert {s.contract_id for s in slices} == {"CTR-grasp-reachable"}

    def test_a_predicate_outside_the_whitelist_is_reported_and_never_runs(self, declared: Path):
        from component_belief.declarations import load
        from component_belief.model import UNBUCKETED, compute_slices

        decl = load(declared)
        assert any(i.code == "BAD_CONDITION" and i.subject == "CTR-bad-bucket" for i in decl.issues)
        slices = compute_slices(decl, [trial(contract="CTR-bad-bucket") for _ in range(10)])
        assert [s.bucket for s in slices] == [UNBUCKETED], "the model buckets nothing on it"


# ---------- IFC-model__diagnose: CMP-belief-model -> CMP-diagnosis ----------

class TestModelToDiagnosis:
    """Guarantees: every slice carries its applicable conditions; insufficient slices carry no
    verdict; a stale slice carries no verdict and names the change it predates."""

    def test_every_slice_carries_its_conditions(self, repo: Path):
        from component_belief.declarations import load
        from component_belief.model import compute_slices

        slices = compute_slices(load(repo), [trial(lighting=l) for l in ("normal", "low") for _ in range(6)])
        assert {s.bucket for s in slices} == {"normal", "low"}
        assert all(s.compat_fields == {"model_revision": "v3"} for s in slices)

    def test_an_insufficient_slice_is_no_verdict_downstream(self, repo: Path):
        from component_belief.decide import MORE_TESTING, active_policy, evaluate_policy
        from component_belief.declarations import load
        from component_belief.diagnose import CONFIRMED, diagnose
        from component_belief.model import STATE_INSUFFICIENT, compute_slices

        decl = load(repo)
        trials = [trial(ik=False) for _ in range(2)]
        slices = compute_slices(decl, trials)
        assert [s.state for s in slices] == [STATE_INSUFFICIENT]
        grasp = next(c for c in diagnose(decl, slices, trials).ranked if c.subject == "CMP-grasp")
        assert grasp.status != CONFIRMED, "two failures below n_min confirm nothing"
        assert evaluate_policy(decl, active_policy(decl), slices).status == MORE_TESTING

    def test_a_stale_slice_is_no_verdict_and_names_its_change(self, repo: Path):
        from component_belief.decide import MORE_TESTING, active_policy, evaluate_policy
        from component_belief.declarations import load
        from component_belief.diagnose import STALE, diagnose
        from component_belief.model import STATE_STALE, compute_slices
        from component_belief.staleness import CodeStaleness

        (repo / "grasp.py").write_text("# v1\n", encoding="utf-8")
        (repo / "belief.yaml").write_text(BASE_YAML.replace(
            "    remediation: Retune approach sampling\n",
            "    remediation: Retune approach sampling\n    code: [grasp.py]\n"), encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "claim the code")
        revision = git(repo, "rev-parse", "--short", "HEAD").stdout.strip()
        trials = []
        for _ in range(30):
            t = trial()
            t["repro"] = {"model_revision": "v3", "sw_revision": revision}
            trials.append(t)
        (repo / "grasp.py").write_text("# v2\n", encoding="utf-8")
        git(repo, "commit", "-qam", "change the planner")

        decl = load(repo)
        slices = compute_slices(decl, trials, staleness=CodeStaleness(repo))
        assert [s.state for s in slices] == [STATE_STALE]
        assert "grasp.py" in slices[0].stale_reasons[0], "it names the change it predates"
        grasp = next(c for c in diagnose(decl, slices, trials).ranked if c.subject == "CMP-grasp")
        assert grasp.status == STALE
        assert evaluate_policy(decl, active_policy(decl), slices).status == MORE_TESTING


# ---------- IFC-cdeclarations__proofdag: CMP-consistency-declarations -> CMP-proof-dag ----------

DESIGN = """
axioms:
  - {id: AXM-root, statement: Power is bounded at 100W.}
lemmas:
  - {id: LMA-cap, statement: Compute stays under 40W., premises: [AXM-root], derivation_rule: budget}
  - {id: LMA-dangling, statement: Something resting on nothing declared., premises: [AXM-missing],
     derivation_rule: none}
  - {id: LMA-a, statement: A holds., premises: [LMA-b], derivation_rule: from b}
  - {id: LMA-b, statement: B holds., premises: [LMA-a], derivation_rule: from a}
"""


@pytest.fixture
def designed(empty_repo: Path, monkeypatch) -> Path:
    (empty_repo / "consistency.yaml").write_text(DESIGN, encoding="utf-8")
    git(empty_repo, "add", "consistency.yaml")
    git(empty_repo, "commit", "-q", "-m", "a design with a dangling premise and a cycle")
    monkeypatch.setenv("CONSISTENCY_PROJECT_ROOT", str(empty_repo))
    return empty_repo


class TestConsistencyDeclarationsToProofDag:
    """Guarantees: every premise names a declared node, or the declaration carries
    UNKNOWN_PREMISE; a cycle among declarations is reported before the graph is built."""

    def test_an_unknown_premise_is_marked_and_never_admitted(self, designed: Path):
        from consistency_belief.declarations import load
        from consistency_belief.graph import ProofDAG

        decl = load(designed)
        assert any(i.code == "UNKNOWN_PREMISE" and i.subject == "LMA-dangling" for i in decl.issues)
        dag = ProofDAG.from_declarations(decl)
        assert dag.get("LMA-dangling") is None and dag.get("LMA-cap") is not None

    def test_a_cycle_is_reported_and_the_graph_built_without_it(self, designed: Path):
        from consistency_belief.declarations import load
        from consistency_belief.graph import ProofDAG

        from consistency_belief.server import status

        decl = load(designed)
        cycle = [i for i in decl.issues if i.code == "CIRCULAR_DEPENDENCY"]
        assert cycle and all(n in cycle[0].message for n in ("LMA-a", "LMA-b")), "it names the cycle"
        dag = ProofDAG.from_declarations(decl)
        assert dag.get("LMA-a") is None and dag.get("LMA-b") is None
        assert all(nid not in dag.ancestors(nid) for nid in dag.nodes), "no node depends on itself"
        left_out = status("tree").split("Declared, not admitted")[1]
        assert "LMA-a" in left_out and "LMA-b" in left_out, "neither is dropped in silence"


# ---------- IFC-proofdag__views: CMP-proof-dag -> CMP-trial-ledger ----------

class TestProofDagToLedgerViews:
    """Guarantees: a trial counts only under the statement fingerprint it was recorded against;
    only a falsified probe refutes."""

    def test_a_trial_stops_counting_once_its_claim_is_restated(self, designed: Path):
        from consistency_belief.server import status, verify_step

        verify_step("LMA-cap", trials=[{"strategy": s, "outcome": "sound", "rationale": "ok"}
                                       for s in ("counterexample", "entailment", "negation")])
        assert "LMA-cap [PROVEN 3/3]" in status("tree")
        (designed / "consistency.yaml").write_text(
            DESIGN.replace("Compute stays under 40W.", "Compute stays under 45W."), encoding="utf-8")
        git(designed, "commit", "-qam", "restate the cap")
        assert "LMA-cap [OBLIGATION 0/3]" in status("tree")

    def test_a_gap_doubts_and_only_a_falsification_refutes(self, designed: Path):
        from consistency_belief.server import status, verify_step

        verify_step("LMA-cap", trials=[
            {"strategy": "counterexample", "outcome": "sound", "rationale": "no scenario found"},
            {"strategy": "entailment", "outcome": "gap", "rationale": "needs a motor bound",
             "counterexample": "the motors draw at most 60W"},
            {"strategy": "negation", "outcome": "sound", "rationale": "the negation does not follow"}])
        assert "REFUTED" not in status("tree").split("LMA-cap")[1].split("\n")[0]
        verify_step("LMA-cap", trials=[{"strategy": "counterexample", "outcome": "falsified",
                                        "rationale": "motors at 70W leave 30W",
                                        "counterexample": "motors draw 70W while the budget holds"}])
        assert "LMA-cap" in status("contradictions")
        assert "LMA-cap [REFUTED" in status("tree")
