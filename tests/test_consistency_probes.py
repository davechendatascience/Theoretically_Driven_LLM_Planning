"""Tests for verification probes, trial parsing, store ledger, and model belief calculation."""

from __future__ import annotations

import tempfile
from pathlib import Path
import pytest

from consistency_belief.graph import ProofDAG, ProofNode
from consistency_belief.model import (
    DOUBTED,
    OBLIGATION,
    PROVEN,
    REFUTED,
    STALE,
    UNGROUNDED,
    compute_consistency,
)
from consistency_belief.probes import (
    STRATEGY_COUNTEREXAMPLE,
    STRATEGY_ENTAILMENT,
    STRATEGY_NEGATION,
    build_probe_prompt,
    parse_probe_result,
)
from consistency_belief.store import Store


@pytest.fixture
def mini_dag() -> ProofDAG:
    dag = ProofDAG()
    dag.add_node(ProofNode("AXM-1", kind="axiom", statement="Inputs are sanitized"))
    dag.add_node(ProofNode("LMA-1", kind="lemma", statement="SQL injection impossible", premises=["AXM-1"], metadata={"n_min": 2, "min_consensus": 0.8}))
    return dag


def test_build_probe_prompt(mini_dag: ProofDAG):
    prompt_info = build_probe_prompt(mini_dag, "LMA-1", STRATEGY_COUNTEREXAMPLE)
    assert prompt_info["target_id"] == "LMA-1"
    assert "AXM-1" in prompt_info["prompt"]
    assert "SQL injection impossible" in prompt_info["prompt"]
    assert len(prompt_info["prompt_hash"]) == 12


def test_parse_probe_result_json_and_markdown():
    # 1. Clean JSON
    raw_json = '{"outcome": "sound", "reasoning": "Deductively sound"}'
    res = parse_probe_result(raw_json)
    assert res["passed"] is True
    assert res["outcome"] == "sound"
    assert res["counterexample"] is None

    # 2. Markdown fenced JSON with counterexample
    raw_md = """
Here is my evaluation:
```json
{
  "outcome": "falsified",
  "counterexample": "Unicode normalization attack bypasses sanitizer",
  "reasoning": "Homoglyph vulnerability"
}
```
"""
    res_falsified = parse_probe_result(raw_md)
    assert res_falsified["passed"] is False
    assert res_falsified["outcome"] == "falsified"
    assert "Unicode" in res_falsified["counterexample"]


def test_store_ledger_immutability_and_amendment(tmp_path: Path):
    store = Store(tmp_path)
    t1 = store.append_trial({
        "target_id": "LMA-1",
        "outcome": "sound",
        "passed": True,
    })
    t2 = store.append_trial({
        "target_id": "LMA-1",
        "outcome": "falsified",
        "passed": False,
        "counterexample": "Flawed mock",
    })

    effective = store.effective_trials()
    assert len(effective) == 2
    assert effective[1]["validity"] == "valid"

    # Amendment folds over target without modifying original line
    store.append_amendment(t2, validity="invalid", reason="Test mock was misconfigured")
    effective_after = store.effective_trials()
    t2_after = next(t for t in effective_after if t["id"] == t2)
    assert t2_after["validity"] == "invalid"
    assert t2_after["validity_reason"] == "Test mock was misconfigured"

    # Raw ledger still holds both lines plus amendment
    assert len(store.raw_records()) == 3


def test_note_channel_is_asserted_and_inert(tmp_path: Path):
    store = Store(tmp_path)
    rec = store.append_note("LMA-1", "This feels rock solid")
    assert rec["provenance"] == "asserted"
    assert rec["kind"] == "note"

    # Notes do not appear in effective_trials
    assert len(store.effective_trials()) == 0


