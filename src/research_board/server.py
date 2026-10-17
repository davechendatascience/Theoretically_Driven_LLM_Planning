"""MCP server -- the research board.

Two reads (board, ledger), three research moves open to scouts (open_direction, add_trail,
feedback), and three moves the director keeps (approve, spend, reflect). Nothing here records
evidence, a trial or a decision in another ledger, and no tool writes a balance or a result: both
are computed from the ledgers every time they are read.
"""

from __future__ import annotations

from pathlib import Path

from component_belief.project import project_root as resolve_root
from mcp.server.fastmcp import FastMCP

from . import board as B
from . import play, reading
from .page import render_board, render_brief

INSTRUCTIONS = """\
Research directions for a goal: the papers behind each, the tweak each suggests to a component,
what was spent testing it, and what came of it. The rules (focus goal, costs, what a trail earns,
how many scouts) live in research.yaml and take effect from git HEAD; the play is an append-only
ledger in .research/, with a page beside it, BOARD.md, for the human.

Research is free and earns points; work for a direction costs them. A result counts for a direction
only from runs recorded after points were spent on it: spend(direction, action, target) first, then
build and run_test. Work done without spending is always allowed -- its results belong to no
direction. While a test paid for waits on its result, keep research running: every hour in which no
trail, new direction or scout's feedback is recorded costs the waiting direction points (idle in
research.yaml; each record keeps research running for its running_minutes).

The director is the main agent: it approves or rejects directions and trails (approve), spends, and
reflects after a result settles (reflect: continue, halt or pivot). Scouts are research-scout
subagents, sent in the background while results are pending: each reads board(direction=...) and
the ledgers (ledger()), never the code, and records add_trail, open_direction and feedback.
Feedback is addressed to a direction, trail or spend, so the next scout on it reads the thread.
A question only the director can answer means the contract is missing a metric: answer it, then
add the metric so the next run records it.

The loop: board() -> scouts (add_trail) -> approve -> spend -> run_test -> board() -> reflect.
Commit .research/ with your work; research.yaml is yours to change, and the board names the commit.
"""

mcp = FastMCP("research-board", instructions=INSTRUCTIONS)


def project_root() -> Path:
    return resolve_root("RESEARCH_BOARD_ROOT", "BELIEF_PROJECT_ROOT")


def _move(fn, *args, **kwargs) -> str:
    try:
        return fn(project_root(), *args, **kwargs)
    except play.Refused as exc:
        return f"not recorded: {exc}"


@mcp.tool()
def board(direction: str | None = None) -> str:
    """The research board: every direction in the order to act on it, with what waits on whom.

    direction: a DIR- id for that direction's brief -- the goal, every trail, spend, result and
               feedback, the closed directions not to walk again, and the components a tweak can
               name. A scout reads this first.
    """
    b = B.build(project_root())
    if direction:
        d = b.directions.get(direction) or b.directions.get(B.direction_id(direction))
        if d is None:
            return f"no direction {direction!r}; directions: {', '.join(sorted(b.directions)) or 'none yet'}"
        return render_brief(b, d)
    return render_board(b)


@mcp.tool()
def ledger(run: str | None = None, contract: str | None = None, node: str | None = None,
           limit: int = 20) -> str:
    """Records from the project's ledgers, read-only. No source file is ever served.

    run:      a RUN- id: its evidence records and the output the run captured (stdout, stderr,
              result.json, the command) -- often more than the contract's metrics kept.
    contract: a CTR- id: its declaration, its tests' run lines and its latest records.
    node:     an AXM-/DEF-/LMA-/BRN- id: its statement and its verifiers' trials and notes.
    With none, an overview of the three ledgers and the latest runs.
    """
    root = project_root()
    limit = max(1, min(int(limit or 20), 200))
    if run:
        return reading.serve_run(root, run)
    if contract:
        return reading.serve_contract(root, contract, limit)
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
              at: str = "", expect: str = "", by: str = "director") -> str:
    """Record one piece of research on a direction: a paper, and the tweak it suggests.

    paper:     the work -- authors, year, title. Only what you read; never a guessed citation.
    at:        where in it -- section, figure, page.
    quote:     the passage, verbatim, from the source you read.
    tweak:     what to change, and how.
    component: the CMP- id in belief.yaml the tweak changes.
    expect:    what a test would show if the tweak helps.
    The trail earns the rules' points for a paper new to this direction, quoted, on a declared
    component; otherwise it is kept, earning nothing, with the reason.
    """
    return _move(play.add_trail, direction, paper, tweak, component, quote, at, expect, by)


@mcp.tool()
def feedback(about: str, text: str, kind: str = "note", reply_to: str | None = None,
             by: str = "director") -> str:
    """Leave feedback on a direction, trail or spend, for whoever works on it next.

    kind:     note, question (stays open until answered) or answer (reply_to the question).
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
    reflected on yet. From a spend on a contract until its result is in, each hour with no research
    recorded on the board costs this direction the idle points the rules set now.
    """
    return _move(play.spend, direction, action, target, expect)


@mcp.tool()
def reflect(direction: str, decision: str, why: str) -> str:
    """After a result settles: continue, halt or pivot, and why. It lands in the direction's
    feedback, and a halted direction stays on the board with its reason."""
    return _move(play.reflect, direction, decision, why)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
