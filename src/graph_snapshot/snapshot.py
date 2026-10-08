"""The join: the declarations committed at one revision, the proof states over them, the gaps.

A snapshot resolves HEAD to one commit before it reads anything and reads every declaration file at
that commit, so a commit landing mid-read cannot mix two revisions into one page. The proof state of
each lemma and branch is the one consistency-belief's own Context computes for that commit and the
ledger as read; nothing here re-derives a state. What the snapshot adds is what no one server sees:
the edges between consistency.yaml, belief.yaml and goals.yaml, and the gaps along them.

Every edge points one way, "rests on": a component rests on the branches that govern it, a claim on
the premises it cites, an axiom on the goal whose requirement it states. A node's lineage is then
two closures, what it rests on and what rests on it.

Tagged code regions (code_links) are drawn on the node they relate to, as a list -- never as an
edge. A region that implements a branch is not a premise of it, and the graph is premise edges.
Each region carries its link state as code_links computes it at the same commit; no source text
is copied onto the page, only ids, paths and lines.

A node's references to the works it came from (consistency.yaml's `sources:`) are drawn the same
way, as a list on the node: a reference is not a premise, so it is never an edge.
"""

from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from component_belief.declarations import DECLARATION_FILE as BELIEF_FILE
from component_belief.declarations import GOALS_FILE
from component_belief.declarations import load as load_components
from component_belief.staleness import named_paths
from code_links import ERROR, REVIEW, CodeIndex, link_state, review_of
from consistency_belief.declarations import DECLARATION_FILE as CONSISTENCY_FILE
from consistency_belief.links import PinHistory
from consistency_belief.links import scan as scan_links
from consistency_belief.measurements import REVIEWED, cited_measurements, uncited_by_kind
from consistency_belief.model import CONDITIONAL, PROVEN
from consistency_belief.views import Context

from .page import PAGE_PATHS

_CONTRACT = re.compile(r"\bCTR-[A-Za-z0-9][A-Za-z0-9_-]*\b")
_STAGED_ISSUE = re.compile(r"^staged (\S+): (.*)$")

#: The sources an issue is reported under: the two loaders, the premise-graph build, the join, the
#: scan of tagged code regions, and the branches' cited measurements (a gap of the join, listed
#: apart because a project that pins none has one per citation).
JOINED = "joined graph"
CODE_LINKS = "code links"
MEASUREMENTS = "cited measurements"

#: Order of the per-kind tallies in the summary: worst first, as the page lists them.
_CLAIM_ORDER = ("refuted", "ungrounded", "doubted", "stale", "obligation", CONDITIONAL, PROVEN)
_COVER_ORDER = ("undeclared design", "planned", "governed", "declared only", "no design claim")


class NoRevision(Exception):
    """The project has no commit, so nothing is declared at any revision."""


