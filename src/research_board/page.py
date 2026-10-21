"""What a person reads: the board, a direction's brief, and the page in .research/.

The board answers "what is being tried, and what next?" in the order a director acts on it. A brief
is everything a scout working one direction may need, and it is all a scout gets of the project's
design: the goal and the human's standing rules for it, the director's digest, the research so far,
what was spent and what came of it, the feedback, and the components a tweak can name.

A scout holds no tool that opens a file, so a reply too long for its client to show in full is a
reply it cannot read: the client saves it to a file and shows the first lines. So a brief is a head
that always fits -- the rules, the digest, what is open, the papers already cited, and an index --
and the rest by section, a page at a time, or one record by its id. The page in .research/ is the
board with every open direction in full, rewritten after every move for a person in an editor.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import board as B

#: The most a brief's head, or one page of a section, holds: under what a client shows in full.
BRIEF_CHARS = 16000
PAGE_CHARS = 12000
SECTIONS = ("trails", "spends", "feedback", "evidence", "goal", "directions", "components")

_HEADINGS = {
    B.NEEDS_REFLECTION: "Needs reflection (a result settled)",
    B.ACTIVE: "Active (a result pending)",
    B.READY: "Ready (approved, can pay for its next step)",
    B.EARNING: "Earning (approved, short of a paid step)",
    B.PROPOSED: "Proposed (waiting for the director)",
    B.HALTED: "Halted",
    B.REJECTED: "Rejected",
}


def _short(text: Any, limit: int = 160) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m"


def _rules_line(rules: B.Rules) -> str:
    where = f"{B.RULES_FILE} at {rules.changed}" if rules.source == "HEAD" else "defaults (no research.yaml committed)"
    costs = ", ".join(f"{action} {cost}" for action, cost in rules.costs.items())
    idle = (f"an idle hour costs a direction waiting on a result {rules.idle_per_hour} "
            f"(research runs {rules.running_minutes}m after each record)" if rules.idle_per_hour
            else "idle hours cost nothing")
    return f"rules: {where} · costs: {costs} · a trail earns {rules.earn} · {idle} · up to {rules.scouts} scouts"


def _balance(board: B.Board, d: B.Direction) -> str:
    idled = board.idle_points(d)
    return (f"balance {board.balance(d)} (earned {board.earned(d)}, spent {board.spent(d)}"
            + (f", idle {idled}" if idled else "") + ")")


def _idle_line(d: B.Direction) -> str:
    """How long the direction has waited with no research running, and whether it still is."""
    idle = d.idle
    if idle is None or not idle.seconds:
        return ""
    line = f"idle {_duration(idle.seconds)} waiting on a result with no research running: {_plural(idle.points, 'point')}"
    if idle.idle_now and idle.next_point_in is not None:
        line += f"; idle now, on {', '.join(idle.waiting_on)} -- the next point in {_duration(idle.next_point_in)}"
    return line


def _goal_lines(board: B.Board, goal_id: str) -> list[str]:
    goal = board.decl.goals.get(goal_id)
    if goal is None:
        return [f"{goal_id or '(no goal)'}: not a goal in goals.yaml at HEAD"]
    lines = [f"{goal_id}: {_short(goal.outcome, 240)}"]
    if goal.measure:
        lines.append(f"  measured by {goal.measure}: {board.measures.get(goal.measure, B.NO_EVIDENCE)}")
    if goal.constraints:
        lines.append("  the human's standing rules for it (goals.yaml) -- propose nothing that breaks one:")
        lines += [f"  - {rule}" for rule in goal.constraints]
    return lines


def _result_line(board: B.Board, spend: dict[str, Any]) -> str:
    result = board.results.get(spend["id"])
    if result is None or not result.states:
        return ""
    parts = []
    for cid, state in result.states.items():
        n = result.counted.get(cid, 0)
        runs = ", ".join(result.runs.get(cid, []))
        parts.append(f"{cid} {state} ({_plural(n, 'record')} after the spend{': ' + runs if runs else ''})")
    return "; ".join(parts)


def _unclaimed_line(run: dict[str, Any]) -> str:
    arm = "".join(f" {k}={v}" for k, v in sorted(run["params"].items()))
    outcomes = ", ".join(f"{n} {o}" for o, n in sorted(run["outcomes"].items()))
    return (f"- {run['run']} · {run['test']}{arm} · {run['at'].strftime('%Y-%m-%d %H:%M')} · "
            f"{', '.join(sorted(run['contracts']))}: {outcomes}")


def _spend_line(board: B.Board, spend: dict[str, Any]) -> str:
    arm = "".join(f" {k}={v}" for k, v in sorted((spend.get("params") or {}).items()))
    line = (f"{spend['id']} · {spend.get('action')} -> {spend.get('target')}{arm} · "
            f"{_plural(int(spend.get('cost') or 0), 'point')} · at {spend.get('commit') or '?'}")
    if spend.get("expect"):
        line += f" · expect: {_short(spend['expect'])}"
    d = board.directions.get(str(spend.get("direction")))
    if d is not None and d.idle is not None and spend["id"] in d.idle.queued:
        line += " · queued: its idle clock starts with its first run"
    result = _result_line(board, spend)
    return line + (f"\n    result: {result}" if result else "")


def _summary(board: B.Board, d: B.Direction, focus: str) -> list[str]:
    head = f"- **{d.id}**"
    if d.goal != focus:
        head += f" · for {d.goal}"
    head += (f" · {_balance(board, d)}"
             f" · {_plural(len(d.trails), 'trail')} · {_plural(len(d.spends), 'spend')}")
    if d.rank:
        head += f" · rank {d.rank}"
    lines = [head, f"  idea: {_short(d.record.get('idea'), 240)}"]
    if d.record.get("assessment"):
        lines.append(f"  assessment: {_short(d.record['assessment'], 240)}")
    if d.state in (B.HALTED, B.REJECTED):
        closing = d.decision if d.state == B.HALTED else d.verdict
        lines.append(f"  {d.state} {str(closing.get('timestamp', ''))[:10]}: \"{_short(closing.get('text'))}\"")
        return lines
    for spend in d.spends:
        lines.append("  " + _spend_line(board, spend).replace("\n", "\n  "))
    if idle := _idle_line(d):
        lines.append(f"  {idle}")
    return lines


def _next(board: B.Board) -> list[str]:
    out = []
    for d in board.directions.values():
        if d.state == B.NEEDS_REFLECTION:
            out.append(f"reflect(\"{d.id}\", continue|halt|pivot, why): {', '.join(d.unreflected)} settled")
    proposed = [d for d in board.ordered() if d.state == B.PROPOSED]
    for d in proposed:
        out.append(f"approve(\"{d.id}\", True|False, why, rank=...): proposed, {board.balance(d)} point(s) of research behind it")
    for q in board.open_questions():
        out.append(f"answer {q['id']} ({q.get('by')} on {q.get('about')}): "
                   f"feedback(\"{q.get('about')}\", text, kind=\"answer\", reply_to=\"{q['id']}\")")
    pending = [d for d in board.directions.values() if d.state == B.ACTIVE]
    live = [d for d in board.ordered() if d.state in (B.ACTIVE, B.READY, B.EARNING, B.PROPOSED)]
    idling = [d for d in board.ordered() if d.idle and d.idle.idle_now]
    if idling:
        soonest = min(d.idle.next_point_in or 3600 for d in idling)
        out.append(f"research is idle while {', '.join(d.id for d in idling)} wait"
                   f"{'s' if len(idling) == 1 else ''} on a result: send a scout now -- the next idle point "
                   f"is taken in {_duration(soonest)}, and an earning trail, a new direction, a finding, "
                   f"a scout's question or an answer stops the clock for {board.rules.running_minutes}m")
    if pending:
        out.append(f"results pending on {', '.join(d.id for d in pending)}: run them (run_test), and meanwhile "
                   f"send up to {board.rules.scouts} scouts, in the background -- one per direction "
                   "(board(direction=...)), or one to look for a new direction")
    ready = [d for d in board.ordered() if d.state == B.READY]
    if ready:
        out.append(f"spend(\"{ready[0].id}\", action, target, expect): ready, and first in the order")
    if not live:
        focus = board.rules.focus or "a goal"
        out.append(f"no open direction: send scouts to look for directions on {focus}, "
                   "or open_direction(name, goal, idea, assessment)")
    return out


def render_board(board: B.Board) -> str:
    focus = board.rules.focus
    lines = ["# Research board", ""]
    if focus:
        lines += ["focus: " + "\n".join(_goal_lines(board, focus)), ""]
    lines.append(_rules_line(board.rules))
    for issue in board.issues():
        lines.append(f"! {issue}")
    if not board.directions:
        lines += ["", "No directions yet."]
    for state in B.DIRECTION_STATES:
        group = [d for d in board.ordered() if d.state == state]
        if group:
            lines += ["", f"## {_HEADINGS[state]}"]
            for d in group:
                lines += _summary(board, d, focus)
    for goal_id, items in sorted(board.goal_feedback.items()):
        lines += ["", f"## On {goal_id} itself ({_plural(len(items), 'note')}, the latest last)"]
        lines += [_feedback_line(f, 240) for f in items[-3:]]
    for goal_id, runs in sorted(board.unclaimed.items()):
        if runs:
            lines += ["", f"## Runs that count for no direction on {goal_id} ({len(runs)}) -- measured on its "
                          "directions' contracts with no spend claiming them; never a result"]
            lines += [_unclaimed_line(r) for r in runs[-10:]]
            if len(runs) > 10:
                lines.append(f"- ... and {len(runs) - 10} earlier")
    questions = board.open_questions()
    if questions:
        lines += ["", "## Open questions and checks for the director"]
        for q in questions:
            lines.append(f"- {q['id']} · {q.get('by')} · {q.get('type')} on {q.get('about')}: "
                         f"\"{_short(q.get('text'), 240)}\"")
    nexts = _next(board)
    if nexts:
        lines += ["", "next:"] + [f"  - {n}" for n in nexts]
    return "\n".join(lines)


def _trail_lines(board: B.Board, trail: dict[str, Any]) -> list[str]:
    points = board.points(trail)
    worth = f"+{points}" if points else "0 points"
    kind = trail.get("type") or B.TWEAK
    lines = [f"### {trail['id']} · {'' if kind == B.TWEAK else kind + ' · '}by {trail.get('by')} · {worth}"]
    paper = trail.get("paper", "")
    if trail.get("at"):
        paper += f", {trail['at']}"
    lines.append(f"paper:  {paper}")
    if trail.get("quote"):
        lines.append(f"says:   \"{trail['quote']}\"")
    component = trail.get("component") or "(no component)"
    if kind == B.SET_ASIDE:
        lines.append(f"why not: {trail.get('tweak')}")
    else:
        lines.append(f"{'method' if kind == B.METHOD else 'tweak'}:  {component} -- {trail.get('tweak')}")
    if trail.get("expect"):
        lines.append(f"expect: {trail['expect']}")
    if trail.get("unearned"):
        lines.append(f"earned nothing: {trail['unearned']}")
    rejected = board.rejected(trail["id"])
    if rejected:
        lines.append(f"rejected by the director: \"{rejected.get('text')}\" -- its points no longer count")
    return lines


def _feedback_line(item: dict[str, Any], limit: int | None = None, pointer: bool = False) -> str:
    """One feedback record on a line, cut at `limit` characters. With `pointer`, a line that was
    cut says where the whole record is: a scout reading a brief has no other way to it."""
    kind = item.get("type")
    about = item.get("about")
    if kind == B.ANSWER:
        what = f"answer to {item.get('reply_to')}"
    elif kind in B.VERDICTS:
        what = f"{kind} {about}" + (f" (rank {item['rank']})" if item.get("rank") else "")
    elif kind in B.DECISIONS:
        what = f"reflection: {kind}"
    elif kind == B.RETARGET:
        what = f"retarget: from {item.get('from_goal')} to {item.get('goal')}"
    else:
        what = f"{kind} on {about}" + (f", replying to {item['reply_to']}" if item.get("reply_to") else "")
    text = item.get("text") if limit is None else _short(item.get("text"), limit)
    cut = pointer and limit is not None and len(" ".join(str(item.get("text") or "").split())) > limit
    whole = f" (cut; in full: board(item=\"{item['id']}\"))" if cut else ""
    return f"- {item['id']} · {item.get('by')} · {what}: \"{text}\"{whole}"


def _head_limit(item: dict[str, Any]) -> int:
    """How much of a feedback record a brief's head shows: an answer, or the director's own word,
    is often the fact a scout needs whole -- a table of measured settings, a ruling -- so it gets
    the room an open question gets."""
    return 1200 if item.get("type") == B.ANSWER or item.get("by") == "director" else 400


def _evidence_line(item: dict[str, Any], limit: int | None = 240) -> str:
    worth = f"+{item['points']}" if item.get("points") else "0 points"
    summary = item.get("summary") if limit is None else _short(item.get("summary"), limit)
    reply = f" · replying to {item['reply_to']}" if item.get("reply_to") else ""
    return (f"- {item['id']} · by {item.get('by')} · {worth}{reply} · {item.get('artifact')} "
            f"(sha256 {item.get('sha256')}): \"{summary}\" -- ledger(evidence=\"{item['id']}\")")


def _digest_lines(d: B.Direction) -> list[str]:
    if not d.digest:
        return []
    when = str(d.digest.get("timestamp", ""))[:16].replace("T", " ")
    return [f"## Facts so far -- the director's digest ({d.digest['id']}, {when})", d.digest.get("text", ""), ""]


def _direction_detail(board: B.Board, d: B.Direction) -> list[str]:
    lines = [f"state: {d.state} · {_balance(board, d)}" + (f" · rank {d.rank}" if d.rank else "")]
    if idle := _idle_line(d):
        lines.append(idle)
    lines += [""] + _digest_lines(d)
    lines.append(f"idea: {d.record.get('idea')}")
    if d.record.get("assessment"):
        lines.append(f"assessment: {d.record['assessment']}")
    if d.record.get("pivot_from"):
        lines.append(f"pivot from: {d.record['pivot_from']}")
    lines += ["", "## Trails"]
    lines += [line for trail in d.trails for line in _trail_lines(board, trail) + [""]] or ["(none yet)", ""]
    lines.append("## Spends")
    lines += [f"- {_spend_line(board, s)}" for s in d.spends] or ["(none yet)"]
    if d.evidence:
        lines += ["", "## Measured findings"] + [_evidence_line(e, None) for e in d.evidence]
    lines += ["", "## Feedback, oldest first"]
    lines += [_feedback_line(f) for f in d.feedback] or ["(none yet)"]
    return lines


# ---------- a brief a scout can read: a head that fits, the rest by section ----------

def _blocks(board: B.Board, d: B.Direction, section: str) -> list[tuple[str, str]]:
    """One section of a direction, as (id, text) blocks in the order recorded."""
    if section == "trails":
        return [(tr["id"], "\n".join(_trail_lines(board, tr))) for tr in d.trails]
    if section == "spends":
        return [(s["id"], f"- {_spend_line(board, s)}") for s in d.spends]
    if section == "feedback":
        return [(f["id"], _feedback_line(f)) for f in d.feedback]
    if section == "evidence":
        return [(e["id"], _evidence_line(e, None)) for e in d.evidence]
    if section == "goal":
        return [(f["id"], _feedback_line(f)) for f in board.goal_feedback.get(d.goal, [])]
    if section == "directions":
        out = []
        for o in board.ordered():
            if o.goal != d.goal or o.id == d.id:
                continue
            if o.state in (B.HALTED, B.REJECTED):
                why = (o.decision if o.state == B.HALTED else o.verdict) or {}
                out.append((o.id, (f"- {o.id} ({o.state} -- do not walk it again): {o.record.get('idea')} "
                                   f"-- \"{why.get('text')}\"")))
            else:
                out.append((o.id, f"- {o.id} ({o.state}): {o.record.get('idea')}"))
        return out
    if section == "components":
        return [(cid, f"- {cid}: {c.purpose}") for cid, c in sorted(board.decl.components.items())]
    return []


def _pages(blocks: list[tuple[str, str]], limit: int = PAGE_CHARS) -> list[list[str]]:
    """Blocks packed into pages of at most `limit` characters; a block longer than a page is cut,
    and says how to read it whole."""
    pages: list[list[str]] = [[]]
    used = 0
    for rid, text in blocks:
        if len(text) > limit:
            text = text[: limit - 200] + f"\n… cut at {limit} characters; in full: board(item=\"{rid}\")"
        if pages[-1] and used + len(text) + 1 > limit:
            pages.append([])
            used = 0
        pages[-1].append(text)
        used += len(text) + 1
    return pages


def _name(d: B.Direction) -> str:
    """A direction in words: its idea, cut short -- not its id."""
    return f"\"{_short(d.record.get('idea'), 120)}\""


def render_human(board: B.Board) -> str:
    """The board for the human, in plain words: for each goal with research on it, whether it is
    met, the best result so far, what is being tried and what comes next, the work no direction
    claims, and what needs the human. No ledger ids: an update built from ids reads as narration
    of the ledger, not as a summary."""
    goals = sorted({d.goal for d in board.directions.values()}, key=lambda g: (g != board.rules.focus, g))
    lines = ["# Where the research stands", ""]
    if not goals:
        lines.append("No research yet: no direction is open on any goal.")
    for goal_id in goals:
        goal = board.decl.goals.get(goal_id)
        mine = [d for d in board.ordered() if d.goal == goal_id]
        state = board.measures.get(goal.measure, B.NO_EVIDENCE) if goal and goal.measure else ""
        met = {"supported": "met", "refuted": "not met", "contested": "not settled",
               "stale": "not current: the code moved since it was measured"}.get(state, "not measured yet")
        lines.append(f"## {_short(goal.outcome, 160) if goal else goal_id}")
        lines.append(f"Goal: {met}." if goal else "Goal: no longer in goals.yaml.")

        settled = [(board.results[s["id"]], d, s) for d in mine for s in d.spends
                   if board.results.get(s["id"]) and board.results[s["id"]].settled]
        held = [x for x in settled if x[0].status == "supported"]
        if held:
            result, d, _spend = max(held, key=lambda x: x[0].settled_at or board.now)
            on = result.settled_at.strftime("%Y-%m-%d") if result.settled_at else "?"
            lines.append(f"Best result so far: {_name(d)} passed its test on {on}.")
        else:
            lines.append("Best result so far: none yet" + (f" -- {_plural(len(settled), 'test')} came back, none passing."
                                                           if settled else "."))
        active = [d for d in mine if d.state == B.ACTIVE]
        for d in active:
            queued = d.idle and d.idle.queued
            how = "paid for, waiting for its run to start" if queued else "its test is running"
            if d.idle and d.idle.idle_now:
                how += f", and no research has been done for {_duration(d.idle.seconds)} of the wait"
            lines.append(f"Trying now: {_name(d)} -- {how}.")
        ready = [d for d in mine if d.state == B.READY]
        if ready:
            lines.append(f"Next up: {_name(ready[0])}" + (f", then {_plural(len(ready) - 1, 'more')}" if len(ready) > 1 else "")
                         + " -- approved, with enough research behind it to test.")
        if not active and not ready:
            earning = [d for d in mine if d.state in (B.EARNING, B.PROPOSED)]
            lines.append(f"Next up: nothing ready to test; {_plural(len(earning), 'idea')} still gathering research."
                         if earning else "Next up: nothing open.")
        closed = [d for d in mine if d.state in (B.HALTED, B.REJECTED)]
        papers = sum(1 for d in mine for t in d.trails if t.get("type") != B.SET_ASIDE)
        put = sum(1 for d in mine for t in d.trails if t.get("type") == B.SET_ASIDE)
        lines.append(f"Research: {_plural(len(mine) - len(closed), 'idea')} open, {_plural(len(closed), 'set')} aside; "
                     f"{_plural(papers, 'paper')} cited" + (f" and {put} read and dropped" if put else "") + ".")
        waiting = [q for q in board.open_questions() if board.direction_of(str(q.get("about"))) in {d.id for d in mine}
                   or q.get("goal") == goal_id]
        reflect = [d for d in mine if d.state == B.NEEDS_REFLECTION]
        if waiting or reflect:
            lines.append("Waiting on the agent: " + "; ".join(
                part for part in (f"{_plural(len(reflect), 'result')} to weigh" if reflect else "",
                                  f"{_plural(len(waiting), 'question')} from its scouts" if waiting else "") if part) + ".")
        unclaimed = board.unclaimed.get(goal_id) or []
        if unclaimed:
            lines.append(f"Work no idea claims: {_plural(len(unclaimed), 'test run')} since research began, "
                         "paid for by no idea, so they count for none.")
        lines.append("")
    needs = list(board.issues())
    gone = sorted({d.goal for d in board.directions.values()} - set(board.decl.goals))
    if gone:
        needs.append(f"research continues on {', '.join(gone)}, which goals.yaml no longer declares")
    lines.append("Needs you: " + ("; ".join(needs) + "." if needs else "nothing."))
    return "\n".join(lines)


def render_section(board: B.Board, d: B.Direction, section: str, part: int = 1) -> str:
    if section not in SECTIONS:
        return f"no section {section!r}; sections: {', '.join(SECTIONS)}"
    pages = _pages(_blocks(board, d, section))
    total = len(pages) if pages[0] else 0
    if not total:
        return f"# {d.id} · {section}: none yet"
    part = min(max(1, part), total)
    lines = [f"# {d.id} · {section} · part {part} of {total}, oldest first", ""] + pages[part - 1]
    if part < total:
        lines += ["", f"next: board(direction=\"{d.id}\", section=\"{section}\", part={part + 1})"]
    return "\n".join(lines)


def _index_line(board: B.Board, d: B.Direction, section: str, what: str) -> str:
    parts = len(_pages(_blocks(board, d, section)))
    return f"- {what} -- board(direction=\"{d.id}\", section=\"{section}\"){f', {parts} parts' if parts > 1 else ''}"


def render_brief(board: B.Board, d: B.Direction) -> str:
    """The head of a direction's brief: what a scout reads first, always short enough to read whole.
    It holds no tool that opens a file, so what the project's design says about this goal reaches it
    from here and the ledgers."""
    lines = [f"# {d.id}", "", "for " + "\n".join(_goal_lines(board, d.goal))]
    lines.append(f"state: {d.state} · {_balance(board, d)}" + (f" · rank {d.rank}" if d.rank else ""))
    if idle := _idle_line(d):
        lines.append(idle)
    lines += [""] + _digest_lines(d)
    lines.append(f"idea: {_short(d.record.get('idea'), 1500)}")
    if d.record.get("assessment"):
        text = d.record["assessment"]
        lines.append(f"assessment: {_short(text, 1500)}" + (f" (in full: board(item=\"{d.id}\"))" if len(text) > 1500 else ""))
    if d.record.get("pivot_from") in board.directions:
        old = board.directions[d.record["pivot_from"]]
        if old.decision:
            lines.append(f"pivot from {old.id}, which was left with: \"{_short(old.decision.get('text'), 600)}\"")

    earning = sum(1 for tr in d.trails if board.points(tr))
    questions = [q for q in board.open_questions() if q.get("direction") == d.id]
    goal_items = board.goal_feedback.get(d.goal, [])
    lines += ["", "## Read the rest by section, a page at a time; one record by its id: board(item=...)"]
    lines.append(_index_line(board, d, "trails", f"{_plural(len(d.trails), 'trail')} ({earning} earning)"))
    lines.append(_index_line(board, d, "spends", _plural(len(d.spends), "spend")))
    lines.append(_index_line(board, d, "feedback", f"{len(d.feedback)} feedback ({len(questions)} open question(s))"))
    if d.evidence:
        lines.append(_index_line(board, d, "evidence", _plural(len(d.evidence), "measured finding")))
    if goal_items:
        lines.append(_index_line(board, d, "goal", f"{_plural(len(goal_items), 'note')} on {d.goal} itself"))
    lines.append(_index_line(board, d, "directions", f"the other directions on {d.goal}"))
    lines.append(_index_line(board, d, "components", "the components a tweak can name"))

    def fits(block: list[str]) -> bool:
        return len("\n".join(lines + block)) <= BRIEF_CHARS - 1200      # room for the rules at the end

    optional: list[tuple[list[str], str]] = []
    if questions:
        optional.append((["", "## Open questions and checks on it, waiting on the director"]
                         + [_feedback_line(q, 1200, pointer=True) for q in questions], "feedback"))
    open_ids = {q["id"] for q in questions}
    latest = [f for f in d.feedback if f["id"] not in open_ids][-5:]      # the open ones are above, whole
    if latest:
        optional.append((["", "## The latest feedback, newest last"]
                         + [_feedback_line(f, _head_limit(f), pointer=True) for f in latest], "feedback"))
    cited = [tr for tr in d.trails if tr.get("type") != B.SET_ASIDE]
    if cited:
        optional.append((["", "## Papers already cited here -- a trail on one of these earns nothing"]
                         + [f"- {tr['id']} · {_short(tr.get('paper'), 110)} · "
                            f"{'+' + str(board.points(tr)) if board.points(tr) else '0'}"
                            + (" · method" if tr.get("type") == B.METHOD else "") for tr in cited], "trails"))
    put_aside = [tr for tr in d.trails if tr.get("type") == B.SET_ASIDE]
    if put_aside:
        optional.append((["", "## Papers read and set aside -- read one again only with a new reason"]
                         + [f"- {tr['id']} · {_short(tr.get('paper'), 110)} · why not: {_short(tr.get('tweak'), 160)}"
                            for tr in put_aside], "trails"))
    if d.evidence:
        optional.append((["", "## Measured findings"] + [_evidence_line(e, 200) for e in d.evidence], "evidence"))
    if goal_items:
        optional.append((["", f"## On {d.goal} itself, the latest last"]
                         + [_feedback_line(f, _head_limit(f), pointer=True) for f in goal_items[-5:]], "goal"))
    closed = [o for o in board.ordered() if o.goal == d.goal and o.id != d.id and o.state in (B.HALTED, B.REJECTED)]
    if closed:
        optional.append((["", f"## Closed directions on {d.goal} -- do not walk them again"]
                         + [f"- {o.id} ({o.state}): {_short(o.record.get('idea'))} -- "
                            f"\"{_short(((o.decision if o.state == B.HALTED else o.verdict) or {}).get('text'))}\""
                            for o in closed], "directions"))
    others = [o for o in board.ordered() if o.goal == d.goal and o.id != d.id and o.state not in (B.HALTED, B.REJECTED)]
    if others:
        optional.append((["", f"## Other open directions on {d.goal}"]
                         + [f"- {o.id} ({o.state}): {_short(o.record.get('idea'))}" for o in others], "directions"))
    optional.append((["", "## Components a tweak can name (belief.yaml at HEAD)"]
                     + ([f"- {cid}: {_short(c.purpose, 140)}" for cid, c in sorted(board.decl.components.items())]
                        or ["(none declared)"]), "components"))
    for block, section in optional:
        if fits(block):
            lines += block
        else:
            lines += ["", (f"{block[1].removeprefix('## ')}: too long for the head -- "
                           f"board(direction=\"{d.id}\", section=\"{section}\")")]

    lines += ["", _rules_line(board.rules),
              (f"A trail earns {board.rules.earn} for a paper new to this direction, quoted, whose tweak "
               "names a component above.")]
    if board.rules.idle_per_hour:
        lines.append(f"While a test waits on its result, an hour with no earning trail, new direction, finding, "
                     f"scout's question or answer recorded costs the waiting direction {board.rules.idle_per_hour}: "
                     "record each trail as you have it, not all at the end. A note does not stop the clock.")
    lines.append("To change the digest above, say what in feedback(..., kind=\"note\"); the director keeps it.")
    return "\n".join(lines)


def render_item(board: B.Board, rid: str) -> str:
    """One record in full, with the feedback on it and the replies to it."""
    about = [f for f in board.feedback.values() if f.get("about") == rid and f.get("id") != rid]
    replies = [f for f in board.feedback.values() if f.get("reply_to") == rid]
    if rid in board.directions:
        d = board.directions[rid]
        lines = [f"# {rid} · for {d.goal} · {d.state}", f"idea: {d.record.get('idea')}",
                 f"assessment: {d.record.get('assessment') or '(none)'}", ""] + _digest_lines(d)
        for record in (d.verdict, d.decision):
            if record:
                lines.append(_feedback_line(record))
        return "\n".join(lines)
    if rid in board.trails:
        lines = _trail_lines(board, board.trails[rid])
    elif rid in board.spends:
        lines = [f"- {_spend_line(board, board.spends[rid])}"]
    elif rid in board.evidence:
        lines = [_evidence_line(board.evidence[rid], None)]
    elif rid in board.feedback:
        item = board.feedback[rid]
        lines = [_feedback_line(item)]
        if item.get("reply_to") in board.feedback:
            lines.insert(0, "in reply to " + _feedback_line(board.feedback[item["reply_to"]], 600, pointer=True))
    else:
        return f"no record {rid!r} on the board"
    if about or replies:
        lines += ["", "feedback on it and replies, oldest first:"]
        lines += [_feedback_line(f) for f in sorted({f["id"]: f for f in about + replies}.values(),
                                                    key=lambda f: str(f.get("timestamp", "")))]
    return "\n".join(lines)


def render_page(board: B.Board) -> str:
    lines = [render_board(board).replace("# Research board", "# Research board\n\n"
             "_Rewritten after every move on the board; `board()` reads it live._", 1)]
    for d in board.ordered():
        if d.state in (B.HALTED, B.REJECTED):
            continue
        lines += ["", "---", "", f"# {d.id}", ""] + _direction_detail(board, d)
    return "\n".join(lines) + "\n"


def write_page(root: Path) -> B.Board:
    """The page sits beside the ledger in .research/, a directory that holds no declaration and
    no part of either of the other ledgers (DEF-research-ledger). Returns the board it drew, so a
    move can answer from it without reading everything again."""
    board = B.build(root)
    page = B.research_dir(root) / B.BOARD_FILE
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(render_page(board), encoding="utf-8", newline="\n")
    return board
