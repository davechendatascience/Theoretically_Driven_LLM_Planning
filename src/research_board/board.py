"""The rules, the ledger, and everything the board computes from them.

Every number the board shows is computed here from three inputs: research.yaml at HEAD, the
research ledger, and component-belief's evidence ledger. Nothing that can be computed is stored: a
direction's balance is summed from its trails, its spends and its idle hours each time it is read,
and a spend's result is read from the evidence recorded after the spend (DEF-research-ledger). The
stored numbers are what a trail earned and what a spend cost and fixed for its idle hours, each set
by the rules in effect when it was recorded, so a later change of rules reprices nothing already
on the board.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

RULES_FILE = "research.yaml"
RESEARCH_DIR = ".research"
LEDGER_FILE = "ledger.jsonl"
BOARD_FILE = "BOARD.md"

DEFAULT_COSTS = {"research": 0, "implement": 1, "test": 1, "dataset_eval": 1, "training_run": 3}
DEFAULT_EARN = 1
DEFAULT_EARN_EVIDENCE = 0       # a measured finding is a stronger reason to test, and the director's own
DEFAULT_SCOUTS = 3
DEFAULT_IDLE_PER_HOUR = 1       # points an idle hour costs a direction waiting on a result
DEFAULT_RUNNING_MINUTES = 30    # how long research counts as running after a research record
RULE_KEYS = ("focus", "costs", "earn", "scouts", "idle")

NOTE, QUESTION, CHECK, ANSWER = "note", "question", "check", "answer"
APPROVED, REJECTED = "approved", "rejected"
CONTINUE, HALT, PIVOT = "continue", "halt", "pivot"
RETARGET = "retarget"
#: A check is a measurement a scout proposes the director make first -- often free, on data that
#: exists. Like a question it waits on the director until answered, or until a finding replies to it.
FEEDBACK_KINDS = (NOTE, QUESTION, CHECK, ANSWER)
#: What a trail is: a tweak to a component, a method or instrument to measure with, or a paper read
#: and set aside, kept so the next scout does not read it again.
TWEAK, METHOD, SET_ASIDE = "tweak", "method", "set-aside"
TRAIL_KINDS = (TWEAK, METHOD, SET_ASIDE)
#: A spend made from 0.13.3 on waits from its first run, not from when it was recorded.
FIRST_RUN = "first-run"
VERDICTS = (APPROVED, REJECTED)
DECISIONS = (CONTINUE, HALT, PIVOT)

NO_EVIDENCE = "no evidence"
#: A spend's status is its weakest contract's state: DEF-contract-state's order, with no evidence
#: just below supported -- a spend whose contracts have not all run has not shown support.
_RANK = {"refuted": 0, "stale": 1, "contested": 2, "insufficient_evidence": 3, NO_EVIDENCE: 4, "supported": 5}
SETTLED = ("supported", "refuted", "contested")
#: A spend waits on its result while the result reads one of these: its test has not come back
#: with enough to say anything yet.
WAITING = ("insufficient_evidence", NO_EVIDENCE)

# Direction states, in the order the board lists them.
NEEDS_REFLECTION = "needs reflection"
ACTIVE = "active"
READY = "ready"
EARNING = "earning"
PROPOSED = "proposed"
HALTED = "halted"
DIRECTION_STATES = (NEEDS_REFLECTION, ACTIVE, READY, EARNING, PROPOSED, HALTED, REJECTED)


def clock() -> datetime:
    """The board's one clock: what records are stamped with and what idle time is counted to."""
    return datetime.now(timezone.utc)


def utc_now() -> str:
    """Microseconds, so two records made in one second keep their order."""
    return clock().isoformat(timespec="microseconds")


def when(stamp: Any) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(stamp))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def git(root: Path, *args: str) -> str | None:
    """stdout, or None when git fails. stdin is closed: an inherited MCP stdio pipe hangs any
    child that reads it."""
    try:
        out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=15,
                             encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


# ---------- the rules ----------

@dataclass
class Rules:
    """research.yaml as committed at HEAD, or the defaults when nothing is committed."""

    focus: str = ""
    costs: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_COSTS))
    earn: int = DEFAULT_EARN
    earn_evidence: int = DEFAULT_EARN_EVIDENCE
    scouts: int = DEFAULT_SCOUTS
    idle_per_hour: int = DEFAULT_IDLE_PER_HOUR
    running_minutes: int = DEFAULT_RUNNING_MINUTES
    source: str = "defaults"
    changed: str = ""              # the last commit that changed research.yaml: "<sha> <date> <subject>"
    issues: list[str] = field(default_factory=list)

    def cheapest_paid(self) -> int | None:
        paid = [cost for cost in self.costs.values() if cost > 0]
        return min(paid) if paid else None


