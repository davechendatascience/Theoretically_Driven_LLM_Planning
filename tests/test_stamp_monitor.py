"""stamp-monitor: the joins across both ledgers, their integrity, and the history's conformance.

What is asserted is what the monitor claims to see -- and that it writes nothing while seeing it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from conftest import BASE_YAML, git, trial
from stamp_monitor import BLOCK, INFO, WARN
from stamp_monitor.audit import audit
from stamp_monitor.impact import impact, render
from stamp_monitor.workflow import workflow

CLAIMED_YAML = BASE_YAML.replace(
    "    remediation: Retune approach sampling\n",
    "    remediation: Retune approach sampling\n    code: [grasp.py]\n",
).replace('run: "echo ok"', 'run: "python check.py $OUT"').replace(
    "    capture: [lighting, model_revision]\n",
    "    capture: [lighting, model_revision]\n    reads: [fixtures.py]\n")

CHECK_PY = ("import json, sys\n"
            "json.dump([{'metrics': {'ik_success': True}} for _ in range(5)], open(sys.argv[1], 'w'))\n")

DESIGN_YAML = """
axioms:
  - id: AXM-reach
    domain: manipulation
    statement: A grasp the arm cannot reach is not a grasp.
    rationale: Kinematics.
definitions:
  - id: DEF-reachable
    term: Reachable
    meaning: IK returns a solution.
branches:
  - id: BRN-grasp-reach
    subject: CMP-grasp
    claim_type: contract
    statement: The planner only proposes reachable poses.
    premises: [AXM-reach, DEF-reachable]
    derivation_rule: DEF-reachable is what CTR-grasp-reachable scores.
policies:
  - id: POL-consistency-gate
    criteria:
      - {target: BRN-grasp-reach, require: proven, evidence: supported}
