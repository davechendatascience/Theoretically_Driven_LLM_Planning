"""research-board: research earns points, work for a direction spends them, and a result counts for
a direction only from runs the server measured after the spend (DEF-research-ledger)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
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
from research_board.page import (BRIEF_CHARS, PAGE_CHARS, render_board, render_brief, render_human, render_item,
                                 render_section)

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


def launched(repo: Path, test_id: str, at: datetime, run_id: str = "RUN-9100") -> None:
    """A background run of `test_id` started at `at` and running still: its job file, with this
    test's own process standing in for the worker."""
    path = Store(repo).artifacts_dir / run_id / "job.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"run_id": run_id, "test": f"{test_id}@0000", "started": at.isoformat(),
                                "pid": os.getpid()}), encoding="utf-8")


def measure(repo: Path, test_id: str = "TST-pick", params: dict | None = None) -> str:
    decl = load(repo)
    return run_test(repo, Store(repo), decl, decl.tests[test_id], params=params)["run_id"]


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
    launched(research, "TST-pick", clock.at)              # ... from its first run, started at once
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


def test_a_spend_waits_from_its_first_run(research, clock):
    """Funding a test four hours before the GPU freed charged the direction for the wait. The
    clock now starts with the spend's first run; until then the spend is queued and costs nothing."""
    did = funded(research, trails=3)                      # research recorded at t0 runs until t0+30m
    reply = play.spend(research, did, "test", "TST-pick")
    assert "Until a run starts, the spend is queued and costs nothing" in reply
    launched(research, "TST-grasp-ik", clock.at, "RUN-9102")      # another test's run starts no clock
    clock.advance(hours=4)
    assert idle(research, did) == (0, 0, False)
    b = B.build(research)
    assert b.directions[did].idle.queued == [last_spend(research)]
    assert "queued: its idle clock starts with its first run" in render_board(b)

    launched(research, "TST-pick", clock.at)              # t0+4h: the GPU frees, the run starts
    clock.advance(minutes=90)
    assert idle(research, did) == (90, 1, True)
    assert B.build(research).directions[did].idle.queued == []

    other = funded(research, "second-axis", trails=3)     # halted while its spend was queued
    play.spend(research, other, "test", "TST-see")         # a test nothing else here runs
    clock.advance(minutes=10)
    play.reflect(research, other, "halt", "the arm is needed elsewhere")
    clock.advance(minutes=50)
    launched(research, "TST-see", clock.at, "RUN-9103")
    clock.advance(hours=2)
    assert idle(research, other) == (0, 0, False)


def test_a_spend_made_before_the_rule_waits_from_when_it_was_recorded(research, clock):
    """A spend fixes when its wait starts. One recorded before spends said so fixed no start, and
    waits from when it was recorded, as it did: no balance already on a board changes."""
    did = funded(research, trails=3)
    play.spend(research, did, "test", "TST-pick")
    path = B.ledger_path(research)
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    records[-1]["idle"].pop("from")
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in records), encoding="utf-8")
    clock.advance(minutes=90)
    assert idle(research, did) == (60, 1, True)           # from t0+30m, when research stopped running


def test_a_spend_keeps_the_idle_terms_it_was_made_under(research, clock):
    did = funded(research, trails=4)
    play.spend(research, did, "test", "TST-pick")         # t0, under one point an idle hour
    assert B.read_ledger(research)[-1]["idle"] == {"per_hour": 1, "running_minutes": 30, "from": B.FIRST_RUN}
    launched(research, "TST-pick", clock.at)

    (research / B.RULES_FILE).write_text(RULES + "idle: {per_hour: 0}\n", encoding="utf-8")
    git(research, "commit", "-qam", "idle hours are free now")
    clock.advance(minutes=90)
    assert idle(research, did) == (60, 1, True)           # priced as when the spend was made
    assert "idle hours cost nothing" in render_board(B.build(research))

    other = funded(research, "second-axis")               # research at t0+90m runs until t0+2h
    play.spend(research, other, "test", "TST-grasp-ik")   # made under the new rules
    assert B.read_ledger(research)[-1]["idle"]["per_hour"] == 0
    launched(research, "TST-grasp-ik", clock.at, "RUN-9101")
    clock.advance(hours=3)
    assert idle(research, other)[1] == 0
    assert idle(research, did) == (60 + 150, 3, True)

    play.reflect(research, did, "halt", "the eval is not coming back")
    clock.advance(hours=5)
    assert idle(research, did) == (210, 3, False)         # a closed direction waits on nothing


