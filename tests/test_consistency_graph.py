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
