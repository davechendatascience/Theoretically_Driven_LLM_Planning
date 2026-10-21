"""research-board: research earns points, work for a direction spends them, and a result counts for
a direction only from runs the server measured after the spend (DEF-research-ledger)."""

from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from component_belief.declarations import load
from component_belief.runner import run_test
from component_belief.store import Store
from conftest import git
from research_board import board as B
from research_board import play, reading
from research_board.page import BRIEF_CHARS, PAGE_CHARS, render_board, render_brief, render_item, render_section

RULES = "focus: GOL-grasp\ncosts: {research: 0, implement: 1, test: 1, training_run: 3}\nearn: {trail: 1}\nscouts: 2\n"
QUOTE = "Sampling approach directions from the object's principal axes raised reachable grasps."


@pytest.fixture
def research(goals_repo: Path, monkeypatch) -> Path:
    (goals_repo / B.RULES_FILE).write_text(RULES, encoding="utf-8")
    git(goals_repo, "add", B.RULES_FILE)
    git(goals_repo, "commit", "-q", "-m", "research rules")
    monkeypatch.setenv("RESEARCH_BOARD_ROOT", str(goals_repo))
    return goals_repo


class Clock:
    """The board's clock, moved by hand: it stamps every research record and is what idle time is
    counted to. Evidence keeps the real time, so it starts hours in the past."""

    def __init__(self) -> None:
        self.at = datetime.now(timezone.utc) - timedelta(hours=6)

    def __call__(self) -> datetime:
        return self.at

    def advance(self, **delta: float) -> None:
        self.at += timedelta(**delta)


@pytest.fixture
def clock(monkeypatch) -> Clock:
    fake = Clock()
    monkeypatch.setattr(B, "clock", fake)
    return fake


def idle(repo: Path, did: str) -> tuple[int, int, bool]:
    """(idle minutes, idle points, idle now) for a direction, as the board reads now."""
    d = B.build(repo).directions[did]
    return round(d.idle.seconds / 60), d.idle.points, d.idle.idle_now


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
    assert f"{trail} · Paper A · 0" in render_brief(b, b.directions["DIR-axes"])
    assert "rejected by the director: \"a survey, not a result\"" in render_section(b, b.directions["DIR-axes"], "trails")


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


# ---------- idle hours ----------

def test_an_idle_hour_costs_the_direction_waiting_on_a_result(research, clock):
    did = funded(research, trails=3)                      # research recorded at t0 runs until t0+30m
    built = play.spend(research, did, "implement", "CMP-grasp")   # names no contract, so waits on nothing
    assert "no result of its own" in built and "commit the declaration, then spend on it" in built
    clock.advance(hours=2)
    assert idle(research, did) == (0, 0, False)

    play.spend(research, did, "test", "TST-pick")         # t0+2h: waits on CTR-pick-success
    clock.advance(minutes=90)
    assert idle(research, did) == (90, 1, True)
    b = B.build(research)
    assert b.balance(b.directions[did]) == 3 - 2 - 1
    page = render_board(b)
    assert "idle 1h 30m waiting on a result" in page and "send a scout now" in page
    assert "record each trail as you have it" in render_brief(b, b.directions[did])

    play.feedback(research, did, "is the pick eval seeded?", kind="question", by="scout-1")
    clock.advance(minutes=30)
    assert idle(research, did) == (90, 1, False)          # a scout's question kept research running
    play.feedback(research, did, "still reading", by="scout-1")    # a note: it does not stop the clock
    clock.advance(minutes=30)
    assert idle(research, did) == (120, 2, True)
    with pytest.raises(play.Refused, match="idle hours took 2"):
        play.spend(research, did, "test", "TST-pick")

    clock.at = datetime.now(timezone.utc)                 # about t0+6h, in the evidence's time
    next_second()
    measure(research)                                     # the result is in, and the clock stops there
    clock.advance(hours=3)
    minutes, points, idle_now = idle(research, did)
    assert 210 <= minutes < 215 and points == 3 and not idle_now
    assert direction(research, did).state == B.NEEDS_REFLECTION