def test_a_scouts_check_waits_on_the_director_until_measured_or_answered(research):
    """"WORTH TESTING FIRST: a free check of X" landed as a note, so the board never showed it
    waiting on the director. A check stays open until a finding replies to it or an answer does."""
    did = funded(research)
    out = play.feedback(research, did, "WORTH TESTING FIRST: count the closes on air in the failure map",
                        kind="check", by="scout-1")
    check = B.read_ledger(research)[-1]
    assert "stays open on the board" in out and B.is_research(check)
    b = B.build(research)
    assert [q["id"] for q in b.open_questions()] == [check["id"]]
    assert "## Open questions and checks on it, waiting on the director" in render_brief(b, b.directions[did])
    assert f"{check['id']} · scout-1 · check on {did}" in render_board(b)

    (research / "failure_map.csv").write_text("start,closed_on_air\n1,yes\n", encoding="utf-8")
    play.evidence(research, did, "failure_map.csv", "1 of 1 starts closes on air", reply_to=check["id"])
    b = B.build(research)
    assert b.open_questions() == [] and f"replying to {check['id']}" in render_section(b, b.directions[did], "evidence")

    play.feedback(research, did, "check the seed first", kind="check", by="scout-2")
    second = B.read_ledger(research)[-1]["id"]
    play.feedback(research, did, "seeded: 7 for every arm", kind="answer", reply_to=second)
    assert B.build(research).open_questions() == []
    with pytest.raises(play.Refused, match="no question or check"):
        play.evidence(research, did, "failure_map.csv", "again", reply_to="FBK-9999")
    play.feedback(research, did, "a check of my own", kind="check")
    assert not B.is_research(B.read_ledger(research)[-1])     # the director's own check keeps no clock


def test_a_direction_is_retargeted_once_its_goal_is_committed(research):
    """Directions opened under a parent goal before the subgoal landed stayed "for" the parent for
    good. retarget moves one, and the ledger keeps the goal it was opened for."""
    did = funded(research)                                # opened for GOL-grasp
    with pytest.raises(play.Refused, match="no goal 'GOL-grasp-95' in goals.yaml at HEAD; commit it first"):
        play.retarget(research, did, "GOL-grasp-95", "the subgoal")
    with pytest.raises(play.Refused, match="already serves GOL-grasp"):
        play.retarget(research, did, "GOL-grasp", "the same goal")
    out = play.retarget(research, did, "GOL-see", "the gap is segmentation, not the grasp")
    assert "now serves GOL-see (it served GOL-grasp)" in out
    b = B.build(research)
    d = b.directions[did]
    assert d.goal == "GOL-see" and d.record["goal"] == "GOL-grasp"
    assert "retarget: from GOL-grasp to GOL-see" in render_section(b, d, "feedback")
    assert "GOL-see: The scene is segmented" in render_brief(b, d)
    assert f"**{did}** · for GOL-see" in render_board(b)    # off the rules' focus, GOL-grasp, now


def test_trail_kinds_a_method_earns_and_a_paper_set_aside_is_listed_as_read(research):
    """A trail pointing at a way to measure, not a model change, had no kind of its own; and a
    scout had no way to say "read this, it does not help", so the next scout read it again."""
    did = funded(research, trails=0)
    method = play.add_trail(research, did, "Lee 2024, Conditional probing", "probe the prefix for the word",
                            "TST-pick", QUOTE, kind="method", by="scout-1")
    assert "+1" in method
    tweak = play.add_trail(research, did, "Lee 2025, Probes", "probe it", "TST-pick", QUOTE, by="scout-1")
    assert "0 points" in tweak and "TST-pick is not a component" in tweak
    put = play.add_trail(research, did, "Kim 2023, Grasp noise", "noise in executed actions, which the human ruled out",
                         kind="set-aside", by="scout-1")
    assert "set aside, 0 points" in put and not B.is_research(B.read_ledger(research)[-1])
    b = B.build(research)
    d = b.directions[did]
    head = render_brief(b, d)
    cited = head.split("## Papers already cited here")[1].split("\n## ")[0]
    assert "· method" in cited and "Kim 2023" not in cited
    assert "## Papers read and set aside -- read one again only with a new reason" in head
    assert "Kim 2023, Grasp noise · why not: noise in executed actions" in head
    trails = render_section(b, d, "trails")
    assert "· method · by scout-1" in trails and "why not: noise in executed actions" in trails
    taken_up = play.add_trail(research, did, "Kim 2023, Grasp noise", "perturb where the episode starts",
                              "CMP-grasp", QUOTE, by="scout-2")
    assert "+1" in taken_up                              # a paper set aside may still be taken up
    with pytest.raises(play.Refused, match="kind must be one of"):
        play.add_trail(research, did, "X", "y", kind="survey")