def _count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def load_rules(root: Path) -> Rules:
    """The rules take effect from HEAD, like every declaration: an uncommitted edit changes no
    cost, and is named so nobody mistakes it for one that did."""
    rules = Rules()
    committed = git(root, "show", f"HEAD:{RULES_FILE}")
    path = root / RULES_FILE
    worktree = path.read_text(encoding="utf-8") if path.exists() else None
    if committed is None:
        if worktree is not None:
            rules.issues.append(f"UNCOMMITTED {RULES_FILE}: rules take effect only once committed; "
                                "the defaults are in effect")
        return rules
    rules.source = "HEAD"
    if worktree is not None and worktree.replace("\r\n", "\n") != committed.replace("\r\n", "\n"):
        rules.issues.append(f"PENDING {RULES_FILE}: the working tree differs from HEAD; "
                            "the uncommitted edits are not in effect")
    rules.changed = (git(root, "log", "-1", "--format=%h %cs %s", "--", RULES_FILE) or "").strip()
    from component_belief.declarations import load_yaml

    try:
        data, duplicates = load_yaml(committed)
    except yaml.YAMLError as exc:
        rules.issues.append(f"MALFORMED {RULES_FILE}: {exc}; the defaults are in effect")
        return rules
    data = data or {}
    rules.issues += [f"DUPLICATE_KEY {RULES_FILE}: {d.describe(RULES_FILE)}" for d in duplicates]
    if not isinstance(data, dict):
        rules.issues.append(f"MALFORMED {RULES_FILE}: expected a mapping; the defaults are in effect")
        return rules

    for key in sorted(set(data) - set(RULE_KEYS)):
        rules.issues.append(f"UNREAD {RULES_FILE}: `{key}` is not a rule this version reads")
    if "focus" in data:
        rules.focus = str(data["focus"] or "")
    if "costs" in data:
        raw = data["costs"]
        if isinstance(raw, dict):
            rules.costs = {}
            for action, cost in raw.items():
                if _count(cost) is None:
                    rules.issues.append(f"MALFORMED {RULES_FILE}: costs.{action} must be a whole number "
                                        f"of points, 0 or more; `{action}` cannot be spent on")
                else:
                    rules.costs[str(action)] = cost
        else:
            rules.issues.append(f"MALFORMED {RULES_FILE}: costs must map an action to its points; "
                                "the default costs are in effect")
    if "earn" in data:
        raw = data["earn"]
        given = raw if isinstance(raw, dict) else {"trail": raw}
        if "trail" in given:
            earn = _count(given["trail"])
            if earn is None:
                rules.issues.append(f"MALFORMED {RULES_FILE}: earn.trail must be a whole number of points, "
                                    f"0 or more; {DEFAULT_EARN} is in effect")
            else:
                rules.earn = earn
        if "evidence" in given:
            earn = _count(given["evidence"])
            if earn is None:
                rules.issues.append(f"MALFORMED {RULES_FILE}: earn.evidence must be a whole number of "
                                    f"points, 0 or more; {DEFAULT_EARN_EVIDENCE} is in effect")
            else:
                rules.earn_evidence = earn
        for key in sorted(set(given) - {"trail", "evidence"}):
            rules.issues.append(f"UNREAD {RULES_FILE}: `earn.{key}` is not a rule this version reads")
    if "scouts" in data:
        scouts = _count(data["scouts"])
        if not scouts:
            rules.issues.append(f"MALFORMED {RULES_FILE}: scouts must be 1 or more; {DEFAULT_SCOUTS} is in effect")
        else:
            rules.scouts = scouts
    if "idle" in data:
        raw = data["idle"]
        given = raw if isinstance(raw, dict) else {"per_hour": raw}
        if "per_hour" in given:
            if _count(given["per_hour"]) is None:
                rules.issues.append(f"MALFORMED {RULES_FILE}: idle.per_hour must be a whole number of points, "
                                    f"0 or more; {DEFAULT_IDLE_PER_HOUR} is in effect")
            else:
                rules.idle_per_hour = given["per_hour"]
        if "running_minutes" in given:
            if not _count(given["running_minutes"]):
                rules.issues.append(f"MALFORMED {RULES_FILE}: idle.running_minutes must be 1 or more; "
                                    f"{DEFAULT_RUNNING_MINUTES} is in effect")
            else:
                rules.running_minutes = given["running_minutes"]
        for key in sorted(set(given) - {"per_hour", "running_minutes"}):
            rules.issues.append(f"UNREAD {RULES_FILE}: `idle.{key}` is not a rule this version reads")
    return rules


