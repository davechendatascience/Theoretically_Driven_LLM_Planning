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
                                    guard_installed, install, ratification_gap)
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
