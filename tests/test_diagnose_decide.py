"""Diagnosis ranking, decision policies, and round planning."""

from __future__ import annotations

from component_belief.declarations import load
from component_belief.decide import (
    ADOPT,
    CONDITIONAL,
    MORE_TESTING,
    REJECT,
    active_policy,
    decision_relevant,
    evaluate_policy,
)
from component_belief.diagnose import CONFIRMED, UNOBSERVED, diagnose
from component_belief.model import compute_slices
from component_belief.planning import plan_round
from conftest import trial


def prepare(repo, trials):
    decl = load(repo)
    slices = compute_slices(decl, trials)
    return decl, slices


def test_unobserved_component_with_no_test_limits_coverage(repo):
    """Rule 7.5 — when instrumentation is the binding constraint, no
    optimisation recommendation is produced at all."""
    trials = [trial(ik=True) for _ in range(30)]
    decl, slices = prepare(repo, trials)
    result = diagnose(decl, slices, trials)

    assert result.coverage_limited is True
    top = result.ranked[0]
    assert top.subject == "CMP-perception"
    assert top.status == UNOBSERVED
    assert "instrument" in result.recommendation
    assert "optimis" not in result.recommendation.replace("optimising any", "")
    assert "CMP-perception" in result.instrumentation_gaps


def test_refuted_slice_is_a_confirmed_failure(repo):
    trials = [trial(ik=False) for _ in range(30)]
    decl, slices = prepare(repo, trials)
    result = diagnose(decl, slices, trials)
    grasp = next(c for c in result.ranked if c.subject == "CMP-grasp")
    assert grasp.status == CONFIRMED
    assert grasp.evidence_ids == [] or grasp.evidence_ids


def test_upstream_of_a_failure_is_suspected_not_ignored(repo):
    trials = [trial(ik=False) for _ in range(30)]
    decl, slices = prepare(repo, trials)
    result = diagnose(decl, slices, trials)
    subjects = {c.subject: c.status for c in result.ranked}
    assert subjects["CMP-grasp"] == CONFIRMED
    # CMP-perception feeds CMP-grasp; it has no evidence of its own, so it
    # stays unobserved rather than being cleared by the downstream failure.
    assert subjects["CMP-perception"] == UNOBSERVED


def test_e2e_failure_alone_does_not_attribute_to_components(repo):
    """Rule 6.4 — a component with no local observation comes back unobserved,
    which is what drives the instrumentation recommendation."""
    decl, slices = prepare(repo, [])
    result = diagnose(decl, slices, [])
    assert all(c.status == UNOBSERVED for c in result.ranked)


class TestDecisionRelevance:
    """The §7 estimator: evaluate the policy at both interval endpoints."""

    def test_wide_interval_that_changes_the_decision_is_relevant(self, repo):
        trials = [trial(ik=True) for _ in range(3)] + [trial(ik=False)]
        decl, slices = prepare(repo, trials)
        policy = active_policy(decl)
        assert decision_relevant(decl, policy, slices, "CTR-grasp-reachable") is True

    def test_tight_interval_that_does_not_is_irrelevant(self, repo):
        """Well-measured and already decided: measuring again changes nothing,
        which is rule 8.3 made mechanical."""
        trials = [trial(ik=True) for _ in range(200)]
        decl, slices = prepare(repo, trials)
        policy = active_policy(decl)
        assert decision_relevant(decl, policy, slices, "CTR-grasp-reachable") is False

    def test_settled_failure_is_also_irrelevant(self, repo):
        trials = [trial(ik=False) for _ in range(200)]
        decl, slices = prepare(repo, trials)
        policy = active_policy(decl)
        assert decision_relevant(decl, policy, slices, "CTR-grasp-reachable") is False


class TestPolicy:
    def test_adopt_when_supported(self, repo):
        decl, slices = prepare(repo, [trial(ik=True) for _ in range(30)])
        assert evaluate_policy(decl, active_policy(decl), slices).status == ADOPT

    def test_reject_when_refuted_everywhere(self, repo):
        decl, slices = prepare(repo, [trial(ik=False) for _ in range(30)])
        assert evaluate_policy(decl, active_policy(decl), slices).status == REJECT

    def test_insufficient_cannot_satisfy_an_adopt_criterion(self, repo):
        """Declaring victory on n=2 is the likeliest failure of an
        agent-driven loop, so it gets its own status."""
        decl, slices = prepare(repo, [trial(ik=True), trial(ik=True)])
        verdict = evaluate_policy(decl, active_policy(decl), slices)
        assert verdict.status == MORE_TESTING
        assert any("trials" in m for m in verdict.missing)

    def test_buckets_that_disagree_return_an_envelope_not_an_average(self, repo):
        trials = [trial(ik=True, lighting="normal") for _ in range(20)]
        trials += [trial(ik=False, lighting="low") for _ in range(20)]
        decl, slices = prepare(repo, trials)
        verdict = evaluate_policy(decl, active_policy(decl), slices)
        assert verdict.status == CONDITIONAL
        assert any("normal" in c and "low" in c for c in verdict.conditions)

    def test_verdict_carries_its_evidence(self, repo):
        decl, slices = prepare(repo, [trial(ik=True) for _ in range(30)])
        verdict = evaluate_policy(decl, active_policy(decl), slices)
        assert len(verdict.evidence_ids) == 0 or verdict.evidence_ids
        assert verdict.policy_id == "POL-release"


