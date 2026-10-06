"""Tests for consistency declarations and git-HEAD loading discipline."""

from __future__ import annotations

from pathlib import Path
import pytest

from consistency_belief.declarations import Declarations, Reference, _parse, load
from consistency_belief.graph import ProofDAG
from consistency_belief.model import PROVEN, compute_consistency
from consistency_belief.probes import PROBE_STRATEGIES, probe_text
from conftest import git

VALID_CONSISTENCY_YAML = """
axioms:
  - id: AXM-safety
    domain: safety
    statement: The robot must not collide.
    rationale: Core physical safety invariant.

definitions:
  - id: DEF-distance
    term: Distance
    meaning: Euclidean clearance in metres.

lemmas:
  - id: LMA-clearance
    statement: Clearance must exceed 0.5m.
    premises: [AXM-safety, DEF-distance]
    derivation_rule: Margin calculation

branches:
  - id: BRN-motion-gate
    subject: CMP-motion
    claim_type: contract
    statement: Abort trajectory if clearance < 0.5m.
    premises: [LMA-clearance]
    derivation_rule: Direct contract specification
"""


def test_parse_valid_yaml():
    decl = _parse(VALID_CONSISTENCY_YAML)
    assert len(decl.axioms) == 1
    assert len(decl.definitions) == 1
    assert len(decl.lemmas) == 1
    assert len(decl.branches) == 1
    assert decl.issues == []


def test_validation_detects_empty_axiom():
    bad_yaml = """
axioms:
  - id: AXM-empty
    statement: ""
    rationale: ""
"""
    decl = _parse(bad_yaml)
    codes = [i.code for i in decl.issues]
    assert "EMPTY_AXIOM" in codes
    assert "MISSING_RATIONALE" in codes


def test_validation_detects_unknown_premise():
    bad_yaml = """
axioms:
  - id: AXM-1
    statement: Ok
    rationale: Ok

lemmas:
  - id: LMA-1
    statement: Sub-claim
    premises: [AXM-1, AXM-ghost]
    derivation_rule: math
"""
    decl = _parse(bad_yaml)
    codes = [i.code for i in decl.issues]
    assert "UNKNOWN_PREMISE" in codes


def test_validation_detects_circular_declarations():
    bad_yaml = """
axioms:
  - id: AXM-1
    statement: Ok
    rationale: Ok

lemmas:
  - id: LMA-A
    statement: A
    premises: [AXM-1, LMA-B]
    derivation_rule: rule1

  - id: LMA-B
    statement: B
    premises: [LMA-A]
    derivation_rule: rule2
"""
    decl = _parse(bad_yaml)
    codes = [i.code for i in decl.issues]
    assert "CIRCULAR_DEPENDENCY" in codes


def test_git_head_loading_and_pending_drift(empty_repo):
    # 1. Uncommitted file in working tree
    (empty_repo / "consistency.yaml").write_text(VALID_CONSISTENCY_YAML, encoding="utf-8")
    decl = load(empty_repo)
    assert decl.source == "none"
    assert any(i.code == "UNCOMMITTED" for i in decl.issues)

    # 2. Commit to git HEAD
    git(empty_repo, "add", "consistency.yaml")
    git(empty_repo, "commit", "-q", "-m", "add consistency declarations")
    committed = load(empty_repo)
    assert committed.source == "git-HEAD"
    assert committed.pending is False
    assert "AXM-safety" in committed.axioms

    # 3. Modify working tree without committing -> PENDING
    (empty_repo / "consistency.yaml").write_text(
        VALID_CONSISTENCY_YAML.replace("0.5m", "0.1m"), encoding="utf-8"
    )
    drift = load(empty_repo)
    assert drift.source == "git-HEAD"
    assert drift.pending is True
    assert any(i.code == "PENDING" for i in drift.issues)
    assert drift.lemmas["LMA-clearance"].statement == "Clearance must exceed 0.5m."


def test_a_malformed_entry_is_reported_and_left_out_of_the_graph():
    decl = _parse("axioms:\n  - AXM-bare\n  - {id: AXM-a, statement: s, rationale: r}\n"
                  "components: [3, CMP-x]\npolicies:\n  - {id: POL-a, criteria: [BRN-a]}\n")
    assert set(decl.axioms) == {"AXM-a"} and set(decl.governs) == {"CMP-x"}
    assert [i.code for i in decl.issues].count("MALFORMED") == 3
    assert decl.policies["POL-a"].criteria == []


# The same declarations, citing a source from the axiom and the lemma.
REFERENCED_YAML = VALID_CONSISTENCY_YAML.replace(
    "    rationale: Core physical safety invariant.\n",
    "    rationale: Core physical safety invariant.\n"
    "    references: [{source: SRC-robot-safety, at: \"sec. 5.10\"}]\n",
).replace(
    "    derivation_rule: Margin calculation\n",
    "    derivation_rule: Margin calculation\n    references: [SRC-robot-safety]\n",
) + """
sources:
  - id: SRC-robot-safety
    title: Safety requirements for industrial robots
    authors: [A. Author, B. Author]
    year: 2011
    url: https://example.org/robot-safety
"""


