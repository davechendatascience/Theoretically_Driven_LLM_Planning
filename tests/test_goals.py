"""The goal set is the human's: the guard refuses the agent's commits to it, the history records
any that got through, and an adoption rests on the human's commit only while there are none.

The trailer (Co-Authored-By: Claude) is the agent's mark on a commit. It is a convention the agent
keeps, not a credential, so what is asserted here is protection against drift -- an agent that
relaxes a measure while sincerely reporting progress -- and that a commit the human types passes.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from component_belief.declarations import load
from component_belief.goals import (GuardError, check_commit, goal_history, goal_set,
                                    guard_installed, guard_line, install, ratification_gap)
from conftest import AGENT_TRAILER, commit_as_agent, git

SRC = Path(__file__).resolve().parents[1] / "src"
GOAL_SET = {"goals.yaml", "eval/see.py", "eval/pick.py", "eval/cloud_fits.py"}


def test_the_goal_set_is_goals_yaml_and_every_file_its_tests_name(goals_repo):
    text = (goals_repo / "goals.yaml").read_text(encoding="utf-8")
    assert goal_set(goals_repo, text) == GOAL_SET
    assert goal_set(goals_repo) == {"goals.yaml"}, "goals.yaml itself, even before it exists"


class TestCheck:
    def test_an_agent_commit_to_the_goal_set_is_refused(self, goals_repo):
        (goals_repo / "eval" / "pick.py").write_text("# always pass\n", encoding="utf-8")
        git(goals_repo, "add", "-A")
        assert check_commit(goals_repo, "loosen the pick check" + AGENT_TRAILER) == ["eval/pick.py"]

    def test_the_same_commit_by_the_human_passes(self, goals_repo):
        (goals_repo / "eval" / "pick.py").write_text("# stricter\n", encoding="utf-8")
        git(goals_repo, "add", "-A")
        assert check_commit(goals_repo, "tighten the pick check") == []

    def test_an_agent_commit_below_the_goals_passes(self, goals_repo):
        (goals_repo / "grasp.py").write_text("# v2\n", encoding="utf-8")
        (goals_repo / "belief.yaml").write_text(
            (goals_repo / "belief.yaml").read_text(encoding="utf-8").replace("target_rate: 0.8", "target_rate: 0.6"),
            encoding="utf-8")
        git(goals_repo, "add", "-A")
        assert check_commit(goals_repo, "retune, and relax my own contract" + AGENT_TRAILER) == []

    def test_dropping_a_test_from_goals_yaml_does_not_free_its_file(self, goals_repo):
        text = (goals_repo / "goals.yaml").read_text(encoding="utf-8")
        (goals_repo / "goals.yaml").write_text(text.replace("python eval/pick.py", "python eval/see.py"),
                                               encoding="utf-8")
        (goals_repo / "eval" / "pick.py").write_text("# gutted\n", encoding="utf-8")
        git(goals_repo, "add", "-A")
        assert check_commit(goals_repo, "x" + AGENT_TRAILER) == ["eval/pick.py", "goals.yaml"]

    def test_creating_goals_yaml_is_the_humans_too(self, repo):
        from conftest import GOALS_YAML

        (repo / "goals.yaml").write_text(GOALS_YAML, encoding="utf-8")
        git(repo, "add", "-A")
        assert check_commit(repo, "draft goals" + AGENT_TRAILER) == ["goals.yaml"]


class TestHook:
    @pytest.fixture
    def guarded(self, goals_repo, monkeypatch):
        """The hook installed with this checkout's interpreter in place of the pinned release."""
        monkeypatch.setenv("PYTHONPATH", str(SRC))
        python = Path(sys.executable).as_posix()
        install(goals_repo, command=f'"{python}" -m component_belief.goals check')
        return goals_repo

    def test_a_real_agent_commit_is_refused_and_yours_goes_through(self, guarded):
        head = git(guarded, "rev-parse", "HEAD").stdout
        (guarded / "eval" / "pick.py").write_text("# always pass\n", encoding="utf-8")
        refused = git(guarded, "commit", "-am", "loosen the pick check" + AGENT_TRAILER)
        assert refused.returncode != 0
        assert "tdlp guard: refused" in refused.stderr and "eval/pick.py" in refused.stderr
        assert git(guarded, "rev-parse", "HEAD").stdout == head

        mine = git(guarded, "commit", "-am", "I loosened it myself")
        assert mine.returncode == 0, mine.stderr

    def test_it_is_reported_as_installed(self, guarded):
        assert guard_installed(guarded)

    def test_a_guard_from_an_earlier_release_says_so(self, goals_repo):
        """Upgrading the plugin leaves the hook on the release that installed it; the view said
        "installed" either way. Reinstalling replaces the guard in place, with no --force."""
        from component_belief import __version__
        from component_belief.goals import RELEASES

        install(goals_repo)
        assert guard_line(goals_repo, "HINT", "NOT INSTALLED") == "installed in this clone"
        install(goals_repo, command=f'uvx --quiet --from "{RELEASES}@tdlp--v0.4.0" tdlp-guard check')
        line = guard_line(goals_repo, "HINT", "NOT INSTALLED")
        assert f"runs v0.4.0 and this release is v{__version__}" in line and "HINT" in line
        install(goals_repo, command='"python" -m component_belief.goals check')
        assert guard_line(goals_repo, "HINT", "NOT INSTALLED") == "installed in this clone", \
            "a guard that runs its own command is pinned to no release"

    def test_another_hook_is_not_overwritten_unasked(self, goals_repo):
        hook = Path(git(goals_repo, "rev-parse", "--git-path", "hooks").stdout.strip())
        hook = (hook if hook.is_absolute() else goals_repo / hook) / "commit-msg"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        with pytest.raises(GuardError):
            install(goals_repo, command="true")
        assert not guard_installed(goals_repo)
        install(goals_repo, command="true", force=True)
        assert guard_installed(goals_repo)