class TestPlanning:
    def test_redundant_test_skipped_with_a_reason(self, repo):
        decl, slices = prepare(repo, [trial(ik=True) for _ in range(200)])
        plan = plan_round(decl, slices)
        assert plan["selected"] == []
        reasons = {item["reason"] for item in plan["skipped"]}
        assert "not_decision_relevant" in reasons

    def test_uncertain_test_is_selected(self, repo):
        decl, slices = prepare(repo, [trial(ik=True) for _ in range(3)] + [trial(ik=False)])
        plan = plan_round(decl, slices)
        assert [item["test_id"] for item in plan["selected"]] == ["TST-grasp-ik"]

    def test_every_skipped_test_is_listed(self, repo):
        """A round that quietly truncates reads as full coverage (8.6)."""
        decl, slices = prepare(repo, [trial(ik=True) for _ in range(200)])
        plan = plan_round(decl, slices)
        listed = {item["test_id"] for item in plan["skipped"]}
        assert "TST-grasp-ik" in listed
        assert any("CMP-perception" in item["test_id"] for item in plan["skipped"])

    def test_mandatory_gate_runs_regardless_of_information_gain(self, repo):
        from conftest import git
        yaml = (repo / "belief.yaml").read_text().replace(
            "    capture: [lighting, model_revision]",
            "    capture: [lighting, model_revision]\n    mandatory: true",
        )
        (repo / "belief.yaml").write_text(yaml, encoding="utf-8")
        git(repo, "add", "belief.yaml")
        git(repo, "commit", "-q", "-m", "gate")
        decl, slices = prepare(repo, [trial(ik=True) for _ in range(200)])
        plan = plan_round(decl, slices)
        assert [item["test_id"] for item in plan["mandatory"]] == ["TST-grasp-ik"]
        assert plan["mandatory"][0]["reason"] == "mandatory_gate"

    def test_budget_exhaustion_is_reported_not_silent(self, repo):
        decl, slices = prepare(repo, [trial(ik=True) for _ in range(3)] + [trial(ik=False)])
        plan = plan_round(decl, slices, budget=0.5)
        assert plan["selected"] == []
        assert any(item["reason"] == "over_budget" for item in plan["skipped"])


def test_contract_gated_only_by_safety_gates_is_decision_relevant(repo):
    """A contract reachable only through `safety_gates` — never named in a
    `slice:` criterion — must still count as decision-relevant when unmeasured.
    Scanning criteria for a slice key missed it; going through the policy
    does not."""
    from conftest import git
    yaml = (repo / "belief.yaml").read_text(encoding="utf-8")
    yaml = yaml.replace(
        "    capture: [lighting, model_revision]",
        "    capture: [lighting, model_revision]\n    mandatory: true",
    ).replace(
        "      - {slice: CTR-grasp-reachable, require: supported}",
        "      - {safety_gates: all_passed}",
    )
    (repo / "belief.yaml").write_text(yaml, encoding="utf-8")
    git(repo, "add", "belief.yaml")
    git(repo, "commit", "-q", "-m", "gate only")

    decl, slices = prepare(repo, [])
    policy = active_policy(decl)
    assert not any(c.get("slice") for c in policy.criteria), "gated only via safety_gates"
    assert decision_relevant(decl, policy, slices, "CTR-grasp-reachable") is True


def test_contested_is_more_testing_not_reject(repo):
    """An unproven claim is not a disproved one. Both block adoption, but
    reporting `reject` sends someone to fix code that may be fine."""
    trials = [trial(ik=True) for _ in range(14)] + [trial(ik=False)]
    decl, slices = prepare(repo, trials)
    assert slices[0].state == "contested"
    verdict = evaluate_policy(decl, active_policy(decl), slices)
    assert verdict.status == MORE_TESTING
    assert any("straddles" in r for r in verdict.reasons)


def test_unproven_safety_gate_is_more_testing_refuted_gate_is_reject(repo):
    from conftest import git
    yaml = (repo / "belief.yaml").read_text(encoding="utf-8").replace(
        "    capture: [lighting, model_revision]",
        "    capture: [lighting, model_revision]\n    mandatory: true",
    )
    (repo / "belief.yaml").write_text(yaml, encoding="utf-8")
    git(repo, "add", "belief.yaml")
    git(repo, "commit", "-q", "-m", "gate")

    decl, unproven = prepare(repo, [trial(ik=True) for _ in range(14)] + [trial(ik=False)])
    assert evaluate_policy(decl, active_policy(decl), unproven).status == MORE_TESTING

    decl, refuted = prepare(repo, [trial(ik=False) for _ in range(30)])
    assert evaluate_policy(decl, active_policy(decl), refuted).status == REJECT
