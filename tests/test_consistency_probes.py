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