class TestHistory:
    def test_an_agent_commit_that_got_through_is_recorded(self, goals_repo):
        commit_as_agent(goals_repo, "eval/pick.py", "# always pass\n", "loosen the pick check")
        changes, yours = goal_history(goals_repo)
        assert [c["files"] for c in changes] == [["eval/pick.py"]]
        assert changes[0]["subject"] == "loosen the pick check"
        assert yours["subject"] == "my goals"

    def test_your_next_commit_to_the_goal_set_takes_them_in(self, goals_repo):
        commit_as_agent(goals_repo, "eval/pick.py", "# always pass\n")
        (goals_repo / "goals.yaml").write_text(
            (goals_repo / "goals.yaml").read_text(encoding="utf-8") + "# reviewed\n", encoding="utf-8")
        git(goals_repo, "commit", "-q", "-am", "reviewed the pick change")
        changes, yours = goal_history(goals_repo)
        assert changes == [] and yours["subject"] == "reviewed the pick change"

    def test_agent_commits_below_the_goals_are_not_in_it(self, goals_repo):
        commit_as_agent(goals_repo, "grasp.py", "# v2\n")
        assert goal_history(goals_repo)[0] == []


class TestRatification:
    def test_your_commit_approves_the_goals_policy(self, goals_repo):
        assert ratification_gap(goals_repo, load(goals_repo), "POL-goals") is None

    def test_an_agent_change_to_the_goal_set_withdraws_that(self, goals_repo):
        commit_as_agent(goals_repo, "goals.yaml",
                        (goals_repo / "goals.yaml").read_text(encoding="utf-8") + "# tidied\n")
        gap = ratification_gap(goals_repo, load(goals_repo), "POL-goals")
        assert gap and "the agent changed your goal set" in gap and "goals.yaml" in gap

    def test_a_policy_in_belief_yaml_is_never_approved_by_it(self, goals_repo):
        assert "belief.yaml" in ratification_gap(goals_repo, load(goals_repo), "POL-release")


