"""graph-snapshot: the design graph at one revision, drawn as one page.

One case per failure mode belief.yaml declares on CMP-graph-snapshot. The project below is small
and built to hold one of each gap the join can show: an axiom naming no goal, a goal no axiom
names, a component with code and no design, goals no branch governs, and ground nothing rests on.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import tomllib
from pathlib import Path

import pytest

from conftest import git

REPO = Path(__file__).resolve().parents[1]

BELIEF = """
components:
  - id: CMP-motion
    purpose: Plan motion
    testable_capability: Produces a trajectory that clears obstacles
    failure_modes: [{id: FM-clip, observable: trajectory clips an obstacle}]
    remediation: Retune the clearance margin
    goal: GOL-move
    code: [motion.py]
  - id: CMP-gripper
    purpose: Close the jaws
    testable_capability: Holds an object through a carry
    failure_modes: [{id: FM-drop, observable: object leaves the jaws}]
    remediation: Raise the squeeze
    goal: GOL-hold
    code: [gripper.py]

contracts:
  - id: CTR-motion-clear
    subject: CMP-motion
    kind: gate
    metrics: [{id: passed, unit: bool}]
    acceptance: {rule: "passed == true"}
    evaluable_by: [TST-motion]

tests:
  - id: TST-motion
    layer: component
    targets: [CMP-motion]
    run: python check_motion.py $OUT
    metrics: [passed]
"""

GOALS = """
goals:
  - {id: GOL-move, outcome: The arm reaches where it is sent, measure: CTR-reaches}
  - {id: GOL-hold, outcome: The gripper holds what it picks up, measure: CTR-holds}
contracts:
  - {id: CTR-reaches, subject: GOL-move, kind: gate, metrics: [{id: passed, unit: bool}],
     acceptance: {rule: "passed == true"}, evaluable_by: [TST-reach]}
  - {id: CTR-holds, subject: GOL-hold, kind: gate, metrics: [{id: passed, unit: bool}],
     acceptance: {rule: "passed == true"}, evaluable_by: [TST-hold]}
tests:
  - {id: TST-reach, layer: e2e, targets: [GOL-move], run: python eval/reach.py $OUT, metrics: [passed]}
  - {id: TST-hold, layer: e2e, targets: [GOL-hold], run: python eval/hold.py $OUT, metrics: [passed]}
policies:
  - id: POL-goals
    criteria:
      - {slice: CTR-reaches, require: supported}
      - {slice: CTR-holds, require: supported}
"""

CONSISTENCY = """
components:
  - {id: CMP-motion, note: the planner}

axioms:
  - id: AXM-safety
    domain: safety
    goal: GOL-move
    statement: The robot must not collide.
    rationale: Core physical safety invariant.
  - id: AXM-unused
    domain: style
    statement: Names read as plain words.
    rationale: Nothing rests on this one, and it names no goal.

definitions:
  - id: DEF-clearance
    term: Clearance
    meaning: The distance from the tool to the nearest obstacle.
  - id: DEF-spare
    term: Spare
    meaning: A term no claim uses.

lemmas:
  - id: LMA-clear-means-safe
    statement: A trajectory that keeps its clearance above zero does not collide.
    premises: [AXM-safety, DEF-clearance]
    derivation_rule: By DEF-clearance, clearance above zero is no contact; by AXM-safety that is what must hold.

branches:
  - id: BRN-motion-gate
    subject: CMP-motion
    claim_type: contract
    statement: The motion gate aborts a trajectory whose clearance reaches zero.
    premises: [LMA-clear-means-safe, DEF-clearance]
    derivation_rule: "By LMA-clear-means-safe. evidence: CTR-motion-clear"

policies:
  - id: POL-gate
    criteria:
      - {target: BRN-motion-gate, require: proven, evidence: supported}