# ---------- the ledger ----------

def research_dir(root: Path) -> Path:
    return root / RESEARCH_DIR


def evidence_dir(root: Path, evidence_id: str) -> Path:
    """Where the board keeps its own copy of a finding's artifact: the bytes it hashed."""
    return research_dir(root) / "evidence" / evidence_id


def ledger_path(root: Path) -> Path:
    return research_dir(root) / LEDGER_FILE


def read_ledger(root: Path) -> list[dict[str, Any]]:
    path = ledger_path(root)
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def paper_key(paper: str) -> str:
    """Two citations of one paper match however they are punctuated or cased."""
    return " ".join(re.sub(r"[^0-9a-z]+", " ", paper.lower()).split())


def direction_id(name: str) -> str:
    slug = re.sub(r"[^0-9a-z]+", "-", name.strip().lower().removeprefix("dir-")).strip("-")
    return f"DIR-{slug}" if slug else ""


def is_research(record: dict[str, Any]) -> bool:
    """What shows research running: a direction opened, a trail that earned when it was recorded,
    a measured finding attached, a question asked or a check proposed by a scout, or an answer. A note, a
    trail that earned nothing, a digest and the director's verdicts and reflections are not: a note
    left only to stop the clock would otherwise stop it."""
    kind = record.get("kind")
    if kind in ("direction", "evidence"):
        return True
    if kind == "trail":
        return int(record.get("points") or 0) > 0
    if kind != "feedback":
        return False
    return (record.get("type") in (QUESTION, CHECK) and record.get("by") != "director") or record.get("type") == ANSWER


# ---------- results ----------

def targeted_contracts(decl: Any, target: str) -> list[str]:
    """A contract names itself; a test names each contract it can measure; anything else -- a
    component an implementation spend targets -- names none, and has no result."""
    if target in decl.contracts:
        return [target]
    if target in decl.tests:
        return sorted(cid for cid, contract in decl.contracts.items() if target in contract.evaluable_by)
    return []


@dataclass
class Result:
    """A spend's result: for each contract it targets, the state its slices read when they are
    computed from the records recorded against it after the spend, and from no other record."""

    states: dict[str, str] = field(default_factory=dict)
    counted: dict[str, int] = field(default_factory=dict)
    runs: dict[str, list[str]] = field(default_factory=dict)
    settled_at: datetime | None = None
    waited_until: datetime | None = None       # the first moment it read other than WAITING; None: still waiting

    @property
    def status(self) -> str:
        return _weakest(self.states)

    @property
    def settled(self) -> bool:
        return self.status in SETTLED


def _weakest(states: dict[str, str]) -> str:
    if not states:
        return ""
    return min(states.values(), key=lambda state: _RANK.get(state, 3))


def _states(decl: Any, records: list[dict[str, Any]], contracts: list[str], staleness: Any) -> dict[str, str]:
    from component_belief.model import compute_slices

    states: dict[str, str] = {}
    for sl in compute_slices(decl, records, contracts, staleness=staleness):
        seen = states.get(sl.contract_id)
        if seen is None or _RANK.get(sl.state, 3) < _RANK.get(seen, 3):
            states[sl.contract_id] = sl.state
    for cid in contracts:
        states.setdefault(cid, NO_EVIDENCE)
    return states


