"""Tests for the Proof DAG kernel: acyclicity, grounding, and blast-radius."""

from __future__ import annotations

import pytest

from consistency_belief.graph import ProofDAG, ProofNode


@pytest.fixture
def sample_dag() -> ProofDAG:
    dag = ProofDAG()
    dag.add_node(ProofNode("AXM-1", kind="axiom", statement="Axiom 1"))
    dag.add_node(ProofNode("AXM-2", kind="axiom", statement="Axiom 2"))
    dag.add_node(ProofNode("DEF-1", kind="definition", statement="Def 1"))
    dag.add_node(ProofNode("LMA-1", kind="lemma", statement="Lemma 1", premises=["AXM-1", "DEF-1"]))
    dag.add_node(ProofNode("LMA-2", kind="lemma", statement="Lemma 2", premises=["AXM-2", "LMA-1"]))
    dag.add_node(ProofNode("BRN-1", kind="branch", statement="Branch 1", premises=["LMA-2"]))
    return dag


def test_ancestors_and_descendants(sample_dag: ProofDAG):
    anc = sample_dag.ancestors("BRN-1")
    assert anc == {"LMA-2", "LMA-1", "AXM-1", "AXM-2", "DEF-1"}

    desc = sample_dag.descendants("AXM-1")
    assert desc == {"LMA-1", "LMA-2", "BRN-1"}

    roots = sample_dag.roots()
    assert roots == {"AXM-1", "AXM-2", "DEF-1"}


def test_axiomatic_basis(sample_dag: ProofDAG):
    basis = sample_dag.axiomatic_basis("BRN-1")
    assert basis == {"AXM-1", "AXM-2"}


def test_grounding_check(sample_dag: ProofDAG):
    grounded, issues = sample_dag.is_grounded("BRN-1")
    assert grounded is True
    assert issues == []

    # Add ungrounded node with floating premise
    sample_dag.add_node(ProofNode("HYP-1", kind="lemma", statement="Floating hypothesis", premises=[]))
    sample_dag.add_node(ProofNode("BRN-floating", kind="branch", statement="Floating branch", premises=["HYP-1"]))
    
    grounded, issues = sample_dag.is_grounded("BRN-floating")
    assert grounded is False
    assert any("HYP-1" in iss for iss in issues)


def test_acyclicity_rejection(sample_dag: ProofDAG):
    # Attempt direct cycle: LMA-1 depends on BRN-1 (which depends on LMA-2 which depends on LMA-1)
    errors = sample_dag.add_node(ProofNode("BRN-cycle", kind="branch", premises=["BRN-1"]))
    assert errors == []

    # Now try to make AXM-1 depend on BRN-cycle
    cycle_errors = sample_dag.add_node(ProofNode("LMA-back", kind="lemma", premises=["BRN-cycle"]))
    assert cycle_errors == []

    # Try to add a node that loops
    errors = sample_dag.add_node(ProofNode("LMA-1", kind="lemma", premises=["LMA-back"]))
    assert any("cycle" in e for e in errors)


def test_blast_radius_topological_ordering(sample_dag: ProofDAG):
    # If AXM-1 is modified, its blast radius must be topologically ordered
    radius = sample_dag.blast_radius("AXM-1")
    assert radius == ["LMA-1", "LMA-2", "BRN-1"]

    # If LMA-2 is modified
    radius_lma2 = sample_dag.blast_radius("LMA-2")
    assert radius_lma2 == ["BRN-1"]

    # If leaf node is modified
    assert sample_dag.blast_radius("BRN-1") == []


def test_declarations_join_in_dependency_order_not_file_order():
    """A branch may be declared above the branch it cites; where it sits in the file is not a
    fact about the proof."""
    from consistency_belief.declarations import Branch, Declarations, Axiom

    decl = Declarations()
    decl.axioms["AXM-root"] = Axiom(id="AXM-root", statement="root", rationale="r")
    decl.branches["BRN-child"] = Branch(id="BRN-child", statement="child", premises=["BRN-parent"],
                                        derivation_rule="d", subject="CMP-x")
    decl.branches["BRN-parent"] = Branch(id="BRN-parent", statement="parent", premises=["AXM-root"],
                                         derivation_rule="d", subject="CMP-x")
    dag = ProofDAG.from_declarations(decl)
    assert set(dag.nodes) == {"AXM-root", "BRN-parent", "BRN-child"}
    assert dag.ancestors("BRN-child") == {"BRN-parent", "AXM-root"}


def test_a_node_citing_itself_is_refused(sample_dag: ProofDAG):
    """A new node that cites itself cites a node not yet in the graph; a restated node that cites
    itself would be a self-loop. Both are refused, so no edge is ever a self-loop."""
    new = sample_dag.add_node(ProofNode("LMA-self", kind="lemma", premises=["AXM-1", "LMA-self"]))
    assert any("unknown premise 'LMA-self'" in e for e in new)
    assert "LMA-self" not in sample_dag.nodes

    restated = sample_dag.add_node(ProofNode("LMA-1", kind="lemma", premises=["AXM-1", "LMA-1"]))
    assert any("cycle" in e for e in restated)
    assert sample_dag.parents["LMA-1"] == {"AXM-1", "DEF-1"}, "a refused restatement changes nothing"


def test_a_node_stays_in_the_graph_only_while_its_premises_do():
    """Remove a declaration and every node that depends on it stays out of the graph, however
    deep; a node that does not depend on it is untouched."""
    from consistency_belief.declarations import Axiom, Branch, Declarations, Lemma

    decl = Declarations()
    decl.axioms["AXM-kept"] = Axiom(id="AXM-kept", statement="kept", rationale="r")
    decl.lemmas["LMA-orphan"] = Lemma(id="LMA-orphan", statement="o",
                                      premises=["AXM-kept", "AXM-removed"], derivation_rule="d")
    decl.branches["BRN-deep"] = Branch(id="BRN-deep", statement="b", premises=["LMA-orphan"],
                                       derivation_rule="d", subject="CMP-x")
    decl.branches["BRN-fine"] = Branch(id="BRN-fine", statement="f", premises=["AXM-kept"],
                                       derivation_rule="d", subject="CMP-x")
    dag = ProofDAG.from_declarations(decl)
    assert set(dag.nodes) == {"AXM-kept", "BRN-fine"}