"""

PASS = [{"strategy": s, "outcome": "sound", "rationale": f"{s}: follows from the premises"}
        for s in ("counterexample", "entailment", "negation")]


def commit(root: Path, files: dict[str, str], message: str) -> str:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)
    return git(root, "rev-parse", "HEAD").stdout.strip()


@pytest.fixture
def project(empty_repo: Path, monkeypatch) -> Path:
    commit(empty_repo, {"belief.yaml": BELIEF, "goals.yaml": GOALS, "consistency.yaml": CONSISTENCY,
                        "motion.py": "# v1\n", "gripper.py": "# v1\n", "check_motion.py": "# check\n"},
           "declare")
    for var in ("GRAPH_SNAPSHOT_ROOT", "CONSISTENCY_PROJECT_ROOT", "BELIEF_PROJECT_ROOT"):
        monkeypatch.setenv(var, str(empty_repo))
    from consistency_belief.server import verify_step

    verify_step("LMA-clear-means-safe", trials=PASS)          # proven; the branch stays an obligation
    return empty_repo


def page_data(root: Path) -> dict:
    text = (root / ".graph-snapshot" / "snapshot.html").read_text(encoding="utf-8")
    return json.loads(re.search(r'<script type="application/json" id="snapshot">(.*?)</script>', text, re.S).group(1))


def tree_digest(root: Path) -> dict[str, str]:
    """Every file in the project outside .git and the page's directory, by content."""
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*"))
            if p.is_file() and ".git" not in p.relative_to(root).parts[:1]
            and ".graph-snapshot" not in p.relative_to(root).parts[:1]}


def test_every_proof_state_is_the_one_the_server_computes(project):
    from consistency_belief.views import Context
    from graph_snapshot.server import snapshot
    from graph_snapshot.snapshot import take

    snap = take(project)
    computed = {s.target_id: s.state for s in Context.build(project).slices}
    assert set(computed.values()) == {"proven", "obligation"}, "the case needs more than one state"
    assert {n: snap["nodes"][n]["state"] for n in computed} == computed
    snapshot()
    shown = page_data(project)["nodes"]
    assert {n: shown[n]["state"] for n in computed} == computed


def test_a_commit_during_a_snapshot_does_not_mix_revisions(project, monkeypatch):
    """The commit lands after HEAD was resolved and before either declaration file was read."""
    from consistency_belief.views import Context
    from graph_snapshot.snapshot import take

    before = git(project, "rev-parse", "HEAD").stdout.strip()
    build = Context.build.__func__

    def build_after_a_commit(cls, root, staged_nodes=None, revision="HEAD"):
        commit(project, {
            "consistency.yaml": CONSISTENCY.replace("definitions:", "  - {id: AXM-late, domain: x, statement: Late., rationale: Late.}\n\ndefinitions:"),
            "belief.yaml": BELIEF.replace("contracts:", "  - {id: CMP-late, purpose: Late, testable_capability: Late, remediation: Late}\n\ncontracts:"),
        }, "a commit mid-snapshot")
        return build(cls, root, staged_nodes, revision)

    monkeypatch.setattr(Context, "build", classmethod(build_after_a_commit))
    snap = take(project)
    assert git(project, "rev-parse", "HEAD").stdout.strip() != before, "the commit did land"
    assert snap["sha"] == before
    assert "AXM-late" not in snap["nodes"] and "CMP-late" not in snap["nodes"]


def test_a_proposal_shows_as_the_ledger_stages_it(project):
    """Restaged, a proposal shows in its latest version; withdrawn, it does not show at all."""
    from consistency_belief.server import propose_branch, withdraw
    from graph_snapshot.snapshot import take

    propose_branch(id="BRN-grip-holds", subject="CMP-gripper", premises=["AXM-safety"],
                   claim="The gripper holds what it closes on.", rationale="first wording")
    propose_branch(id="BRN-grip-holds", subject="CMP-gripper", premises=["AXM-safety", "DEF-clearance"],
                   claim="The gripper holds what it closes on, clear of the arm.", rationale="second wording")
    propose_branch(id="BRN-grip-gone", subject="CMP-gripper", premises=["AXM-safety"],
                   claim="A design that will not be built.", rationale="withdrawn below")
    withdraw("BRN-grip-gone", reason="not built")
    nodes = take(project)["nodes"]
    staged = nodes["BRN-grip-holds"]
    assert staged["staged"] and staged["text"] == "The gripper holds what it closes on, clear of the arm."
    assert staged["premises"] == ["AXM-safety", "DEF-clearance"]
    assert "BRN-grip-gone" not in nodes