def spend_result(decl: Any, trials: list[dict[str, Any]], staleness: Any, spend: dict[str, Any]) -> Result:
    """The evidence a spend may claim is the measured evidence recorded after it, against the
    contracts it named when it was recorded -- by the test it named, when it named one -- so three
    arms on one contract, each its own test and its own spend, keep their results apart
    (DEF-research-ledger).

    Measured only: the server recorded it from a run it captured itself, so it is the first record
    of its measurement. An imported record can carry a measurement made long before the spend, and
    a declaration that later widens a test's reach adds no contract to a spend already made.

    Records keep whole seconds and a spend keeps microseconds, so a record made in the same second
    as the spend reads as made before it. That errs the safe way: a result never rests on a run
    that may have finished before the points were committed (AXM-attribution-follows-commitment).

    When the spend stopped waiting is found by reading the result again over the records recorded
    by each moment, in the order they were recorded, up to the first that says something. Code
    changed since reads as stale, which is not waiting: a test that came back is not in flight,
    whatever has happened to the code since, so a doubt about when errs toward charging less idle.
    """
    result = Result()
    contracts = [c for c in spend.get("contracts", []) if c in decl.contracts]
    since = when(spend.get("timestamp"))
    if not contracts or since is None:
        return result
    test = spend.get("test") or ""            # a spend that named a test counts that test's runs only
    arm = spend.get("params") or {}           # ... run with the values it fixed, if it fixed any
    after = [t for t in trials
             if t.get("contract_id") in contracts and t.get("provenance") == "measured"
             and (not test or t.get("test_id") == test) and _same_arm(t.get("params"), arm)
             and (when(t.get("timestamp")) or since) > since]
    result.states = _states(decl, after, contracts, staleness)
    for cid in contracts:
        mine = [t for t in after if t.get("contract_id") == cid]
        result.counted[cid] = len(mine)
        result.runs[cid] = sorted({str(t.get("run_id")) for t in mine if t.get("run_id")})
    moments = [m for m in (when(t.get("timestamp")) for t in after) if m is not None]
    result.settled_at = max(moments) if moments else None
    for moment in sorted(set(moments)):
        by_then = [t for t in after if (when(t.get("timestamp")) or moment) <= moment]
        if _weakest(_states(decl, by_then, contracts, staleness)) not in WAITING:
            result.waited_until = moment
            break
    return result


# ---------- idle hours ----------

