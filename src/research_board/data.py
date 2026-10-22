"""The board as data: what the live view and its export send to a page (DEF-live-board).

One function shapes it, from one build, and the page formats what it is given: every state,
balance, result and time in it is the build's. It is an allowlist -- fields are copied by name --
so a process id, an absolute path or the text of an exception never reaches a page.

Diagrams are drawn only from digests: only the director writes them, and scouts, who copy text
from the web, hold no tool that does. A mermaid block anywhere else is passed on as plain code.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from . import board as B

SCHEMA = 1
FEED = 200                 # the latest research records the feed carries
ACTIVITY_HOURS = 72
_MERMAID = re.compile(r"```[ \t]*mermaid\b", re.IGNORECASE)
EVIDENCE_UNREAD = "The evidence ledger could not be read, so no result is shown."


def plain_code(text: Any) -> str:
    """Text whose mermaid blocks are shown as code: the page draws diagrams from digests only."""
    return _MERMAID.sub("```text", str(text or ""))


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment else None


def name(direction_id: str) -> str:
    """A direction's id in words: DIR-door-tower-vla -> Door tower vla."""
    words = direction_id.removeprefix("DIR-").replace("-", " ")
    return words[:1].upper() + words[1:]


def _feedback(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not item:
        return None
    out = {k: item.get(k) for k in ("id", "type", "by", "about", "reply_to", "timestamp", "direction", "goal")}
    out["text"] = plain_code(item.get("text"))
    return out


def _trail(board: B.Board, trail: dict[str, Any]) -> dict[str, Any]:
    verdict = board.trail_verdicts.get(trail["id"])
    out = {k: trail.get(k) for k in ("id", "component", "by", "timestamp", "type")}
    out.update({k: plain_code(trail.get(k)) for k in ("paper", "tweak", "quote", "expect")})
    out.update(points=board.points(trail), verdict=(verdict or {}).get("type"))
    return out


def _spend(board: B.Board, spend: dict[str, Any]) -> dict[str, Any]:
    out = {k: spend.get(k) for k in ("id", "action", "target", "test", "cost", "commit", "timestamp",
                                     "params", "contracts")}
    out["expect"] = plain_code(spend.get("expect"))
    out["waits_from"] = _iso(board.starts.get(spend["id"]))
    result = board.results.get(spend["id"])
    if result is not None:
        out["result"] = {"status": result.status, "settled": result.settled, "states": result.states,
                         "counted": result.counted, "passed": result.passed, "scored": result.scored,
                         "runs": result.runs, "settled_at": _iso(result.settled_at)}
    return out


def _evidence(item: dict[str, Any]) -> dict[str, Any]:
    out = {k: item.get(k) for k in ("id", "timestamp", "points", "artifact", "copy", "by", "bytes", "sha256")}
    out["summary"] = plain_code(item.get("summary"))
    return out


def _summary(record: dict[str, Any]) -> str:
    kind = record.get("kind")
    if kind == "trail":
        return f"{record.get('paper') or ''} -- {record.get('tweak') or ''}".strip(" -")
    if kind == "spend":
        return f"{record.get('action')} -> {record.get('target')}" + (
            f": expects {record['expect']}" if record.get("expect") else "")
    if kind == "direction":
        return str(record.get("idea") or "")
    if kind == "evidence":
        return str(record.get("summary") or "")
    return str(record.get("text") or "")


def board_data(board: B.Board, mode: str = "live") -> dict[str, Any]:
    """The board as one JSON-ready mapping: `mode` is "live" for the live view, "snapshot" for an
    export, and tells the page whether a stream follows."""
    rules = board.rules
    issues = [EVIDENCE_UNREAD if i == board.evidence_error else i for i in board.issues()]
    goals = {}
    for gid, goal in board.decl.goals.items():
        goals[gid] = {"id": gid, "outcome": goal.outcome, "paused": goal.status == "paused",
                      "measure": goal.measure,
                      "measure_state": board.measures.get(goal.measure) if goal.measure else None,
                      "constraints": [plain_code(c) for c in goal.constraints or []]}

    directions = []
    for d in board.ordered():
        idle = d.idle
        directions.append({
            "id": d.id, "name": name(d.id), "goal": d.goal, "state": d.state, "rank": d.rank,
            "balance": board.balance(d), "earned": board.earned(d), "spent": board.spent(d),
            "idle_points": board.idle_points(d),
            "idea": plain_code(d.record.get("idea")), "assessment": plain_code(d.record.get("assessment")),
            "opened": d.record.get("timestamp"), "by": d.record.get("by"), "pivot_from": d.record.get("pivot_from"),
            "digest": (d.digest or {}).get("text"), "digest_at": (d.digest or {}).get("timestamp"),
            "verdict": _feedback(d.verdict), "decision": _feedback(d.decision), "retarget": _feedback(d.retarget),
            "unreflected": list(d.unreflected),
            "idle": None if idle is None else {
                "seconds": idle.seconds, "points": idle.points, "idle_now": idle.idle_now,
                "next_point_in": idle.next_point_in, "waiting_on": list(idle.waiting_on),
                "queued": list(idle.queued)},
            "trails": [_trail(board, t) for t in d.trails],
            "spends": [_spend(board, s) for s in d.spends],
            "evidence": [_evidence(e) for e in d.evidence],
            "feedback": [_feedback(f) for f in d.feedback],
        })
    names = {d["id"] for d in directions}

    def direction_of(record: dict[str, Any]) -> str | None:
        did = record.get("direction") or (record.get("id") if record.get("kind") == "direction" else None)
        if not did and record.get("about"):
            did = board.direction_of(str(record["about"]))
        return did if did in names else None

    research = [r for r in board.records if r.get("id")]
    feed = [{"id": r["id"], "kind": r.get("kind"), "type": r.get("type"), "by": r.get("by"),
             "timestamp": r.get("timestamp"), "direction": direction_of(r),
             "summary": r.get("text") if r.get("kind") == "digest" else plain_code(_summary(r)),
             "quote": plain_code(r.get("quote")) if r.get("kind") == "trail" else None}
            for r in research[-FEED:][::-1]]

    hours: Counter = Counter()
    for r in research:
        moment = B.when(r.get("timestamp"))
        if moment and timedelta(0) <= board.now - moment < timedelta(hours=ACTIVITY_HOURS):
            kind = r.get("kind") if r.get("kind") in ("trail", "feedback") else "other"
            hours[(int((board.now - moment).total_seconds() // 3600), kind)] += 1
    activity = [{"ago": h, "trail": hours[(h, "trail")], "feedback": hours[(h, "feedback")],
                 "other": hours[(h, "other")]} for h in range(ACTIVITY_HOURS)]

    unclaimed = {gid: {"count": len(runs), "latest": [
        {"run": r["run"], "test": r["test"], "at": _iso(r["at"]), "contracts": sorted(r["contracts"]),
         "outcomes": dict(r["outcomes"])} for r in runs[-5:]]}
        for gid, runs in board.unclaimed.items() if runs}

    return {
        "meta": {"schema": SCHEMA, "mode": mode, "generated_at": board.now.isoformat(),
                 "commit": board.commit, "records": len(board.records)},
        "rules": {"focus": rules.focus, "costs": rules.costs, "earn": rules.earn, "scouts": rules.scouts,
                  "idle_per_hour": rules.idle_per_hour, "running_minutes": rules.running_minutes,
                  "source": rules.source, "changed": rules.changed},
        "research_until": _iso(board.research_until),
        "issues": issues,
        "goals": goals,
        "directions": directions,
        "questions": [{**_feedback(q), "direction": direction_of(q)} for q in board.open_questions()],
        "feed": feed,
        "activity": activity,
        "running": [{k: j.get(k) for k in ("run_id", "test", "started")} for j in board.running],
        "unclaimed": unclaimed,
    }