def test_uncommitted_edits_are_named_and_not_shown(project):
    from graph_snapshot.server import snapshot
    from graph_snapshot.snapshot import take

    (project / "consistency.yaml").write_text(
        CONSISTENCY.replace("definitions:", "  - {id: AXM-draft, domain: x, statement: Draft., rationale: Draft.}\n\ndefinitions:"),
        encoding="utf-8")
    snap = take(project)
    assert "AXM-draft" not in snap["nodes"]
    assert snap["pending"] == ["consistency.yaml"]
    assert "uncommitted edits, not shown: consistency.yaml" in snapshot()


def test_the_joined_graph_lists_its_gaps(project):
    from graph_snapshot.snapshot import take

    found = {(i["code"], i["subject"]) for i in take(project)["issues"] if i["source"] == "joined graph"}
    assert found == {
        ("AXIOM_WITHOUT_GOAL", "AXM-unused"),
        ("GOAL_WITHOUT_AXIOM", "GOL-hold"),
        ("UNDECLARED_DESIGN", "CMP-gripper"),
        ("NO_DESIGN_CLAIM", "GOL-move"),
        ("NO_DESIGN_CLAIM", "GOL-hold"),
        ("UNUSED_GROUND", "AXM-unused"),
        ("UNUSED_GROUND", "DEF-spare"),
    }


def test_a_snapshot_writes_only_its_page(project):
    from graph_snapshot.server import snapshot

    before = tree_digest(project)
    assert "page: " in snapshot() and "not written" not in snapshot()
    assert tree_digest(project) == before, "a snapshot changed a file outside its page's directory"
    assert sorted(p.name for p in (project / ".graph-snapshot").iterdir()) == [".gitignore", "snapshot.html"]


def test_a_snapshot_reads_no_evidence(project, monkeypatch):
    import component_belief.model
    from component_belief.store import Store
    from graph_snapshot.snapshot import take

    Store(project).append_trial({"contract_id": "CTR-motion-clear", "provenance": "measured",
                                 "metrics": {"passed": True}, "validity": "valid"})

    def refuse(*_args, **_kwargs):
        raise AssertionError("a snapshot read the evidence ledger")

    monkeypatch.setattr(Store, "_read", refuse)
    monkeypatch.setattr(component_belief.model, "compute_slices", refuse)
    snap = take(project)
    assert "state" not in snap["nodes"].get("CTR-motion-clear", {}), "a contract has no state here"
    assert snap["nodes"]["CMP-motion"]["measured_by"] == ["CTR-motion-clear"]


def test_git_does_not_see_the_page(project):
    from graph_snapshot.server import snapshot

    snapshot()
    assert ".graph-snapshot" not in git(project, "status", "--porcelain", "--untracked-files=all").stdout
    git(project, "add", "-A")
    assert ".graph-snapshot" not in git(project, "diff", "--cached", "--name-only").stdout


def test_a_page_a_declaration_names_is_not_written(project):
    from graph_snapshot.server import snapshot

    snapshot()
    page = project / ".graph-snapshot" / "snapshot.html"
    first = page.read_bytes()
    commit(project, {"belief.yaml": BELIEF.replace("    metrics: [passed]\n", "    metrics: [passed]\n    reads: [.graph-snapshot/snapshot.html]\n"),
                     "motion.py": "# v2\n"}, "a test reads the page")
    said = snapshot()
    assert "page: not written -- TST-motion names .graph-snapshot/" in said
    assert page.read_bytes() == first
    # A component claiming the directory as its code is the same case.
    commit(project, {"belief.yaml": BELIEF.replace("    code: [gripper.py]\n", "    code: [gripper.py, .graph-snapshot]\n")},
           "a component claims the page's directory")
    assert "page: not written -- CMP-gripper names .graph-snapshot/" in snapshot()
    assert page.read_bytes() == first


