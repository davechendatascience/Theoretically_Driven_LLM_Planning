"""The kernel's own tests. Each maps to a claim in docs/redesign.md."""

from pathlib import Path

import pytest

from kernel import (
    Change, Constraint, Expectation, Given, Goal, Store,
    Unfalsifiable, admit, can_fail, check_all, evaluate, migrate,
    next_action, open_constraints, prior_check, reduce_universal,
)
from kernel.grammar import freeze, revised
from kernel.invariants import i1_citation_required, i5_every_field_has_a_reader

PKG = Path(__file__).resolve().parents[2] / "src" / "kernel"


# --- the central rule: no expectation that cannot fail --------------------

def test_range_without_bounds_is_refused():
    e = Expectation(id="E1", change_id="C1", form="range", metric_id="ops", instrument="pytest")
    ok, reason = can_fail(e)
    assert not ok and "no bounds" in reason
    with pytest.raises(Unfalsifiable):
        admit(e)


def test_invariance_without_baseline_is_refused():
    """v1's live defect: no_change with expected_range null."""
    e = Expectation(id="E2", change_id="C1", form="invariance", metric_id="ops", instrument="pytest")
    ok, reason = can_fail(e)
    assert not ok and "baseline" in reason


def test_admissible_forms_are_admitted():
    for e in [
        Expectation(id="a", change_id="C", form="range", metric_id="m", lo=1, hi=2, instrument="pytest"),
        Expectation(id="b", change_id="C", form="invariance", metric_id="m", baseline=0, instrument="pytest"),
        Expectation(id="c", change_id="C", form="golden", unit_ref="u", inputs=["i"], golden_ref="g", instrument="pytest"),
        Expectation(id="d", change_id="C", form="exit", command="pytest", instrument="pytest"),
        Expectation(id="e", change_id="C", form="witness", inputs=["z"], expected_output="y", instrument="pytest"),
        Expectation(id="f", change_id="C", form="membership", allowed_set=["a.py"], instrument="pytest"),
    ]:
        assert can_fail(e)[0], e.form
        assert admit(e).frozen_hash


def test_universal_claim_needs_witnesses():
    """E7 is undecidable; it is admitted only after reduction."""
    with pytest.raises(Unfalsifiable):
        reduce_universal("F never returns null for class X", [])
    reduced = reduce_universal("F never returns null", [("z1", "0"), ("z2", "0")])
    assert len(reduced) == 2
    assert all(r["form"] == "witness" for r in reduced)
    for r in reduced:
        assert can_fail(Expectation(id="w", change_id="C", **{
            k: v for k, v in r.items() if k != "rationale"}, instrument="pytest"))[0]


def test_empty_range_is_refused_too():
    e = Expectation(id="x", change_id="C", form="range", metric_id="m", lo=5, hi=1, instrument="pytest")
    assert not can_fail(e)[0]


# --- polarity is derived, never stored ------------------------------------

def test_polarity_is_derived():
    e = Expectation(id="E", change_id="C", form="range", metric_id="m", lo=0, hi=10, instrument="pytest")
    assert evaluate(e, 5) == "match"
    assert evaluate(e, 11) == "miss"
    assert evaluate(e, None) == "inconclusive"
    assert not hasattr(e, "polarity")


def test_membership_detects_out_of_scope_write():
    e = Expectation(id="E", change_id="C", form="membership", allowed_set=["a.py", "b.py"], instrument="git")
    assert evaluate(e, ["a.py"]) == "match"
    assert evaluate(e, ["a.py", "c.py"]) == "miss"


# --- tamper evidence ------------------------------------------------------

def test_revision_after_freeze_is_visible():
    e = admit(Expectation(id="E", change_id="C", form="range", metric_id="m", lo=0, hi=10, instrument="pytest"))
    assert not revised(e)
    moved = e.model_copy(update={"hi": 999})
    assert revised(moved), "moving a band after freezing must be detectable"


# --- ordering is total and shuffle-invariant ------------------------------

def test_order_is_deterministic_under_shuffle():
    import random
    cs = [
        Constraint(id=f"C-{i}", statement="s", severity=sev, status=st)
        for i, (sev, st) in enumerate(
            [("high", "unknown"), ("critical", "unsat"), ("low", "unknown"), ("high", "unsat")]
        )
    ]
    expected = [c.id for c in open_constraints(cs)]
    for seed in range(100):
        shuffled = cs[:]
        random.Random(seed).shuffle(shuffled)
        assert [c.id for c in open_constraints(shuffled)] == expected


