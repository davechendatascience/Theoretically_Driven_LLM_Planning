"""End-to-end: the runner, the tool surface, and the response envelope."""

from __future__ import annotations

import hashlib
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


def results_file(repo, text='[{"ik_success": true}]'):
    """A results file an external run left in the project, as `ingest` expects to find one."""
    path = repo / "out" / "round1.trials.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def complete_record(**overrides):
    return {
        "contract_id": "CTR-grasp-reachable", "test_id": "TST-grasp-ik",
        "outcome": "pass", "metrics": {"ik_success": True},
        "conditions": {"lighting": "normal"},
        "repro": {"model_revision": "v3", "sw_revision": "deadbeef"},
        **overrides,
    }


def emit_yaml(repo, run_command):
    yaml = (repo / "belief.yaml").read_text().replace('run: "echo ok"', f'run: {json.dumps(run_command)}')
    (repo / "belief.yaml").write_text(yaml, encoding="utf-8")
    git(repo, "add", "belief.yaml")
    git(repo, "commit", "-q", "-m", "runnable test")


class TestFailureModes:
    """Row 9's risk register: each failure mode a component declares, and the contract -- and the
    case -- that would see it. The graph lists those nothing observes, and checks a named case
    against the ledger instead of taking the link on trust."""

    def _declare(self, repo, fm):
        yaml = (repo / "belief.yaml").read_text().replace(
            "failure_modes: [{id: FM-unreachable, observable: IK returns nothing}]", f"failure_modes: [{fm}]")
        (repo / "belief.yaml").write_text(yaml, encoding="utf-8")
        git(repo, "add", "belief.yaml")
        git(repo, "commit", "-q", "-m", "a failure mode's observer")

    def test_a_failure_mode_nothing_observes_is_listed(self, project):
        graph = server.status(view="graph")
        assert "failure modes no contract observes (2 of 2" in graph
        assert "CMP-grasp: FM-unreachable" in graph

    def test_a_named_case_is_checked_against_the_ledger(self, project):
        from conftest import trial

        self._declare(project, "{id: FM-unreachable, observable: IK returns nothing, "
                               "observed_by: CTR-grasp-reachable, case: tests.test_ik::test_reach}")
        graph = server.status(view="graph")
        assert "CMP-grasp: FM-unreachable" not in graph.split("no contract observes")[1].split("\n\n")[0]
        assert "CTR-grasp-reachable has no trial of tests.test_ik::test_reach" in graph

        measured = trial()
        measured["conditions"]["raw"]["case"] = "tests.test_ik::test_reach[low]"
        Store(project).append_trials([measured])
        assert "not measured passing" not in server.status(view="graph")

    def test_an_observer_that_is_not_a_contract_is_reported(self, project):
        self._declare(project, "{id: FM-unreachable, observable: IK returns nothing, observed_by: CTR-nope}")
        decl = load(project)
        assert any(i.code == "UNKNOWN_REF" and "CTR-nope" in i.message for i in decl.issues)


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

    def test_a_long_run_tells_the_client_it_is_still_running(self, project, monkeypatch):
        """A stdio tool call that sends nothing for 30 minutes is aborted by the client's idle
        timeout. The tool runs the test in a worker thread and beats while it runs: progress when
        the client gave a token, a log message either way."""
        import anyio

        emit_yaml(project, 'python -c "import time; time.sleep(0.6)"')
        monkeypatch.setattr(server, "HEARTBEAT_S", 0.1)
        beats = []

        class Client:
            async def report_progress(self, progress, total=None, message=None):
                beats.append(("progress", message))

            async def info(self, message, **extra):
                beats.append(("info", message))

        out = anyio.run(lambda: server.run_test_tool(test_id="TST-grasp-ik", ctx=Client()))
        assert out.startswith("RUN-0001 TST-grasp-ik"), out
        assert ("info", "TST-grasp-ik: still running, 0 min") in beats
        assert any(kind == "progress" for kind, _ in beats)
        n = len(beats)
        anyio.run(lambda: anyio.sleep(0.3))
        assert len(beats) == n, "the heartbeat stops with the run"

    def test_every_measured_record_names_the_revision_it_ran_at(self, repo):
        """FM-unversioned-run: a measured record carries the revision and whether the tree was
        dirty, so staleness and a reader can tell which code it measured."""
        emit_yaml(repo, "echo nothing-structured")
        decl = load(repo)
        store = Store(repo)
        execute(repo, store, decl, decl.tests["TST-grasp-ik"])
        head = git(repo, "rev-parse", "HEAD").stdout.strip()
        [record] = store.effective_trials()
        assert record["repro"]["sw_revision"] and head.startswith(record["repro"]["sw_revision"])
        assert "sw_dirty" in record["repro"]

    @pytest.mark.parametrize("command, problem", [
        ("echo nothing-structured", "the test wrote no $OUT file"),
        ("python -c \"import os; os.makedirs(os.environ['OUT'])\"", "$OUT is a directory, not a file"),
        ("python -c \"import os; open(os.environ['OUT'], 'w').write('{not json')\"",
         "$OUT is not valid JSON"),
        ("python -c \"import os; open(os.environ['OUT'], 'w').write('{}')\"",
         "$OUT is JSON in none of the accepted shapes"),
    ])
    def test_a_result_it_cannot_read_is_named_not_crashed_on(self, repo, command, problem):
        """A measure in several parts that made $OUT a directory crashed the run before anything
        was recorded; each way $OUT can be wrong is now a fallback that says which it was."""
        emit_yaml(repo, command)
        decl = load(repo)
        result = execute(repo, Store(repo), decl, decl.tests["TST-grasp-ik"])
        assert result["synthesized_from_exit_code"] is True
        assert result["result_problem"] == problem
        if "directory" in problem:
            assert result["artifact_uri"].endswith("stdout.txt"), "a directory is not hashed"

    def test_failing_command_records_a_failing_trial(self, repo):
        emit_yaml(repo, "exit 1")
        decl = load(repo)
        store = Store(repo)
        result = execute(repo, store, decl, decl.tests["TST-grasp-ik"])
        assert result["exit_code"] != 0
        assert result["outcome_counts"] == {"fail": 1}

    @staticmethod
    def _tool_env(tmp_path_factory, monkeypatch):
        """A server interpreter in an isolated tool environment outside the project, as uvx
        installs one; its directory leads PATH, as uvx leaves it."""
        tool = tmp_path_factory.mktemp("uv-cache") / "tool-env"
        own = tool / ("Scripts" if os.name == "nt" else "bin")
        monkeypatch.setattr("sys.executable", str(own / "python"))
        return tool, own

    def test_a_plugin_server_runs_tests_with_the_projects_python(self, repo, tmp_path_factory, monkeypatch):
        from component_belief.runner import project_environment

        tool, own = self._tool_env(tmp_path_factory, monkeypatch)
        project_bin = repo / ".venv" / ("Scripts" if os.name == "nt" else "bin")
        project_bin.mkdir(parents=True)
        env = project_environment(repo, {"PATH": os.pathsep.join([str(own), "/usr/bin"]),
                                         "VIRTUAL_ENV": str(tool), "CLAUDE_PLUGIN_ROOT": "p"})
        entries = env["PATH"].split(os.pathsep)
        assert entries[0] == str(project_bin)
        assert str(own) not in entries and "/usr/bin" in entries
        assert env["VIRTUAL_ENV"] == str(repo / ".venv")

    def test_a_plugin_server_never_lends_tests_its_own_python(self, repo, tmp_path_factory, monkeypatch):
        """No project .venv: the harness's interpreter still leaves PATH, so `python` is whatever
        the client inherited -- or missing, which fails loudly -- never the harness's own."""
        from component_belief.runner import project_environment

        tool, own = self._tool_env(tmp_path_factory, monkeypatch)
        env = project_environment(repo, {"PATH": os.pathsep.join([str(own), "/usr/bin"]),
                                         "VIRTUAL_ENV": str(tool), "CLAUDE_PLUGIN_ROOT": "p"})
        assert env["PATH"].split(os.pathsep) == ["/usr/bin"]
        assert "VIRTUAL_ENV" not in env

    def test_outside_a_plugin_the_servers_environment_is_left_alone(self, repo, tmp_path_factory, monkeypatch):
        from component_belief.runner import project_environment

        tool, own = self._tool_env(tmp_path_factory, monkeypatch)
        inherited = {"PATH": os.pathsep.join([str(own), "/usr/bin"]), "VIRTUAL_ENV": str(tool)}
        assert project_environment(repo, inherited) == inherited

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
            source="ci", artifact_uri=str(results_file(project)),
        )
        assert "rejected" in out
        assert "repro" in out

    def test_ingest_requires_an_artifact(self, project):
        assert "artifact_uri is required" in server.ingest(records=[], source="ci", artifact_uri="")

    @pytest.mark.parametrize("uri, problem", [
        ("ci://run/1", "it is a URL"),
        ("out/never-written.json", "nothing exists at that path"),
        ("out", "it is a directory"),
        ("out/a.json out/b.json", "it names more than one path"),
        ("out/a.json ; out/b.json", "it names more than one path"),
    ])
    def test_ingest_refuses_an_artifact_it_cannot_read(self, project, uri, problem):
        """DEF-belief-eligible: an import comes with an artifact and its hash. The server can
        hash only bytes it can read, one file of them, so a URL, a missing path, a directory or
        two paths in one string imports nothing -- and the refusal says which it was."""
        (project / "out").mkdir(exist_ok=True)
        for name in ("a.json", "b.json"):
            (project / "out" / name).write_text("[]", encoding="utf-8")
        out = server.ingest(records=[complete_record()], source="ci", artifact_uri=uri)
        assert "not a file on this machine" in out and problem in out
        assert Store(project).effective_trials() == []

    def test_ingest_refuses_a_test_the_contract_does_not_list(self, project):
        out = server.ingest(records=[complete_record(test_id="TST-never-declared")],
                            source="ci", artifact_uri=str(results_file(project)))
        assert "ingested 0 record" in out
        assert "is not a test CTR-grasp-reachable lists in evaluable_by" in out
        assert Store(project).effective_trials() == []
        assert not list(Store(project).artifacts_dir.glob("RUN-*")), "a rejected import copies nothing"

    def test_ingest_accepts_a_complete_record(self, project):
        original = results_file(project)
        out = server.ingest(records=[complete_record(artifact_hash="0000000000000000")],
                            source="ci", artifact_uri=str(original))
        assert "ingested 1 record" in out
        [t] = Store(project).effective_trials()
        assert t["provenance"] == "imported"
        assert t["source_system"] == "ci"
        assert t["test_ref"] == load(project).tests["TST-grasp-ik"].ref

        # the server's copy, hashed by the server; the caller's hash is not what is recorded
        copy = project / t["artifact_uri"]
        assert t["artifact_uri"].startswith(".belief/artifacts/")
        assert copy.read_bytes() == original.read_bytes()
        assert t["artifact_hash"] == hashlib.sha256(original.read_bytes()).hexdigest()[:16]
        assert t["source_artifact"] == str(original.resolve())

    def test_an_import_naming_a_bare_test_id_records_the_declared_version(self, project):
        """412,060 imports in one project carried `test_ref: TST-x` with no version, which no
        later edit of the test could ever make stale. The declared version is recorded instead."""
        out = server.ingest(records=[complete_record(test_ref="TST-grasp-ik")], source="ci",
                            artifact_uri=str(results_file(project)))
        assert "ingested 1 record" in out
        [t] = Store(project).effective_trials()
        assert t["test_ref"] == load(project).tests["TST-grasp-ik"].ref

    def test_a_fabricated_import_cannot_adopt(self, project):
        """The probe that found the hole: an undeclared test, no hash, an artifact that does not
        exist, an empty repro. It must neither record a trial nor let a policy adopt."""
        fabricated = complete_record(test_id="TST-never-declared", repro={})
        for uri in ("nowhere/none.json", str(results_file(project))):
            server.ingest(records=[fabricated], source="CI", artifact_uri=uri)
        assert Store(project).effective_trials() == []
        assert not server.decide(change_id="CHG-x", approver="David").startswith("ADOPT")

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