def test_a_run_that_opened_research_files_stops_recording(research):
    """A test that read .research/ without declaring it was not caught by the no-record rule: its
    evidence rested on the ledger, and recording moved it. The board now reads what the latest run
    of each declared test opened."""
    did = funded(research)
    run_id = measure(research)
    record = [t for t in Store(research).effective_trials() if t.get("run_id") == run_id][0]
    assert record["started"] <= record["timestamp"]       # a run says when it started
    (Store(research).artifacts_dir / run_id / "reads.json").write_text(
        json.dumps(["eval/pick.py", ".research/ledger.jsonl"]), encoding="utf-8")
    with pytest.raises(play.Refused, match=rf"the latest run of TST-pick \({run_id}\) opened a file in .research/"):
        play.feedback(research, did, "a note")
    next_second()
    measure(research)                                     # run again, and it reads nothing there
    assert "recorded" in play.feedback(research, did, "a note")


@pytest.fixture
def arms(research) -> Path:
    """TST-pick as one test with two arms, plain and noise."""
    text = (research / "goals.yaml").read_text(encoding="utf-8").replace(
        "    run: python eval/pick.py $OUT\n", "    run: python eval/pick.py $OUT {arm}\n    params: {arm: [plain, noise]}\n", 1)
    (research / "goals.yaml").write_text(text, encoding="utf-8")
    git(research, "commit", "-qam", "the pick eval has two arms")
    return research


def test_a_spend_on_one_arm_counts_that_arms_runs_and_the_rest_count_for_no_direction(arms, clock):
    """Several spends on one contract blurred, and a family of arms needed a declared test per
    arm. A spend may fix the arm of a test it names; only that arm's runs are its result. A run of
    the other arm belongs to no direction, and the board lists it per goal -- never as a result."""
    did = funded(arms, trails=2)
    with pytest.raises(play.Refused, match="'wobbly' is not a value TST-pick declares for arm"):
        play.spend(arms, did, "test", "TST-pick", params={"arm": "wobbly"})
    with pytest.raises(play.Refused, match="params fix the arm of a test; CTR-pick-success is no test"):
        play.spend(arms, did, "test", "CTR-pick-success", params={"arm": "noise"})
    reply = play.spend(arms, did, "test", "TST-pick", params={"arm": "noise"})
    assert "TST-pick arm=noise's runs" in reply
    sid = last_spend(arms)
    assert B.read_ledger(arms)[-1]["params"] == {"arm": "noise"}

    launched(arms, "TST-pick", clock.at)                  # a background run of the other arm ...
    path = Store(arms).artifacts_dir / "RUN-9100" / "job.json"
    job = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**job, "params": {"arm": "plain"}}), encoding="utf-8")
    clock.advance(hours=1)
    assert idle(arms, did) == (0, 0, False)               # ... starts no clock for this spend

    clock.at = datetime.now(timezone.utc)
    next_second()
    plain = measure(arms, params={"arm": "plain"})
    assert result_of(arms, sid).counted["CTR-pick-success"] == 0
    noise = measure(arms, params={"arm": "noise"})
    assert result_of(arms, sid).runs["CTR-pick-success"] == [noise]

    b = B.build(arms)
    assert [r["run"] for r in b.unclaimed["GOL-grasp"]] == [plain]
    page = render_board(b)
    assert "## Runs that count for no direction on GOL-grasp (1)" in page
    assert f"- {plain} · TST-pick arm=plain · " in page and "CTR-pick-success: 1 pass" in page
    assert f"{sid} · test -> TST-pick arm=noise · " in page