class TestSourceReferences:
    def test_references_change_no_graph_fingerprint_proof_state_or_probe(self):
        plain, cited = _parse(VALID_CONSISTENCY_YAML), _parse(REFERENCED_YAML)
        assert cited.issues == []
        assert cited.axioms["AXM-safety"].references == [Reference("SRC-robot-safety", "sec. 5.10")]
        assert cited.lemmas["LMA-clearance"].references == [Reference("SRC-robot-safety")]

        a, b = ProofDAG.from_declarations(plain), ProofDAG.from_declarations(cited)
        assert set(a.nodes) == set(b.nodes) and a.parents == b.parents
        assert {n: x.fingerprint() for n, x in a.nodes.items()} == {n: x.fingerprint() for n, x in b.nodes.items()}

        # Trials recorded against the uncited graph count, unchanged, against the cited one.
        trials = [{"id": f"TRL-{target}-{strategy}", "target_id": target, "validity": "valid", "passed": True,
                   "outcome": "sound", "strategy": strategy, "actor": "agent",
                   "statement_sha": a.nodes[target].fingerprint(), "basis": a.basis_fingerprints(target)}
                  for target in ("LMA-clearance", "BRN-motion-gate") for strategy in PROBE_STRATEGIES]
        def states(dag: ProofDAG) -> list[tuple]:
            return [(s.target_id, s.state, s.n_independent, s.trial_ids) for s in compute_consistency(dag, trials)]

        assert states(a) == states(b) and {s[1] for s in states(b)} == {PROVEN}

        for nid in ("LMA-clearance", "BRN-motion-gate"):
            assert probe_text(a, nid) == probe_text(b, nid)
            assert "SRC-" not in probe_text(b, nid) and "industrial robots" not in probe_text(b, nid)

        # Whatever its id, a source is no candidate for the graph and displaces none.
        clash = _parse(REFERENCED_YAML + "  - {id: LMA-clearance, title: A source sharing a lemma's id}\n")
        c = ProofDAG.from_declarations(clash)
        assert c.nodes["LMA-clearance"].kind == "lemma" and c.parents == a.parents
        assert {n: x.fingerprint() for n, x in c.nodes.items()} == {n: x.fingerprint() for n, x in a.nodes.items()}
        assert states(c) == states(a) and probe_text(c, "BRN-motion-gate") == probe_text(a, "BRN-motion-gate")

    def test_a_dangling_reference_and_an_unreferenced_source_are_reported(self):
        decl = _parse(REFERENCED_YAML.replace("references: [SRC-robot-safety]", "references: [SRC-missing]")
                      + "  - {id: SRC-unused, title: A work nothing references}\n")
        found = {(i.code, i.subject) for i in decl.issues}
        assert found == {("DANGLING_REFERENCE", "LMA-clearance"), ("UNREFERENCED_SOURCE", "SRC-unused")}
        assert "SRC-missing" in next(i.message for i in decl.issues if i.code == "DANGLING_REFERENCE")
        # A broken reference is a broken record for the reader, never a broken claim.
        assert decl.is_valid_node("LMA-clearance")

    def test_a_malformed_source_or_reference_is_reported(self):
        decl = _parse(REFERENCED_YAML.replace(
            "references: [SRC-robot-safety]",
            "references: [{source: SRC-robot-safety, at: Thm 2, p. 3}, 3]",
        ) + "  - {id: SRC-untitled, url: \"javascript:alert(1)\"}\n"
            "definitions_note: ignored\n")
        codes = sorted(i.code for i in decl.issues)
        assert codes == ["MALFORMED_REFERENCE", "MALFORMED_REFERENCE", "UNREFERENCED_SOURCE", "UNTITLED_SOURCE"]
        assert decl.lemmas["LMA-clearance"].references == [Reference("SRC-robot-safety", "Thm 2")]
        assert decl.sources["SRC-untitled"].identifiers() == [("url", "javascript:alert(1)", "")]

    def test_a_source_reads_as_a_reference_list_entry(self):
        src = _parse(REFERENCED_YAML).sources["SRC-robot-safety"]
        assert src.entry() == ("A. Author, B. Author (2011). Safety requirements for industrial robots. "
                               "url:https://example.org/robot-safety")
        assert src.identifiers() == [("url", "https://example.org/robot-safety", "https://example.org/robot-safety")]
        arxiv = _parse("sources:\n  - {id: SRC-a, title: T, arxiv: \"2210.02747\"}\n").sources["SRC-a"]
        assert arxiv.identifiers() == [("arxiv", "2210.02747", "https://arxiv.org/abs/2210.02747")]