class TestNoDeclarationsInEffect:
    """An uncommitted belief.yaml must not read as a clean bill of health."""

    @pytest.fixture
    def uncommitted(self, empty_repo, monkeypatch):
        from conftest import BASE_YAML
        (empty_repo / "belief.yaml").write_text(BASE_YAML, encoding="utf-8")
        monkeypatch.setenv("BELIEF_PROJECT_ROOT", str(empty_repo))
        return empty_repo

    @pytest.mark.parametrize("view", ["belief", "diagnose", "plan", "cycle", "trace"])
    def test_evidence_views_name_the_blocker(self, uncommitted, view):
        out = server.status(view=view)
        assert "NONE IN EFFECT" in out
        assert "UNCOMMITTED" in out
        assert "next: commit belief.yaml" in out
        assert "every observed component is supported" not in out
        assert "no belief-eligible evidence for that subject" not in out

    def test_graph_and_coverage_keep_their_headers(self, uncommitted):
        for view in ("graph", "coverage"):
            assert "NONE IN EFFECT" in server.status(view=view)

    def test_run_test_and_decide_point_at_the_commit(self, uncommitted):
        assert "next: commit belief.yaml" in server.run_test(test_id="TST-grasp-ik")
        assert "next: commit belief.yaml" in server.decide(change_id="CHG-1")

    def test_missing_file_says_author_it(self, empty_repo, monkeypatch):
        monkeypatch.setenv("BELIEF_PROJECT_ROOT", str(empty_repo))
        assert "author belief.yaml" in server.status(view="diagnose")


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