def test_the_human_view_says_where_the_research_stands_in_plain_words(arms, clock):
    """"You are too into the research, it's hard for me to follow": the director's updates had
    become ledger narration. board(view="human") gives the state in plain words, without ids."""
    from research_board import server

    did = funded(arms, trails=3)
    play.spend(arms, did, "test", "TST-pick", params={"arm": "noise"})
    human = render_human(B.build(arms))
    assert "## The arm picks up the object it is asked for" in human
    assert '"Sample grasp approaches from principal axes" -- waiting for its first run (funded ' in human
    assert "Best result so far: none yet -- nothing has been measured for it." in human and "Needs you: nothing." in human

    clock.at = datetime.now(timezone.utc)
    next_second()
    measure(arms, params={"arm": "plain"})
    measure(arms, params={"arm": "noise"})
    human = render_human(B.build(arms))
    assert 'Best result so far: "Sample grasp approaches from principal axes" passed its test, 1 of 1, on' in human
    assert "Waiting on the agent: 1 result to weigh." in human
    assert "Work no idea claims: 1 test run since research began" in human
    assert not re.search(r"\b(DIR|TRAIL|SPD|FBK|EVD|RUN|TST|CTR|CMP)-", human)
    assert server.board(view="human") == human
    assert "no view 'robot'" in server.board(view="robot")


def test_the_human_view_says_what_each_spend_is_doing_and_the_best_measured_result(research, clock):
    """On a real board the view read "its test is running" for three directions while nothing ran:
    one result had gone stale, one spend had never run. It said "Best result so far: none yet"
    though a run had measured 465 of 500 before going stale, and "then 5 mores", "0 sets aside"."""
    def opened(name: str, idea: str) -> str:
        play.open_direction(research, name, "GOL-grasp", idea)
        did = B.direction_id(name)
        for i in range(2):
            play.add_trail(research, did, f"Paper {name} {i}", "a tweak", "CMP-grasp", QUOTE, by="scout-1")
        play.approve(research, did, True, "worth a test")
        return did

    running = opened("seg", "Segment the scene first")
    play.spend(research, running, "test", "TST-see")
    launched(research, "TST-see", clock.at)
    never = opened("hold", "Hold the gripper closed longer")
    play.spend(research, never, "test", "TST-grasp-ik")          # made before spends waited for a run
    path = B.ledger_path(research)
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    records[-1]["idle"].pop("from")
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in records), encoding="utf-8")
    went_stale = opened("clock", "Close on a clock")
    play.spend(research, went_stale, "test", "TST-pick")
    for name in ("one", "two", "three"):
        opened(name, f"Idea {name}")
    clock.advance(hours=3)

    clock.at = datetime.now(timezone.utc)
    next_second()
    measure(research)                                            # TST-pick: 1 of 1 passes ...
    pick = research / "eval" / "pick.py"
    pick.write_text(pick.read_text(encoding="utf-8") + "# edited\n", encoding="utf-8")
    git(research, "commit", "-qam", "the pick eval moved")      # ... and the code moves under it
    clock.advance(minutes=5)

    human = render_human(B.build(research))
    assert '"Segment the scene first" -- its test is running (started ' in human
    assert '"Hold the gripper closed longer" -- waiting for its first run (funded ' in human
    assert "and no research has been done for" in human           # that old spend still waits, and idles
    assert ('"Close on a clock" -- measured 1 of 1, now stale: the code moved since, so it counts again '
            "only once re-run") in human
    assert human.count("its test is running") == 1
    assert ('Best result so far: "Close on a clock" measured 1 of 1 on ') in human and "now stale" in human
    assert '"Idea one", then 2 more -- approved' in human or '"Idea three", then 2 more -- approved' in human
    assert "0 set aside;" in human and "mores" not in human and "sets aside" not in human


def test_the_best_result_is_the_one_its_count_can_vouch_for():
    """Ranked by raw pass rate, a one-trial diagnostic (1 of 1) outranked 440 of 500 episodes."""
    from types import SimpleNamespace

    from research_board.page import _best_line

    def stale(passed: int, judged: int) -> B.Result:
        return B.Result(states={"CTR-x": "stale"}, counted={"CTR-x": judged}, passed={"CTR-x": passed},
                        scored={"CTR-x": judged})

    board = SimpleNamespace(results={"S1": stale(1, 1), "S2": stale(440, 500)}, now=datetime.now(timezone.utc))
    lucky = B.Direction(record={"id": "DIR-a", "idea": "one noise draw"}, spends=[{"id": "S1"}])
    many = B.Direction(record={"id": "DIR-b", "idea": "five hundred episodes"}, spends=[{"id": "S2"}])
    assert '"five hundred episodes" measured 440 of 500' in _best_line(board, [lucky, many])


