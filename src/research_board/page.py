"""What a person reads: the board, a direction's brief, and the page in .research/.

The board answers "what is being tried, and what next?" in the order a director acts on it. A brief
is everything a scout working one direction may need, and it is all a scout gets of the project's
design: the goal, the research so far, what was spent and what came of it, the feedback, and the
components a tweak can name. The page is the board with every open direction's brief, rewritten
after every move so it can be read in an editor or on GitHub without a server.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import board as B

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


def _spend_line(board: B.Board, spend: dict[str, Any]) -> str:
    line = (f"{spend['id']} · {spend.get('action')} -> {spend.get('target')} · "
            f"{_plural(int(spend.get('cost') or 0), 'point')} · at {spend.get('commit') or '?'}")
    if spend.get("expect"):
        line += f" · expect: {_short(spend['expect'])}"
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
                   f"is taken in {_duration(soonest)}, and any trail, new direction or scout's feedback "
                   f"stops the clock for {board.rules.running_minutes}m")
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
    for issue in board.rules.issues + ([board.evidence_error] if board.evidence_error else []):
        lines.append(f"! {issue}")
    if not board.directions:
        lines += ["", "No directions yet."]
    for state in B.DIRECTION_STATES:
        group = [d for d in board.ordered() if d.state == state]
        if group:
            lines += ["", f"## {_HEADINGS[state]}"]
            for d in group:
                lines += _summary(board, d, focus)
    questions = board.open_questions()
    if questions:
        lines += ["", "## Open questions for the director"]
        for q in questions:
            lines.append(f"- {q['id']} · {q.get('by')} on {q.get('about')}: \"{_short(q.get('text'), 240)}\"")
    nexts = _next(board)
    if nexts:
        lines += ["", "next:"] + [f"  - {n}" for n in nexts]
    return "\n".join(lines)


def _trail_lines(board: B.Board, trail: dict[str, Any]) -> list[str]:
    points = board.points(trail)
    worth = f"+{points}" if points else "0 points"
    lines = [f"### {trail['id']} · by {trail.get('by')} · {worth}"]
    paper = trail.get("paper", "")
    if trail.get("at"):
        paper += f", {trail['at']}"
    lines.append(f"paper:  {paper}")
    if trail.get("quote"):
        lines.append(f"says:   \"{trail['quote']}\"")
    component = trail.get("component") or "(no component)"
    lines.append(f"tweak:  {component} -- {trail.get('tweak')}")
    if trail.get("expect"):
        lines.append(f"expect: {trail['expect']}")
    if trail.get("unearned"):
        lines.append(f"earned nothing: {trail['unearned']}")
    rejected = board.rejected(trail["id"])
    if rejected:
        lines.append(f"rejected by the director: \"{rejected.get('text')}\" -- its points no longer count")
    return lines


def _feedback_line(item: dict[str, Any]) -> str:
    kind = item.get("type")
    about = item.get("about")
    if kind == B.ANSWER:
        what = f"answer to {item.get('reply_to')}"
    elif kind in B.VERDICTS:
        what = f"{kind} {about}" + (f" (rank {item['rank']})" if item.get("rank") else "")
    elif kind in B.DECISIONS:
        what = f"reflection: {kind}"
    else:
        what = f"{kind} on {about}" + (f", replying to {item['reply_to']}" if item.get("reply_to") else "")
    return f"- {item['id']} · {item.get('by')} · {what}: \"{item.get('text')}\""


def _direction_detail(board: B.Board, d: B.Direction) -> list[str]:
    lines = [f"state: {d.state} · {_balance(board, d)}" + (f" · rank {d.rank}" if d.rank else "")]
    if idle := _idle_line(d):
        lines.append(idle)
    lines.append(f"idea: {d.record.get('idea')}")
    if d.record.get("assessment"):
        lines.append(f"assessment: {d.record['assessment']}")
    if d.record.get("pivot_from"):
        lines.append(f"pivot from: {d.record['pivot_from']}")
    lines += ["", "## Trails"]
    lines += [line for trail in d.trails for line in _trail_lines(board, trail) + [""]] or ["(none yet)", ""]
    lines.append("## Spends")
    lines += [f"- {_spend_line(board, s)}" for s in d.spends] or ["(none yet)"]
    lines += ["", "## Feedback, oldest first"]
    lines += [_feedback_line(f) for f in d.feedback] or ["(none yet)"]
    return lines


def render_brief(board: B.Board, d: B.Direction) -> str:
    """Everything a scout on one direction reads: it holds no tool that opens a file, so what the
    project's design says about this goal reaches it from here and the ledgers."""
    lines = [f"# {d.id}", "", "for " + "\n".join(_goal_lines(board, d.goal))]
    lines += _direction_detail(board, d)
    if d.record.get("pivot_from") in board.directions:
        old = board.directions[d.record["pivot_from"]]
        if old.decision:
            lines += ["", f"{old.id} was left with: \"{old.decision.get('text')}\""]
    closed = [o for o in board.ordered() if o.goal == d.goal and o.id != d.id and o.state in (B.HALTED, B.REJECTED)]
    if closed:
        lines += ["", f"## Closed directions on {d.goal} -- do not walk them again"]
        for o in closed:
            why = (o.decision if o.state == B.HALTED else o.verdict) or {}
            lines.append(f"- {o.id} ({o.state}): {_short(o.record.get('idea'))} -- \"{_short(why.get('text'))}\"")
    others = [o for o in board.ordered() if o.goal == d.goal and o.id != d.id and o.state not in (B.HALTED, B.REJECTED)]
    if others:
        lines += ["", f"## Other open directions on {d.goal}"]
        lines += [f"- {o.id} ({o.state}): {_short(o.record.get('idea'))}" for o in others]
    lines += ["", "## Components a tweak can name (belief.yaml at HEAD)"]
    comps = board.decl.components
    lines += [f"- {cid}: {_short(c.purpose, 200)}" for cid, c in sorted(comps.items())] or ["(none declared)"]
    lines += ["", _rules_line(board.rules),
              f"A trail earns {board.rules.earn} for a paper new to this direction, quoted, whose tweak "
              "names a component above."]
    if board.rules.idle_per_hour:
        lines.append(f"While a test waits on its result, an hour with no trail, new direction or scout's "
                     f"feedback recorded costs the waiting direction {board.rules.idle_per_hour}: record "
                     "each trail as you have it, not all at the end.")
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