def test_the_template_ships_with_the_package():
    """The template is package data: a git install builds a wheel, and a file pyproject does not
    list is left out of it, so the server would start and fail on its first snapshot."""
    from graph_snapshot.page import template

    text = template()
    assert "__SNAPSHOT__" in text and "__TITLE__" in text and text.startswith('<meta charset="utf-8">')
    declared = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["setuptools"]["package-data"]
    assets = [p.name for p in (REPO / "src" / "graph_snapshot").iterdir() if p.is_file() and p.suffix != ".py"]
    assert assets and all(any(fnmatch.fnmatch(a, pat) for pat in declared["graph_snapshot"]) for a in assets), assets


def test_a_statement_cannot_end_the_page_early(project):
    """A declaration's text is data in the page: one that contains a closing script tag is escaped,
    not executed, and reads back intact."""
    from graph_snapshot.server import snapshot

    commit(project, {"consistency.yaml": CONSISTENCY.replace("Names read as plain words.", "Names read as plain words </script><b>.")}, "a hostile statement")
    snapshot()
    assert page_data(project)["nodes"]["AXM-unused"]["text"] == "Names read as plain words </script><b>."


def test_the_cli_says_what_the_tool_says(project, capsys):
    from graph_snapshot.cli import main

    assert main(["--focus", "BRN-motion-gate"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("graph snapshot: ") and "branches 1: 1 obligation" in out
    assert page_data(project)["focus"] == "BRN-motion-gate"


def test_tagged_code_is_listed_on_its_claim_and_is_never_an_edge(project):
    """A region that implements a branch is drawn on the branch, with the link state code_links
    computes at the same commit; the graph's edges stay premise edges, and no source is copied."""
    from code_links import UNPINNED
    from graph_snapshot.snapshot import take

    commit(project, {"motion.py": "def plan():\n    # tdlp:begin CODE-plan\n    # tdlp:implements BRN-motion-gate\n"
                                  "    secret = 'do not copy me'\n    # tdlp:end CODE-plan\n"
                                  "# tdlp:end CODE-<script>\n"}, "tag the planner")
    snap = take(project)
    [region] = snap["nodes"]["BRN-motion-gate"]["regions"]
    assert region == {"id": "CODE-plan", "relation": "implements", "at": "motion.py:2-5", "state": UNPINNED}
    assert not any("CODE-" in a or "CODE-" in b for a, b in snap["edges"])
    issues = {(i["code"], i["source"]) for i in snap["issues"]}
    assert ("UNPINNED", "code links") in issues and ("MALFORMED_MARKER", "code links") in issues
    assert "do not copy me" not in json.dumps(snap)


def test_cited_measurements_and_uncited_contracts_are_shown(project):
    """Reported from embodied_ai on 0.7.5: the snapshot showed neither, while coverage and audit did.
    Judged from the declarations at the snapshot's commit; no evidence is read."""
    from graph_snapshot.snapshot import take

    snap = take(project)
    assert snap["nodes"]["BRN-motion-gate"]["measured"] == [{"contract": "CTR-motion-clear", "state": "unpinned"}]
    issues = {(i["code"], i["subject"], i["source"]) for i in snap["issues"]}
    assert ("MEASUREMENT_UNPINNED", "BRN-motion-gate", "cited measurements") in issues
    uncited = {i["subject"]: i["message"] for i in snap["issues"] if i["code"] == "UNCITED_CONTRACT"}
    assert set(uncited) == {"CTR-reaches", "CTR-holds"}
    assert all("a goal's measure" in m for m in uncited.values())
