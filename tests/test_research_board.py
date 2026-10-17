"""research-board: research earns points, work for a direction spends them, and a result counts for
a direction only from runs the server measured after the spend (DEF-research-ledger)."""

from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import datetime
from pathlib import Path

import pytest

from component_belief.declarations import load
from component_belief.runner import run_test
from component_belief.store import Store
from conftest import git
from research_board import board as B
from research_board import play, reading
from research_board.page import render_board, render_brief

RULES = "focus: GOL-grasp\ncosts: {research: 0, implement: 1, test: 1, training_run: 3}\nearn: {trail: 1}\nscouts: 2\n"
QUOTE = "Sampling approach directions from the object's principal axes raised reachable grasps."


@pytest.fixture
def research(goals_repo: Path, monkeypatch) -> Path:
    (goals_repo / B.RULES_FILE).write_text(RULES, encoding="utf-8")
    git(goals_repo, "add", B.RULES_FILE)
    git(goals_repo, "commit", "-q", "-m", "research rules")
    monkeypatch.setenv("RESEARCH_BOARD_ROOT", str(goals_repo))
    return goals_repo


def measure(repo: Path, test_id: str = "TST-pick") -> str:
    decl = load(repo)
    return run_test(repo, Store(repo), decl, decl.tests[test_id])["run_id"]


def next_second() -> None:
    """Evidence records keep whole seconds, so a run in the spend's own second reads as before it
    (on purpose). A test that means "after" waits for the clock to tick over."""
    start = datetime.now().second
    while datetime.now().second == start:
        time.sleep(0.02)


def funded(repo: Path, name: str = "principal-axes", trails: int = 1) -> str:
    """A direction on GOL-grasp, approved, with `trails` points of research behind it."""
    play.open_direction(repo, name, "GOL-grasp", "Sample grasp approaches from principal axes",
                        "cheapest decisive test: the pick eval, 1 point")
    did = B.direction_id(name)
    for i in range(trails):
        play.add_trail(repo, did, f"Paper {name} {i}", "sample along principal axes", "CMP-grasp", QUOTE,
                       by="scout-1")
    play.approve(repo, did, True, "worth one eval", rank=1)
    return did


def direction(repo: Path, did: str) -> B.Direction:
    return B.build(repo).directions[did]


def result_of(repo: Path, spend_id: str) -> B.Result:
    return B.build(repo).results[spend_id]


def last_spend(repo: Path) -> str:
    return [r for r in B.read_ledger(repo) if r["kind"] == "spend"][-1]["id"]


# ---------- results follow their spend ----------

def test_a_result_recorded_before_the_spend_is_not_the_directions(research):
    measure(research)                              # CTR-pick-success supported, before any spend
    did = funded(research)
    play.spend(research, did, "test", "TST-pick", expect="the pick eval still passes")
    sid = last_spend(research)

    before = result_of(research, sid)
    assert before.states == {"CTR-pick-success": B.NO_EVIDENCE} and before.counted["CTR-pick-success"] == 0
    assert direction(research, did).state == B.ACTIVE
    assert B.build(research).measures["CTR-pick-success"] == "supported"     # the goal's own reading is untouched

    next_second()
    run_id = measure(research)
    after = result_of(research, sid)
    assert after.states == {"CTR-pick-success": "supported"}
    assert after.runs["CTR-pick-success"] == [run_id]
    assert direction(research, did).state == B.NEEDS_REFLECTION
    assert f"CTR-pick-success supported (1 record after the spend: {run_id})" in render_board(B.build(research))


def test_only_records_the_server_measured_are_a_result(research):
    did = funded(research)
    play.spend(research, did, "test", "CTR-pick-success")
    sid = last_spend(research)
    next_second()
    store = Store(research)
    store.append_trials([{
        "subject": "GOL-grasp", "contract_id": "CTR-pick-success", "test_id": "TST-pick",
        "run_id": "RUN-9001", "provenance": "imported", "outcome": "pass", "metrics": {"passed": True},
        "conditions": {"raw": {}}, "artifact_uri": "elsewhere/result.json", "artifact_hash": "0" * 16,
    }])
    imported = result_of(research, sid)
    assert imported.counted["CTR-pick-success"] == 0 and imported.status == B.NO_EVIDENCE

    measure(research)
    assert result_of(research, sid).counted["CTR-pick-success"] == 1


def test_a_spend_keeps_the_contracts_it_named(research):
    did = funded(research)
    play.spend(research, did, "test", "TST-grasp-ik")
    sid = last_spend(research)
    assert B.read_ledger(research)[-1]["contracts"] == ["CTR-grasp-reachable"]

    widened = (research / "belief.yaml").read_text(encoding="utf-8").replace("\ntests:\n", """
  - id: CTR-grasp-fast
    subject: CMP-grasp
    kind: gate
    metrics: [{id: ik_success, unit: bool}]
    acceptance: {rule: "ik_success == true"}
    evaluable_by: [TST-grasp-ik]

tests:
""", 1)
    (research / "belief.yaml").write_text(widened, encoding="utf-8")
    git(research, "commit", "-qam", "TST-grasp-ik now measures a second contract")
    assert "CTR-grasp-fast" in B.targeted_contracts(load(research), "TST-grasp-ik")
    assert set(result_of(research, sid).states) == {"CTR-grasp-reachable"}