"""


@pytest.fixture
def project(repo: Path, monkeypatch) -> Path:
    (repo / "grasp.py").write_text("# v1\n", encoding="utf-8")
    (repo / "fixtures.py").write_text("# shared fixtures\n", encoding="utf-8")
    (repo / "check.py").write_text(CHECK_PY, encoding="utf-8")
    (repo / "belief.yaml").write_text(CLAIMED_YAML, encoding="utf-8")
    (repo / "consistency.yaml").write_text(DESIGN_YAML, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "a claimed component, a test, a design branch")
    monkeypatch.setenv("BELIEF_PROJECT_ROOT", str(repo))
    monkeypatch.setenv("STAMP_MONITOR_ROOT", str(repo))
    return repo


def run(repo: Path) -> dict:
    from component_belief.declarations import load
    from component_belief.runner import run_test
    from component_belief.store import Store

    decl = load(repo)
    return run_test(repo, Store(repo), decl, decl.tests["TST-grasp-ik"])


def commit(repo: Path, path: str, text: str, message: str = "change") -> None:
    (repo / path).write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


def codes(findings) -> dict[str, str]:
    return {f.code: f.severity for f in findings}


# --- impact ----------------------------------------------------------------------------------

class TestImpact:
    def test_a_claimed_change_is_traced_through_both_ledgers(self, project):
        run(project)
        commit(project, "grasp.py", "# v2\n", "change the planner")
        result = impact(project, "HEAD~1")
        assert result.components == {"CMP-grasp": ["grasp.py"]}
        assert result.contracts == {"CTR-grasp-reachable": "stale"}, "stale is measured at HEAD"
        assert result.branches == {"BRN-grasp-reach": ["governs CMP-grasp", "cites CTR-grasp-reachable"]}
        assert result.policies["POL-release"] == ["CTR-grasp-reachable"]
        assert result.policies["POL-consistency-gate"] == ["BRN-grasp-reach"]
        assert result.reruns == ["TST-grasp-ik"]
        assert "next: run_test TST-grasp-ik" in render(result)

    def test_a_declared_read_is_part_of_the_chain(self, project):
        run(project)
        commit(project, "fixtures.py", "# fixtures changed\n")
        result = impact(project, "HEAD~1")
        assert result.tests == {"TST-grasp-ik": ["fixtures.py"]} and not result.components
        assert result.contracts == {"CTR-grasp-reachable": "stale"}

    def test_an_unrelated_change_touches_nothing_and_says_so(self, project):
        run(project)
        commit(project, "notes.md", "# notes\n")
        result = impact(project, "HEAD~1")
        assert not (result.components or result.contracts or result.branches or result.reruns)
        assert result.unclaimed == ["notes.md"]

    def test_uncommitted_edits_stale_nothing_but_name_the_rerun(self, project):
        run(project)
        (project / "grasp.py").write_text("# edited, not committed\n", encoding="utf-8")
        result = impact(project, "HEAD")
        assert result.uncommitted == ["grasp.py"]
        assert "stale" not in result.contracts["CTR-grasp-reachable"]
        assert result.reruns == ["TST-grasp-ik"]
        assert impact(project, "HEAD", worktree=False).components == {}

    def test_an_unknown_base_is_an_answer_not_a_crash(self, project):
        assert "does not know" in render(impact(project, "no-such-rev"))


# --- audit -----------------------------------------------------------------------------------

class TestAudit:
    def test_a_fresh_run_audits_clean(self, project):
        run(project)
        assert not [f for f in audit(project) if f.severity in (BLOCK, WARN)]

    def test_an_edited_artifact_is_caught(self, project):
        from component_belief.store import Store

        result = run(project)
        (Store(project).artifacts_dir / result["run_id"] / "result.json").write_text("[]", encoding="utf-8")
        assert codes(audit(project)).get("ARTIFACT_HASH_MISMATCH") == BLOCK

    def test_a_line_ending_rewrite_is_not_tampering(self, project):
        """A checkout on another platform rewrites LF to CRLF; the record did not change."""
        from component_belief.store import Store

        result = run(project)
        path = Store(project).artifacts_dir / result["run_id"] / "result.json"
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
        assert "ARTIFACT_HASH_MISMATCH" not in codes(audit(project))

    def test_a_run_hashed_on_windows_and_checked_out_as_lf_is_not_tampering(self, project):
        """The other direction: the runner on Windows hashed CRLF, git stored LF, and the clone
        here holds LF. 43 artifacts in this repository read as tampered until both counted."""
        import hashlib
        import json

        from component_belief.store import Store

        result = run(project)
        path = Store(project).artifacts_dir / result["run_id"] / "result.json"
        crlf = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        ledger = project / ".belief" / "evidence.jsonl"
        records = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
        for record in records:
            if record.get("run_id") == result["run_id"]:
                record["artifact_hash"] = hashlib.sha256(crlf).hexdigest()[:16]
        ledger.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
        assert "ARTIFACT_HASH_MISMATCH" not in codes(audit(project))
        path.write_text("[]", encoding="utf-8")
        assert codes(audit(project)).get("ARTIFACT_HASH_MISMATCH") == BLOCK, "an edit still is"

    def test_a_run_recorded_on_windows_audits_clean_elsewhere(self, project):
        """A run on Windows recorded its artifact path with backslashes. The file is present in
        every clone, and the audit read 43 of them in this repository as gone."""
        import json

        run(project)
        ledger = project / ".belief" / "evidence.jsonl"
        lines = []
        for line in ledger.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if record.get("artifact_uri"):
                record["artifact_uri"] = record["artifact_uri"].replace("/", "\\")
            lines.append(json.dumps(record))
        ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
        assert "ARTIFACT_MISSING" not in codes(audit(project))

    def test_a_run_records_its_artifact_path_the_same_on_every_platform(self, project):
        assert "\\" not in run(project)["artifact_uri"]

    def test_a_missing_artifact_whose_records_are_all_set_aside_informs(self, project, monkeypatch):
        """The remedy for an artifact nobody can audit is to set its records aside with amend.
        The audit read raw trials and went on blocking after every record was quarantined;
        it now says what was done and stops blocking -- but only once nothing counts on it."""
        from component_belief import server
        from component_belief.store import Store

        monkeypatch.setenv("BELIEF_PROJECT_ROOT", str(project))
        result = run(project)
        (Store(project).artifacts_dir / result["run_id"] / "result.json").unlink()
        assert codes(audit(project))["ARTIFACT_MISSING"] == BLOCK

        ids = result["evidence_ids"]
        server.amend(evidence_ids=ids[:-1], validity="quarantined", reason="artifact lost")
        assert codes(audit(project))["ARTIFACT_MISSING"] == BLOCK, "one record still counts"

        server.amend(evidence_id=ids[-1], validity="quarantined", reason="artifact lost")
        [finding] = [f for f in audit(project) if f.code == "ARTIFACT_MISSING"]
        assert finding.severity == INFO
        assert f"all {len(ids)} of its records are set aside (quarantined: artifact lost)" in finding.message

    def test_an_unhashed_import_set_aside_is_no_longer_a_warning(self, project, monkeypatch):
        import json

        from component_belief import server

        monkeypatch.setenv("BELIEF_PROJECT_ROOT", str(project))
        run(project)
        ledger = project / ".belief" / "evidence.jsonl"
        records = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
        old = {**records[0], "id": "EV-9000", "run_id": "RUN-0900", "provenance": "imported",
               "artifact_hash": ""}
        ledger.write_text("".join(json.dumps(r) + "\n" for r in records + [old]), encoding="utf-8")
        assert codes(audit(project))["IMPORT_UNHASHED"] == WARN

        server.amend(evidence_id="EV-9000", validity="quarantined", reason="predates hashing")
        unhashed = [f for f in audit(project) if f.code == "IMPORT_UNHASHED"]
        assert [f.severity for f in unhashed] == [INFO] and "RUN-0900" in unhashed[0].message

    def test_an_edited_stamp_and_a_damaged_ledger_line_are_caught(self, project):
        from component_belief.store import Store

        result = run(project)
        stamp = Store(project).artifacts_dir / result["run_id"] / "stamp.json"
        stamp.write_text(stamp.read_text(encoding="utf-8").replace('"version": 1', '"version": 9'),
                         encoding="utf-8")
        with (project / ".belief" / "evidence.jsonl").open("a", encoding="utf-8") as fh:
            fh.write('{"kind": "trial", "id": "EV-9999", truncated\n')
        found = codes(audit(project))
        assert found.get("STAMP_UNTRUSTED") == BLOCK
        assert found.get("LEDGER_UNPARSABLE") == BLOCK

    def test_duplicate_ids_and_dangling_citations(self, project):
        from component_belief.store import Store

        store = Store(project)
        store._append(store.evidence_path, {**trial(id="EV-0001"), "kind": "trial"})
        store._append(store.evidence_path, {**trial(id="EV-0001"), "kind": "trial"})
        store.append_amendment("EV-4040", validity="invalid", reason="r")
        store.append_decision({"change_id": "C", "status": "hold", "evidence_ids": ["EV-7777"]})
        found = codes(audit(project))
        assert found.get("DUPLICATE_ID") == BLOCK
        assert found.get("AMENDMENT_TARGET_UNKNOWN") == WARN
        assert found.get("DECISION_EVIDENCE_UNKNOWN") == BLOCK

    def test_an_import_audits_like_a_run(self, project):
        """ingest keeps its own copy: editing the original changes nothing, editing the copy is
        tampering with the ledger's artifact."""
        from component_belief import server
        from component_belief.store import Store

        original = project / "out" / "robot.trials.json"
        original.parent.mkdir()
        original.write_text('[{"ik_success": true}]', encoding="utf-8")
        server.ingest(records=[{"contract_id": "CTR-grasp-reachable", "test_id": "TST-grasp-ik",
                                "outcome": "pass", "metrics": {"ik_success": True},
                                "repro": {"model_revision": "v3"}}],
                      source="bench", artifact_uri=str(original))
        original.write_text("[]", encoding="utf-8")
        assert not [f for f in audit(project) if f.severity in (BLOCK, WARN)]

        [t] = Store(project).effective_trials()
        (project / t["artifact_uri"]).write_text("[]", encoding="utf-8")
        assert codes(audit(project)).get("ARTIFACT_HASH_MISMATCH") == BLOCK

    def test_an_import_recorded_without_a_hash_is_reported(self, project):
        """Before ingest hashed what it imports, an import could name a URL and carry no hash."""
        from component_belief.store import Store

        Store(project).append_trials([{**trial(), "provenance": "imported", "run_id": "RUN-0007",
                                       "artifact_uri": "ci://run/1"}])
        found = codes(audit(project))
        assert found.get("ARTIFACT_MISSING") == BLOCK
        assert found.get("IMPORT_UNHASHED") == WARN

    def test_uncommitted_declarations_are_reported(self, project):
        (project / "belief.yaml").write_text(CLAIMED_YAML + "\n# a lowered threshold\n", encoding="utf-8")
        assert codes(audit(project)).get("DECLARATIONS_PENDING") == WARN


