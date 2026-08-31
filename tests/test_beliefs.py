"""The belief layer: what can move a posterior, and what provably cannot."""

from __future__ import annotations

from component_belief.declarations import load
from component_belief.model import (
    STATE_INSUFFICIENT,
    STATE_REFUTED,
    STATE_SUPPORTED,
    compare,
    compute_slices,
)
from component_belief.store import Store
from conftest import trial


def slices_for(repo, trials):
    return compute_slices(load(repo), trials)


def test_asserted_evidence_can_never_move_a_posterior(repo):
    """Rule 10.4, enforced structurally rather than by instruction."""
    measured = [trial(ik=True) for _ in range(6)]
    with_assertions = measured + [trial(ik=False, provenance="asserted") for _ in range(50)]

    base = slices_for(repo, measured)
    polluted = slices_for(repo, with_assertions)

    assert len(base) == len(polluted) == 1
    assert base[0].point == polluted[0].point
    assert base[0].n_valid == polluted[0].n_valid == 6


def test_note_channel_creates_no_evidence(repo):
    store = Store(repo)
    store.append_note("CMP-grasp", "felt jittery on the bench")
    assert store.effective_trials() == []
    assert len(store.notes("CMP-grasp")) == 1


def test_insufficient_evidence_is_a_state_not_a_low_number(repo):
    """Two passing trials must not present as a verdict (5.7)."""
    slices = slices_for(repo, [trial(ik=True), trial(ik=True)])
    assert slices[0].state == STATE_INSUFFICIENT
    assert slices[0].missing["trials_needed"] == 2
    assert slices[0].point > 0.5, "the estimate exists; it just cannot be a verdict"


def test_supported_and_refuted(repo):
    supported = slices_for(repo, [trial(ik=True) for _ in range(30)])
    assert supported[0].state == STATE_SUPPORTED
    refuted = slices_for(repo, [trial(ik=False) for _ in range(30)])
    assert refuted[0].state == STATE_REFUTED


def test_incompatible_evidence_is_never_pooled(repo):
    """Trials differing on a declared compatibility key land in separate
    slices (5.6). Pooling these would average a working revision with a broken
    one and report the mean as the system's health."""
    trials = [trial(ik=True, model_revision="v3") for _ in range(30)]
    trials += [trial(ik=False, model_revision="v4") for _ in range(30)]
    slices = slices_for(repo, trials)

    assert len(slices) == 2
    assert len({s.compat_group for s in slices}) == 2
    by_group = {s.compat_group: s for s in slices}
    assert sorted((s.passes, s.fails) for s in by_group.values()) == [(0, 30), (30, 0)]
    assert {s.state for s in slices} == {STATE_SUPPORTED, STATE_REFUTED}


def test_declared_buckets_partition_evidence(repo):
    trials = [trial(ik=True, lighting="normal") for _ in range(30)]
    trials += [trial(ik=False, lighting="low") for _ in range(30)]
    slices = slices_for(repo, trials)
    buckets = {s.bucket: s.state for s in slices}
    assert buckets == {"normal": STATE_SUPPORTED, "low": STATE_REFUTED}


def test_unmatched_conditions_land_unbucketed(repo):
    slices = slices_for(repo, [trial(ik=True, lighting="strobe") for _ in range(6)])
    assert slices[0].bucket == "unbucketed"


def test_invalid_trials_are_excluded_but_retained(repo):
    """A trial that failed because the rig was mis-calibrated is not evidence
    against the component (3.6). The posterior must be identical to the one
    computed without those trials present at all."""
    valid = [trial(ik=True) for _ in range(30)]
    with_invalid = valid + [trial(ik=False, validity="invalid") for _ in range(20)]

    clean = slices_for(repo, valid)[0]
    mixed = slices_for(repo, with_invalid)[0]

    assert mixed.n_valid == clean.n_valid == 30
    assert mixed.n_invalid == 20 and clean.n_invalid == 0
    assert mixed.point == clean.point
    assert mixed.state == clean.state == STATE_SUPPORTED


def test_missing_metrics_excluded_not_scored_off_exit_code(repo):
    """A quiet fallback to the runner's outcome is how an unmeasured thing
    starts looking measured. It must be excluded with a reason instead."""
    trials = [trial(ik=True) for _ in range(4)]
    trials += [trial(metrics={}, outcome="pass") for _ in range(4)]
    slices = slices_for(repo, trials)
    assert slices[0].n_valid == 4
    assert slices[0].n_excluded == 4
    assert slices[0].exclusions == {"missing_metrics": 4}


def test_set_hash_is_stable_and_order_independent(repo):
    """The same evidence set must always cite as the same handle, whatever
    order it was read in."""
    trials = [trial(ik=True) for _ in range(6)]
    a = slices_for(repo, trials)[0]
    b = slices_for(repo, list(reversed(trials)))[0]
    assert a.set_hash == b.set_hash


def test_set_hash_changes_when_the_evidence_set_changes(repo):
    six = [trial(ik=True) for _ in range(6)]
    a = slices_for(repo, six)[0]
    b = slices_for(repo, six + [trial(ik=False)])[0]
    assert a.set_hash != b.set_hash, "a citation must not survive its evidence changing"


def test_regression_only_across_compatible_slices(repo):
    before = slices_for(repo, [trial(ik=True, model_revision="v3") for _ in range(30)])
    after = slices_for(repo, [trial(ik=False, model_revision="v3") for _ in range(30)])
    result = compare(before, after)
    assert len(result["regressions"]) == 1
    assert result["not_comparable"] == []


def test_hardware_swap_reports_not_comparable_not_no_regression(repo):
    """The reading that lets a real regression hide behind a hardware swap."""
    before = slices_for(repo, [trial(ik=True, model_revision="v3") for _ in range(30)])
    after = slices_for(repo, [trial(ik=False, model_revision="v9") for _ in range(30)])
    result = compare(before, after)
    assert result["regressions"] == []
    assert len(result["not_comparable"]) == 1
    assert result["not_comparable"][0]["differing_fields"] == ["model_revision"]


def test_amendment_folds_over_the_original(repo):
    store = Store(repo)
    ids = store.append_trials([trial(ik=True) for _ in range(3)])
    store.append_amendment(ids[0], validity="invalid", reason="rig was mis-calibrated")

    folded = {t["id"]: t for t in store.effective_trials()}
    assert folded[ids[0]]["validity"] == "invalid"
    assert folded[ids[0]]["validity_reason"] == "rig was mis-calibrated"
    assert folded[ids[1]]["validity"] == "valid"

    raw = [r for r in store.raw_records() if r.get("kind") == "trial"]
    assert all(r["validity"] == "valid" for r in raw), "the original record is never edited"
    assert any(r.get("kind") == "amendment" for r in store.raw_records())


def test_prior_is_named_in_the_slice(repo):
    from conftest import git
    yaml = (repo / "belief.yaml").read_text() + """
priors:
  - contract: CTR-grasp-reachable
    alpha: 8
    beta: 2
    rationale: prior generation shipped at ~0.8
"""
    (repo / "belief.yaml").write_text(yaml, encoding="utf-8")
    git(repo, "add", "belief.yaml")
    git(repo, "commit", "-q", "-m", "prior")
    slices = slices_for(repo, [trial(ik=True) for _ in range(6)])
    assert slices[0].prior_id == "PRI-CTR-grasp-reachable"
    assert slices[0].alpha == 8 + 6