# ---------- points ----------

def test_a_trail_earns_only_for_a_new_paper_on_a_declared_component(research):
    play.open_direction(research, "axes", "GOL-grasp", "Sample along principal axes")
    earned = play.add_trail(research, "DIR-axes", "Doe et al. 2021, Sampling Grasps",
                            "sample along principal axes", "CMP-grasp", QUOTE, by="scout-1")
    assert "+1" in earned
    again = play.add_trail(research, "DIR-axes", "doe et al 2021 -- sampling grasps",
                           "a second tweak from it", "CMP-grasp", QUOTE, by="scout-2")
    assert "0 points" in again and "already cites this paper" in again
    assert "no quote" in play.add_trail(research, "DIR-axes", "Paper B", "tweak", "CMP-grasp", "")
    assert "not a component" in play.add_trail(research, "DIR-axes", "Paper C", "tweak", "CMP-nope", QUOTE)
    assert "names no component" in play.add_trail(research, "DIR-axes", "Paper D", "tweak", "", QUOTE)
    b = B.build(research)
    assert b.balance(b.directions["DIR-axes"]) == 1
    assert len(b.directions["DIR-axes"].trails) == 5         # kept, with the reason, earning nothing
    with pytest.raises(play.Refused):
        play.add_trail(research, "DIR-axes", "", "tweak", "CMP-grasp", QUOTE)


def test_a_rejected_trail_loses_its_points(research):
    play.open_direction(research, "axes", "GOL-grasp", "Sample along principal axes")
    play.add_trail(research, "DIR-axes", "Paper A", "tweak", "CMP-grasp", QUOTE)
    trail = B.read_ledger(research)[-1]["id"]
    assert B.build(research).balance(direction(research, "DIR-axes")) == 1
    reply = play.approve(research, trail, False, "a survey, not a result")
    assert "no longer count" in reply
    b = B.build(research)
    assert b.balance(b.directions["DIR-axes"]) == 0
    assert "rejected by the director: \"a survey, not a result\"" in render_brief(b, b.directions["DIR-axes"])


# ---------- the director's moves ----------

def test_a_spend_needs_approval_balance_and_reflection(research):
    play.open_direction(research, "axes", "GOL-grasp", "Sample along principal axes")
    with pytest.raises(play.Refused, match="not approved"):
        play.spend(research, "DIR-axes", "test", "TST-pick")
    play.approve(research, "DIR-axes", True, "try it", rank=1)
    with pytest.raises(play.Refused, match="1 more point"):
        play.spend(research, "DIR-axes", "test", "TST-pick")
    play.add_trail(research, "DIR-axes", "Paper A", "tweak", "CMP-grasp", QUOTE)
    with pytest.raises(play.Refused, match="no action"):
        play.spend(research, "DIR-axes", "dataset_eval", "TST-pick")
    with pytest.raises(play.Refused, match="not declared"):
        play.spend(research, "DIR-axes", "test", "TST-nothing")
    ledger_before = len(B.read_ledger(research))
    play.spend(research, "DIR-axes", "test", "TST-pick")
    assert len(B.read_ledger(research)) == ledger_before + 1
    assert B.build(research).balance(direction(research, "DIR-axes")) == 0

    next_second()
    measure(research)
    play.add_trail(research, "DIR-axes", "Paper B", "tweak", "CMP-grasp", QUOTE)
    with pytest.raises(play.Refused, match="reflect"):
        play.spend(research, "DIR-axes", "test", "TST-pick")
    play.reflect(research, "DIR-axes", "continue", "it passed; one more eval")
    play.spend(research, "DIR-axes", "test", "TST-pick")

    play.reflect(research, "DIR-axes", "halt", "nothing left to learn here")
    play.add_trail(research, "DIR-axes", "Paper C", "tweak", "CMP-grasp", QUOTE)
    assert direction(research, "DIR-axes").state == B.HALTED
    with pytest.raises(play.Refused, match="halted"):
        play.spend(research, "DIR-axes", "implement", "CMP-grasp")


def test_rules_take_effect_from_head(goals_repo, monkeypatch):
    assert B.load_rules(goals_repo).source == "defaults"
    (goals_repo / B.RULES_FILE).write_text("costs: {test: 5}\n", encoding="utf-8")
    rules = B.load_rules(goals_repo)
    assert rules.costs == B.DEFAULT_COSTS and any(i.startswith("UNCOMMITTED") for i in rules.issues)

    git(goals_repo, "add", B.RULES_FILE)
    git(goals_repo, "commit", "-q", "-m", "tests cost more")
    rules = B.load_rules(goals_repo)
    assert rules.costs == {"test": 5} and "tests cost more" in rules.changed

    (goals_repo / B.RULES_FILE).write_text("costs: {test: 0}\nmood: generous\n", encoding="utf-8")
    rules = B.load_rules(goals_repo)
    assert rules.costs == {"test": 5} and any(i.startswith("PENDING") for i in rules.issues)
    board_text = render_board(B.build(goals_repo))
    assert "tests cost more" in board_text and "PENDING research.yaml" in board_text