def test_next_action_is_lexicographic():
    crit = Constraint(id="C1", statement="s", severity="critical", status="unsat")
    unk = Constraint(id="C2", statement="s", severity="high", status="unknown")
    ok = Constraint(id="C3", statement="s", status="sat", citations=["EV-1"])
    assert next_action([crit], []) == "rollback"
    assert next_action([unk], []) == "measure"
    assert next_action([ok], []) == "stop"
    draft = Change(id="CH1", title="t", status="draft", allowed_files=["a.py"])
    assert next_action([ok], [draft]) == "authorise"


# --- invariants -----------------------------------------------------------

def test_not_applicable_now_requires_a_citation():
    """The v1 escape: N/A overrode UNKNOWN and its evidence was never read."""
    bad = Constraint(id="C1", statement="s", status="not_applicable")
    good = Constraint(id="C2", statement="s", status="not_applicable", citations=["EV-1"])
    assert i1_citation_required([bad])
    assert not i1_citation_required([good])


def test_i5_flags_a_field_nothing_reads():
    assert i5_every_field_has_a_reader(PKG) == [], (
        "the kernel must not ship a computed field with no reader"
    )


def test_check_all_composes():
    v = check_all(
        constraints=[Constraint(id="C", statement="s", status="sat")],
        givens=[], changes=[Change(id="CH", title="t", status="authorised")],
        expectations=[Expectation(id="E", change_id="CH", form="range")],
        seqs=[1, 2, 2],
    )
    kinds = {x.invariant for x in v}
    assert kinds == {"I1", "I2", "I3", "I4"}


# --- prior check: unsatisfiable before data exists ------------------------

def test_prior_check_catches_impossible_bands():
    es = [
        Expectation(id="a", change_id="C", form="range", metric_id="total", lo=0, hi=1, instrument="pytest"),
        Expectation(id="b", change_id="C", form="range", metric_id="x", lo=10, hi=20, instrument="pytest"),
        Expectation(id="c", change_id="C", form="range", metric_id="y", lo=10, hi=20, instrument="pytest"),
    ]
    assert prior_check(es, ["total = x + y"]).status == "unsatisfiable"
    assert prior_check(es, []).status == "satisfiable"
    assert prior_check(es, ["nonsense"]).status == "inconclusive"


# --- goals carry a typed distance ----------------------------------------

def test_goal_distance_is_arithmetic():
    g = Goal(id="G", statement="s", metric_name="m", baseline=2, target=5)
    assert g.distance(3) == 2
    assert g.is_met(5) is True
    assert g.is_met(4) is False
    assert g.is_met(None) is None
    assert "met" not in Goal.model_fields


# --- migration ------------------------------------------------------------

def test_migrates_a_real_v1_store(tmp_path: Path):
    from plan_auto.config import resolve_data_dir
    src = resolve_data_dir(Path("/home/edge-host/Documents/GitHub/robot-navigation-planning"))
    if not src.exists():
        pytest.skip("live store not present")
    data, rep = migrate(src)
    assert rep.lossless
    assert rep.changes > 0 and rep.goals > 0
    st = Store(tmp_path)
    for name, items in data.items():
        st.save(name, items)
        assert len(st.load(name)) == len(items)


def test_unfailable_predictions_become_intents_not_expectations(tmp_path: Path):
    import json
    (tmp_path / "plans").mkdir(parents=True)
    (tmp_path / "plans" / "P.json").write_text(json.dumps({
        "id": "P-1", "title": "t", "status": "validated",
        "validation_steps": [{"id": "V-1", "command": "uv run pytest -q"}],
        "predictive_contract": {"predictions": [
            {"id": "PR-1", "metric_id": "m", "direction": "increase",
             "expected_range": None, "expected_pattern": ""},
            {"id": "PR-2", "metric_id": "n", "direction": "no_change",
             "expected_range": [0, 0]},
        ]},
    }))
    data, rep = migrate(tmp_path)
    assert rep.intents == 1 and rep.expectations == 1
    assert all(can_fail(e)[0] for e in data["expectations"])


def test_evidence_without_an_expectation_becomes_a_given(tmp_path: Path):
    import json
    (tmp_path / "evidence").mkdir(parents=True)
    (tmp_path / "evidence" / "EV.json").write_text(json.dumps({
        "id": "EV-1", "summary": "a test passed", "polarity": "supports",
        "observations": [], "linked_plan_id": None,
    }))
    data, rep = migrate(tmp_path)
    assert rep.outcomes == 0 and rep.givens == 1
    g = data["givens"][0]
    assert g.asserted_polarity == "supports" and g.verified is False
