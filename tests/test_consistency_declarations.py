"""Tests for consistency declarations and git-HEAD loading discipline."""

from __future__ import annotations

from pathlib import Path
import pytest

from consistency_belief.declarations import Declarations, _parse, load
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