@dataclass
class Idle:
    """A direction's idle time: the hours a spend on it waited on a result while no research was
    running anywhere on the board, each priced at the rate its spend fixed (DEF-research-ledger)."""

    seconds: float = 0.0           # idle time, counted once however many spends waited through it
    cost: float = 0.0              # idle time priced, in point-hours: rate x hours, summed
    waiting_on: list[str] = field(default_factory=list)    # the spends waiting now
    queued: list[str] = field(default_factory=list)        # spends waiting for their first run to start
    idle_now: bool = False         # idle at this moment: the clock is running
    rate_now: int = 0

    @property
    def points(self) -> int:
        """Whole points: one at the first idle hour, two at the second, ..."""
        return int((self.cost + 1e-6) // 3600)

    @property
    def next_point_in(self) -> float | None:
        """Seconds until the next point, if the clock runs on at the present rate."""
        if not self.idle_now or not self.rate_now:
            return None
        return (3600 - (self.cost % 3600)) / self.rate_now


def idle_stretches(start: datetime, end: datetime, research: list[datetime],
                   running: timedelta) -> list[tuple[datetime, datetime]]:
    """The parts of [start, end) no research record ran over; each runs `running` after it.
    `research` is in the order recorded."""
    stretches: list[tuple[datetime, datetime]] = []
    cursor = start
    for moment in research:
        if moment >= end:
            break
        if moment + running <= cursor:
            continue
        if moment > cursor:
            stretches.append((cursor, moment))
        cursor = max(cursor, moment + running)
        if cursor >= end:
            return stretches
    if cursor < end:
        stretches.append((cursor, end))
    return stretches


def _closed_after(d: Direction, since: datetime) -> datetime | None:
    """The first halt, pivot or rejection of a direction recorded after `since`."""
    for item in d.feedback:
        if item.get("about") == d.id and item.get("type") in (HALT, PIVOT, REJECTED):
            moment = when(item.get("timestamp"))
            if moment is not None and moment > since:
                return moment
    return None


def unclaimed_runs(board: "Board", goal: str, trials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The runs that count for no direction on a goal (DEF-research-ledger): measured runs recorded
    against a contract a spend on one of the goal's directions targets, after the first such spend
    was recorded, whose records enter no spend's result. Work the board did not attribute -- listed
    so the human sees it, and never a direction's result. Oldest first."""
    first: dict[str, datetime] = {}
    for d in board.directions.values():
        if d.goal != goal:
            continue
        for spend in d.spends:
            at = when(spend.get("timestamp"))
            for cid in spend.get("contracts", []):
                if at is not None and (cid not in first or at < first[cid]):
                    first[cid] = at
    if not first:
        return []
    claimed = {run for result in board.results.values() for ids in result.runs.values() for run in ids}
    runs: dict[str, dict[str, Any]] = {}
    for t in trials:
        cid, at, rid = t.get("contract_id"), when(t.get("timestamp")), str(t.get("run_id") or "")
        if (cid not in first or at is None or at <= first[cid] or not rid or rid in claimed
                or t.get("provenance") != "measured"):
            continue
        run = runs.setdefault(rid, {"run": rid, "test": t.get("test_id"), "params": t.get("params") or {},
                                    "contracts": set(), "outcomes": {}, "at": at})
        run["contracts"].add(cid)
        outcome = str(t.get("outcome") or "?")
        run["outcomes"][outcome] = run["outcomes"].get(outcome, 0) + 1
        run["at"] = max(run["at"], at)
    return sorted(runs.values(), key=lambda r: r["at"])


def _same_arm(ran: dict[str, Any] | None, fixed: dict[str, Any]) -> bool:
    """Whether a run was given every value a spend fixed."""
    ran = ran or {}
    return all(str(ran.get(k)) == str(v) for k, v in fixed.items())


def run_starts(trials: list[dict[str, Any]]) -> dict[str, datetime]:
    """When each recorded run started: the time its records carry, or, for a run recorded before
    runs said, when it was recorded -- which errs toward charging less idle."""
    out: dict[str, datetime] = {}
    for t in trials:
        run, moment = str(t.get("run_id") or ""), when(t.get("started")) or when(t.get("timestamp"))
        if run and moment is not None and (run not in out or moment < out[run]):
            out[run] = moment
    return out


def wait_start(decl: Any, spend: dict[str, Any], result: Result | None, started: dict[str, datetime],
               running: list[dict[str, Any]]) -> datetime | None:
    """When a spend starts to wait (DEF-research-ledger): when it was recorded, or, for one that
    waits from its first run, the later of that and when the first run counting for it started --
    a run whose records entered its result, or one still running its test (or, naming none, a test
    that can measure a contract it targets). None while no such run has started."""
    recorded = when(spend.get("timestamp"))
    if (spend.get("idle") or {}).get("from") != FIRST_RUN or recorded is None:
        return recorded
    runs = {r for ids in (result.runs.values() if result else ()) for r in ids}
    starts: list[datetime | None] = [started[r] for r in runs if r in started]
    test = spend.get("test") or ""
    tests = {test} if test else {tid for cid in spend.get("contracts", []) if cid in decl.contracts
                                 for tid in decl.contracts[cid].evaluable_by}
    starts += [when(j.get("started")) for j in running if str(j.get("test", "")).split("@", 1)[0] in tests
               and _same_arm(j.get("params"), spend.get("params") or {})]
    first = min((m for m in starts if m is not None), default=None)
    return None if first is None else max(recorded, first)


def direction_idle(d: Direction, results: dict[str, Result], research: list[datetime], now: datetime,
                   starts: dict[str, datetime | None] | None = None) -> Idle:
    """A spend waits from its start (wait_start) until its result first says something, or its
    direction is halted or rejected; while one waits and no research record falls within its
    running time, the direction is idle. A spend recorded before idle hours were priced fixed no
    rate, and costs nothing; one that waits from its first run and has none started is queued."""
    idle = Idle()
    segments: list[tuple[datetime, datetime, int]] = []
    for spend in d.spends:
        terms = spend.get("idle") or {}
        rate, running = _count(terms.get("per_hour")), _count(terms.get("running_minutes"))
        result = results.get(spend["id"])
        start = (starts or {}).get(spend["id"], when(spend.get("timestamp")))
        if start is None:
            if result is not None and result.states and _closed_after(d, when(spend.get("timestamp")) or now) is None:
                idle.queued.append(spend["id"])
            continue
        if not rate or not running or result is None or not result.states:
            continue
        # closed since the spend, not since its wait began: a direction halted while the spend was
        # queued waits on nothing when the run starts afterwards
        closed = _closed_after(d, when(spend.get("timestamp")) or start)
        ends = [now] + [m for m in (result.waited_until, closed) if m is not None]
        end = min(ends)
        if end == now and start < now:
            idle.waiting_on.append(spend["id"])
        for a, b in idle_stretches(start, end, research, timedelta(minutes=running)):
            segments.append((a, b, rate))
    bounds = sorted({moment for a, b, _ in segments for moment in (a, b)})
    for lo, hi in zip(bounds, bounds[1:]):
        rate = max((r for a, b, r in segments if a <= lo and hi <= b), default=0)
        if rate:
            idle.seconds += (hi - lo).total_seconds()
            idle.cost += rate * (hi - lo).total_seconds()
            if hi == now:
                idle.idle_now, idle.rate_now = True, rate
    return idle


# ---------- the board ----------

@dataclass
class Direction:
    record: dict[str, Any]
    trails: list[dict[str, Any]] = field(default_factory=list)
    spends: list[dict[str, Any]] = field(default_factory=list)
    feedback: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)    # measured findings attached to it
    digest: dict[str, Any] | None = None        # the director's latest "facts so far"
    verdict: dict[str, Any] | None = None       # the latest approval or rejection
    decision: dict[str, Any] | None = None      # the latest continue, halt or pivot
    retarget: dict[str, Any] | None = None      # the latest move to another goal, if any
    state: str = PROPOSED
    unreflected: list[str] = field(default_factory=list)   # spends whose result settled since the last decision
    idle: Idle | None = None                    # computed with the results; None on a board built without them

    @property
    def id(self) -> str:
        return self.record["id"]

    @property
    def goal(self) -> str:
        """The goal it serves: the one it was opened for, or the one the latest retarget named."""
        return str((self.retarget or self.record).get("goal", ""))

    @property
    def rank(self) -> int | None:
        if self.verdict and self.verdict.get("type") == APPROVED:
            return self.verdict.get("rank")
        return None

    @property
    def approved(self) -> bool:
        return bool(self.verdict) and self.verdict.get("type") == APPROVED


@dataclass
class Board:
    root: Path
    rules: Rules
    decl: Any
    records: list[dict[str, Any]]
    directions: dict[str, Direction] = field(default_factory=dict)
    trails: dict[str, dict[str, Any]] = field(default_factory=dict)
    spends: dict[str, dict[str, Any]] = field(default_factory=dict)
    feedback: dict[str, dict[str, Any]] = field(default_factory=dict)
    evidence: dict[str, dict[str, Any]] = field(default_factory=dict)
    results: dict[str, Result] = field(default_factory=dict)
    starts: dict[str, datetime | None] = field(default_factory=dict)     # when each spend's wait starts
    unclaimed: dict[str, list[dict[str, Any]]] = field(default_factory=dict)   # per goal: runs no direction claims
    trail_verdicts: dict[str, dict[str, Any]] = field(default_factory=dict)
    measures: dict[str, str] = field(default_factory=dict)      # each goal's measure, as it reads now
    goal_feedback: dict[str, list[dict[str, Any]]] = field(default_factory=dict)   # feedback on a goal itself
    evidence_error: str = ""
    ledger_ignored: str = ""       # why git would leave the ledger out of a commit, if it would
    now: datetime = field(default_factory=clock)
    research_until: datetime | None = None    # research counts as running until then, by the rules now

    # ---- what a record is worth ----

    def rejected(self, trail_id: str) -> dict[str, Any] | None:
        verdict = self.trail_verdicts.get(trail_id)
        return verdict if verdict and verdict.get("type") == REJECTED else None

    def points(self, trail: dict[str, Any]) -> int:
        return 0 if self.rejected(trail["id"]) else int(trail.get("points") or 0)

    def earned(self, d: Direction) -> int:
        return sum(self.points(t) for t in d.trails) + sum(int(e.get("points") or 0) for e in d.evidence)

    def spent(self, d: Direction) -> int:
        return sum(int(s.get("cost") or 0) for s in d.spends)

    def idle_points(self, d: Direction) -> int:
        return d.idle.points if d.idle else 0

    def balance(self, d: Direction) -> int:
        """DEF-research-ledger: the points its trails and its measured findings earned, less those
        of rejected trails, less the costs of its spends, less what its idle hours have cost by now
        -- computed from the research ledger and the evidence ledger, never written to either."""
        return self.earned(d) - self.spent(d) - self.idle_points(d)

    def issues(self) -> list[str]:
        """What the director should know before trusting what the board shows or commits."""
        return self.rules.issues + [i for i in (self.evidence_error, self.ledger_ignored) if i]

    def direction_of(self, research_id: str) -> str:
        """The direction a research id belongs to, or "" when it names none."""
        if research_id in self.directions:
            return research_id
        for table in (self.trails, self.spends, self.feedback, self.evidence):
            if research_id in table:
                return str(table[research_id].get("direction", ""))
        return ""

    def open_questions(self) -> list[dict[str, Any]]:
        """The questions and proposed checks waiting on the director: not answered, and, for a
        check, no measured finding attached in reply to it."""
        answered = {f.get("reply_to") for f in self.feedback.values() if f.get("type") == ANSWER}
        answered |= {e.get("reply_to") for e in self.evidence.values() if e.get("reply_to")}
        return [f for f in self.feedback.values() if f.get("type") in (QUESTION, CHECK) and f["id"] not in answered]

    def ordered(self) -> list[Direction]:
        """The board's order: what waits on the director, what waits on a run, what can be tried
        next -- the director's rank first, then the most research behind it -- what is still
        earning, the proposals by their research, and last the directions closed."""
        def key(d: Direction) -> tuple:
            rank = d.rank if isinstance(d.rank, int) else 10**6
            return (DIRECTION_STATES.index(d.state), rank, -self.balance(d), d.record.get("timestamp", ""))
        return sorted(self.directions.values(), key=key)


#: The declarations and rules last read for each project, keyed by HEAD and the declaration files'
#: stats: both are read from HEAD and compared with the working tree, so they change only when one
#: of those does. A git process costs a tenth of a second on some machines, and every move reads
#: the board twice.
_READS: dict[str, tuple[tuple, Any, Rules]] = {}
_DECLARATION_FILES = ("belief.yaml", "goals.yaml", RULES_FILE)


def _stat(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def head_reads(root: Path) -> tuple[Any, Rules]:
    """component-belief's declarations and the research rules, as committed at HEAD."""
    from component_belief.declarations import load as load_components

    key = ((git(root, "rev-parse", "HEAD") or "").strip(),
           *(_stat(root / name) for name in _DECLARATION_FILES))
    seen = _READS.get(str(root))
    if seen is not None and seen[0] == key:
        return seen[1], seen[2]
    decl, rules = load_components(root), load_rules(root)
    _READS[str(root)] = (key, decl, rules)
    return decl, rules


def build(root: Path, *, with_results: bool = True) -> Board:
    """The board as it reads now. Without results it has no idle hours either -- when a spend stops
    waiting is read from its result -- so its balances leave them out; the moves check against such
    a board only what no balance decides."""
    decl, rules = head_reads(root)
    board = Board(root=root, rules=rules, decl=decl, records=read_ledger(root), now=clock())
    for record in board.records:
        kind = record.get("kind")
        rid = record.get("id")
        if not rid:
            continue
        if kind == "direction":
            board.directions[rid] = Direction(record=record)
        elif kind == "trail":
            board.trails[rid] = record
        elif kind == "spend":
            board.spends[rid] = record
        elif kind == "feedback":
            board.feedback[rid] = record
        elif kind == "evidence":
            board.evidence[rid] = record
        elif kind == "digest" and (d := board.directions.get(str(record.get("direction")))) is not None:
            d.digest = record                      # the ledger's order: the latest stands

    for trail in board.trails.values():
        if (d := board.directions.get(str(trail.get("direction")))) is not None:
            d.trails.append(trail)
    for spend in board.spends.values():
        if (d := board.directions.get(str(spend.get("direction")))) is not None:
            d.spends.append(spend)
    for item in board.evidence.values():
        if (d := board.directions.get(str(item.get("direction")))) is not None:
            d.evidence.append(item)
    for item in board.feedback.values():          # the ledger's order is the order recorded
        about = str(item.get("about", ""))
        kind = item.get("type")
        if kind in VERDICTS and about in board.trails:
            board.trail_verdicts[about] = item
        if item.get("goal") and not item.get("direction"):
            board.goal_feedback.setdefault(str(item["goal"]), []).append(item)
        if (d := board.directions.get(str(item.get("direction")))) is not None:
            d.feedback.append(item)
            if kind in VERDICTS and about == d.id:
                d.verdict = item
            elif kind in DECISIONS and about == d.id:
                d.decision = item
            elif kind == RETARGET and about == d.id:
                d.retarget = item

    board.ledger_ignored = ignored_ledger(root)
    if with_results:
        try:
            from component_belief.model import compute_slices
            from component_belief.staleness import CodeStaleness
            from component_belief.store import Store

            from component_belief.jobs import jobs as background_runs

            trials = Store(root).effective_trials()
            staleness = CodeStaleness(root)
            running = [j for j in background_runs(root) if j.get("state") == "running"]
            started = run_starts(trials)
            for sid, spend in board.spends.items():
                board.results[sid] = spend_result(board.decl, trials, staleness, spend)
                board.starts[sid] = wait_start(board.decl, spend, board.results[sid], started, running)
            # what each goal's measure reads now, on all its evidence: context for a direction, never
            # one of its results
            measures = sorted({g.measure for g in board.decl.goals.values() if g.measure in board.decl.contracts})
            for sl in compute_slices(board.decl, trials, measures, staleness=staleness) if measures else []:
                seen = board.measures.get(sl.contract_id)
                if seen is None or _RANK.get(sl.state, 3) < _RANK.get(seen, 3):
                    board.measures[sl.contract_id] = sl.state
            for cid in measures:
                board.measures.setdefault(cid, NO_EVIDENCE)
            for goal_id in sorted({d.goal for d in board.directions.values()}):
                board.unclaimed[goal_id] = unclaimed_runs(board, goal_id, trials)
        except Exception as exc:                  # a ledger this server does not own
            board.evidence_error = f"component-belief's evidence could not be read ({exc}); no result is shown"

        research = sorted(m for m in (when(r.get("timestamp")) for r in board.records if is_research(r))
                          if m is not None)
        if research:
            board.research_until = research[-1] + timedelta(minutes=board.rules.running_minutes)
        for d in board.directions.values():
            d.idle = direction_idle(d, board.results, research, board.now, board.starts)

    cheapest = board.rules.cheapest_paid()
    for d in board.directions.values():
        decided = when(d.decision.get("timestamp")) if d.decision else None
        for spend in d.spends:
            result = board.results.get(spend["id"])
            if result and result.settled and (decided is None or (result.settled_at and result.settled_at > decided)):
                d.unreflected.append(spend["id"])
        if d.verdict and d.verdict.get("type") == REJECTED:
            d.state = REJECTED
        elif d.decision and d.decision.get("type") in (HALT, PIVOT):
            d.state = HALTED
        elif not d.approved:
            d.state = PROPOSED
        elif d.unreflected:
            d.state = NEEDS_REFLECTION
        elif any(board.results.get(s["id"]) and not board.results[s["id"]].settled
                 and board.results[s["id"]].states for s in d.spends):
            d.state = ACTIVE
        elif cheapest is None or board.balance(d) >= cheapest:
            d.state = READY
        else:
            d.state = EARNING
    return board


def ignored_ledger(root: Path) -> str:
    """Why `git add .research/` would leave the ledger out, or "" when it would not. A repository
    that ignores *.jsonl ignores it in silence, and the page beside it is committed alone."""
    path = f"{RESEARCH_DIR}/{LEDGER_FILE}"
    rule = git(root, "check-ignore", "-v", path)
    if not rule:
        return ""
    source = rule.split("\t", 1)[0].strip()
    return (f"IGNORED {path}: git ignores it ({source}), so committing {RESEARCH_DIR}/ leaves the "
            f"ledger out and keeps only the page; add `!{path}` to .gitignore")


def research_files(root: Path) -> set[str]:
    """Every file in .research/ now, and the two the board writes, as repository paths."""
    paths = {f"{RESEARCH_DIR}/{LEDGER_FILE}", f"{RESEARCH_DIR}/{BOARD_FILE}"}
    directory = research_dir(root)
    if directory.is_dir():
        paths |= {p.relative_to(root).as_posix() for p in directory.rglob("*") if p.is_file()}
    return paths


def reading_research(root: Path, decl: Any) -> list[str]:
    """The declared tests whose latest recorded run, as its read hook saw, opened a file in
    .research/ -- each as "TST-x (RUN-n)". Such a run's evidence rests on what is there, though no
    declaration says so, and recording would move it (DEF-research-ledger). Its latest run only: a
    test changed to leave .research/ alone and run again stops the refusal."""
    from component_belief.readlog import read
    from component_belief.store import Store

    store = Store(root)
    latest: dict[str, str] = {}
    for t in store.effective_trials():             # the ledger's order: the last run of a test stands
        if t.get("test_id") in decl.tests and t.get("run_id"):
            latest[str(t["test_id"])] = str(t["run_id"])
    return sorted(f"{tid} ({run})" for tid, run in latest.items()
                  if any(p.split("/", 1)[0] == RESEARCH_DIR for p in read(store.artifacts_dir / run)))


def naming_research(root: Path, decl: Any) -> list[str]:
    """The components whose code claims a file in .research/, and the tests that name one on their
    run line or among what they read -- matched exactly as staleness matches them. Evidence would
    rest on such a file, and recording would move it, so the board records nothing while any
    declaration names one (DEF-research-ledger)."""
    from component_belief.staleness import named_paths

    probe = research_files(root)
    hits = [cid for cid, comp in decl.components.items() if named_paths("", list(comp.code), probe)]
    hits += [tid for tid, test in decl.tests.items() if named_paths(test.run, list(test.reads), probe)]
    return sorted(hits)
