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