def test_a_paused_goal_stops_its_directions_clocks_from_the_commit_that_pauses_it(research, clock, monkeypatch):
    """A subgoal paused only in a comment kept charging its direction: 45 hours of idle points, a
    balance of -31. `status: paused` on a goal in goals.yaml -- the human's commit -- stops every
    wait on its directions from that commit's time until a commit sets it active again, and no spend
    is made on them meanwhile. A direction retargeted to an active goal waits again."""
    def commit_goals(status: str, message: str) -> None:
        text = (research / "goals.yaml").read_text(encoding="utf-8")
        text = re.sub(r"(  - id: GOL-grasp\n(?:    .*\n)*?)(    status: \w+\n)?(?=  - id:|\n\S|\Z)",
                      lambda m: m.group(1) + f"    status: {status}\n", text, count=1)
        (research / "goals.yaml").write_text(text, encoding="utf-8")
        monkeypatch.setenv("GIT_COMMITTER_DATE", clock.at.isoformat())
        git(research, "commit", "-qam", message)

    clock.at = clock.at.replace(microsecond=0)                    # git keeps commit times in whole seconds
    did = funded(research, trails=3)
    play.spend(research, did, "test", "TST-pick")
    launched(research, "TST-pick", clock.at)
    clock.advance(minutes=90)                                     # t0+90: idle since t0+30
    assert idle(research, did) == (60, 1, True)

    commit_goals("paused", "set the grasp goal aside for now")
    assert load(research).goals["GOL-grasp"].paused
    clock.advance(hours=5)
    assert idle(research, did) == (60, 1, False)                  # no wait while it is paused
    with pytest.raises(play.Refused, match="GOL-grasp is paused in goals.yaml"):
        play.spend(research, did, "test", "TST-grasp-ik")
    assert "+1" in play.add_trail(research, did, "Paper after the pause", "a tweak", "CMP-grasp", QUOTE)  # runs 30m
    b = B.build(research)
    human = render_human(b)
    assert "## The arm picks up the object it is asked for (paused)" in human
    assert "Paused: paused in goals.yaml since " in human
    assert "paused in goals.yaml since " in render_brief(b, b.directions[did])

    commit_goals("active", "back to the grasp goal")
    clock.advance(minutes=60)
    assert idle(research, did) == (90, 1, True)                   # it waits again from that commit

    commit_goals("paused", "aside again")
    clock.advance(minutes=30)
    play.retarget(research, did, "GOL-see", "the gap is segmentation")
    clock.advance(minutes=60)
    assert idle(research, did) == (150, 2, True)                  # paused 30m, then its goal is an active one

    commit_goals("sleeping", "a word goals.yaml does not know")
    assert any(i.code == "MALFORMED" and i.subject == "GOL-grasp" and "sleeping" in i.message
               for i in load(research).issues)
    assert not load(research).goals["GOL-grasp"].paused


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

def test_the_server_registers_two_reads_and_nine_moves():
    from research_board import server

    names = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert names == {"board", "ledger", "open_direction", "add_trail", "feedback", "approve", "spend", "reflect",
                     "evidence", "digest", "retarget"}


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


def _board_state(board: B.Board) -> str:
    """Everything a board computes from the evidence ledger, as text two builds can be compared by."""
    return json.dumps({
        "results": {sid: vars(result) for sid, result in board.results.items()},
        "starts": board.starts, "measures": board.measures, "unclaimed": board.unclaimed,
        "running": board.running, "error": board.evidence_error,
        "directions": {d.id: [d.state, board.balance(d), vars(d.idle) if d.idle else None, d.unreflected]
                       for d in board.directions.values()},
    }, sort_keys=True, default=lambda o: sorted(o) if isinstance(o, set) else str(o))


def test_the_board_reads_only_the_records_its_results_can_use(arms, clock, monkeypatch):
    """A build reads the trials of the contracts a spend recorded or a goal measures, and every
    trial of their runs -- and computes exactly the board it would from every record."""
    measure(arms, "TST-cloud-fits")                       # a contract no spend names and no goal measures
    measure(arms, "TST-see")
    did = funded(arms, trails=2)
    play.spend(arms, did, "test", "TST-pick", params={"arm": "plain"})
    next_second()
    measure(arms, "TST-pick", params={"arm": "plain"})
    measure(arms, "TST-pick", params={"arm": "noise"})   # counts for no direction: unclaimed
    clock.at = datetime.now(timezone.utc) + timedelta(minutes=1)   # the board's clock catches up with the runs
    play.reflect(arms, did, "continue", "the plain arm passed")
    play.spend(arms, did, "test", "TST-pick", params={"arm": "noise"})
    clock.advance(hours=3)

    read: list[int] = []
    real = Store.trials_for

    def counted(self, contracts=(), runs=()):
        found = real(self, contracts, runs)
        read.append(len(found))
        return found

    monkeypatch.setattr(Store, "trials_for", counted)
    narrow = _board_state(B.build(arms))
    every = Store(arms).effective_trials()
    assert read and max(read) < len(every), "the build read fewer trials than the ledger holds"

    monkeypatch.setattr(Store, "trials_for", lambda self, contracts=(), runs=(): self.effective_trials())
    assert narrow == _board_state(B.build(arms))


