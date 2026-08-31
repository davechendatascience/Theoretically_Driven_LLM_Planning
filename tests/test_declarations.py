"""Declaration loading and validation — the gate that runs before any evidence."""

from __future__ import annotations

import pytest

from component_belief.declarations import load
from component_belief.expr import ExprError, evaluate_bool, referenced_names
from conftest import git


def test_loads_from_git_head(repo):
    decl = load(repo)
    assert decl.source == "git-HEAD"
    assert set(decl.components) == {"CMP-perception", "CMP-grasp"}
    assert decl.is_scorable("CTR-grasp-reachable")


def test_working_tree_edits_do_not_take_effect(repo):
    """The whole approval gate: an agent editing belief.yaml changes nothing
    until a human commits."""
    original = load(repo)
    assert original.contracts["CTR-grasp-reachable"].target_rate == 0.8

    (repo / "belief.yaml").write_text(
        (repo / "belief.yaml").read_text().replace("target_rate: 0.8", "target_rate: 0.1"),
        encoding="utf-8",
    )
    after = load(repo)
    assert after.contracts["CTR-grasp-reachable"].target_rate == 0.8, \
        "uncommitted threshold change must not take effect"
    assert after.pending is True
    assert any(i.code == "PENDING" for i in after.issues)

    git(repo, "add", "belief.yaml")
    git(repo, "commit", "-q", "-m", "lower the bar")
    committed = load(repo)
    assert committed.contracts["CTR-grasp-reachable"].target_rate == 0.1
    assert committed.pending is False


def test_uncommitted_file_is_not_in_effect(empty_repo):
    (empty_repo / "belief.yaml").write_text("components: []\n", encoding="utf-8")
    decl = load(empty_repo)
    assert decl.source == "none"
    assert any(i.code == "UNCOMMITTED" for i in decl.issues)


def test_node_worthiness(repo):
    """Rule 1.4 — a node needs a capability, a failure mode, and a remediation."""
    (repo / "belief.yaml").write_text(
        "components:\n  - id: CMP-thin\n    purpose: a helper function\n", encoding="utf-8"
    )
    git(repo, "add", "belief.yaml")
    git(repo, "commit", "-q", "-m", "thin")
    decl = load(repo)
    codes = [i.code for i in decl.issues_for("CMP-thin")]
    assert "NOT_A_NODE" in codes
    assert "CMP-thin" not in decl.active_components()


def test_not_evaluable_contract_accepts_no_evidence(repo):
    yaml = (repo / "belief.yaml").read_text().replace(
        "evaluable_by: [TST-grasp-ik]", "evaluable_by: []"
    )
    (repo / "belief.yaml").write_text(yaml, encoding="utf-8")
    git(repo, "add", "belief.yaml")
    git(repo, "commit", "-q", "-m", "unmeasurable")
    decl = load(repo)
    assert not decl.is_scorable("CTR-grasp-reachable")
    assert any(i.code == "NOT_EVALUABLE" for i in decl.issues_for("CTR-grasp-reachable"))


def test_rule_needing_a_metric_no_test_produces(repo):
    yaml = (repo / "belief.yaml").read_text().replace(
        'rule: "ik_success == true"', 'rule: "grasp_force > 2"'
    )
    (repo / "belief.yaml").write_text(yaml, encoding="utf-8")
    git(repo, "add", "belief.yaml")
    git(repo, "commit", "-q", "-m", "unproduced metric")
    decl = load(repo)
    messages = [i.message for i in decl.issues_for("CTR-grasp-reachable")]
    assert any("grasp_force" in m for m in messages)
    assert not decl.is_scorable("CTR-grasp-reachable")


def test_capability_claim_cannot_reference_implementation(repo):
    yaml = (repo / "belief.yaml").read_text().replace(
        'rule: "ik_success == true"', 'rule: "_internal_flag == true"'
    ).replace("metrics: [ik_success]", "metrics: [_internal_flag]")
    (repo / "belief.yaml").write_text(yaml, encoding="utf-8")
    git(repo, "add", "belief.yaml")
    git(repo, "commit", "-q", "-m", "leaky")
    decl = load(repo)
    codes = [i.code for i in decl.issues_for("CTR-grasp-reachable")]
    assert "CAPABILITY_REFERENCES_IMPLEMENTATION" in codes


def test_unbacked_assumption_found_by_set_difference(repo):
    decl = load(repo)
    unbacked = [i for i in decl.issues if i.code == "UNBACKED_ASSUMPTION"]
    assert len(unbacked) == 1
    assert "cloud covers full object" in unbacked[0].message


def test_test_version_changes_with_the_command(repo):
    before = load(repo).tests["TST-grasp-ik"].version
    (repo / "belief.yaml").write_text(
        (repo / "belief.yaml").read_text().replace('run: "echo ok"', 'run: "echo better"'),
        encoding="utf-8",
    )
    git(repo, "add", "belief.yaml")
    git(repo, "commit", "-q", "-m", "improve the test")
    after = load(repo).tests["TST-grasp-ik"].version
    assert before != after, "editing a test must mint a new version (3.5)"


class TestExpressionSafety:
    """belief.yaml is reviewed, but it is still parsed by a server an agent
    talks to. The rule language must not be a code-execution surface."""

    def test_calls_are_rejected(self):
        with pytest.raises(ExprError):
            evaluate_bool("__import__('os').system('echo pwned')", {})

    def test_attribute_access_rejected(self):
        with pytest.raises(ExprError):
            evaluate_bool("x.__class__", {"x": 1})

    def test_undefined_name_rejected(self):
        with pytest.raises(ExprError):
            evaluate_bool("nope == 1", {})

    def test_ordinary_rules_work(self):
        assert evaluate_bool("ik_success == true", {"ik_success": True})
        assert evaluate_bool("latency < 100 and jitter <= 5", {"latency": 20, "jitter": 5})
        assert not evaluate_bool("lighting == 'low'", {"lighting": "normal"})

    def test_referenced_names_drives_the_coverage_check(self):
        assert referenced_names("a > 1 and b == true") == {"a", "b"}


def test_non_ascii_declarations_still_load(repo):
    """Regression: subprocess text=True decodes with the *locale* codec, so on
    a non-UTF-8 console `git show` raised UnicodeDecodeError and load() fell
    through to "no declarations" — silently disabling the entire gate."""
    yaml = (repo / "belief.yaml").read_text(encoding="utf-8").replace(
        "purpose: Choose a grasp pose",
        "purpose: Choose a grasp pose — naïve sampling, 抓取 planner",
    )
    (repo / "belief.yaml").write_text(yaml, encoding="utf-8")
    git(repo, "add", "belief.yaml")
    git(repo, "commit", "-q", "-m", "unicode purpose")

    decl = load(repo)
    assert decl.source == "git-HEAD", "non-ASCII declarations must still load"
    assert decl.is_scorable("CTR-grasp-reachable")
    assert "naïve" in decl.components["CMP-grasp"].purpose
