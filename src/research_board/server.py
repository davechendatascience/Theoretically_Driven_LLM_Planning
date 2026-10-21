"""MCP server -- the research board.

Two reads (board, ledger), three research moves open to scouts (open_direction, add_trail,
feedback), and five moves the director keeps (approve, spend, reflect, evidence, digest). Nothing here records
evidence, a trial or a decision in another ledger, and no tool writes a balance or a result: both
are computed from the ledgers every time they are read.
"""

from __future__ import annotations

from pathlib import Path

from component_belief.project import ProjectServer, project_root as resolve_root

from . import board as B
from . import play, reading
from .page import render_board, render_brief, render_item, render_section

INSTRUCTIONS = """\
Research directions for a goal: the papers behind each, the tweak each suggests to a component,
what was spent testing it, and what came of it. The rules (focus goal, costs, what a trail earns,
how many scouts) live in research.yaml and take effect from git HEAD; the play is an append-only
ledger in .research/, with a page beside it, BOARD.md, for the human.

Research is free and earns points; work for a direction costs them. A result counts for a direction
only from runs recorded after points were spent on it: spend(direction, action, target) first, then
build and run_test. Work done without spending is always allowed -- its results belong to no
direction. While a test paid for waits on its result, keep research running: every hour in which no
research is recorded costs the waiting direction points (idle in
research.yaml): an earning trail, a new direction, a measured finding, a scout's question or an
answer keeps research running for running_minutes; a note does not.

The director is the main agent: it approves or rejects directions and trails (approve), spends, and
reflects after a result settles (reflect: continue, halt or pivot). Scouts are research-scout
subagents, sent in the background while results are pending: each reads board(direction=...) -- a
head that always fits, with the human's standing rules for the goal, the director's digest and an
index -- then the sections it needs, and the ledgers (ledger()), never the code; it records
add_trail, open_direction and feedback. Feedback is addressed to a goal, direction, trail or spend,
so the next scout on it reads the thread. A question only the director can answer means the
contract is missing a metric: answer it, then add the metric so the next run records it. The
director keeps each direction's digest (digest) and attaches its own measured findings (evidence).

The loop: board() -> scouts (add_trail) -> approve -> spend -> run_test -> board() -> reflect.
Commit .research/ with your work; research.yaml is yours to change, and the board names the commit.
"""

mcp = ProjectServer("research-board", instructions=INSTRUCTIONS)


def project_root() -> Path:
    return resolve_root("RESEARCH_BOARD_ROOT", "BELIEF_PROJECT_ROOT")


def _move(fn, *args, **kwargs) -> str:
    try:
        return fn(project_root(), *args, **kwargs)
    except play.Refused as exc:
        return f"not recorded: {exc}"


@mcp.tool()
def board(direction: str | None = None, section: str | None = None, part: int = 1,
          item: str | None = None) -> str:
    """The research board: every direction in the order to act on it, with what waits on whom.

    direction: a DIR- id for that direction's brief. Its head always fits: the goal and the human's
               standing rules for it, the director's digest, open questions, the latest feedback,
               the papers already cited, and an index of the rest. A scout reads this first.
    section:   with direction, the rest a page at a time: trails, spends, feedback, evidence, goal
               (notes on the goal itself), directions (the others on the goal) or components.
    part:      which page of a section, from 1.
    item:      any one record in full, by its id (DIR-, TRAIL-, SPD-, FBK-, EVD-), with the
               feedback on it and the replies to it.
    """
    b = B.build(project_root())
    if item:
        return render_item(b, item)
    if direction:
        d = b.directions.get(direction) or b.directions.get(B.direction_id(direction))
        if d is None:
            return f"no direction {direction!r}; directions: {', '.join(sorted(b.directions)) or 'none yet'}"
        return render_section(b, d, section, part) if section else render_brief(b, d)
    return render_board(b)


@mcp.tool()
def ledger(run: str | None = None, contract: str | None = None, node: str | None = None,
           evidence: str | None = None, limit: int = 20, fields: str = "") -> str:
    """Records from the project's ledgers, read-only. No source file is ever served.

    run:      a RUN- id: its evidence records and the output the run captured (stdout, stderr,
              result.json, the command) -- often more than the contract's metrics kept.
    contract: a CTR- id: its declaration, its tests' run lines and its latest records.
    node:     an AXM-/DEF-/LMA-/BRN- id: its statement and its verifiers' trials and notes.
    evidence: an EVD- id: a measured finding the director attached, as the board kept it.
    limit:    how many records, at most.
    fields:   for a run or a contract, what each record shows, comma-separated: metrics,
              conditions, output (the run's captured files). Default: all. "metrics" reads a run
              whose records or output are too long to read whole.
    With none, an overview of the three ledgers and the latest runs.
    """
    root = project_root()
    limit = max(1, min(int(limit or 20), 200))
    shown = {f.strip() for f in fields.split(",") if f.strip()} or set(reading.FIELDS)
    unknown = shown - set(reading.FIELDS)
    if unknown:
        return f"no field {', '.join(sorted(unknown))}; fields: {', '.join(reading.FIELDS)}"
    if evidence:
        return reading.serve_evidence(root, evidence)
    if run:
        return reading.serve_run(root, run, limit, shown)
    if contract:
        return reading.serve_contract(root, contract, limit, shown)
    if node:
        return reading.serve_node(root, node, limit)
    return reading.serve_overview(root, limit)