def _git(root: Path, *args: str) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=30,
                             encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def resolve(root: Path) -> str:
    """HEAD as one commit, resolved once: every declaration in a snapshot is read at this sha."""
    sha = _git(root, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
    if not sha:
        raise NoRevision(f"{root} has no commit, so no declaration is in effect at any revision; "
                         f"commit {CONSISTENCY_FILE} and {BELIEF_FILE} first")
    return sha


def take(root: Path) -> dict[str, Any]:
    """The snapshot of `root` at the commit HEAD names now."""
    sha = resolve(root)
    ctx = Context.build(root, revision=sha)
    components = load_components(root, revision=sha)
    proof = {s.target_id: s for s in ctx.slices}

    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[tuple[str, str], None] = {}       # (a, b): a rests on b; a dict keeps first-seen order

    def add(nid: str, kind: str, **fields: Any) -> None:
        nodes[nid] = {"id": nid, "kind": kind, **fields}

    for gid, goal in components.goals.items():
        add(gid, "goal", text=goal.outcome, measure=goal.measure)
    for aid, axiom in ctx.decl.axioms.items():
        add(aid, "axiom", text=axiom.statement, rationale=axiom.rationale, domain=axiom.domain,
            goals=axiom.goals, references=references(ctx.decl, aid))
        edges.update(dict.fromkeys((aid, g) for g in axiom.goals))
    for did, definition in ctx.decl.definitions.items():
        add(did, "definition", term=definition.term, text=definition.meaning,
            references=references(ctx.decl, did))

    governs: dict[str, list[str]] = {}            # subject -> branches in the graph, staged or not
    for nid, node in ctx.dag.nodes.items():
        if node.kind not in ("lemma", "branch"):
            continue
        s = proof.get(nid)
        add(nid, node.kind, text=node.statement, rule=node.derivation_rule, subject=node.subject,
            premises=list(node.premises), staged=node.staged,
            state=s.state if s else None,
            count=f"{s.n_independent}/{s.n_min}" if s else "",
            why=s.issues[0] if s and s.issues else "",
            waiting=[list(w) for w in s.waiting_on] if s else [],
            cites=sorted(set(_CONTRACT.findall(node.derivation_rule or ""))),
            references=[] if node.staged else references(ctx.decl, nid))
        edges.update(dict.fromkeys((nid, p) for p in node.premises))
        if node.kind == "branch" and node.subject:
            governs.setdefault(node.subject, []).append(nid)
            edges[(node.subject, nid)] = None

    def declared(subject: str) -> list[str]:
        return [b for b in governs.get(subject, []) if not nodes[b]["staged"]]

    for cid, comp in components.components.items():
        coverage = ("governed" if declared(cid) else "undeclared design") if comp.implemented else (
            "planned" if governs.get(cid) else "declared only")
        add(cid, "component", text=comp.purpose, capability=comp.testable_capability, goal=comp.goal,
            code=list(comp.code), coverage=coverage, inputs=list(comp.inputs), outputs=list(comp.outputs),
            measured_by=[k.id for k in components.contracts_for_subject(cid)])
    for iid, iface in components.interfaces.items():
        add(iid, "interface", text=iface.semantics, producer=iface.producer, consumer=iface.consumer,
            coverage="governed" if governs.get(iid) else "no design claim",
            measured_by=[k.id for k in components.contracts_for_subject(iid)])
    for iid, between in components.goal_interfaces.items():
        add(iid, "interface", text=between.hands_over, producer=between.from_goal, consumer=between.to_goal,
            coverage="governed" if governs.get(iid) else "no design claim",
            measured_by=[between.measure] if between.measure else [])

    for pid, policy in ctx.decl.policies.items():
        for criterion in policy.criteria:
            target = criterion.get("target")
            if target in nodes:
                nodes[target].setdefault("gated_by", []).append(pid)

    # Judged from the declarations at this commit and the reviews in the ledger as read -- a review
    # against a claim digest -- so no evidence record is read; a contract's own state is never
    # shown (DEF-snapshot).
    cited = cited_measurements(ctx.decl, ctx.store.measurement_reviews(), PinHistory(root, sha).translate)
    for m in cited:
        if m.branch in nodes:
            nodes[m.branch].setdefault("measured", []).append({"contract": m.contract, "state": m.state,
                                                               "review": review_line(m.latest)})

    links = scan_links(root, sha, explain=False)
    if links is not None:
        for block in links.blocks:
            for r in block.relations:
                if r.target in nodes:
                    nodes[r.target].setdefault("regions", []).append({
                        "id": block.block_id, "relation": r.kind, "at": block.location,
                        "state": link_state(block, r, links.claims), "origin": block.origin,
                        "review": review_line(review_of(block, r))})

    committed = {CONSISTENCY_FILE: ctx.decl.source != "none", BELIEF_FILE: components.source != "none",
                 GOALS_FILE: bool(components.goals_blob)}
    issues = (_loader_issues(ctx, components) + gaps(ctx, nodes, governs) + _link_issues(links)
              + _measurement_issues(cited, uncited_by_kind(ctx.decl)))
    pending = sorted({i["subject"] for i in issues if i["code"] == "PENDING"})
    return {
        "project": root.name,
        "sha": sha,
        "revision": sha[:7],
        "subject": _git(root, "log", "-1", "--format=%s", sha),
        "committed": _git(root, "log", "-1", "--format=%cs", sha),
        "taken": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "sources": committed,
        "pending": pending,
        "nodes": nodes,
        "edges": [[a, b] for a, b in edges if a in nodes and b in nodes],
        "issues": issues,
        "page_named_by": naming_the_page(components),
    }


def review_line(review: dict | None) -> str:
    """Who read it, at which commit, and what they checked -- one line for the page."""
    if not review:
        return "never reviewed"
    if review.get("legacy"):
        return "pinned in the source, before reviews were records"
    note = f": {review['note']}" if review.get("note") else ""
    outcome = "" if review.get("outcome") == "aligned" else " (not aligned)"
    return (f"{review.get('id', 'reviewed')} at {str(review.get('commit') or '')[:7]} by "
            f"{review.get('actor') or '?'}{outcome}{note}")


def references(decl: Any, node_id: str) -> list[dict[str, str]]:
    """A declared node's references, each with its source's entry as committed; a reference naming
    no declared source keeps its id and has no entry (the loader reports it)."""
    out = []
    for ref in decl.references_of(node_id):
        src = decl.sources.get(ref.source)
        links = [address for _kind, _value, address in src.identifiers() if address] if src else []
        out.append({"source": ref.source, "at": ref.at, "entry": src.entry() if src else "",
                    "link": links[0] if links else ""})
    return out


def _loader_issues(ctx: Context, components: Any) -> list[dict[str, str]]:
    """What the two loaders and the premise-graph build already report, under their own codes."""
    seen: dict[tuple[str, str, str], dict[str, str]] = {}
    for source, found in ((CONSISTENCY_FILE, ctx.decl.issues), (BELIEF_FILE, components.issues)):
        for i in found:
            seen.setdefault((i.code, i.subject, i.message),
                            {"code": i.code, "subject": i.subject, "message": i.message, "source": source})
    out = list(seen.values())
    for text in ctx.staged_issues:
        m = _STAGED_ISSUE.match(text)
        out.append({"code": "UNRESOLVED_PROPOSAL", "subject": m.group(1) if m else "",
                    "message": m.group(2) if m else text, "source": "premise graph"})
    return out


def _measurement_issues(cited: list, uncited: dict[str, list[str]]) -> list[dict[str, str]]:
    """Every cited measurement not reviewed, and every contract no declared branch names, marked by
    what it measures -- the two gaps DEF-snapshot adds to the join's."""
    out = [{"code": "MEASUREMENT_" + m.state.upper().replace(" ", "_"),
            "subject": m.branch, "message": f"cites {m.contract}: {m.why}", "source": MEASUREMENTS}
           for m in cited if m.state != REVIEWED]
    marks = {"component": "a component's measure", "interface": "an interface's measure",
             "goal": "a goal's measure, which the goal's outcome explains"}
    out += [{"code": "UNCITED_CONTRACT", "subject": cid,
             "message": f"{marks.get(kind, kind)}; no declared branch names it in its derivation rule",
             "source": JOINED}
            for kind, ids in uncited.items() for cid in ids]
    return out


def _link_issues(links: CodeIndex | None) -> list[dict[str, str]]:
    """Broken tags and links needing review, as code_links reports them at the same commit.
    Observations (untracked mentions, unlinked branches) stay in `stamp-monitor links`."""
    if links is None:
        return []
    return [{"code": d.code, "subject": d.subject, "message": d.message, "source": CODE_LINKS}
            for d in links.sorted_diagnostics() if d.severity in (ERROR, REVIEW)]


def gaps(ctx: Context, nodes: dict[str, dict[str, Any]], governs: dict[str, list[str]]) -> list[dict[str, str]]:
    """The gaps only the join shows, each on the node it is about (DEF-snapshot lists them)."""
    found: list[dict[str, str]] = []

    def gap(code: str, subject: str, message: str) -> None:
        found.append({"code": code, "subject": subject, "message": message, "source": JOINED})

    goals = {n for n, v in nodes.items() if v["kind"] == "goal"}
    named = {g for a in ctx.decl.axioms.values() for g in a.goals}
    for aid, axiom in ctx.decl.axioms.items():
        if not axiom.goals:
            gap("AXIOM_WITHOUT_GOAL", aid, "names no goal, so no requirement traces from it to a goal")
    for gid in sorted(goals - named):
        gap("GOAL_WITHOUT_AXIOM", gid, "no axiom names this goal, so no theory traces to it")
    for nid, node in nodes.items():
        if node["kind"] == "component" and node["coverage"] == "undeclared design":
            gap("UNDECLARED_DESIGN", nid, "has code and no declared branch governs it: declare the "
                                          "design, or prune the code")
        elif node["kind"] in ("interface", "goal") and not governs.get(nid):
            gap("NO_DESIGN_CLAIM", nid, f"no branch governs this {node['kind']}")
    for nid, node in ctx.dag.nodes.items():
        if node.kind in ("axiom", "definition") and not ctx.dag.children.get(nid):
            gap("UNUSED_GROUND", nid, f"no lemma or branch rests on this {node.kind}")
    return found


def naming_the_page(components: Any) -> list[str]:
    """The components whose `code:` claims a file the snapshot writes, and the tests whose run line
    or `reads:` names one -- matched exactly as staleness matches them. Evidence rests on such a
    file, so rewriting it would stale that evidence; where any declaration names one, the
    snapshot writes nothing (DEF-snapshot)."""
    probe = set(PAGE_PATHS)
    hits = [cid for cid, comp in components.components.items()
            if named_paths("", list(comp.code), probe)]
    hits += [tid for tid, test in components.tests.items() if named_paths(test.run, list(test.reads), probe)]
    return hits


def summary(snap: dict[str, Any]) -> list[str]:
    """What a snapshot shows, in the few lines the tool returns."""
    nodes = list(snap["nodes"].values())
    files = ", ".join(f for f, ok in snap["sources"].items() if ok) or "nothing"
    lines = [f"graph snapshot: {snap['project']} @ {snap['revision']} ({snap['committed']}) -- "
             f"{files} as committed there"]
    if snap["pending"]:
        lines.append(f"uncommitted edits, not shown: {', '.join(snap['pending'])}")

    plural = {"branch": "branches"}

    def tally(kind: str, field: str, order: tuple[str, ...]) -> str:
        of = [n.get(field) or "?" for n in nodes if n["kind"] == kind]
        counts = {s: of.count(s) for s in dict.fromkeys([*order, *of]) if of.count(s)}
        name = plural.get(kind, kind + "s")
        return f"{name} {len(of)}" + (": " + ", ".join(f"{k} {s}" for s, k in counts.items()) if of else "")

    count = lambda kind: sum(1 for n in nodes if n["kind"] == kind)            # noqa: E731
    lines.append(" · ".join([tally("branch", "state", _CLAIM_ORDER), tally("lemma", "state", _CLAIM_ORDER)]))
    lines.append(" · ".join([tally("component", "coverage", _COVER_ORDER), tally("interface", "coverage", _COVER_ORDER),
                             f"{count('axiom')} axioms", f"{count('definition')} definitions", f"{count('goal')} goals"]))
    by_code: dict[str, int] = {}
    for i in snap["issues"]:
        by_code[i["code"]] = by_code.get(i["code"], 0) + 1
    lines.append("issues: " + (", ".join(f"{n} {c}" for c, n in by_code.items()) or "none"))
    return lines
