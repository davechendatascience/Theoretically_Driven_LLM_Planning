"""The moves: every write the board makes, and the rules each one is checked against.

Each move appends one record to the research ledger and rewrites the board page beside it, and
does nothing else (DEF-research-ledger). A move the rules do not allow appends nothing and says
why, and what would allow it. Research moves -- opening a direction, adding a trail, feedback --
are open to the scouts; approving, spending and reflecting are the director's, and the scout's
tool list leaves them out.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from . import board as B
from .page import write_page

#: One writer at a time within a server process: ids are counted from the ledger as it stands, so
#: two moves counting at once would hand out the same id.
_LOCK = threading.RLock()

_PREFIX = {"trail": "TRAIL", "spend": "SPD", "feedback": "FBK"}


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
    record = {"kind": kind, **fields, "timestamp": B.utc_now()}
    if kind in _PREFIX:
        n = sum(1 for r in B.read_ledger(root) if r.get("kind") == kind)
        record = {"id": f"{_PREFIX[kind]}-{n + 1:04d}", **record}
    path = B.ledger_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")
    return record, write_page(root)


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
              at: str = "", expect: str = "", by: str = "director") -> str:
    _required(paper=paper, tweak=tweak)
    with _LOCK:
        board = B.build(root, with_results=False)
        d = _direction(board, direction)
        unearned: list[str] = []
        if d.state in (B.REJECTED, B.HALTED):
            unearned.append(f"{d.id} is {d.state}")
        if not quote.strip():
            unearned.append("no quote: a paper not quoted is a lead, not yet research")
        if not component:
            unearned.append("it names no component")
        elif component not in board.decl.components:
            unearned.append(f"{component} is not a component belief.yaml declares at HEAD")
        key = B.paper_key(paper)
        for earlier in d.trails:
            if B.paper_key(str(earlier.get("paper", ""))) == key and not board.rejected(earlier["id"]):
                unearned.append(f"{earlier['id']} already cites this paper in {d.id}")
                break
        points = 0 if unearned else board.rules.earn
        record, after = _record(root, board, "trail", {
            "direction": d.id, "paper": paper.strip(), "at": at.strip(), "quote": quote.strip(),
            "tweak": tweak.strip(), "component": component.strip(), "expect": expect.strip(), "by": by,
            "points": points, "unearned": "; ".join(unearned)})
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
        if not direction:
            raise Refused(f"{about!r} is no direction, trail or spend on the board; feedback is addressed "
                          "to what it is about, so the next scout on that direction reads it")
        if reply_to:
            parent = board.feedback.get(reply_to)
            if parent is None:
                raise Refused(f"no feedback {reply_to!r} to reply to")
            if kind == B.ANSWER and parent.get("type") != B.QUESTION:
                raise Refused(f"{reply_to} is a {parent.get('type')}, not a question")
        elif kind == B.ANSWER:
            raise Refused("an answer names the question it answers: reply_to=<FBK- id>")
        record, _ = _record(root, board, "feedback", {
            "about": about, "direction": direction, "type": kind, "text": text.strip(),
            "reply_to": reply_to or "", "by": by})
    if kind == B.QUESTION:
        return (f"{record['id']}: question on {about} recorded; it stays open on the board until the "
                f"director answers it with feedback(..., kind=\"answer\", reply_to=\"{record['id']}\").")
    return f"{record['id']}: {kind} on {about} recorded, in {direction}'s feedback."


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


def spend(root: Path, direction: str, action: str, target: str, expect: str = "") -> str:
    """A spend commits points, and a commitment to test the direction by every measurement recorded
    afterwards against the contracts it names now (DEF-research-ledger)."""
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
        cost = costs[action]
        balance = board.balance(d)
        if balance < cost:
            raise Refused(f"{action} costs {cost} and {d.id} holds {balance}: {cost - balance} more "
                          "point(s) of research first (add_trail)")
        commit = (B.git(root, "rev-parse", "--short", "HEAD") or "").strip()
        contracts = B.targeted_contracts(decl, target)        # fixed now; a later declaration adds none
        record, _ = _record(root, board, "spend", {
            "direction": d.id, "action": action, "target": target, "contracts": contracts,
            "expect": expect.strip(), "cost": cost, "commit": commit, "by": "director"})
    counts = (f"Runs measured on {', '.join(contracts)} from now count for {d.id}; run them with run_test."
              if contracts else f"{target} names no contract, so this spend has no result of its own.")
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