# --- workflow --------------------------------------------------------------------------------

class TestWorkflow:
    def test_reclassifying_only_failures_is_a_pattern(self, project):
        from component_belief.store import Store

        store = Store(project)
        ids = store.append_trials([trial(ik=False, outcome="fail") for _ in range(3)]
                                  + [trial(ik=True) for _ in range(3)])
        for eid in ids[:3]:
            store.append_amendment(eid, validity="invalid", reason="rig was off")
        assert codes(workflow(project)).get("AMEND_ONLY_ADVERSE") == WARN

    def test_a_single_retraction_is_reported_not_flagged(self, project):
        from component_belief.store import Store

        store = Store(project)
        ids = store.append_trials([trial(ik=False, outcome="fail"), trial(ik=True)])
        store.append_amendment(ids[0], validity="invalid", reason="the fixture was mis-seeded")
        found = workflow(project)
        assert codes(found).get("AMEND_ADVERSE") == INFO
        assert "the fixture was mis-seeded" in found[0].message

    def test_an_agent_cannot_approve_its_own_adoption(self, project):
        from component_belief.store import Store

        store = Store(project)
        store.append_decision({"change_id": "C1", "status": "adopt", "approver": "agent"})
        store.append_decision({"change_id": "C2", "status": "adopt", "approver": None})
        store.append_decision({"change_id": "C3", "status": "adopt", "approver": "david"})
        found = {(f.code, f.subject) for f in workflow(project)}
        assert ("SELF_APPROVAL", ".belief/DEC-0001") in found
        assert ("UNAPPROVED_ADOPTION", ".belief/DEC-0002") in found
        assert not any(s == ".belief/DEC-0003" for _, s in found)

    def test_an_adoption_on_evidence_since_gone_stale(self, project):
        from component_belief.store import Store

        result = run(project)
        Store(project).append_decision({"change_id": "C", "status": "adopt", "approver": "david",
                                        "head": "abc", "evidence_ids": result["evidence_ids"]})
        assert "ADOPTION_NOW_STALE" not in codes(workflow(project))
        commit(project, "grasp.py", "# v2\n")
        assert codes(workflow(project)).get("ADOPTION_NOW_STALE") == INFO

    def test_a_decision_on_dirty_tree_evidence(self, project):
        from component_belief.store import Store

        (project / "grasp.py").write_text("# uncommitted\n", encoding="utf-8")
        result = run(project)
        Store(project).append_decision({"change_id": "C", "status": "hold",
                                        "evidence_ids": result["evidence_ids"]})
        assert codes(workflow(project)).get("DECISION_ON_DIRTY_EVIDENCE") == WARN


