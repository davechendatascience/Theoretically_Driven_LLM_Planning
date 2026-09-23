"""Gate contracts, and evidence that goes stale with the code it measured."""

from __future__ import annotations

from pathlib import Path

import pytest

from component_belief.decide import ADOPT, MORE_TESTING, active_policy, decision_relevant, evaluate_policy
from component_belief.declarations import load
from component_belief.diagnose import STALE, diagnose
from component_belief.model import STATE_REFUTED, STATE_STALE, STATE_SUPPORTED, compute_slices
from component_belief.planning import plan_round
from component_belief.staleness import CodeStaleness
from conftest import BASE_YAML, git, trial

GATE_YAML = BASE_YAML.replace(
    'acceptance: {rule: "ik_success == true", target_rate: 0.8}',
    'kind: gate\n    acceptance: {rule: "ik_success == true"}',
).replace("    sufficiency: {n_min: 4, max_ci_width: 0.9}\n", "")

CLAIMED_YAML = BASE_YAML.replace(
    "    remediation: Retune approach sampling\n",
    "    remediation: Retune approach sampling\n    code: [grasp.py, grasp/*.py]\n",
)


def head(repo: Path) -> str:
    return git(repo, "rev-parse", "--short", "HEAD").stdout.strip()


def measured_at(repo: Path, n: int = 30, ik: bool = True, run_id: str = "RUN-0001") -> list[dict]:
    """Trials whose sw_revision is this repository's HEAD, as the runner would record them."""
    out = []
    for _ in range(n):
        t = trial(ik=ik, run_id=run_id)
        t["repro"] = {"model_revision": "v3", "sw_revision": head(repo)}
        out.append(t)
    return out


def change_claimed_code(repo: Path) -> None:
    (repo / "grasp.py").write_text("# v2\n", encoding="utf-8")
    git(repo, "commit", "-qam", "change the grasp planner")


@pytest.fixture
def gate_repo(repo: Path) -> Path:
    (repo / "belief.yaml").write_text(GATE_YAML, encoding="utf-8")
    git(repo, "add", "belief.yaml")
    git(repo, "commit", "-q", "-m", "declare a gate")
    return repo


@pytest.fixture
def code_repo(repo: Path) -> Path:
    (repo / "grasp.py").write_text("# v1\n", encoding="utf-8")
    (repo / "belief.yaml").write_text(CLAIMED_YAML, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "claim the code")
    return repo


# --- gates -----------------------------------------------------------------------------------

class TestGate:
    def test_one_fully_passing_run_supports_it(self, gate_repo):
        slices = compute_slices(load(gate_repo), [trial(ik=True) for _ in range(3)])
        assert slices[0].kind == "gate"
        assert slices[0].state == STATE_SUPPORTED
        assert slices[0].n_valid == 3 and slices[0].lo == slices[0].hi == 1.0
        assert slices[0].latest_run == "RUN-0001"

    def test_one_failing_case_refutes_it(self, gate_repo):
        slices = compute_slices(load(gate_repo), [trial(ik=True) for _ in range(30)] + [trial(ik=False)])
        assert slices[0].state == STATE_REFUTED

    def test_it_reads_its_latest_run_only(self, gate_repo):
        """An old pass must not outvote a new fail, and an old fail must not haunt a new pass."""
        decl = load(gate_repo)
        fixed = compute_slices(decl, [trial(ik=False, run_id="RUN-0001")]
                               + [trial(ik=True, run_id="RUN-0002") for _ in range(3)])
        assert fixed[0].state == STATE_SUPPORTED and fixed[0].latest_run == "RUN-0002"
        assert fixed[0].n_valid == 3, "the earlier run is on record, not counted"

        broken = compute_slices(decl, [trial(ik=True, run_id="RUN-0001") for _ in range(3)]
                                + [trial(ik=False, run_id="RUN-0002")])
        assert broken[0].state == STATE_REFUTED

    def test_it_adopts_without_reruns_and_stops_being_decision_relevant(self, gate_repo):
        """The deterministic-suite problem: a rate contract at 0.95 needed about 72 passes."""
        decl = load(gate_repo)
        slices = compute_slices(decl, [trial(ik=True) for _ in range(3)])
        assert evaluate_policy(decl, active_policy(decl), slices).status == ADOPT
        assert decision_relevant(decl, active_policy(decl), slices, "CTR-grasp-reachable") is False

    def test_a_bad_kind_is_reported(self, repo):
        from component_belief.declarations import _parse
        decl = _parse(BASE_YAML.replace("claim_type: capability", "claim_type: capability\n    kind: vibes"))
        assert any(i.code == "BAD_KIND" for i in decl.issues)


# --- staleness -------------------------------------------------------------------------------

