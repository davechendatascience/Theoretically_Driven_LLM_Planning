"""The moves: every write the board makes, and the rules each one is checked against.

Each move appends one record to the research ledger and rewrites the board page beside it, and
does nothing else (DEF-research-ledger). A move the rules do not allow appends nothing and says
why, and what would allow it. Research moves -- opening a direction, adding a trail, feedback --
are open to the scouts; approving, spending and reflecting are the director's, and the scout's
tool list leaves them out.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import threading
from pathlib import Path
from typing import Any

from . import board as B
from .page import write_page

#: One writer at a time within a server process: ids are counted from the ledger as it stands, so
#: two moves counting at once would hand out the same id.
_LOCK = threading.RLock()

_PREFIX = {"trail": "TRAIL", "spend": "SPD", "feedback": "FBK", "evidence": "EVD", "digest": "DGT"}

#: What a measured finding may be: data and reports, which a scout may read, never source code.
EVIDENCE_SUFFIXES = (".json", ".jsonl", ".csv", ".tsv", ".txt", ".md", ".log")
EVIDENCE_BYTES = 2_000_000
#: A digest leads every brief on its direction, so it stays short enough to always be read.
DIGEST_CHARS = 4000


class Refused(Exception):
    """A move the rules do not allow; its message says why and what would allow it."""


def _record(root: Path, board: B.Board, kind: str, fields: dict[str, Any]) -> tuple[dict[str, Any], B.Board]:
    """Append one record and rewrite the page; nothing else on disk changes. `board` is the one the
    move was checked against. Returns the record and the board the page drew after it."""
    named = B.naming_research(root, board.decl)
    if named:
        raise Refused(
            f"{', '.join(named)} name{'s' if len(named) == 1 else ''} a file in {B.RESEARCH_DIR}/, so "
            f"evidence rests on what is there and recording would move it. Drop {B.RESEARCH_DIR}/ "
            "from those declarations to keep research here.")
    read = B.reading_research(root, board.decl)
    if read:
        raise Refused(
            f"the latest run of {', '.join(read)} opened a file in {B.RESEARCH_DIR}/, as its read hook saw, "
            "so its evidence rests on what is there and recording would move it. Change the test to leave "
            f"{B.RESEARCH_DIR}/ alone and run it again.")
    record = {"kind": kind, **fields, "timestamp": B.utc_now()}
    if kind in _PREFIX and not fields.get("id"):
        record = {"id": _next_id(root, kind), **record}
    path = B.ledger_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")
    return record, write_page(root)


def _next_id(root: Path, kind: str) -> str:
    n = sum(1 for r in B.read_ledger(root) if r.get("kind") == kind)
    return f"{_PREFIX[kind]}-{n + 1:04d}"


def _direction(board: B.Board, direction: str) -> B.Direction:
    d = board.directions.get(direction) or board.directions.get(B.direction_id(direction))
    if d is None:
        known = ", ".join(sorted(board.directions)) or "none yet"
        raise Refused(f"no direction {direction!r}; directions: {known}")
    return d


def _required(**values: str) -> None:
    for name, value in values.items():
        if not str(value or "").strip():
            raise Refused(f"{name} is required")


def _balance(board: B.Board, direction_id: str) -> int:
    return board.balance(board.directions[direction_id])


def open_direction(root: Path, name: str, goal: str, idea: str, assessment: str = "",
                   by: str = "director", pivot_from: str | None = None) -> str:
    _required(name=name, goal=goal, idea=idea)
    with _LOCK:
        board = B.build(root, with_results=False)
        did = B.direction_id(name)
        if not did:
            raise Refused(f"name {name!r} has no letters or digits to make an id from")
        if did in board.directions:
            raise Refused(f"{did} is already open; add research to it with add_trail")
        if goal not in board.decl.goals:
            declared = ", ".join(sorted(board.decl.goals)) or "none: goals.yaml declares no goal at HEAD"
            raise Refused(f"no goal {goal!r} in goals.yaml at HEAD; a direction serves one of yours. "
                          f"Goals: {declared}")
        if pivot_from:
            pivot_from = _direction(board, pivot_from).id
        record, _ = _record(root, board, "direction", {
            "id": did, "goal": goal, "idea": idea.strip(), "assessment": assessment.strip(), "by": by,
            "pivot_from": pivot_from or ""})
    return (f"{record['id']} opened for {goal} at 0 points. It earns through add_trail; nothing is "
            f"spent on it before the director's approve(\"{record['id']}\", ...).")


def add_trail(root: Path, direction: str, paper: str, tweak: str, component: str = "", quote: str = "",
              at: str = "", expect: str = "", by: str = "director", kind: str = B.TWEAK) -> str:
    """A trail: a paper and what it suggests. A tweak names the component it would change; a method
    -- an instrument or a way to measure -- names the component, test or contract it measures with;
    a paper set aside says, in `tweak`, why it was read and not taken up, and earns nothing."""
    _required(paper=paper, tweak=tweak)
    if kind not in B.TRAIL_KINDS:
        raise Refused(f"kind must be one of {', '.join(B.TRAIL_KINDS)}")
    with _LOCK:
        board = B.build(root, with_results=False)
        d = _direction(board, direction)
        decl = board.decl
        unearned: list[str] = []
        if kind == B.SET_ASIDE:
            unearned.append("a paper set aside earns nothing; it is kept so the next scout does not read it again")
        elif d.state in (B.REJECTED, B.HALTED):
            unearned.append(f"{d.id} is {d.state}")
        if kind != B.SET_ASIDE:
            if not quote.strip():
                unearned.append("no quote: a paper not quoted is a lead, not yet research")
            if not component:
                unearned.append("it names no component" + (", test or contract" if kind == B.METHOD else ""))
            elif kind == B.METHOD and not any(component in t for t in (decl.components, decl.tests, decl.contracts)):
                unearned.append(f"{component} is no component, test or contract declared at HEAD")
            elif kind == B.TWEAK and component not in decl.components:
                unearned.append(f"{component} is not a component belief.yaml declares at HEAD")
            key = B.paper_key(paper)
            for earlier in d.trails:
                if (B.paper_key(str(earlier.get("paper", ""))) == key and not board.rejected(earlier["id"])
                        and earlier.get("type") != B.SET_ASIDE):     # a paper set aside may still be taken up
                    unearned.append(f"{earlier['id']} already cites this paper in {d.id}")
                    break
        points = 0 if unearned else board.rules.earn
        record, after = _record(root, board, "trail", {
            "direction": d.id, "type": kind, "paper": paper.strip(), "at": at.strip(), "quote": quote.strip(),
            "tweak": tweak.strip(), "component": component.strip(), "expect": expect.strip(), "by": by,
            "points": points, "unearned": "; ".join(unearned)})
    if kind == B.SET_ASIDE:
        return f"{record['id']} on {d.id}: set aside, 0 points; every brief on {d.id} lists it as read."
    earned = f"+{points}" if points else f"0 points ({'; '.join(unearned)})"
    return f"{record['id']} on {d.id}: {earned}. {d.id} balance {_balance(after, d.id)}."


def feedback(root: Path, about: str, text: str, kind: str = B.NOTE, reply_to: str | None = None,
             by: str = "director") -> str:
    _required(about=about, text=text)
    if kind not in B.FEEDBACK_KINDS:
        raise Refused(f"kind must be one of {', '.join(B.FEEDBACK_KINDS)}; approvals and reflections "
                      "are approve() and reflect()")
    with _LOCK:
        board = B.build(root, with_results=False)
        direction = board.direction_of(about)
        goal = about if not direction and about in board.decl.goals else ""
        if not direction and not goal:
            raise Refused(f"{about!r} is no goal, direction, trail or spend on the board; feedback is "
                          "addressed to what it is about, so the next scout on it reads it")
        if reply_to:
            parent = board.feedback.get(reply_to)
            if parent is None:
                raise Refused(f"no feedback {reply_to!r} to reply to")
            if kind == B.ANSWER and parent.get("type") not in (B.QUESTION, B.CHECK):
                raise Refused(f"{reply_to} is a {parent.get('type')}, not a question or a check")
        elif kind == B.ANSWER:
            raise Refused("an answer names the question it answers: reply_to=<FBK- id>")
        fields = {"about": about, "direction": direction, "type": kind, "text": text.strip(),
                  "reply_to": reply_to or "", "by": by}
        if goal:
            fields["goal"] = goal
        record, _ = _record(root, board, "feedback", fields)
    if kind == B.QUESTION:
        return (f"{record['id']}: question on {about} recorded; it stays open on the board until the "
                f"director answers it with feedback(..., kind=\"answer\", reply_to=\"{record['id']}\").")
    if kind == B.CHECK:
        return (f"{record['id']}: check on {about} recorded; it stays open on the board until the director "
                f"answers it (feedback(..., kind=\"answer\", reply_to=\"{record['id']}\")) or attaches what "
                f"it measured (evidence(..., reply_to=\"{record['id']}\")).")
    where = f"{direction}'s feedback" if direction else f"the notes on {goal}, which every brief on it carries"
    return f"{record['id']}: {kind} on {about} recorded, in {where}."


def approve(root: Path, target: str, approved: bool, why: str, rank: int | None = None) -> str:
    _required(target=target, why=why)
    with _LOCK:
        board = B.build(root, with_results=False)
        if target in board.trails:
            if rank is not None:
                raise Refused("rank orders directions, not trails")
            direction = str(board.trails[target].get("direction"))
        else:
            direction = _direction(board, target).id
            target = direction
            if rank is not None and (not isinstance(rank, int) or isinstance(rank, bool) or rank < 1):
                raise Refused("rank is 1 for the direction to try first, 2 for the next, ...")
        verdict = B.APPROVED if approved else B.REJECTED
        record, after = _record(root, board, "feedback", {
            "about": target, "direction": direction, "type": verdict, "text": why.strip(),
            "rank": rank if approved else None, "reply_to": "", "by": "director"})
    balance = _balance(after, direction)
    if target in after.trails:
        worth = int(after.trails[target].get("points") or 0)
        moved = f"its {worth} point{'s' if worth != 1 else ''} {'count' if approved else 'no longer count'}"
        return f"{record['id']}: {target} {verdict} -- {moved}. {direction} balance {balance}."
    ranked = f", rank {rank}" if approved and rank else ""
    return f"{record['id']}: {direction} {verdict}{ranked}. Balance {balance}."


def spend(root: Path, direction: str, action: str, target: str, expect: str = "",
          params: dict[str, Any] | None = None) -> str:
    """A spend commits points, and a commitment to test the direction by every measurement recorded
    afterwards against the contracts it names now (DEF-research-ledger) -- by the test it names, run
    with the parameter values it fixes, when it fixes any."""
    _required(direction=direction, action=action, target=target)
    with _LOCK:
        board = B.build(root)
        d = _direction(board, direction)
        if d.state == B.REJECTED:
            raise Refused(f"{d.id} was rejected; open another direction, or approve this one again")
        if d.state == B.HALTED:
            raise Refused(f"{d.id} is halted ({d.decision.get('text', '')}); "
                          f"reflect(\"{d.id}\", \"continue\", why) to resume it")
        if not d.approved:
            raise Refused(f"{d.id} is not approved; approve(\"{d.id}\", True, why) comes before anything "
                          "is spent on it")
        if d.unreflected:
            raise Refused(f"{', '.join(d.unreflected)} settled since {d.id}'s last reflection; "
                          f"reflect(\"{d.id}\", continue|halt|pivot, why) before spending again")
        costs = board.rules.costs
        if action not in costs:
            raise Refused(f"no action {action!r} in the rules; actions: "
                          + ", ".join(f"{a} {c}" for a, c in costs.items()))
        decl = board.decl
        if not any(target in table for table in (decl.components, decl.contracts, decl.tests, decl.goals,
                                                 decl.interfaces, decl.goal_interfaces)):
            raise Refused(f"{target!r} is not declared in belief.yaml or goals.yaml at HEAD")
        values: dict[str, str] = {}
        if params:
            if target not in decl.tests:
                raise Refused(f"params fix the arm of a test; {target} is no test")
            values, why = decl.tests[target].bind(params)
            if why:
                raise Refused(why)
        cost = costs[action]
        balance = board.balance(d)
        if balance < cost:
            idled = board.idle_points(d)
            raise Refused(f"{action} costs {cost} and {d.id} holds {balance}"
                          + (f" (idle hours took {idled})" if idled else "")
                          + f": {cost - balance} more point(s) of research first (add_trail)")
        commit = (B.git(root, "rev-parse", "--short", "HEAD") or "").strip()
        contracts = B.targeted_contracts(decl, target)        # fixed now; a later declaration adds none
        rules = board.rules                                   # so are the idle terms: a later rule reprices none
        record, _ = _record(root, board, "spend", {
            "direction": d.id, "action": action, "target": target, "contracts": contracts,
            "test": target if target in decl.tests else "", "params": values,
            "expect": expect.strip(), "cost": cost, "commit": commit, "by": "director",
            "idle": {"per_hour": rules.idle_per_hour, "running_minutes": rules.running_minutes,
                     "from": B.FIRST_RUN}})
    arm = "".join(f" {k}={v}" for k, v in values.items())
    by_test = f"{target}{arm}'s runs " if target in decl.tests else "Runs "
    if target in decl.tests and decl.tests[target].declared_params() and not values:
        by_test = f"{target}'s runs, every arm of it (fix one with params=), "
    counts = (f"{by_test}measured on {', '.join(contracts)} from now count for {d.id}; run them with run_test."
              if contracts else
              f"{target} names no contract, so this spend pays for the work and has no result of its own. "
              f"Its result comes from a later spend on the contract or test that measures the work, once "
              f"belief.yaml or goals.yaml declares it at HEAD: commit the declaration, then spend on it.")
    if contracts and rules.idle_per_hour:
        counts += (f" From when its first run starts until the result is in, every hour with no research "
                   f"recorded costs {d.id} {rules.idle_per_hour} point{'s' if rules.idle_per_hour != 1 else ''}: "
                   "keep scouts out while it runs. Until a run starts, the spend is queued and costs nothing.")
    return f"{record['id']}: {action} -> {target} for {d.id}, {cost} point(s); balance {balance - cost}. {counts}"


def reflect(root: Path, direction: str, decision: str, why: str) -> str:
    _required(direction=direction, decision=decision, why=why)
    if decision not in B.DECISIONS:
        raise Refused(f"decision must be one of {', '.join(B.DECISIONS)}")
    with _LOCK:
        board = B.build(root, with_results=False)
        d = _direction(board, direction)
        if not d.approved:
            raise Refused(f"{d.id} is not approved; a proposal is rejected with approve(\"{d.id}\", False, why)")
        record, _ = _record(root, board, "feedback", {
            "about": d.id, "direction": d.id, "type": decision, "text": why.strip(), "reply_to": "",
            "by": "director"})
    if decision == B.PIVOT:
        return (f"{record['id']}: {d.id} halted to pivot. Open the next one with "
                f"open_direction(..., pivot_from=\"{d.id}\"); its brief will carry this reflection.")
    if decision == B.HALT:
        return f"{record['id']}: {d.id} halted; it stays on the board with this reason."
    return f"{record['id']}: {d.id} continues."


def evidence(root: Path, direction: str, artifact: str, summary: str, by: str = "director",
             reply_to: str | None = None) -> str:
    """Attach a measured finding to a direction: a data file or report the director produced
    outside a declared test. The board keeps its own copy of the bytes and their digest, so what a
    scout reads later is what was attached, and serves it through ledger(evidence=...). It is
    never a result: a spend's result comes from measured runs only (DEF-research-ledger). With
    `reply_to`, it answers the check or question it measured, which then waits on no one."""
    _required(direction=direction, artifact=artifact, summary=summary)
    from component_belief.staleness import matches, named_paths

    with _LOCK:
        board = B.build(root, with_results=False)
        d = _direction(board, direction)
        if reply_to:
            parent = board.feedback.get(reply_to)
            if parent is None or parent.get("type") not in (B.QUESTION, B.CHECK):
                raise Refused(f"{reply_to} is no question or check on the board; a finding replies to the "
                              "one it measured")
        path = (root / artifact).resolve()
        try:
            rel = path.relative_to(root.resolve()).as_posix()
        except ValueError:
            raise Refused(f"{artifact!r} is outside the project") from None
        if not path.is_file():
            raise Refused(f"no file {rel!r}")
        if rel.split("/", 1)[0] in (".git", ".belief", ".consistency", B.RESEARCH_DIR):
            raise Refused(f"{rel} is in a ledger; ledger(run=...) and ledger(node=...) already serve those")
        if path.suffix.lower() not in EVIDENCE_SUFFIXES:
            raise Refused(f"{rel} is not a data file or report ({', '.join(EVIDENCE_SUFFIXES)}); a finding "
                          "is what was measured, never the code that measured it")
        claimed = sorted(cid for cid, comp in board.decl.components.items() if any(matches(rel, e) for e in comp.code))
        named = sorted(tid for tid, test in board.decl.tests.items()
                       if named_paths(test.run, list(test.reads), {rel}))
        if claimed or named:
            raise Refused(f"{rel} is {'claimed by ' + ', '.join(claimed) if claimed else 'named by ' + ', '.join(named)}"
                          "; a scout reads no file a component claims or a test runs")
        size = path.stat().st_size
        if size > EVIDENCE_BYTES:
            raise Refused(f"{rel} is {size} bytes; attach a summary table under {EVIDENCE_BYTES} bytes instead")
        eid = _next_id(root, "evidence")
        copy = B.evidence_dir(root, eid) / path.name
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, copy)
        digest = hashlib.sha256(copy.read_bytes()).hexdigest()[:16]
        points = 0 if d.state in (B.REJECTED, B.HALTED) else board.rules.earn_evidence
        record, after = _record(root, board, "evidence", {
            "id": eid, "direction": d.id, "artifact": rel, "copy": copy.relative_to(root).as_posix(),
            "sha256": digest, "bytes": size, "summary": summary.strip(), "by": by, "points": points,
            "reply_to": reply_to or "",
            "commit": (B.git(root, "rev-parse", "--short", "HEAD") or "").strip()})
    worth = f"+{points}" if points else "0 points"
    return (f"{eid} on {d.id}: {rel} ({size} bytes, sha256 {digest}) kept as {record['copy']}, {worth}; "
            f"scouts read it with ledger(evidence=\"{eid}\"). {d.id} balance {_balance(after, d.id)}.")


def retarget(root: Path, direction: str, goal: str, why: str) -> str:
    """Point a direction at another goal of yours -- the subgoal it was really for, once committed.
    Its trails, spends and feedback stay where they are; every brief on it then carries that goal's
    standing rules and sits among that goal's directions."""
    _required(direction=direction, goal=goal, why=why)
    with _LOCK:
        board = B.build(root, with_results=False)
        d = _direction(board, direction)
        if goal not in board.decl.goals:
            declared = ", ".join(sorted(board.decl.goals)) or "none: goals.yaml declares no goal at HEAD"
            raise Refused(f"no goal {goal!r} in goals.yaml at HEAD; commit it first. Goals: {declared}")
        if goal == d.goal:
            raise Refused(f"{d.id} already serves {goal}")
        was = d.goal
        record, _ = _record(root, board, "feedback", {
            "about": d.id, "direction": d.id, "type": B.RETARGET, "goal": goal, "from_goal": was,
            "text": why.strip(), "reply_to": "", "by": "director"})
    return f"{record['id']}: {d.id} now serves {goal} (it served {was}); its briefs carry {goal}'s standing rules."


def digest(root: Path, direction: str, text: str) -> str:
    """The director's "facts so far" for a direction, which leads every brief on it. A new digest
    replaces the last on the board; the ledger keeps every one. Scouts propose changes through
    feedback; the director decides what the next scout reads first."""
    _required(direction=direction, text=text)
    if len(text.strip()) > DIGEST_CHARS:
        raise Refused(f"a digest leads every brief, so it is at most {DIGEST_CHARS} characters "
                      f"({len(text.strip())} given); leave the rest in feedback, where a scout can page it")
    with _LOCK:
        board = B.build(root, with_results=False)
        d = _direction(board, direction)
        record, _ = _record(root, board, "digest", {"direction": d.id, "text": text.strip(), "by": "director"})
    return f"{record['id']}: {d.id}'s digest is now what every brief on it leads with."