# --- the surface -----------------------------------------------------------------------------

def _ledger_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted((root / ".belief").rglob("*")):
        if path.is_file() and "cache" not in path.parts:
            digest.update(str(path.relative_to(root)).encode() + path.read_bytes())
    return digest.hexdigest()


def test_the_tools_read_and_never_write(project):
    from stamp_monitor import server

    run(project)
    commit(project, "grasp.py", "# v2\n")
    before = _ledger_digest(project)
    assert "CTR-grasp-reachable [stale]" in server.impact()
    assert server.audit().startswith("audit:")
    assert server.workflow().startswith("workflow:")
    assert _ledger_digest(project) == before, "a monitor that writes is not a monitor"


def test_the_cli_exits_nonzero_on_a_block(project, capsys):
    from component_belief.store import Store
    from stamp_monitor.cli import main

    assert main(["audit"]) == 0
    Store(project).append_decision({"change_id": "C", "status": "adopt", "approver": "agent"})
    assert main(["workflow"]) == 1
    assert "SELF_APPROVAL" in capsys.readouterr().out
    assert json.loads((project / ".belief" / "decisions.jsonl").read_text().splitlines()[0])["approver"] == "agent"


# --- goals ------------------------------------------------------------------------------------

class TestGoals:
    @pytest.fixture
    def goals(self, goals_repo, monkeypatch):
        monkeypatch.setenv("BELIEF_PROJECT_ROOT", str(goals_repo))
        return goals_repo

    def test_an_adoption_your_goals_approved_is_not_self_approval(self, goals):
        from component_belief import server

        for tid in ("TST-see", "TST-pick", "TST-cloud-fits"):
            server.run_test(tid)
        assert server.decide("CHG-1").startswith("ADOPT recorded")
        found = codes(workflow(goals))
        assert "UNAPPROVED_ADOPTION" not in found and "SELF_APPROVAL" not in found

    def test_an_agent_commit_to_the_goal_set_is_a_finding_until_you_commit_it(self, goals):
        from conftest import commit_as_agent

        commit_as_agent(goals, "eval/pick.py", "# always pass\n", "loosen the pick check")
        assert codes(workflow(goals)).get("GOAL_SET_CHANGED_BY_AGENT") == WARN
        (goals / "eval" / "pick.py").write_text("# restored\n", encoding="utf-8")
        git(goals, "commit", "-q", "-am", "put the pick check back")
        assert "GOAL_SET_CHANGED_BY_AGENT" not in codes(workflow(goals))

    def test_a_change_to_a_serving_component_reaches_the_goal_it_serves(self, goals):
        commit(goals, "grasp.py", "# v2\n", "change the planner")
        result = impact(goals, "HEAD~1")
        assert result.components == {"CMP-grasp": ["grasp.py"]}
        assert {"CTR-pick-success", "CTR-cloud-fits-grasp"} <= set(result.contracts), \
            "a goal and the hand-over into it rest on the components that serve them"
        assert result.policies["POL-goals"] == ["CTR-pick-success", "CTR-cloud-fits-grasp"]