class TestGoals:
    """The human's side of the surface: one view to check in with, and a decision rule under which
    committing goals.yaml is the approval."""

    @pytest.fixture
    def goals(self, goals_repo, monkeypatch):
        monkeypatch.setenv("BELIEF_PROJECT_ROOT", str(goals_repo))
        monkeypatch.setenv("BELIEF_ACTOR", "test-agent")
        return goals_repo

    @staticmethod
    def measure_all():
        for tid in ("TST-see", "TST-pick", "TST-cloud-fits"):
            assert "exit=0" in server.run_test(tid)

    def test_the_goals_view_is_what_you_read_to_check_in(self, goals):
        view = server.status(view="goals")
        assert "GOL-grasp  UNMEASURED -- The arm picks up the object it is asked for" in view
        assert "CTR-pick-success: no evidence yet -- run TST-pick" in view
        assert "IFC-see__grasp  GOL-see -> GOL-grasp  UNMEASURED" in view
        assert "served by: CMP-grasp" in view
        assert "you last committed the goal set in" in view and "my goals" in view
        assert "guard: NOT INSTALLED" in view and "tdlp-guard install" in view

        server.note("GOL-grasp", "0.8 is out of reach on the old arm; propose 0.7 on the tabletop scene")
        self.measure_all()
        view = server.status(view="goals")
        assert "GOL-grasp  MET" in view and "IFC-see__grasp  GOL-see -> GOL-grasp  MET" in view
        assert "proposals on your goals (1):" in view and "propose 0.7" in view
        assert "basis:" in view

    def test_without_goals_the_view_says_what_to_write(self, project):
        view = server.status(view="goals")
        assert "no goals in effect" in view and "commit it yourself" in view

    def test_an_adoption_under_your_goals_needs_no_approver(self, goals):
        self.measure_all()
        out = server.decide("CHG-1")
        assert out.startswith("ADOPT recorded") and "no approver needed" in out
        [decision] = Store(goals).decisions()
        assert decision["approver"] is None and decision["criteria_committed"]["goals.yaml"]

    def test_after_the_agent_touches_your_goal_set_it_needs_you_again(self, goals):
        from conftest import commit_as_agent

        self.measure_all()
        commit_as_agent(goals, "goals.yaml",
                        (goals / "goals.yaml").read_text(encoding="utf-8") + "# tidied\n", "tidy goals")
        out = server.decide("CHG-2")
        assert "NOT RECORDED" in out and "the agent changed your goal set" in out
        assert "changes to your goal set by the agent" in server.status(view="goals")
        assert "tidy goals" in server.status(view="goals")

        (goals / "goals.yaml").write_text(
            (goals / "goals.yaml").read_text(encoding="utf-8") + "# fine\n", encoding="utf-8")
        git(goals, "commit", "-q", "-am", "reviewed the tidy")
        assert server.decide("CHG-2").startswith("ADOPT recorded")

    def test_a_policy_in_belief_yaml_still_needs_an_approver(self, goals):
        from conftest import trial

        # current evidence in both lighting buckets, so the policy reaches the approval question
        Store(goals).append_trials([{**trial(ik=True, lighting=light), "repro": {"model_revision": "v3"}}
                                    for light in ("normal", "low") for _ in range(40)])
        out = server.decide("CHG-3", policy_id="POL-release")
        assert "requires a human approver" in out and "Not covered by your goals.yaml" in out