def test_model_state_transitions(mini_dag: ProofDAG):
    # 0 trials -> OBLIGATION
    slices = compute_consistency(mini_dag, [], targets=["LMA-1"])
    assert slices[0].state == OBLIGATION
    assert slices[0].n_trials == 0

    # 1 trial (n_min = 2) -> still OBLIGATION
    trials = [{"id": "TRL-1", "target_id": "LMA-1", "outcome": "sound", "passed": True, "validity": "valid"}]
    slices = compute_consistency(mini_dag, trials, targets=["LMA-1"])
    assert slices[0].state == OBLIGATION
    assert slices[0].n_trials == 1

    # a second trial of the same strategy by the same actor is recorded, not progress (rule 4.3:
    # independent trials) -- still OBLIGATION, 2 trials, 1 independent
    trials.append({"id": "TRL-2", "target_id": "LMA-1", "outcome": "sound", "passed": True, "validity": "valid"})
    slices = compute_consistency(mini_dag, trials, targets=["LMA-1"])
    assert slices[0].state == OBLIGATION
    assert slices[0].n_trials == 2 and slices[0].n_independent == 1
    assert slices[0].untried == ["entailment", "negation"]

    # a different strategy -> PROVEN
    trials.append({"id": "TRL-2b", "target_id": "LMA-1", "strategy": "entailment",
                   "outcome": "sound", "passed": True, "validity": "valid"})
    slices = compute_consistency(mini_dag, trials, targets=["LMA-1"])
    assert slices[0].state == PROVEN
    assert slices[0].n_trials == 3 and slices[0].n_independent == 2

    # Counterexample trial -> REFUTED
    trials.append({"id": "TRL-3", "target_id": "LMA-1", "outcome": "falsified", "passed": False, "counterexample": "Buffer overflow", "validity": "valid"})
    slices = compute_consistency(mini_dag, trials, targets=["LMA-1"])
    assert slices[0].state == REFUTED
    assert "Buffer overflow" in slices[0].counterexamples

    # Stale ancestor -> STALE
    slices_stale = compute_consistency(mini_dag, trials[:2], targets=["LMA-1"], stale_ancestors={"AXM-1"})
    assert slices_stale[0].state == STALE


def test_source_citations_finds_files_not_prose():
    from consistency_belief.probes import source_citations

    assert source_citations("skills.py:482 calls choose() without strict=True") == ["skills.py:482"]
    assert source_citations("reach.py:186 returns lo; see reach.py:99-103 and contacts.py") == [
        "reach.py:186", "reach.py:99-103", "contacts.py"]
    # prose about the design names no file, whatever it says about functions
    assert source_citations("The jaws hold a handle when both finger groups touch its geometry.") == []
    assert source_citations("A query answers for the stations it names and nothing between them.") == []


def test_a_declared_minimum_of_zero_proves_nothing(mini_dag: ProofDAG):
    """A node declared with n_min 0 and consensus 0 must not come out proven with no trials: a
    minimum below one is read as one, so a proof always rests on at least one trial."""
    mini_dag.nodes["LMA-1"].metadata.update({"n_min": 0, "min_consensus": 0.0})
    slices = compute_consistency(mini_dag, [], targets=["LMA-1"])
    assert slices[0].state == OBLIGATION
    assert slices[0].n_min == 1


def test_a_gap_doubts_and_never_refutes(mini_dag: ProofDAG):
    """FM-gap-refutes: an unstated assumption leaves a claim unproven, not false."""
    from consistency_belief.model import DOUBTED

    trials = [{"id": "TRL-1", "target_id": "LMA-1", "strategy": "counterexample", "outcome": "sound",
               "passed": True, "validity": "valid"},
              {"id": "TRL-2", "target_id": "LMA-1", "strategy": "entailment", "outcome": "gap",
               "passed": False, "counterexample": "an unstated bound", "validity": "valid"}]
    [sl] = compute_consistency(mini_dag, trials, targets=["LMA-1"])
    assert sl.state == DOUBTED and sl.state != REFUTED
    assert sl.counterexamples == [] and sl.gaps


