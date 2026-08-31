"""End-to-end: the runner, the tool surface, and the response envelope."""

from __future__ import annotations

import json
import os

import pytest

from component_belief import server
from component_belief.declarations import load
from component_belief.runner import run_test as execute
from component_belief.store import Store
from conftest import git


@pytest.fixture
def project(repo, monkeypatch):
    monkeypatch.setenv("BELIEF_PROJECT_ROOT", str(repo))
    monkeypatch.setenv("BELIEF_ACTOR", "test-agent")
    return repo


def emit_yaml(repo, run_command):
    yaml = (repo / "belief.yaml").read_text().replace('run: "echo ok"', f'run: {json.dumps(run_command)}')
    (repo / "belief.yaml").write_text(yaml, encoding="utf-8")
    git(repo, "add", "belief.yaml")
    git(repo, "commit", "-q", "-m", "runnable test")


class TestRunner:
    def test_structured_trials_become_measured_evidence(self, repo):
        script = repo / "emit.py"
        script.write_text(
            "import json, os, sys\n"
            "json.dump({'trials': [{'metrics': {'ik_success': True}, 'conditions': {'lighting': 'normal'}},\n"
            "                      {'metrics': {'ik_success': False}, 'conditions': {'lighting': 'low'}}]},\n"
            "          open(os.environ['OUT'], 'w'))\n",
            encoding="utf-8",
        )
        emit_yaml(repo, f'python "{script}"')
        decl = load(repo)
        store = Store(repo)
        result = execute(repo, store, decl, decl.tests["TST-grasp-ik"])

        assert result["n_trials"] == 2
        assert result["n_records"] == 2
        assert result["synthesized_from_exit_code"] is False
        trials = store.effective_trials()
        assert {t["provenance"] for t in trials} == {"measured"}
        assert all(t["artifact_hash"] for t in trials)

    def test_out_placeholder_is_expanded_cross_platform(self, repo):
        script = repo / "emit.py"
        script.write_text(
            "import json, sys\n"
            "json.dump({'trials': [{'metrics': {'ik_success': True}}]}, open(sys.argv[1], 'w'))\n",
            encoding="utf-8",
        )
        emit_yaml(repo, f'python "{script}" $OUT')
        decl = load(repo)
        store = Store(repo)
        result = execute(repo, store, decl, decl.tests["TST-grasp-ik"])
        assert result["n_trials"] == 1
        assert result["synthesized_from_exit_code"] is False

    def test_exit_code_fallback_does_not_fabricate_a_declared_metric(self, repo):
        """The test declares ik_success but emits nothing. The trial must be
        recorded and then excluded, never scored off the exit status."""
        emit_yaml(repo, "echo nothing-structured")
        decl = load(repo)
        store = Store(repo)
        result = execute(repo, store, decl, decl.tests["TST-grasp-ik"])
        assert result["synthesized_from_exit_code"] is True
        assert result["outcome_counts"] == {"pass": 1}

        from component_belief.model import compute_slices
        slices = compute_slices(decl, store.effective_trials())
        assert slices[0].n_valid == 0
        assert slices[0].exclusions == {"missing_metrics": 1}

    def test_failing_command_records_a_failing_trial(self, repo):
        emit_yaml(repo, "exit 1")
        decl = load(repo)
        store = Store(repo)
        result = execute(repo, store, decl, decl.tests["TST-grasp-ik"])
        assert result["exit_code"] != 0
        assert result["outcome_counts"] == {"fail": 1}

    def test_artifacts_are_written(self, repo):
        emit_yaml(repo, "echo hello")
        decl = load(repo)
        store = Store(repo)
        result = execute(repo, store, decl, decl.tests["TST-grasp-ik"])
        artifact_dir = store.artifact_dir(result["run_id"])
        assert (artifact_dir / "stdout.txt").exists()
        assert (artifact_dir / "command.txt").exists()
        assert "hello" in (artifact_dir / "stdout.txt").read_text()