class TestStaleness:
    def test_evidence_measured_before_a_claimed_file_changed_is_stale(self, code_repo):
        trials = measured_at(code_repo)
        current = compute_slices(load(code_repo), trials, staleness=CodeStaleness(code_repo))
        assert current[0].state == STATE_SUPPORTED and current[0].n_stale == 0

        change_claimed_code(code_repo)
        after = compute_slices(load(code_repo), trials, staleness=CodeStaleness(code_repo))
        assert after[0].state == STATE_STALE
        assert after[0].n_stale == 30 and after[0].n_valid == 0
        assert "grasp.py changed since" in after[0].stale_reasons[0]
        assert after[0].evidence_ids, "stale evidence is still cited"
        assert (after[0].lo, after[0].hi) == (0.0, 1.0), "nothing is known about the current revision"

    def test_a_change_to_unclaimed_code_does_not_stale_it(self, code_repo):
        trials = measured_at(code_repo)
        (code_repo / "other.py").write_text("# unrelated\n", encoding="utf-8")
        git(code_repo, "add", "-A")
        git(code_repo, "commit", "-q", "-m", "unrelated")
        slices = compute_slices(load(code_repo), trials, staleness=CodeStaleness(code_repo))
        assert slices[0].state == STATE_SUPPORTED and slices[0].n_stale == 0

    def test_new_evidence_counts_and_old_is_set_aside(self, code_repo):
        old = measured_at(code_repo, run_id="RUN-0001")
        change_claimed_code(code_repo)
        new = measured_at(code_repo, run_id="RUN-0002")
        slices = compute_slices(load(code_repo), old + new, staleness=CodeStaleness(code_repo))
        assert slices[0].state == STATE_SUPPORTED
        assert slices[0].n_valid == 30 and slices[0].n_stale == 30

    def test_an_unknown_revision_is_stale_and_a_missing_one_is_unknown(self, code_repo):
        decl = load(code_repo)
        foreign = [trial(ik=True) for _ in range(30)]          # sw_revision abc123, not in this history
        slices = compute_slices(decl, foreign, staleness=CodeStaleness(code_repo))
        assert slices[0].state == STATE_STALE
        assert "not in this repository's history" in slices[0].stale_reasons[0]

        unversioned = []
        for t in [trial(ik=True) for _ in range(30)]:
            t["repro"] = {"model_revision": "v3"}
            t["system_version"] = ""
            unversioned.append(t)
        slices = compute_slices(decl, unversioned, staleness=CodeStaleness(code_repo))
        assert slices[0].state == STATE_SUPPORTED, "no revision at all is unknown, not stale"

    def test_a_component_claiming_no_code_never_goes_stale(self, repo):
        slices = compute_slices(load(repo), [trial(ik=True) for _ in range(30)], staleness=CodeStaleness(repo))
        assert slices[0].state == STATE_SUPPORTED

    def test_stale_evidence_cannot_satisfy_an_adopt_criterion(self, code_repo):
        trials = measured_at(code_repo)
        change_claimed_code(code_repo)
        decl = load(code_repo)
        slices = compute_slices(decl, trials, staleness=CodeStaleness(code_repo))
        verdict = evaluate_policy(decl, active_policy(decl), slices)
        assert verdict.status == MORE_TESTING
        assert any("stale" in m and "re-run TST-grasp-ik" in m for m in verdict.missing)

    def test_diagnose_names_the_rerun(self, code_repo):
        trials = measured_at(code_repo)
        change_claimed_code(code_repo)
        decl = load(code_repo)
        slices = compute_slices(decl, trials, staleness=CodeStaleness(code_repo))
        result = diagnose(decl, slices, trials)
        grasp = next(c for c in result.ranked if c.subject == "CMP-grasp")
        assert grasp.status == STALE and grasp.confidence == "low"
        assert result.recommendation.startswith("re-run TST-grasp-ik for CMP-grasp")
        assert result.coverage_limited is False

    def test_the_plan_reschedules_the_test(self, code_repo):
        trials = measured_at(code_repo, n=200)
        decl = load(code_repo)
        before = plan_round(decl, compute_slices(decl, trials, staleness=CodeStaleness(code_repo)))
        assert before["selected"] == [], "well measured and current: nothing to run"

        change_claimed_code(code_repo)
        decl = load(code_repo)
        after = plan_round(decl, compute_slices(decl, trials, staleness=CodeStaleness(code_repo)))
        assert [item["test_id"] for item in after["selected"]] == ["TST-grasp-ik"]


# --- through the server ----------------------------------------------------------------------

class TestServerSurface:
    @pytest.fixture
    def project(self, code_repo, monkeypatch):
        monkeypatch.setenv("BELIEF_PROJECT_ROOT", str(code_repo))
        return code_repo

    def test_belief_view_prints_the_stale_line_and_the_rerun(self, project):
        from component_belief import server
        from component_belief.store import Store

        Store(project).append_trials(measured_at(project))
        assert "supported" in server.status(view="belief")
        change_claimed_code(project)
        out = server.status(view="belief")
        assert "stale n=30 -- grasp.py changed since" in out
        assert "next: run_test TST-grasp-ik" in out
        assert "stale evidence" in server.status(view="coverage")

    def test_gate_line_names_the_run(self, gate_repo, monkeypatch):
        from component_belief import server
        from component_belief.store import Store

        monkeypatch.setenv("BELIEF_PROJECT_ROOT", str(gate_repo))
        Store(gate_repo).append_trials([trial(ik=True) for _ in range(3)])
        assert "supported gate 3/3 passed in RUN-0001" in server.status(view="belief")

    def test_a_run_records_whether_the_tree_was_dirty(self, project):
        from component_belief.runner import run_test as execute
        from component_belief.store import Store

        decl = load(project)
        store = Store(project)
        execute(project, store, decl, decl.tests["TST-grasp-ik"])
        clean = store.effective_trials()[-1]
        assert clean["repro"]["sw_dirty"] is False
        assert clean["repro"]["sw_revision"] == head(project)

        (project / "grasp.py").write_text("# edited, not committed\n", encoding="utf-8")
        execute(project, store, decl, decl.tests["TST-grasp-ik"])
        dirty = store.effective_trials()[-1]
        assert dirty["repro"]["sw_dirty"] is True

    def test_decide_records_the_revision(self, project):
        from component_belief import server
        from component_belief.store import Store

        Store(project).append_trials(measured_at(project))
        out = server.decide("CHG-1", approver="david")
        assert f"at HEAD {head(project)}" in out
        assert Store(project).decisions()[0]["head"] == head(project)