def test_a_trial_recorded_against_another_statement_is_not_carried(mini_dag: ProofDAG):
    """FM-stale-carried: a trial counts only under the fingerprints it recorded -- the target's and
    every premise's -- so a restated target or premise sets it aside, and a trial made before
    fingerprints is judged by the ones its build had then."""
    node = mini_dag.get("LMA-1")
    now = (node.fingerprint(), mini_dag.basis_fingerprints("LMA-1"))
    sound = {"target_id": "LMA-1", "outcome": "sound", "passed": True, "validity": "valid"}
    current = [{**sound, "id": f"TRL-{s}", "strategy": s, "statement_sha": now[0], "basis": now[1]}
               for s in ("counterexample", "entailment")]
    assert compute_consistency(mini_dag, current, targets=["LMA-1"])[0].state == PROVEN

    restated = [{**t, "statement_sha": "another-statement"} for t in current]
    [sl] = compute_consistency(mini_dag, restated, targets=["LMA-1"])
    assert sl.state != PROVEN and sl.n_superseded == 2

    premise_moved = [{**t, "basis": {k: "earlier" for k in now[1]}} for t in current]
    [sl] = compute_consistency(mini_dag, premise_moved, targets=["LMA-1"])
    assert sl.state == STALE and sl.n_stale == 2

    legacy = [{k: v for k, v in t.items() if k not in ("statement_sha", "basis")} for t in current]
    then_same = compute_consistency(mini_dag, legacy, targets=["LMA-1"], legacy=lambda _id, _when: now)
    assert then_same[0].state == PROVEN, "a legacy trial whose build matched still counts"
    then_other = compute_consistency(mini_dag, legacy, targets=["LMA-1"],
                                     legacy=lambda _id, _when: ("older", now[1]))
    assert then_other[0].state != PROVEN, "and one made against another statement does not"


# ---------- a proof rests on its steps: conditional, and only the steps that read a change ----------

def _chain(axiom: str = "Inputs are sanitized", lemma: str = "SQL injection impossible",
           lemma_premises: tuple[str, ...] = ("AXM-1",)) -> ProofDAG:
    """AXM-1 <- LMA-1 <- BRN-1 <- BRN-2: each step cites only the one beneath it."""
    dag = ProofDAG()
    dag.add_node(ProofNode("AXM-1", kind="axiom", statement=axiom))
    dag.add_node(ProofNode("DEF-1", kind="definition", statement="Sanitized: escaped before use"))
    dag.add_node(ProofNode("LMA-1", kind="lemma", statement=lemma, premises=list(lemma_premises)))
    dag.add_node(ProofNode("BRN-1", kind="branch", statement="The query layer is safe", premises=["LMA-1"]))
    dag.add_node(ProofNode("BRN-2", kind="branch", statement="The service is safe", premises=["BRN-1"]))
    return dag


def _pass(dag: ProofDAG, target: str, outcome: str = "sound", record: str = "statements") -> list[dict]:
    """One verification pass on a target, recorded as the server records it: its fingerprint and
    what its probe served of each cited premise -- or, for trials from before 0.7.8, fingerprints."""
    node = dag.nodes[target]
    trials = []
    for strategy in (STRATEGY_COUNTEREXAMPLE, STRATEGY_ENTAILMENT, STRATEGY_NEGATION):
        t = {"id": f"TRL-{target}-{strategy}-{record}", "target_id": target, "validity": "valid",
             "strategy": strategy, "actor": "agent", "statement_sha": node.fingerprint(),
             "basis": dag.basis_fingerprints(target),
             "outcome": "falsified" if outcome == "falsified" and strategy == STRATEGY_COUNTEREXAMPLE else "sound",
             "passed": not (outcome == "falsified" and strategy == STRATEGY_COUNTEREXAMPLE),
             "counterexample": "a mocap root" if outcome == "falsified" and strategy == STRATEGY_COUNTEREXAMPLE else None}
        if record == "statements":
            t["read"] = dag.premise_statements(target)
        trials.append(t)
    return trials


def _states(dag: ProofDAG, trials: list[dict]) -> dict[str, tuple[str, list]]:
    return {s.target_id: (s.state, s.waiting_on) for s in compute_consistency(dag, trials)}