class TestToolSurface:
    def test_exactly_six_tools(self):
        import asyncio
        tools = asyncio.run(server.mcp.list_tools())
        assert sorted(t.name for t in tools) == [
            "amend", "decide", "ingest", "note", "run_test", "status",
        ]

    def test_no_tool_writes_a_belief(self):
        import asyncio
        tools = asyncio.run(server.mcp.list_tools())
        names = " ".join(t.name for t in tools)
        for forbidden in ("set_belief", "update_belief", "update_posterior", "set_state"):
            assert forbidden not in names

    def test_status_views_carry_a_basis_line(self, project):
        for view in ("graph", "coverage", "belief", "diagnose", "plan"):
            out = server.status(view=view)
            assert "basis:" in out, f"{view} must declare its basis (10.3)"

    def test_unknown_view_is_reported(self, project):
        assert "unknown view" in server.status(view="nonsense")

    def test_note_is_inert(self, project):
        out = server.note("CMP-grasp", "looked jittery")
        assert "not belief-eligible" in out
        assert Store(project).effective_trials() == []

    def test_amend_requires_a_reason(self, project):
        store = Store(project)
        from conftest import trial
        ids = store.append_trials([trial()])
        assert "reason is required" in server.amend(ids[0], validity="invalid")
        assert "unknown evidence id" in server.amend("EV-9999", validity="invalid", reason="x")

    def test_ingest_rejects_records_without_repro(self, project):
        out = server.ingest(
            records=[{"contract_id": "CTR-grasp-reachable", "test_id": "TST-grasp-ik",
                      "outcome": "pass", "metrics": {"ik_success": True}}],
            source="ci", artifact_uri="ci://run/1",
        )
        assert "rejected" in out
        assert "repro" in out

    def test_ingest_requires_an_artifact(self, project):
        assert "artifact_uri is required" in server.ingest(records=[], source="ci", artifact_uri="")

    def test_ingest_accepts_a_complete_record(self, project):
        out = server.ingest(
            records=[{
                "contract_id": "CTR-grasp-reachable", "test_id": "TST-grasp-ik",
                "outcome": "pass", "metrics": {"ik_success": True},
                "conditions": {"lighting": "normal"},
                "repro": {"model_revision": "v3", "sw_revision": "deadbeef"},
            }],
            source="ci", artifact_uri="ci://run/1",
        )
        assert "ingested 1 record" in out
        trials = Store(project).effective_trials()
        assert trials[0]["provenance"] == "imported"
        assert trials[0]["source_system"] == "ci"

    def test_run_test_reports_unknown_test(self, project):
        assert "unknown test" in server.run_test("TST-nope")

    def test_trace_expands_a_citation_handle(self, project):
        from conftest import trial
        Store(project).append_trials([trial(ik=True) for _ in range(6)])
        belief = server.status(view="belief")
        handle = belief.split("set=")[1].split()[0]
        traced = server.status(view="trace", set=handle)
        assert "EV-0001" in traced
        assert "TST-grasp-ik" in traced

    def test_trace_lists_known_handles_when_none_match(self, project):
        from conftest import trial
        Store(project).append_trials([trial(ik=True) for _ in range(6)])
        out = server.status(view="trace", set="ffffff")
        assert "Known handles" in out

    def test_cycle_emits_the_seven_outputs(self, project):
        from conftest import trial
        Store(project).append_trials([trial(ik=True) for _ in range(30)])
        report = json.loads(server.status(view="cycle"))
        for key in ("1_graph", "2_coverage", "3_beliefs", "4_e2e",
                    "5_bottlenecks", "6_recommendation", "7_decision"):
            assert key in report
        assert report["3_beliefs"][0]["evidence_ids"], "the report carries full chains (10.1)"
        assert report["model_version"]

    def test_decide_refuses_to_self_approve_an_adopt(self, project):
        from conftest import trial
        Store(project).append_trials([trial(ik=True) for _ in range(30)])
        out = server.decide("CHG-1")
        assert "NOT RECORDED" in out
        assert "requires a human approver" in out
        assert Store(project).decisions() == []

    def test_decide_records_with_an_approver(self, project):
        from conftest import trial
        Store(project).append_trials([trial(ik=True) for _ in range(30)])
        out = server.decide("CHG-1", approver="david")
        assert "ADOPT recorded" in out
        decisions = Store(project).decisions()
        assert decisions[0]["approver"] == "david"
        assert decisions[0]["policy_id"] == "POL-release"

    def test_more_testing_records_without_an_approver(self, project):
        """A cautious verdict needs no human sign-off to write down."""
        from conftest import trial
        Store(project).append_trials([trial(ik=True), trial(ik=True)])
        out = server.decide("CHG-2")
        assert "MORE_TESTING recorded" in out


class TestPendingGate:
    def test_uncommitted_threshold_change_does_not_reach_a_decision(self, project):
        from conftest import trial
        Store(project).append_trials([trial(ik=False) for _ in range(30)])
        assert "REJECT" in server.decide("CHG-3")

        (project / "belief.yaml").write_text(
            (project / "belief.yaml").read_text().replace("target_rate: 0.8", "target_rate: 0.01"),
            encoding="utf-8",
        )
        assert "REJECT" in server.decide("CHG-3"), \
            "an uncommitted threshold change must not flip a decision"
        assert "PENDING" in server.status(view="graph")


def test_multi_slice_basis_handle_resolves(project):
    """The handle printed on a multi-slice read is a union hash. If trace only
    matched per-slice hashes, the citation the agent is told to quote would be
    unresolvable — provenance in appearance only."""
    from conftest import trial
    Store(project).append_trials(
        [trial(ik=True, lighting="normal") for _ in range(30)]
        + [trial(ik=True, lighting="low") for _ in range(30)]
    )
    belief = server.status(view="belief")
    assert belief.count("CTR-grasp-reachable") == 2, "two slices in scope"
    handle = belief.split("set=")[1].split()[0]

    traced = server.status(view="trace", set=handle)
    assert "Known handles" not in traced, f"union handle {handle} must resolve"
    assert traced.count("CTR-grasp-reachable") == 2