# ---------- reading ----------

def test_the_ledger_serves_records_and_run_output_never_a_source_file(research):
    (research / "grasp.py").write_text("SECRET_GRASP_HEURISTIC = 42\n", encoding="utf-8")
    git(research, "commit", "-qam", "the code")
    run_id = measure(research)
    served = reading.serve_run(research, run_id)
    assert "CTR-pick-success" in served and "result.json" in served and '"passed": true' in served
    for probe in ("../grasp.py", "RUN-1/../../grasp.py", "grasp.py", f"{run_id}/../../../grasp.py"):
        assert "not a run id" in reading.serve_run(research, probe)
    every = "\n".join([served, reading.serve_contract(research, "CTR-pick-success", 50),
                       reading.serve_node(research, "BRN-anything", 50),
                       reading.serve_overview(research, 50)])
    assert "SECRET_GRASP_HEURISTIC" not in every

    from research_board import server
    assert "SECRET_GRASP_HEURISTIC" not in server.ledger(run=run_id)
    assert "acceptance" in server.ledger(contract="CTR-pick-success")


def test_feedback_reaches_the_next_scout(research):
    play.open_direction(research, "axes", "GOL-grasp", "Sample along principal axes", by="scout-1")
    play.approve(research, "DIR-axes", True, "cheap to test, try first", rank=1)
    play.add_trail(research, "DIR-axes", "Paper A", "tweak", "CMP-grasp", QUOTE, by="scout-1")
    trail = B.read_ledger(research)[-1]["id"]
    play.approve(research, trail, False, "the tweak is the default already")
    play.feedback(research, "DIR-axes", "was the eval on held-out objects?", kind="question", by="scout-2")
    question = B.read_ledger(research)[-1]["id"]
    assert [q["id"] for q in B.build(research).open_questions()] == [question]
    play.feedback(research, "DIR-axes", "all objects; the split is not recorded", kind="answer", reply_to=question)
    play.open_direction(research, "bigger-net", "GOL-grasp", "A bigger network")
    play.approve(research, "DIR-bigger-net", True, "try")
    play.reflect(research, "DIR-bigger-net", "halt", "the gain was data, not size")

    b = B.build(research)
    assert b.open_questions() == []
    brief = render_brief(b, b.directions["DIR-axes"])
    for said in ("cheap to test, try first", "the tweak is the default already",
                 "was the eval on held-out objects?", "all objects; the split is not recorded",
                 "DIR-bigger-net (halted)", "the gain was data, not size", "CMP-grasp: Choose a grasp pose"):
        assert said in brief, said

    with pytest.raises(play.Refused, match="no direction, trail or spend"):
        play.feedback(research, "RUN-0001", "a note on a run")
    with pytest.raises(play.Refused, match="names the question"):
        play.feedback(research, "DIR-axes", "an answer to nothing", kind="answer")


# ---------- what recording touches ----------

def _tree(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file() and ".git" not in p.relative_to(root).parts}


def test_recording_writes_only_inside_research(research):
    measure(research)
    head = git(research, "rev-parse", "HEAD").stdout
    before = _tree(research)
    did = funded(research, trails=2)
    play.feedback(research, did, "a note", by="scout-1")
    play.spend(research, did, "implement", "CMP-grasp")
    play.spend(research, did, "test", "TST-pick")
    play.reflect(research, did, "continue", "keep going")
    after = _tree(research)
    moved = {p for p in set(before) | set(after) if before.get(p) != after.get(p)}
    assert moved == {".research/ledger.jsonl", ".research/BOARD.md"}
    assert git(research, "rev-parse", "HEAD").stdout == head
    assert "# DIR-principal-axes" in (research / ".research" / "BOARD.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("claim", ["component", "test"])
def test_a_declaration_naming_research_files_stops_recording(research, claim):
    text = (research / "belief.yaml").read_text(encoding="utf-8")
    if claim == "component":
        text = text.replace("    code: [grasp.py]\n", "    code: [grasp.py, .research/]\n")
    else:
        text = text.replace('    run: "echo ok"\n', '    run: "echo ok"\n    reads: [.research/ledger.jsonl]\n')
    (research / "belief.yaml").write_text(text, encoding="utf-8")
    git(research, "commit", "-qam", "a declaration names the research ledger")
    with pytest.raises(play.Refused, match="name"):
        play.open_direction(research, "axes", "GOL-grasp", "Sample along principal axes")
    assert not (research / ".research").exists()

    from research_board import server
    assert server.open_direction("axes", "GOL-grasp", "an idea").startswith("not recorded:")


# ---------- the tools ----------

def test_the_server_registers_two_reads_and_six_moves():
    from research_board import server

    names = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert names == {"board", "ledger", "open_direction", "add_trail", "feedback", "approve", "spend", "reflect"}