def test_a_step_over_an_unverified_premise_is_conditional():
    """Reported from embodied_ai on 0.7.7: a refuted premise left two branches resting on it
    reading PROVEN 3/3. Their steps hold; their ground does not."""
    from consistency_belief.model import CONDITIONAL
    dag = _chain()
    above = _pass(dag, "BRN-1") + _pass(dag, "BRN-2")

    refuted = _states(dag, above + _pass(dag, "LMA-1", outcome="falsified"))
    assert refuted["LMA-1"][0] == REFUTED
    assert refuted["BRN-1"] == (CONDITIONAL, [("LMA-1", REFUTED)])
    # BRN-2's own premise, BRN-1, has a verified step: what it waits on is the refuted lemma.
    assert refuted["BRN-2"] == (CONDITIONAL, [("LMA-1", REFUTED)])

    open_lemma = _states(dag, above)
    assert open_lemma["BRN-1"] == (CONDITIONAL, [("LMA-1", OBLIGATION)])

    proven = _states(dag, above + _pass(dag, "LMA-1"))
    assert {nid: state for nid, (state, _w) in proven.items()} == {"LMA-1": PROVEN, "BRN-1": PROVEN, "BRN-2": PROVEN}

    # Asked about one target, the steps beneath it are judged all the same.
    only = compute_consistency(dag, above + _pass(dag, "LMA-1", outcome="falsified"), targets=["BRN-2"])
    assert [(s.target_id, s.state) for s in only] == [("BRN-2", CONDITIONAL)]


def test_a_restatement_sets_aside_only_the_steps_that_read_it():
    """A trial vouches for one step: its claim from what its premises state. Restating the axiom
    stales the lemma that cites it and nothing above; restating the lemma's premises while keeping
    its statement leaves the branch that cites it current -- unless that branch's trials recorded
    only fingerprints, from before trials carried statements."""
    from consistency_belief.model import CONDITIONAL
    dag = _chain()
    trials = _pass(dag, "LMA-1") + _pass(dag, "BRN-1") + _pass(dag, "BRN-2")
    assert {s for s, _w in _states(dag, trials).values()} == {PROVEN}

    axiom_moved = _states(_chain(axiom="Inputs are sanitized and typed"), trials)
    assert axiom_moved["LMA-1"][0] == STALE
    assert axiom_moved["BRN-1"] == (CONDITIONAL, [("LMA-1", STALE)])
    assert axiom_moved["BRN-2"] == (CONDITIONAL, [("LMA-1", STALE)])

    # The lemma restated in its premises alone: its own trials go, the steps above keep theirs.
    resupported = _chain(lemma_premises=("AXM-1", "DEF-1"))
    after = compute_consistency(resupported, trials)
    by_id = {s.target_id: s for s in after}
    assert by_id["LMA-1"].state == OBLIGATION and by_id["LMA-1"].n_superseded == 3
    assert by_id["BRN-1"].state == CONDITIONAL and by_id["BRN-1"].n_trials == 3 and by_id["BRN-1"].n_stale == 0
    after_pass = _states(resupported, trials + _pass(resupported, "LMA-1"))
    assert {s for s, _w in after_pass.values()} == {PROVEN}, "re-proving the lemma alone discharges both branches"

    # Its statement restated: the branch that read the old one is set aside, however the lemma is proven.
    reworded = _chain(lemma="SQL injection impossible through the query layer")
    reworded_states = _states(reworded, trials + _pass(reworded, "LMA-1"))
    assert reworded_states["LMA-1"][0] == PROVEN and reworded_states["BRN-1"][0] == STALE
    assert reworded_states["BRN-2"] == (CONDITIONAL, [("BRN-1", STALE)])

    # Trials from before 0.7.8 recorded fingerprints only: a change to a cited premise's premises
    # sets them aside, since a fingerprint cannot say whether the statement moved.
    legacy = _pass(dag, "LMA-1") + _pass(dag, "BRN-1", record="fingerprints") + _pass(dag, "BRN-2", record="fingerprints")
    legacy_after = _states(resupported, legacy + _pass(resupported, "LMA-1"))
    assert legacy_after["BRN-1"][0] == STALE and legacy_after["BRN-2"] == (CONDITIONAL, [("BRN-1", STALE)])


def test_the_order_trials_arrive_in_decides_nothing():
    """The same trials in any order give the same states: a premise refuted after its dependents
    were verified reaches them on the next read."""
    dag = _chain()
    trials = _pass(dag, "BRN-2") + _pass(dag, "LMA-1", outcome="falsified") + _pass(dag, "BRN-1")
    states = [_states(dag, order) for order in (trials, list(reversed(trials)), trials[3:] + trials[:3])]
    assert states[0] == states[1] == states[2]