def test_a_spend_keeps_the_idle_terms_it_was_made_under(research, clock):
    did = funded(research, trails=4)
    play.spend(research, did, "test", "TST-pick")         # t0, under one point an idle hour
    assert B.read_ledger(research)[-1]["idle"] == {"per_hour": 1, "running_minutes": 30}

    (research / B.RULES_FILE).write_text(RULES + "idle: {per_hour: 0}\n", encoding="utf-8")
    git(research, "commit", "-qam", "idle hours are free now")
    clock.advance(minutes=90)
    assert idle(research, did) == (60, 1, True)           # priced as when the spend was made
    assert "idle hours cost nothing" in render_board(B.build(research))

    other = funded(research, "second-axis")               # research at t0+90m runs until t0+2h
    play.spend(research, other, "test", "TST-grasp-ik")   # made under the new rules
    assert B.read_ledger(research)[-1]["idle"]["per_hour"] == 0
    clock.advance(hours=3)
    assert idle(research, other)[1] == 0
    assert idle(research, did) == (60 + 150, 3, True)

    play.reflect(research, did, "halt", "the eval is not coming back")
    clock.advance(hours=5)
    assert idle(research, did) == (210, 3, False)         # a closed direction waits on nothing


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


def test_a_rule_given_twice_is_named(goals_repo):
    """The second `costs:` replaces the first whole; the board says which one is in effect."""
    (goals_repo / B.RULES_FILE).write_text("costs: {test: 5}\nscouts: 2\ncosts: {test: 1}\n", encoding="utf-8")
    git(goals_repo, "add", B.RULES_FILE)
    git(goals_repo, "commit", "-q", "-m", "costs twice")
    rules = B.load_rules(goals_repo)
    assert rules.costs == {"test": 1}
    assert ("DUPLICATE_KEY research.yaml: `costs` is given twice in research.yaml (lines 1 and 3); YAML keeps "
            "the value at line 3") in "\n".join(rules.issues)
    assert "`costs` is given twice" in render_board(B.build(goals_repo))


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

    with pytest.raises(play.Refused, match="no goal, direction, trail or spend"):
        play.feedback(research, "RUN-0001", "a note on a run")
    with pytest.raises(play.Refused, match="names the question"):
        play.feedback(research, "DIR-axes", "an answer to nothing", kind="answer")


# ---------- what recording touches ----------

def _tree(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file() and ".git" not in p.relative_to(root).parts}


def test_recording_writes_only_inside_research(research):
    """Every move, the measured finding and the digest among them: the ledger, the page and, for a
    finding, its one copy move, and nothing else -- no evidence or consistency ledger, no
    declaration, no commit."""
    measure(research)
    (research / "failure_map.csv").write_text("start,closed_on_air\n1,yes\n", encoding="utf-8")
    head = git(research, "rev-parse", "HEAD").stdout
    before = _tree(research)
    did = funded(research, trails=2)
    play.feedback(research, did, "a note", by="scout-1")
    play.evidence(research, did, "failure_map.csv", "one start closes on air")
    play.digest(research, did, "facts so far: one start closes on air")
    play.spend(research, did, "implement", "CMP-grasp")
    play.spend(research, did, "test", "TST-pick")
    play.reflect(research, did, "continue", "keep going")
    after = _tree(research)
    moved = {p for p in set(before) | set(after) if before.get(p) != after.get(p)}
    copy = next(r["copy"] for r in B.read_ledger(research) if r.get("kind") == "evidence")
    assert copy.startswith(".research/")
    assert moved == {".research/ledger.jsonl", ".research/BOARD.md", copy}
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

def test_the_server_registers_two_reads_and_eight_moves():
    from research_board import server

    names = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert names == {"board", "ledger", "open_direction", "add_trail", "feedback", "approve", "spend", "reflect",
                     "evidence", "digest"}


# ---------- what counts as research for the idle clock ----------

def test_research_is_what_moves_the_question_not_a_note():
    research = [{"kind": "direction"}, {"kind": "trail", "points": 1}, {"kind": "evidence", "points": 0},
                {"kind": "feedback", "type": "question", "by": "scout-1"},
                {"kind": "feedback", "type": "answer", "by": "director"}]
    not_research = [{"kind": "trail", "points": 0}, {"kind": "feedback", "type": "note", "by": "scout-1"},
                    {"kind": "feedback", "type": "question", "by": "director"}, {"kind": "digest"},
                    {"kind": "feedback", "type": "approved", "by": "director"}, {"kind": "spend"}]
    assert all(B.is_research(r) for r in research)
    assert not any(B.is_research(r) for r in not_research)