class TestAdoption:
    """Setting up goals in a project that already uses TDLP: the view shows what could measure a
    goal and checks a draft without putting it in effect, and a measure promoted from belief.yaml
    keeps the evidence it already has."""

    E2E_YAML = """
components:
  - id: CMP-grasp
    purpose: Choose a grasp pose
    testable_capability: Produces a reachable pose
    failure_modes: [{id: FM-unreachable, observable: IK returns nothing}]
    remediation: Retune approach sampling
    code: [grasp.py]
contracts:
  - {id: CTR-pick-success, subject: CMP-grasp, kind: gate, metrics: [{id: passed, unit: bool}],
     acceptance: {rule: "passed == true"}, evaluable_by: [TST-pick]}
tests:
  - {id: TST-pick, layer: e2e, targets: [CMP-grasp], run: python eval/pick.py $OUT, metrics: [passed]}
"""
    PROMOTED_GOALS = """
goals:
  - {id: GOL-grasp, outcome: The arm picks up the object it is asked for, measure: CTR-pick-success}
contracts:
  - {id: CTR-pick-success, subject: GOL-grasp, kind: gate, metrics: [{id: passed, unit: bool}],
     acceptance: {rule: "passed == true"}, evaluable_by: [TST-pick]}
tests:
  - {id: TST-pick, layer: e2e, targets: [GOL-grasp], run: python eval/pick.py $OUT, metrics: [passed]}
policies:
  - {id: POL-goals, criteria: [{slice: CTR-pick-success, require: supported}]}
"""

    @pytest.fixture
    def measured(self, repo, monkeypatch):
        """A project with an end-to-end contract and one passing run of it, and no goals yet."""
        from component_belief.runner import run_test
        from component_belief.store import Store
        from conftest import EVAL_PY

        (repo / "belief.yaml").write_text(self.E2E_YAML, encoding="utf-8")
        (repo / "grasp.py").write_text("# v1\n", encoding="utf-8")
        (repo / "eval").mkdir()
        (repo / "eval" / "pick.py").write_text(EVAL_PY, encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "an end-to-end test")
        decl = load(repo)
        run_test(repo, Store(repo), decl, decl.tests["TST-pick"])
        monkeypatch.setenv("BELIEF_PROJECT_ROOT", str(repo))
        return repo

    @staticmethod
    def pick_slice(repo):
        from component_belief.model import compute_slices
        from component_belief.staleness import CodeStaleness
        from component_belief.store import Store

        [sl] = compute_slices(load(repo), Store(repo).effective_trials(), ["CTR-pick-success"],
                              staleness=CodeStaleness(repo))
        return sl

    def test_before_any_goals_the_view_lists_what_could_measure_one(self, measured):
        from component_belief import server

        view = server.status(view="goals")
        assert "candidate measures" in view
        assert "CTR-pick-success (TST-pick): CTR-pick-success [unbucketed] supported gate 1/1" in view

    def test_a_draft_is_checked_without_taking_effect(self, measured):
        from component_belief import server

        (measured / "goals.yaml").write_text(self.PROMOTED_GOALS.replace(
            "measure: CTR-pick-success}", "measure: CTR-not-declared}"), encoding="utf-8")
        view = server.status(view="goals")
        assert "no goals in effect" in view and "draft in the working tree" in view
        assert "UNMEASURED_GOAL GOL-grasp: measure CTR-not-declared is not a declared contract" in view
        assert not load(measured).goals, "a draft is reported, never in effect"

    def test_a_promoted_measure_keeps_its_evidence(self, measured):
        """The prediction step 4 rests on: a contract moved into goals.yaml with its id and test
        keeps its trials -- while both files declare it, and after belief.yaml lets it go -- with
        no re-run."""
        before = self.pick_slice(measured)
        assert before.state == "supported"

        (measured / "goals.yaml").write_text(self.PROMOTED_GOALS, encoding="utf-8")
        git(measured, "add", "-A")
        git(measured, "commit", "-q", "-m", "my goals, promoting the pick test")
        decl = load(measured)
        assert decl.contracts["CTR-pick-success"].subject == "GOL-grasp"
        assert any(i.code == "DUPLICATE_ID" for i in decl.issues)
        during = self.pick_slice(measured)
        assert (during.state, during.evidence_ids) == (before.state, before.evidence_ids)

        cleaned = self.E2E_YAML.split("contracts:")[0].replace(
            "    code: [grasp.py]\n", "    code: [grasp.py]\n    goal: GOL-grasp\n")
        (measured / "belief.yaml").write_text(cleaned, encoding="utf-8")
        git(measured, "commit", "-q", "-am", "belief.yaml lets the promoted ids go; tag the goal" + AGENT_TRAILER)
        decl = load(measured)
        assert not [i for i in decl.issues if i.code in ("DUPLICATE_ID", "UNMEASURED_GOAL")]
        after = self.pick_slice(measured)
        assert (after.state, after.evidence_ids) == (before.state, before.evidence_ids)