def test_one_build_reads_one_commit(research, monkeypatch):
    """A commit landing while a build reads its declarations does not reach the rules it reads next."""
    import component_belief.declarations as declarations

    real = declarations.load

    def load_then_commit(root, revision="HEAD"):
        decl = real(root, revision)
        monkeypatch.setattr(declarations, "load", real)
        (research / B.RULES_FILE).write_text(RULES.replace("implement: 1", "implement: 5"), encoding="utf-8")
        git(research, "commit", "-qam", "the rules change mid-build")
        return decl

    head = git(research, "rev-parse", "HEAD").stdout.strip()
    monkeypatch.setattr(declarations, "load", load_then_commit)
    board = B.build(research)
    assert board.commit == head
    assert board.rules.costs["implement"] == 1, "the rules came from the commit the declarations did"
    assert git(research, "rev-parse", "HEAD").stdout.strip() != head


def test_a_recording_move_saves_no_content_digest(research, clock):
    """A result judged against a git-ignored input hashes it, and a move keeps that digest in memory:
    recording writes .research/ and nothing else (DEF-research-ledger)."""
    (research / ".gitignore").write_text("ckpt/\n", encoding="utf-8")
    (research / "ckpt").mkdir()
    (research / "ckpt" / "w.bin").write_bytes(b"weights-v1")
    text = (research / "goals.yaml").read_text(encoding="utf-8").replace(
        "    run: python eval/pick.py $OUT\n", "    run: python eval/pick.py $OUT\n    reads: [ckpt/w.bin]\n", 1)
    (research / "goals.yaml").write_text(text, encoding="utf-8")
    git(research, "add", "-A")
    git(research, "commit", "-qm", "the pick eval reads a checkpoint git ignores")
    did = funded(research)
    play.spend(research, did, "test", "TST-pick")
    next_second()
    measure(research)
    (research / "ckpt" / "w.bin").write_bytes(b"weights-v2-retrained")
    before = _tree(research)
    play.feedback(research, did, "the checkpoint was retrained", by="scout-1")
    moved = {p for p in set(before) | set(_tree(research)) if before.get(p) != _tree(research).get(p)}
    assert moved == {".research/ledger.jsonl", ".research/BOARD.md"}
    result = B.build(research).results[last_spend(research)]
    assert "stale" in result.states.values(), "the retrained checkpoint was judged, by its content"


# ---------- the live board and its export (DEF-live-board) ----------

import http.client
import threading as _threading

from research_board.data import board_data
from research_board.live import EXPORT_DIR, export
from research_board.live.scouts import ScoutWatch, project_folder
from research_board.live.server import LiveBoard, start