@mcp.tool()
def open_direction(name: str, goal: str, idea: str, assessment: str = "", by: str = "director",
                   pivot_from: str | None = None) -> str:
    """Open a research direction for one of the human's goals, at 0 points.

    name:       a short name; the id is DIR-<name>.
    idea:       the direction in one or two sentences.
    assessment: why it could move the goal, the cheapest test that would decide it, and its cost.
    by:         who opens it -- "director", or the scout's name.
    pivot_from: the halted direction this one replaces, if any.
    """
    return _move(play.open_direction, name, goal, idea, assessment, by, pivot_from)


@mcp.tool()
def add_trail(direction: str, paper: str, tweak: str, component: str = "", quote: str = "",
              at: str = "", expect: str = "", by: str = "director", kind: str = "tweak") -> str:
    """Record one piece of research on a direction: a paper, and what it suggests.

    kind:      tweak (a change to a component), method (an instrument or a way to measure), or
               set-aside (a paper you read and did not take up: earns nothing, and every brief on the
               direction lists it so the next scout does not read it again).
    paper:     the work -- authors, year, title. Only what you read; never a guessed citation.
    at:        where in it -- section, figure, page.
    quote:     the passage, verbatim, from the source you read.
    tweak:     what to change, and how; for a method, how to measure with it; for set-aside, why not.
    component: the CMP- id in belief.yaml the tweak changes; for a method, the CMP-, TST- or CTR- id
               it measures with.
    expect:    what a test would show if the tweak helps.
    A tweak or method earns the rules' points for a paper new to this direction, quoted, naming
    what is declared; otherwise it is kept, earning nothing, with the reason.
    """
    return _move(play.add_trail, direction, paper, tweak, component, quote, at, expect, by, kind)


@mcp.tool()
def feedback(about: str, text: str, kind: str = "note", reply_to: str | None = None,
             by: str = "director") -> str:
    """Leave feedback on a goal, direction, trail or spend, for whoever works on it next. A note on
    a GOL- id reaches every brief on that goal: what has been tried and measured, before any
    direction holds it.

    kind:     note; question (stays open until answered); check -- a measurement you propose the
              director make first, often free on data that exists (stays open until answered, or
              until a finding replies to it); or answer (reply_to the question or check).
    reply_to: the FBK- id this answers or follows.
    by:       "director", or the scout's name.
    """
    return _move(play.feedback, about, text, kind, reply_to, by)


@mcp.tool()
def approve(target: str, approved: bool, why: str, rank: int | None = None) -> str:
    """The director's verdict on a direction or a trail; it lands in the direction's feedback.

    A direction must be approved before anything is spent on it; rank orders the approved ones
    (1 = try first). A rejected trail's points stop counting.
    """
    return _move(play.approve, target, approved, why, rank)


@mcp.tool()
def spend(direction: str, action: str, target: str, expect: str = "") -> str:
    """Commit points to work for a direction, before doing it.

    action: one the rules price -- e.g. implement, test, dataset_eval, training_run.
    target: what the work is on: a CMP- to implement, or a CTR-/TST- whose results will count for
            this direction from now on.
    Refused on a direction not approved, short of the cost, or with a settled result nobody has
    reflected on yet. From when the spend's first run starts until its result is in, each hour with
    no research recorded on the board costs this direction the idle points the rules set now; a
    spend whose run has not started is queued and costs nothing, so spend when you decide.
    """
    return _move(play.spend, direction, action, target, expect)


@mcp.tool()
def reflect(direction: str, decision: str, why: str) -> str:
    """After a result settles: continue, halt or pivot, and why. It lands in the direction's
    feedback, and a halted direction stays on the board with its reason."""
    return _move(play.reflect, direction, decision, why)


@mcp.tool()
def evidence(direction: str, artifact: str, summary: str, reply_to: str | None = None) -> str:
    """Attach a measured finding to a direction: a data file or report you produced outside a
    declared test (a failure map, a table of a free check). The board keeps a copy and its digest,
    and scouts read it with ledger(evidence=...). It earns what research.yaml's earn.evidence sets
    (0 by default) and counts as research for the idle clock, but it is never a spend's result.

    artifact: a path in the project -- .json, .jsonl, .csv, .tsv, .txt, .md or .log, under 2 MB --
              that no component claims and no test runs.
    summary:  what it shows, in a line or two, with the number that matters.
    reply_to: the FBK- check or question this measures; it then waits on no one.
    """
    return _move(play.evidence, direction, artifact, summary, "director", reply_to)


@mcp.tool()
def retarget(direction: str, goal: str, why: str) -> str:
    """Point a direction at another of the human's goals -- the subgoal it was for, once committed.
    Its trails, spends and feedback stay; its briefs then carry that goal's standing rules."""
    return _move(play.retarget, direction, goal, why)


@mcp.tool()
def digest(direction: str, text: str) -> str:
    """Set a direction's "facts so far": what every brief on it leads with, so a scout reads the
    state of the question before its history. At most 4000 characters; a new one replaces the last
    on the board. Scouts propose changes in feedback; this is the director's."""
    return _move(play.digest, direction, text)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