# ---------- a brief a scout can read ----------

LONG = "A long passage the scout read, quoted in full, as the rules ask. " * 30


def test_a_long_brief_has_a_head_that_fits_and_every_record_in_its_sections(research):
    """Briefs of 50-120 KB were saved to a file the scout cannot open; it read the first 2 KB and
    missed the answers it needed. The head fits, and every record is one page or one id away."""
    did = funded(research, trails=0)
    for i in range(120):
        play.add_trail(research, did, f"Paper {i}", "tweak " + LONG, "CMP-grasp", LONG, by="scout-1")
    for i in range(60):
        play.feedback(research, did, f"note {i} " + LONG, by="scout-2")
    b = B.build(research)
    d = b.directions[did]
    head = render_brief(b, d)
    assert len(head) <= BRIEF_CHARS
    assert "section=\"trails\"" in head and "section=\"feedback\"" in head

    for section, ids in (("trails", [tr["id"] for tr in d.trails]), ("feedback", [f["id"] for f in d.feedback])):
        first = render_section(b, d, section)
        total = int(first.split(" of ", 1)[1].split(",", 1)[0])
        assert total > 1
        pages = [render_section(b, d, section, n) for n in range(1, total + 1)]
        assert all(len(page) <= PAGE_CHARS + 400 for page in pages)
        assert all(any(i in page for page in pages) for i in ids), section
    one = d.trails[57]["id"]
    assert LONG.strip() in render_item(b, one)


def test_a_feedback_line_the_head_cuts_says_where_it_is_whole(research):
    """A scout found the director's table of settings cut at about 400 characters in the head, and
    nothing said the rest was one call away. A director's word and an answer get the room an open
    question gets; any line the head cuts names the record it came from."""
    did = funded(research)
    table = "settings: " + "; ".join(f"arm {i} decodes with {i * 3} Euler steps" for i in range(60))
    play.feedback(research, did, "scout note " + LONG, by="scout-1")
    play.feedback(research, did, table[:1000])                  # the director's, under 1,200: whole
    play.feedback(research, did, table)                         # the director's, over it: cut
    b = B.build(research)
    d = b.directions[did]
    scout, whole, cut = (f["id"] for f in d.feedback if f.get("type") == B.NOTE)
    head = render_brief(b, d)
    assert f'(cut; in full: board(item="{scout}"))' in head
    assert table[:1000] in head and f'(cut; in full: board(item="{whole}"))' not in head
    assert f'(cut; in full: board(item="{cut}"))' in head and table in render_item(b, cut)
    assert "(cut; in full" not in render_board(b)          # the page for the human names no tool call


def test_the_humans_rules_lead_every_brief_on_the_goal(research):
    text = (research / "goals.yaml").read_text(encoding="utf-8").replace(
        "    measure: CTR-pick-success\n",
        "    measure: CTR-pick-success\n    constraints:\n      - actions are executed exactly, with no noise\n"
        "      - on-policy states only from non-test starts\n", 1)
    (research / "goals.yaml").write_text(text, encoding="utf-8")
    git(research, "commit", "-qam", "my standing rules")
    did = funded(research)
    head = render_brief(B.build(research), direction(research, did))
    assert "propose nothing that breaks one" in head
    assert "- actions are executed exactly, with no noise" in head and "- on-policy states only from non-test starts" in head


def test_a_digest_leads_the_brief_and_the_latest_stands(research):
    did = funded(research)
    play.digest(research, did, "t1 reaches 402/480 on its own starts; the gap is grasp closure.")
    play.digest(research, did, "t1 reaches 402/480; closure, not detection, is the gap (EVD-0001).")
    head = render_brief(B.build(research), direction(research, did))
    assert "closure, not detection, is the gap" in head and "the gap is grasp closure" not in head
    assert head.index("Facts so far") < head.index("idea:")
    with pytest.raises(play.Refused, match="at most"):
        play.digest(research, did, "x" * (play.DIGEST_CHARS + 1))


