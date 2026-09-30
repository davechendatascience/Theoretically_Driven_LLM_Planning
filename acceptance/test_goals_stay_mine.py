"""GOL-goals-stay-mine: my goals and how they are measured change only by my commit, and the agent's
loop waits on me for nothing else."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from component_belief import server
from component_belief.goals import install

from conftest import AGENT_TRAILER, SRC, commit, git

GOALS_YAML = """
goals:
  - {id: GOL-plans, outcome: Planned grasps succeed on the bench, measure: CTR-plans-succeed}
contracts:
  - {id: CTR-plans-succeed, subject: GOL-plans, kind: gate, metrics: [{id: passed, unit: bool}],
     acceptance: {rule: "passed == true"}, evaluable_by: [TST-bench]}
tests:
  - {id: TST-bench, layer: e2e, targets: [GOL-plans], run: python bench.py $OUT, metrics: [passed]}
policies:
  - {id: POL-goals, criteria: [{slice: CTR-plans-succeed, require: supported}]}
"""
BENCH_PY = "import json, sys\njson.dump([{'metrics': {'passed': True}}], open(sys.argv[1], 'w'))\n"


@pytest.fixture
def mine(project: Path) -> Path:
    """The project after I committed my goals myself."""
    (project / "goals.yaml").write_text(GOALS_YAML, encoding="utf-8")
    (project / "bench.py").write_text(BENCH_PY, encoding="utf-8")
    commit(project, "my goals")
    return project


def test_the_agent_cannot_commit_a_change_to_how_my_goal_is_measured(mine, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(SRC))
    install(mine, command=f'"{Path(sys.executable).as_posix()}" -m component_belief.goals check')
    (mine / "bench.py").write_text(BENCH_PY + "# always pass\n", encoding="utf-8")
    refused = git(mine, "commit", "-qam", "loosen the bench" + AGENT_TRAILER)
    assert refused.returncode != 0 and "bench.py" in refused.stderr
    assert git(mine, "commit", "-qam", "I loosened the bench myself").returncode == 0


def test_my_commit_is_the_approval_so_the_agent_can_adopt_without_asking(mine):
    server.run_test("TST-bench")
    out = server.decide("CHG-1")
    assert out.startswith("ADOPT recorded") and "no approver needed" in out


def test_once_the_agent_touches_my_goals_it_has_to_ask_again(mine):
    server.run_test("TST-bench")
    (mine / "goals.yaml").write_text(GOALS_YAML + "# tidied\n", encoding="utf-8")
    commit(mine, "tidy the goals", as_agent=True)
    assert "NOT RECORDED" in server.decide("CHG-2")
    assert "tidy the goals" in server.status(view="goals")


def test_the_agent_proposes_a_goal_change_and_i_see_it_in_one_view(mine):
    server.note("GOL-plans", "the bench is too easy; propose the cluttered-table scene")
    view = server.status(view="goals")
    assert "GOL-plans" in view and "cluttered-table" in view