class Served:
    """research-board serve on a free port, its loop not running: the test moves it by hand."""

    def __init__(self, root: Path, **kwargs) -> None:
        self.server, self.live = start(root, "127.0.0.1", 0, follow=False, **kwargs)
        self.port = self.server.server_address[1]
        self.thread = _threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def get(self, path: str, host: str | None = None) -> tuple[int, dict, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", path, headers={"Host": host or f"127.0.0.1:{self.port}"})
        reply = conn.getresponse()
        if path == "/events":                              # the first events, then hang up
            body = b""
            while body.count(b"\n\n") < 2:
                body += reply.read1(65536)
        else:
            body = reply.read()
        conn.close()
        return reply.status, dict(reply.getheaders()), body

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def served(research, clock, monkeypatch):
    monkeypatch.delenv("GIT_OPTIONAL_LOCKS", raising=False)
    did = funded(research)
    play.spend(research, did, "test", "TST-pick")
    next_second()
    measure(research)
    instance = Served(research)
    yield instance
    instance.close()


def test_the_live_view_serves_the_board_its_build_computed(served, research):
    status, headers, body = served.get("/board.json")
    shown = json.loads(body)
    expected = board_data(B.build(research), mode="live")      # the same clock: the same moment
    head = git(research, "rev-parse", "HEAD").stdout.strip()
    assert status == 200
    assert shown["meta"]["commit"] == head and shown["meta"]["generated_at"] == expected["meta"]["generated_at"]
    shown["meta"].pop("build_seconds")
    assert shown == json.loads(json.dumps(expected, default=str))
    status, headers, page = served.get("/")
    nonce = re.search(r"'nonce-([^']+)'", headers["Content-Security-Policy"]).group(1)
    assert status == 200 and f'nonce="{nonce}"' in page.decode()
    assert "https://" not in page.decode().split("<script", 1)[0], "the live page loads nothing from another host"


def test_serving_the_live_view_writes_nothing(served, research, clock):
    import os

    before, index = _tree(research), (research / ".git" / "index").read_bytes()
    for path in ("/", "/board.json", "/scouts.json", "/static/mermaid.min.js", "/events"):
        assert served.get(path)[0] == 200, path
    clock.advance(minutes=20)
    served.live.rebuild()
    served.live.tick()
    assert os.environ["GIT_OPTIONAL_LOCKS"] == "0"
    assert _tree(research) == before
    assert (research / ".git" / "index").read_bytes() == index


def test_the_server_answers_only_requests_addressed_to_it(served):
    assert served.get("/board.json", host="evil.example")[0] == 403
    assert served.get("/board.json", host="evil.example:8765")[0] == 403
    assert served.get("/", host=f"localhost:{served.port + 1}")[0] == 200     # a tunnel's port
    assert served.get("/board.json", host="[::1]:9")[0] == 200


def test_a_board_is_pushed_only_when_it_changed(research, clock):
    live = LiveBoard(research, period=15.0)
    assert live.rebuild() and live.version == 1
    assert not live.rebuild() and live.version == 1, "nothing moved: no new board"
    play.open_direction(research, "another-idea", "GOL-grasp", "Try another idea")
    assert live.rebuild() and live.version == 2


def test_a_mermaid_block_a_scout_wrote_is_shown_as_code(research):
    block = "```mermaid\nflowchart LR\n  A[click] --> B\n```"
    play.open_direction(research, "copied", "GOL-grasp", f"From a page:\n\n{block}", by="scout-1")
    did = "DIR-copied"
    play.add_trail(research, did, "A paper", f"tweak\n\n{block}", "CMP-grasp", QUOTE, by="scout-1")
    play.feedback(research, did, f"see this\n\n{block}", by="director")      # a scout can claim to be one
    play.digest(research, did, f"facts\n\n{block}")
    data = board_data(B.build(research))
    d = next(x for x in data["directions"] if x["id"] == did)
    assert "```mermaid" in d["digest"], "the director's digest keeps its diagram"
    d.pop("digest")
    data["feed"] = [f for f in data["feed"] if f["kind"] != "digest"]
    assert "```mermaid" not in json.dumps(data)
    assert "```text" in d["idea"] and "```text" in d["trails"][0]["tweak"] and "```text" in d["feedback"][0]["text"]


def test_an_export_writes_its_three_files_and_nothing_else(research):
    funded(research)
    before = _tree(research)
    said = export(research)
    moved = {p for p in set(before) | set(_tree(research)) if before.get(p) != _tree(research).get(p)}
    assert moved == {f"{EXPORT_DIR}/board.html", f"{EXPORT_DIR}/board.json", f"{EXPORT_DIR}/.gitignore"}, said
    assert git(research, "status", "--porcelain", "--", EXPORT_DIR).stdout == "", "git leaves the directory alone"
    page = (research / EXPORT_DIR / "board.html").read_text(encoding="utf-8")
    assert not page.lstrip().lower().startswith(("<!doctype", "<html")), "a fragment an Artifact publishes"
    assert 'integrity="sha384-' in page and '"mode": "snapshot"' in page


def test_an_export_writes_nothing_where_a_declaration_names_its_files(research):
    text = (research / "belief.yaml").read_text(encoding="utf-8").replace(
        "    code: [grasp.py]\n", f"    code: [grasp.py, {EXPORT_DIR}/board.json]\n", 1)
    (research / "belief.yaml").write_text(text, encoding="utf-8")
    git(research, "commit", "-qam", "a component claims the export's data")
    said = export(research)
    assert said.startswith("nothing written") and "CMP-grasp" in said
    assert not (research / EXPORT_DIR).exists()


def test_an_export_writes_nothing_where_a_tests_latest_run_read_its_files(research):
    from component_belief.store import Store

    run_id = measure(research)
    (Store(research).artifacts_dir / run_id / "reads.json").write_text(
        json.dumps(["eval/pick.py", f"{EXPORT_DIR}/board.json"]), encoding="utf-8")
    said = export(research)
    assert said.startswith("nothing written") and f"TST-pick ({run_id})" in said
    assert not (research / EXPORT_DIR).exists()


def test_an_exported_board_carries_no_process_id_path_or_exception(research, clock, monkeypatch):
    from component_belief.store import Store

    did = funded(research)
    play.spend(research, did, "test", "TST-pick")
    launched(research, "TST-pick", clock.at)

    def unreadable(self, contracts=(), runs=()):
        raise OSError(f"cannot open {research}/.belief/evidence.jsonl: secret detail")

    monkeypatch.setattr(Store, "trials_for", unreadable)
    export(research)
    data = (research / EXPORT_DIR / "board.json").read_text(encoding="utf-8")
    assert str(research) not in data and "secret detail" not in data and '"pid"' not in data
    assert "could not be read" in data


def _transcript(folder: Path, name: str, calls: list[dict], brief: str, age: float, meta: dict | None = None) -> None:
    import os

    sub = folder / "session-1" / "subagents"
    sub.mkdir(parents=True, exist_ok=True)
    (sub / f"agent-{name}.meta.json").write_text(json.dumps({"agentType": "tdlp:research-scout",
                                                              "description": f"Scout {name}", **(meta or {})}))
    lines = [{"timestamp": "2026-10-22T05:00:00Z", "message": {"role": "user", "content": brief}}]
    for i, call in enumerate(calls):
        block = {"type": "tool_use", "id": f"{name}-{i}", "name": call["name"], "input": call["input"]}
        lines += [{"timestamp": "2026-10-22T05:01:00Z", "message": {"role": "assistant", "content": [block]}}] * 2
    path = sub / f"agent-{name}.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    moment = time.time() - age
    os.utime(path, (moment, moment))


def test_a_scout_works_while_it_writes_whatever_its_meta_file_says(tmp_path):
    folder = tmp_path / "project"
    _transcript(folder, "writing", [], "Deepen DIR-a on GOL-x", age=20)
    _transcript(folder, "quiet", [], "Deepen DIR-b on GOL-x", age=3600)
    _transcript(folder, "done", [], "Deepen DIR-c on GOL-x", age=3600, meta={"finished": True})
    _transcript(folder, "claims-done", [], "Deepen DIR-d on GOL-x", age=5, meta={"finished": True})
    scouts = {s["id"].removeprefix("agent-"): s for s in ScoutWatch([folder]).poll()["scouts"]}
    assert scouts["writing"]["working"] and scouts["claims-done"]["working"]
    assert not scouts["quiet"]["working"] and not scouts["quiet"]["finished"]
    assert not scouts["done"]["working"] and scouts["done"]["finished"]


def test_a_scouts_directions_come_from_its_own_calls_counted_once(tmp_path):
    folder = tmp_path / "project"
    calls = [{"name": "mcp__plugin_tdlp_research-board__board", "input": {"direction": "DIR-read-first"}},
             {"name": "WebSearch", "input": {"query": "door handles"}},
             *[{"name": "mcp__plugin_tdlp_research-board__add_trail", "input": {"direction": "DIR-door", "paper": f"P{i}"}}
               for i in range(3)],
             {"name": "mcp__plugin_tdlp_research-board__feedback", "input": {"about": "DIR-handle", "text": "q"}},
             {"name": "mcp__plugin_tdlp_research-board__open_direction", "input": {"name": "On-policy labels", "goal": "GOL-x"}}]
    _transcript(folder, "s", calls, "Research GOL-x, starting from DIR-elsewhere", age=10)
    scout = ScoutWatch([folder]).poll()["scouts"][0]
    assert scout["directions"] == [["DIR-door", 3], ["DIR-handle", 1], ["DIR-on-policy-labels", 1]]
    assert scout["goal"] == "GOL-x" and scout["reading"] == "DIR-read-first"
    assert scout["counts"] == {"searches": 1, "pages": 0, "trails": 3, "feedback": 1, "directions": 1}
    assert len(scout["actions"]) == 7


def test_the_scouts_view_says_why_it_shows_none(tmp_path):
    assert "no transcripts found" in ScoutWatch([tmp_path / "missing"]).poll()["empty"]
    (tmp_path / "empty").mkdir()
    assert ScoutWatch([tmp_path / "empty"]).poll()["empty"] == "no scout has run in this project"
    assert project_folder(Path("/home/me/My_Repo.v2"), home=Path("/h")) == Path("/h/.claude/projects/-home-me-My-Repo-v2")