class TestWhatTheGoalsPolicyReads:
    """The human's commit approves a goals policy only if everything the policy reads is theirs."""

    def test_a_prior_on_a_goal_measure_is_the_agents(self, goals_repo):
        text = (goals_repo / "belief.yaml").read_text(encoding="utf-8").replace(
            "priors: []", "") + "\npriors:\n  - {contract: CTR-pick-success, alpha: 2000, beta: 1}\n"
        commit_as_agent(goals_repo, "belief.yaml", text, "a strong prior")
        gap = ratification_gap(goals_repo, load(goals_repo), "POL-goals")
        assert gap and "CTR-pick-success has a prior" in gap

    def test_safety_gates_read_the_agents_mandatory_flags(self, goals_repo):
        text = (goals_repo / "goals.yaml").read_text(encoding="utf-8").replace(
            "      - {slice: CTR-cloud-fits-grasp, require: supported}\n",
            "      - {slice: CTR-cloud-fits-grasp, require: supported}\n      - {safety_gates: all_passed}\n")
        (goals_repo / "goals.yaml").write_text(text, encoding="utf-8")
        git(goals_repo, "commit", "-qam", "gate on safety")
        gap = ratification_gap(goals_repo, load(goals_repo), "POL-goals")
        assert gap and "safety_gates" in gap and "TST-grasp-ik" in gap

    def test_a_file_moved_out_of_a_goal_directory_is_refused_and_recorded(self, goals_repo):
        text = (goals_repo / "goals.yaml").read_text(encoding="utf-8").replace(
            "python eval/pick.py $OUT", "python -m pytest eval/goals $OUT")
        (goals_repo / "eval" / "goals").mkdir()
        (goals_repo / "eval" / "goals" / "test_hard.py").write_text("def test_hard(): pass\n", encoding="utf-8")
        (goals_repo / "goals.yaml").write_text(text, encoding="utf-8")
        git(goals_repo, "add", "-A")
        git(goals_repo, "commit", "-q", "-m", "my harder pick check")
        (goals_repo / "eval" / "other").mkdir()
        git(goals_repo, "mv", "eval/goals/test_hard.py", "eval/other/test_hard.py")
        assert "eval/goals/test_hard.py" in check_commit(goals_repo, "tidy" + AGENT_TRAILER), \
            "a rename is a deletion from the goal set"
        git(goals_repo, "commit", "-q", "--no-verify", "-m", "tidy" + AGENT_TRAILER)
        changes, _ = goal_history(goals_repo)
        assert changes and "eval/goals/test_hard.py" in changes[0]["files"]