def test_a_note_on_the_goal_reaches_every_brief_on_it(research):
    did = funded(research)
    reply = play.feedback(research, "GOL-grasp", "t1's own-start success is 402/480; any direction starts there",
                          by="director")
    assert "every brief on it carries" in reply
    b = B.build(research)
    assert "402/480" in render_brief(b, b.directions[did]) and "On GOL-grasp itself" in render_board(b)
    play.feedback(research, "GOL-grasp", "does the 352k budget count states from t1's rollouts?",
                  kind="question", by="scout-1")
    assert [q["about"] for q in B.build(research).open_questions()] == ["GOL-grasp"]


# ---------- measured findings ----------

def test_a_measured_finding_is_kept_as_it_was_and_served_to_scouts(research, clock):
    did = funded(research)
    (research / "failure_map.csv").write_text("start,closed_on_air\n1,yes\n2,no\n", encoding="utf-8")
    reply = play.evidence(research, did, "failure_map.csv", "1,997 closes on air; most at starts 1-40")
    eid = B.read_ledger(research)[-1]["id"]
    assert eid.startswith("EVD-") and "0 points" in reply           # earns nothing by default
    (research / "failure_map.csv").write_text("rewritten later\n", encoding="utf-8")
    served = reading.serve_evidence(research, eid)
    assert "start,closed_on_air" in served and "rewritten later" not in served
    assert "1,997 closes on air" in render_brief(B.build(research), direction(research, did))
    assert B.is_research(B.read_ledger(research)[-1])

    copy = research / B.read_ledger(research)[-1]["copy"]
    copy.write_text("tampered\n", encoding="utf-8")
    assert "no longer matches the digest" in reading.serve_evidence(research, eid)


def test_a_finding_is_never_code(research):
    did = funded(research)
    (research / "probe.py").write_text("print(1)\n", encoding="utf-8")
    with pytest.raises(play.Refused, match="not a data file"):
        play.evidence(research, did, "probe.py", "a probe")
    (research / "grasp.json").write_text("{}", encoding="utf-8")
    text = (research / "belief.yaml").read_text(encoding="utf-8").replace("code: [grasp.py]", "code: [grasp.py, grasp.json]")
    (research / "belief.yaml").write_text(text, encoding="utf-8")
    git(research, "commit", "-qam", "the grasp claims its config")
    with pytest.raises(play.Refused, match="claimed by CMP-grasp"):
        play.evidence(research, did, "grasp.json", "the config")
    with pytest.raises(play.Refused, match="outside the project"):
        play.evidence(research, did, "../elsewhere.txt", "x")


# ---------- a spend on a test ----------

def test_a_spend_on_a_test_counts_that_tests_runs_only(research):
    """Three arms of one evaluation, three tests on one contract, three spends: each reads its own."""
    text = (research / "goals.yaml").read_text(encoding="utf-8")
    text = text.replace("evaluable_by: [TST-pick]", "evaluable_by: [TST-pick, TST-pick-noise]")
    text = text.replace("tests:\n", "tests:\n  - id: TST-pick-noise\n    layer: e2e\n    targets: [GOL-grasp]\n"
                                    "    run: python eval/pick.py $OUT noise\n    metrics: [passed]\n", 1)
    (research / "goals.yaml").write_text(text, encoding="utf-8")
    git(research, "commit", "-qam", "a second arm")
    did = funded(research, trails=2)
    play.spend(research, did, "test", "TST-pick")
    plain = last_spend(research)
    play.spend(research, did, "test", "TST-pick-noise")
    noise = last_spend(research)
    next_second()
    run_id = measure(research, "TST-pick-noise")
    assert result_of(research, noise).runs["CTR-pick-success"] == [run_id]
    assert result_of(research, plain).counted["CTR-pick-success"] == 0


# ---------- the ledger itself ----------

def test_a_ledger_git_ignores_is_named(research):
    funded(research)
    assert not B.build(research).ledger_ignored
    (research / ".gitignore").write_text("*.jsonl\n", encoding="utf-8")
    b = B.build(research)
    assert "IGNORED .research/ledger.jsonl" in b.ledger_ignored and "!.research/ledger.jsonl" in b.ledger_ignored
    assert "! IGNORED" in render_board(b)


def test_a_run_can_be_read_metrics_only(research):
    run_id = measure(research)
    full = reading.serve_run(research, run_id)
    lean = reading.serve_run(research, run_id, fields={"metrics"})
    assert "conditions" in full and "conditions" not in lean and "metrics" in lean
    assert "---" in full and "---" not in lean
