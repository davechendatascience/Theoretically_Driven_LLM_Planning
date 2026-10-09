"""Views for consistency-belief: status reports across proof dimensions."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .declarations import (BOUNDARY_ID, COMPONENT_ID, DECLARATION_FILE, Declarations, _git_show, _parse, git_head,
                           contract_beliefs,
                           load as load_declarations)
from .graph import ProofDAG, ProofNode
from .ids import content_hash
from .lean import CERTIFIED, Certificate, current_certificates, judge, probe_block
from .measurements import (NOT_REVIEWED, REVIEW_FAILED, UNREVIEWED, CitedMeasurement, cited_measurements,
                           uncited_by_kind)
from .measurements import adopted as adopted_reviews
from .model import (CONDITIONAL, DOUBTED, PROVEN, REFUTED, OBLIGATION, STALE, UNGROUNDED, ConsistencySlice,
                    compute_consistency)
from .probes import probe_text
from .render import basis_line, bullet, envelope, render_ascii_dag, render_lineage, slice_badge
from .store import Store

VIEWS = ("tree", "branches", "axioms", "sources", "obligations", "probe", "contradictions", "coverage", "audit",
         "reviews", "certificates", "cycle")

#: The views that read status(subject=...); every other view ignores it, and says so.
SUBJECT_VIEWS = ("tree", "branches", "probe", "audit", "reviews", "certificates")

#: States a verifier can still act on: the probe view serves these.
OPEN_STATES = (OBLIGATION, STALE, DOUBTED)


@dataclass
class Context:
    root: Path
    store: Store
    decl: Declarations
    dag: ProofDAG
    slices: list[ConsistencySlice]
    staged_issues: list[str] = field(default_factory=list)
    #: The Lean certificate certifying each node's claim now, by node id (DEF-lean-certificate).
    certified: dict[str, Certificate] = field(default_factory=dict)

    @classmethod
    def build(cls, root: Path, staged_nodes: list[Any] | None = None, revision: str = "HEAD") -> Context:
        store = Store(root)
        decl = load_declarations(root, revision)
        dag = ProofDAG.from_declarations(decl)

        staged = [staged_node(p) for p in store.staged_proposals() if p["id"] not in dag.nodes]
        staged_issues = _add_in_dependency_order(dag, staged + list(staged_nodes or []))

        trials = store.effective_trials()
        slices = compute_consistency(dag, trials, legacy=HistoricalBuilds(root, store, revision).fingerprints)
        # Read after the proof states, and only beside them: a certificate moves none.
        certified = current_certificates(dag, store.certificates())
        for s in slices:
            if s.target_id in certified:
                s.certified_by = certified[s.target_id].id
        return cls(root=root, store=store, decl=decl, dag=dag, slices=slices, staged_issues=staged_issues,
                   certified=certified)


class HistoricalBuilds:
    """The premise graph as it stood when a trial was made, for the trials made before trials
    recorded fingerprints: consistency.yaml as the last commit before that moment held it, and
    the proposals staged by then. One build per distinct (revision, staged set), cached."""

    def __init__(self, root: Path, store: Store, revision: str = "HEAD") -> None:
        self.root, self.store, self.revision = root, store, revision
        self._builds: dict[tuple[str, str], ProofDAG] = {}

    def _revision(self, when: str) -> str:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%H", f"--before={when}", self.revision, "--", DECLARATION_FILE],
            cwd=self.root, capture_output=True, text=True, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL, timeout=60)
        return out.stdout.strip() if out.returncode == 0 else ""

    def build_at(self, when: str) -> ProofDAG:
        revision = self._revision(when) if when else ""
        staged = self.store.staged_proposals(until=when) if when else []
        key = (revision, content_hash([(p["id"], p.get("claim"), p.get("premises")) for p in staged], 12))
        if key not in self._builds:
            text = _git_show(self.root, revision) if revision else None
            dag = ProofDAG.from_declarations(_parse(text) if text else Declarations())
            _add_in_dependency_order(dag, [staged_node(p) for p in staged if p["id"] not in dag.nodes])
            self._builds[key] = dag
        return self._builds[key]

    def fingerprints(self, target_id: str, when: str) -> tuple[str, dict[str, str]] | None:
        dag = self.build_at(when)
        node = dag.get(target_id)
        return None if node is None else (node.fingerprint(), dag.basis_fingerprints(target_id))


def staged_node(proposal: dict[str, Any]) -> ProofNode:
    """The proof node a propose_branch event stands for."""
    return ProofNode(
        id=proposal["id"],
        kind="branch" if proposal.get("branch_type", "contract") == "contract" else "lemma",
        statement=proposal.get("claim", ""),
        premises=list(proposal.get("premises", [])),
        derivation_rule=proposal.get("rationale", ""),
        subject=proposal.get("subject", ""),
        metadata={"staged": True},
    )


def _add_in_dependency_order(dag: ProofDAG, nodes: list[ProofNode]) -> list[str]:
    """Add staged nodes whose premises are present, repeatedly, so a proposal may cite another
    proposal made after it; report the ones that never resolve (a withdrawn or renamed premise)."""
    pending = list(nodes)
    while pending:
        ready = [n for n in pending if all(p in dag.nodes for p in n.premises)]
        if not ready:
            break
        for n in ready:
            dag.add_node(n)
        pending = [n for n in pending if n not in ready]
    return [f"staged {n.id}: premise(s) {', '.join(p for p in n.premises if p not in dag.nodes)} not found"
            for n in pending]


def no_declarations_next(decl: Declarations) -> str:
    if decl.raw_present:
        return "commit consistency.yaml — it exists in the working tree but not at git HEAD, so no axioms or branches are in effect"
    return "author consistency.yaml and commit it; nothing is declared at git HEAD"


def view_no_declarations(ctx: Context, view: str) -> str:
    decl = ctx.decl
    lines = [
        "declarations: NONE IN EFFECT (no consistency.yaml at git HEAD)",
        "  Declarations load from git HEAD, not the working tree — commit consistency.yaml for it to take effect.",
        "",
        f"view {view!r} has nothing to report: no axioms, lemmas, or branches are declared at git HEAD.",
    ]
    if decl.issues:
        lines += ["", "declaration issues:", bullet(i.render() for i in decl.issues)]
    return envelope("\n".join(lines), f"basis: declarations none · next: {no_declarations_next(decl)}")


def view_tree(ctx: Context, subject: str | None = None) -> str:
    if subject:
        return view_lineage(ctx, subject)
    n_staged = sum(1 for n in ctx.dag.nodes.values() if n.staged)
    header = [
        f"Proof DAG: {len(ctx.dag.nodes)} nodes ({len(ctx.decl.axioms)} axioms, "
        f"{len(ctx.decl.lemmas)} lemmas, {len(ctx.decl.branches)} branches"
        + (f", {n_staged} staged -- proposed, not yet declared at git HEAD" if n_staged else "") + ")",
        f"Source: {ctx.decl.source}{' [PENDING UNCOMMITTED EDITS]' if ctx.decl.pending else ''}",
    ]
    withdrawn = ctx.store.withdrawn()
    if withdrawn:
        header.append(f"Withdrawn: {len(withdrawn)} staged proposal(s) retired -- "
                      + ", ".join(sorted(withdrawn)))
    if ctx.staged_issues:
        header += ["Staged proposals that do not resolve:", bullet(ctx.staged_issues)]
    # A declared node that failed admission has no slice, so no other view would show it: it is
    # neither an obligation a verifier can close nor anything a policy can adopt.
    unadmitted = sorted(nid for nid in list(ctx.decl.lemmas) + list(ctx.decl.branches)
                        if nid not in ctx.dag.nodes)
    if unadmitted:
        header.append("Declared, not admitted -- a premise each cites is unknown, removed or on a "
                      "cycle, so it cannot be verified or decided on:")
        header.append(bullet(
            f"{nid}: cites {', '.join(p for p in ctx.decl.node(nid).premises if p not in ctx.dag.nodes)}"
            for nid in unadmitted))
    header.append("")
    tree_text = render_ascii_dag(ctx.dag, ctx.slices)
    return envelope("\n".join(header) + "\n" + tree_text, basis_line(ctx.slices))


def view_lineage(ctx: Context, subject: str) -> str:
    """The tree for one node, or for each branch governing a component, interface or goal: what it
    rests on and what rests on it, and nothing else of the graph."""
    if ctx.dag.get(subject) is not None:
        targets = [subject]
    elif ctx.decl.subject_known(subject):
        targets = sorted(nid for nid, n in ctx.dag.nodes.items() if n.kind == "branch" and n.subject == subject)
        if not targets:
            return envelope(f"{subject} has no branch in the graph; status(view=\"coverage\") says what governs it.",
                            basis_line(ctx.slices))
    else:
        return f"unknown node {subject!r}; status(view=\"tree\") without a subject draws the whole graph."
    head = (f"Lineage of {subject}" + (f" -- its {len(targets)} branch(es)" if targets != [subject] else "")
            + f" · source: {ctx.decl.source}{' [PENDING UNCOMMITTED EDITS]' if ctx.decl.pending else ''}")
    body = "\n\n".join(render_lineage(ctx.dag, ctx.slices, t) for t in targets)
    return envelope(head + "\n\n" + body, basis_line(ctx.slices))


def view_branches(ctx: Context, subject: str | None = None) -> str:
    lines = []
    target_slices = ctx.slices
    if subject:
        target_slices = [s for s in ctx.slices if s.target_id == subject or subject in s.target_id]

    if not target_slices:
        return f"No branches found matching subject {subject!r}"

    for s in target_slices:
        badge = slice_badge(s)
        lines.append(f"{s.target_id} {badge} {s.kind.upper()}")
        lines.append(f"  claim: {s.statement}")
        lines.append(f"  premises: {', '.join(s.premises) or '(none)'}")
        lines.append(f"  axiomatic roots: {', '.join(s.axiomatic_basis) or '(none)'}")
        if s.counterexamples:
            lines.append(f"  counterexamples: {'; '.join(s.counterexamples)}")
        if s.gaps:
            lines.append(f"  entailment gaps: {'; '.join(s.gaps)}")
        if s.issues:
            lines.append(f"  issues: {'; '.join(s.issues)}")
        lines.append(f"  verification trials: {s.n_passed}/{s.n_trials} passed, "
                     f"{s.n_independent}/{s.n_min} independent (n_min={s.n_min}, set={s.set_handle})")
        if s.strategies_tried:
            lines.append(f"  strategies: {', '.join(s.strategies_tried)}"
                         + (f"; untried: {', '.join(s.untried)}" if s.untried else ""))
        if s.n_superseded or s.n_stale:
            lines.append(f"  not counted: {s.n_superseded} verified an earlier statement, "
                         f"{s.n_stale} predate a restated premise")
        if s.target_id in ctx.certified:
            c = ctx.certified[s.target_id]
            lines.append(f"  lean: {c.id} via {c.service} certifies {c.declaration} : "
                         f"{' '.join(c.reading.statement.split())}")
        if s.staged:
            lines.append("  staged: proposed, not declared at git HEAD -- declare it in consistency.yaml "
                         "and commit before it can support decide()")
        lines.append("")

    return envelope("\n".join(lines).rstrip(), basis_line(target_slices))


def view_axioms(ctx: Context) -> str:
    if not ctx.decl.axioms:
        if ctx.decl.source == "none":
            return view_no_declarations(ctx, "axioms")
        return "No axioms declared."

    lines = [f"Declared Root Axioms ({len(ctx.decl.axioms)}):", ""]
    for aid, axm in sorted(ctx.decl.axioms.items()):
        downstream = sorted(ctx.dag.descendants(aid))
        lines.append(f"{aid} [{axm.domain}]")
        lines.append(f"  statement: {axm.statement}")
        lines.append(f"  rationale: {axm.rationale}")
        if axm.references:
            lines.append(f"  references: {'; '.join(r.render() for r in axm.references)}")
        lines.append(f"  downstream dependents ({len(downstream)}): {', '.join(downstream) or '(none)'}")
        lines.append("")
    return envelope("\n".join(lines).rstrip(), basis_line(ctx.slices))


def view_reviews(ctx: Context, subject: str | None = None) -> str:
    """Every review recorded (DEF-review), newest first -- of a region, a node, a branch or a
    contract when `subject` names one -- with the latest of each link or measurement marked."""
    reviews = ctx.store.reviews()
    latest: dict[tuple, str] = {}
    for r in reviews:
        key = (r.get("region"), r.get("target")) if r.get("kind") == "link" else (r.get("branch"), r.get("contract"))
        latest[key] = r.get("id", "")
    shown = [r for r in reviews if not subject or subject in (r.get("region"), r.get("target"), r.get("branch"),
                                                                r.get("contract"))]
    lines = [f"Reviews ({len(shown)}" + (f" of {subject}" if subject else "") + f", of {len(reviews)} recorded)"
             f" -- {ctx.store.reviews_where()}", ""]
    if not shown:
        lines.append("None. review(<CODE-id>, note=...) records one after you read committed code against its claim; "
                     "review(<BRN-id>, target=<CTR-id>) one of a cited contract.")
    for r in reversed(shown):
        key = (r.get("region"), r.get("target")) if r.get("kind") == "link" else (r.get("branch"), r.get("contract"))
        what = (f"{r.get('region')} {r.get('relation', 'relates to')} {r.get('target')}" if r.get("kind") == "link"
                else f"{r.get('branch')} cites {r.get('contract')}")
        mark = "  [latest]" if latest.get(key) == r.get("id") else ""
        lines.append(f"{r.get('id')} {str(r.get('timestamp') or '')[:16]} {what} -- {r.get('outcome')} at "
                     f"{str(r.get('commit') or '')[:7]} by {r.get('actor') or '?'}{mark}")
        if r.get("note"):
            lines.append(f"    {r['note']}")
    return envelope("\n".join(lines).rstrip(), basis_line(ctx.slices))


def view_certificates(ctx: Context, subject: str | None = None) -> str:
    """Every Lean certificate recorded, newest first, as it reads now: certifying its node,
    failed, or set aside by a restatement (DEF-lean-certificate). The probe serves only the
    certifying one; this is where the rest are."""
    records = [r for r in ctx.store.certificates() if not subject or r.get("target_id") == subject]
    total = len(ctx.store.certificates())
    lines = [f"Lean certificates ({len(records)}" + (f" of {subject}" if subject else "") + f", of {total} recorded)"
             " -- a certificate moves no proof state; the probe serves the one certifying a node to its verifier",
             ""]
    if not records:
        lines.append("None. certify(<node id>, declaration=..., expected_statement=..., files=[...]) proves a "
                     "lemma or branch in Lean before its verifier pass.")
    for record in reversed(records):
        c = judge(ctx.dag, record)
        r = c.reading
        serving = ctx.certified.get(c.target_id)
        mark = "  [served]" if serving is not None and serving.id == c.id else ""
        lines.append(f"{c.id} {str(record.get('timestamp') or '')[:16]} {c.target_id} -- {c.state.upper()}"
                     f" ({c.service} {r.status}) by {record.get('actor') or '?'}{mark}")
        lines.append(f"    {c.declaration} : {' '.join(r.statement.split()) or '(no statement)'}")
        lines.append(f"    {r.reference or '?'} · {r.environment}")
        if c.why and c.state != CERTIFIED:
            lines.append("    " + "; ".join(c.why))
    return envelope("\n".join(lines).rstrip(), basis_line(ctx.slices))


def view_sources(ctx: Context) -> str:
    """The reference list: each declared source, its entry and the nodes that reference it, then
    the references naming no declared source. A reference is for the reader; it weighs nothing in
    a proof and no probe carries it (DEF-source-reference)."""
    decl = ctx.decl
    named = decl.referenced_by()
    dangling = sorted(sid for sid in named if sid not in decl.sources)
    if not decl.sources and not dangling:
        return envelope("No sources declared. A declaration may reference one: list it under sources: in "
                        "consistency.yaml and name it in the declaration's references: -- "
                        "{source: SRC-x, at: \"Thm 2\"}.", basis_line(ctx.slices))
    lines = [(f"Sources ({len(decl.sources)}) -- for the reader: a reference is no premise, no part of a "
              "fingerprint and never in a probe, and nothing here checks that a source says what a node "
              "referencing it states."), ""]
    for sid, src in sorted(decl.sources.items()):
        lines.append(sid)
        lines.append(f"  {src.entry()}")
        links = [address for _kind, _value, address in src.identifiers() if address]
        if links:
            lines.append(f"  at: {' '.join(links)}")
        if src.note:
            lines.append(f"  note: {src.note}")
        by = named.get(sid, [])
        lines.append("  referenced by: " + ("; ".join(f"{nid}" + (f" ({ref.at})" if ref.at else "")
                                                       for nid, ref in by) or "(nothing -- reported)"))
        lines.append("")
    if dangling:
        lines.append(f"Dangling references ({sum(len(named[s]) for s in dangling)}): no source with the id is declared")
        lines += [f"  {nid} -> {sid}" for sid in dangling for nid, _ref in named[sid]]
    return envelope("\n".join(lines).rstrip(), basis_line(ctx.slices))


def view_obligations(ctx: Context) -> str:
    # DOUBTED is open too: enough trials, too little consensus. Leaving it out made this list
    # shorter than the obligation count in its own basis line.
    open_obs = [s for s in ctx.slices if s.state in (OBLIGATION, UNGROUNDED, STALE, DOUBTED)]
    waiting = conditional_lines(ctx)
    if not open_obs:
        head = "No open proof obligations." + (" Nothing to probe; the conditional claims below wait on refuted "
                                               "premises, which only restating them can mend." if waiting else
                                               " All derived branches are verified or axiomatic.")
        return envelope("\n".join([head, *waiting]), basis_line(ctx.slices))

    lines = [f"Open Proof Obligations ({len(open_obs)}):", ""]
    for s in open_obs:
        lines.append(f"• {s.target_id} [{s.state.upper()}{' · STAGED' if s.staged else ''}]: {s.statement}")
        lines.append(f"    premises: {', '.join(s.premises) or '(none)'}")
        need = max(0, s.n_min - s.n_independent)
        lines.append(f"    progress: {s.n_independent}/{s.n_min} independent trials (need {need} more"
                     + (f"; untried: {', '.join(s.untried)}" if s.untried and need else "") + ")")
        if s.issues:
            lines.append(f"    blocker: {'; '.join(s.issues)}")
        lines.append("")
    lines.append('probe: status(view="probe") serves each obligation with its premises in full; '
                 'status(view="probe", subject=<id>) serves one.')
    lines += waiting
    return envelope("\n".join(lines).rstrip(), basis_line(ctx.slices))


def conditional_lines(ctx: Context) -> list[str]:
    """The claims whose own step is verified over a step that is not: proofs modulo a premise, as
    a Lean theorem over a lemma proved by sorry. None needs a probe of its own; each is proven
    again, with no new trial, once what it waits on is verified at the statement it read."""
    conditional = [s for s in ctx.slices if s.state == CONDITIONAL]
    if not conditional:
        return []
    lines = ["", f"Conditional ({len(conditional)}) -- own step verified, waiting on a step beneath it; "
                 "nothing to probe here:"]
    for s in conditional:
        lines.append(f"• {s.target_id}: waits on " + ", ".join(f"{a} ({state})" for a, state in s.waiting_on))
    return lines


def view_probe(ctx: Context, subject: str | None = None) -> str:
    """What a verifier reads, and all it reads: for each open obligation (or the one named), the
    claim, its premises with their statements, the derivation rule, the three strategies, and
    the one verify_step call that records them. Nothing here comes from the implementation."""
    slices = {s.target_id: s for s in ctx.slices}
    if subject:
        if ctx.decl.subject_known(subject):
            targets = sorted(nid for nid, n in ctx.dag.nodes.items()
                             if n.kind == "branch" and n.subject == subject)
            if not targets:
                return f"{subject} has no branch to probe; status(view=\"coverage\") says what governs it."
        elif ctx.dag.get(subject) is None:
            return f"unknown node {subject!r}"
        elif ctx.dag.get(subject).kind in ("axiom", "definition"):
            return f"{subject} is a root: it is declared, not verified. Probe a lemma or branch."
        else:
            targets = [subject]
    else:
        targets = [s.target_id for s in ctx.slices if s.state in OPEN_STATES]
        if not targets:
            return envelope("Nothing to probe: no lemma or branch is open. status(view=\"tree\") "
                            "shows what is proven and what is refuted.", basis_line(ctx.slices))

    blocks = []
    for target in targets:
        s = slices.get(target)
        status = slice_badge(s) if s else ""
        if s and s.state not in OPEN_STATES:
            status += (" -- already proven; a new pass re-verifies it" if s.state == PROVEN else
                       " -- its own step is verified; it waits on "
                       + ", ".join(f"{a} ({state})" for a, state in s.waiting_on) if s.state == CONDITIONAL else
                       " -- refuted; amend the trial or restate the claim before re-probing" if s.state == REFUTED
                       else " -- ungrounded; its premises must be declared first")
        elif s and s.untried:
            status += f" untried: {', '.join(s.untried)}"
        formal = probe_block(ctx.certified[target]) if target in ctx.certified else None
        blocks.append(probe_text(ctx.dag, target, status, formal))
    header = f"{len(targets)} probe(s). Judge each from its premises alone; record one verify_step per node."
    return envelope(header + "\n\n" + "\n\n".join(blocks), basis_line([slices[t] for t in targets if t in slices]))


def view_contradictions(ctx: Context) -> str:
    refuted = [s for s in ctx.slices if s.state == REFUTED]
    ungrounded = [s for s in ctx.slices if s.state == UNGROUNDED]
    gapped = [s for s in ctx.slices if s.gaps and s.state not in (REFUTED, UNGROUNDED, PROVEN)]
    # A verified step over a refuted or ungrounded premise: the step holds, and its ground does not.
    resting = [s for s in ctx.slices if s.state == CONDITIONAL
               and any(state in (REFUTED, UNGROUNDED) for _a, state in s.waiting_on)]

    if not refuted and not ungrounded and not gapped and not resting:
        return envelope("Zero contradictions, entailment gaps or ungrounded branches detected.",
                        basis_line(ctx.slices))

    lines = []
    if refuted:
        lines.append(f"Refuted Claims / Counterexamples ({len(refuted)}):")
        for s in refuted:
            lines.append(f"• {s.target_id}: {s.statement}")
            for cx in s.counterexamples:
                lines.append(f"    COUNTEREXAMPLE: {cx}")
        lines.append("")

    if gapped:
        lines.append(f"Entailment Gaps -- unproven, not refuted ({len(gapped)}):")
        for s in gapped:
            lines.append(f"• {s.target_id} [{s.state.upper()}]: {s.statement}")
            for gap in s.gaps:
                lines.append(f"    GAP: {gap}")
        lines.append("")

    if resting:
        lines.append(f"Resting on a Refuted or Ungrounded Premise -- own step verified, not proven ({len(resting)}):")
        for s in resting:
            lines.append(f"• {s.target_id}: {s.statement}")
            lines.append("    RESTS ON: " + ", ".join(f"{a} ({state})" for a, state in s.waiting_on
                                                       if state in (REFUTED, UNGROUNDED)))
        lines.append("")

    if ungrounded:
        lines.append(f"Ungrounded Branches ({len(ungrounded)}):")
        for s in ungrounded:
            lines.append(f"• {s.target_id}: {s.statement}")
            for iss in s.issues:
                lines.append(f"    ISSUE: {iss}")
        lines.append("")

    return envelope("\n".join(lines).rstrip(), basis_line(ctx.slices))


def view_coverage(ctx: Context) -> str:
    """Where the two ledgers meet: per component, the design declared over it.

    A component the repository implements with no declared branch is the prune-or-declare case;
    a component with a branch and no code is design running ahead of implementation, which is
    allowed and is reported as planned rather than as a gap.
    """
    decl = ctx.decl
    if decl.components_source != "git-HEAD":
        reason = {
            "none": "no belief.yaml at git HEAD in this repository",
            "unavailable": "component-belief is not installed alongside this server",
        }.get(decl.components_source, decl.components_source)
        return envelope(
            "Design coverage needs the component ledger, and it is not readable: " + reason + ".\n"
            "Declare components in belief.yaml and commit it; each branch's subject then names one.",
            "basis: consistency.yaml@" + decl.source + " × belief.yaml@none",
        )

    slices = {s.target_id: s for s in ctx.slices}
    beliefs = contract_beliefs(ctx.root)
    cited = re.compile(r"\bCTR-[A-Za-z0-9][A-Za-z0-9-]*\b")
    from .links import PinHistory
    head = git_head(ctx.root)
    measured = cited_measurements(decl, ctx.store.measurement_reviews(),
                                  PinHistory(ctx.root, head).translate if head else None)
    review = {(m.branch, m.contract): m for m in measured}
    designs: dict[str, list[str]] = {}
    removed: list[str] = []          # subject was a component id; belief.yaml no longer declares it
    unattached: list[str] = []       # subject is prose: the design was never bound to a component
    for nid, node in ctx.dag.nodes.items():
        if node.kind not in ("branch", "lemma") or not node.subject:
            continue
        if decl.subject_known(node.subject):
            designs.setdefault(node.subject, []).append(nid)
        elif COMPONENT_ID.fullmatch(node.subject) or BOUNDARY_ID.fullmatch(node.subject):
            removed.append(nid)
        else:
            unattached.append(nid)

    def line(nid: str) -> str:
        """The proof state, and the measurement standing behind it -- a claim is worth nothing
        while nothing measures it, so the two are printed together."""
        node = ctx.dag.nodes[nid]
        head = f"      {nid} {slice_badge(slices.get(nid))}"
        if node.kind != "branch":
            return head
        refs = sorted(set(cited.findall(node.derivation_rule or "")))
        if not refs:
            return head + "  · evidence: none cited"
        def state(r: str) -> str:
            m = review.get((nid, r))
            return "" if m is None else f" ({m.state})"
        return head + "  · " + "; ".join(f"{r} [{beliefs.get(r, 'not declared')}]{state(r)}" for r in refs)

    def declared_of(cid: str) -> list[str]:
        return [n for n in designs.get(cid, []) if not ctx.dag.nodes[n].staged]

    governed, undeclared, planned, bare = [], [], [], []
    for cid, comp in sorted(decl.components.items()):
        bucket = (governed if declared_of(cid) else undeclared) if comp.implemented else (
            planned if designs.get(cid) else bare)
        bucket.append(cid)

    def block(title: str, cids: list[str], *, show_code: bool) -> list[str]:
        if not cids:
            return []
        out = [f"{title} ({len(cids)}):"]
        for cid in cids:
            comp = decl.components[cid]
            facts = []
            if show_code:
                facts.append(f"{len(comp.code)} code path{'s' if len(comp.code) != 1 else ''}")
            if comp.contracts:
                facts.append(", ".join(comp.contracts))
            out.append(f"  {cid}" + (f"  [{' · '.join(facts)}]" if facts else ""))
            out += [line(n) for n in sorted(designs.get(cid, []))]
        out.append("")
        return out

    lines = [
        f"Design coverage: {len(decl.branches)} declared branches over "
        f"{len(decl.components)} components ({sum(1 for c in decl.components.values() if c.implemented)} implemented)",
        f"Source: consistency.yaml@{decl.source} × belief.yaml@{decl.components_source}",
        "",
    ]
    if decl.governs:
        lines += [f"consistency.yaml governs ({len(decl.governs)}): " + ", ".join(sorted(decl.governs)), ""]
    lines += block("governed -- code exists and a declared branch says why", governed, show_code=True)
    lines += block("undeclared design -- code exists, no declared branch (prune it, or declare the design)",
                   undeclared, show_code=True)
    lines += block("planned -- design declared, nothing implemented yet", planned, show_code=False)
    if bare:
        lines += [f"no design, no code claimed ({len(bare)}):", "  " + ", ".join(bare),
                  "  -- either planned (allowed) or built and unclaimed: a component whose code exists "
                  "claims it with code: in belief.yaml, and a design over it belongs here", ""]
    lines += _boundary_lines(decl, designs, line)
    lines += _requirement_lines(decl)
    def subject_block(title: str, ids: list[str]) -> list[str]:
        if not ids:
            return []
        out = [f"{title} ({len(ids)}):"]
        by_subject: dict[str, list[str]] = {}
        for nid in ids:
            by_subject.setdefault(ctx.dag.nodes[nid].subject, []).append(nid)
        for subject, nodes in sorted(by_subject.items()):
            out.append(f"  {subject[:70]}")
            out += [line(n) for n in sorted(nodes)]
        out.append("")
        return out

    lines += subject_block(
        "BROKEN -- the subject is gone from belief.yaml or goals.yaml; these designs govern "
        "nothing", removed)
    lines += subject_block(
        "unattached -- the subject is prose, not a component, interface or goal id", unattached)

    issues = [i for i in decl.issues
              if i.code in ("REMOVED_SUBJECT", "UNATTACHED_SUBJECT", "UNKNOWN_EVIDENCE", "UNKNOWN_GOAL",
                            "REMOVED_COMPONENT", "UNLISTED_SUBJECT", "MISSING_EVIDENCE",
                            "UNKNOWN_DEFINITION", "THRESHOLD_DRIFT")]
    if issues:
        lines += [f"link issues ({len(issues)}):", bullet(i.render() for i in issues), ""]
    lines += _measurement_lines(measured, uncited_by_kind(decl), beliefs)

    nxt = ("repoint or prune the designs whose component is gone" if removed else
           "declare or prune the undeclared designs" if undeclared else
           "attach every design to a component" if unattached else
           "every implemented component has a declared design")
    return envelope("\n".join(lines).rstrip(),
                    f"basis: consistency.yaml@{decl.source} × belief.yaml@{decl.components_source} · next: {nxt}")


def _measurement_lines(measured: list[CitedMeasurement], uncited: dict[str, list[str]],
                       beliefs: dict[str, str]) -> list[str]:
    """Cited measurements to re-read, and contracts no design cites (DEF-cited-measurement).

    A reviewed one whose branch was restated since, or whose review found it not aligned, is
    always listed; an unreviewed one only once the project reviews any, so a project that has not
    taken reviews up is not handed a list of every branch. A contract no branch cites is listed either way: it is measured, and no design says
    why that matters -- which may be right, for a plain regression measure."""
    out: list[str] = []
    stale = [m for m in measured if m.state in (NOT_REVIEWED, REVIEW_FAILED)]
    unreviewed = [m for m in measured if m.state == UNREVIEWED] if adopted_reviews(measured) else []
    if stale or unreviewed:
        out.append(f"cited measurements to re-read against their claims ({len(stale) + len(unreviewed)}):")
        for m in stale:
            out.append(f"  {m.branch} cites {m.contract}: {m.why} -- {m.fix}")
        for m in unreviewed:
            out.append(f"  {m.branch} cites {m.contract}, never reviewed -- {m.fix}")
        out.append("")
    total = sum(len(v) for v in uncited.values())
    if total:
        def named(ids: list[str]) -> str:
            return ", ".join(cid + (" (no evidence yet)" if beliefs.get(cid, "no evidence") == "no evidence"
                                    else "") for cid in ids)
        heads = {"component": "on components -- measured, and no design says why it matters: declare "
                              "the design, or keep it as a plain regression measure, knowingly",
                 "interface": "on interfaces -- a design claim over the interface would say why the "
                              "hand-over suffices",
                 "goal": "goal measures -- the goal's outcome says why they matter; a design claim on "
                         "the goal would say how it is met"}
        out.append(f"contracts no branch cites ({total}):")
        for kind, ids in uncited.items():
            if ids:
                out.append(f"  {heads.get(kind, kind)} ({len(ids)}): {named(ids)}")
        out.append("")
    return out


def _boundary_lines(decl: Declarations, designs: dict[str, list[str]], line: Any) -> list[str]:
    """The interfaces and goals, with the design claims over them.

    A component's design says why it works; an interface's, why the producer's guarantees suffice
    for its consumer; a goal's, why the system meets the outcome. Integration and validation are
    where a V-model checks those, and a boundary with no design claim is listed as one, not
    counted as a defect: the measure on it may be all it needs."""
    if not decl.boundaries:
        return []
    out: list[str] = []
    for kind, title in (("interface", "interfaces"), ("goal", "goals")):
        ids = sorted(b for b, ref in decl.boundaries.items() if ref.kind == kind)
        if not ids:
            continue
        claimed = [b for b in ids if designs.get(b)]
        out.append(f"{title} ({len(ids)}, {len(claimed)} with a design claim):")
        for bid in claimed:
            ref = decl.boundaries[bid]
            measure = f"  [{', '.join(ref.contracts)}]" if ref.contracts else "  [no contract]"
            out.append(f"  {bid}{measure}")
            out += [line(n) for n in sorted(designs[bid])]
        bare = [b for b in ids if not designs.get(b)]
        if bare:
            unmeasured = [b for b in bare if not decl.boundaries[b].contracts]
            out.append(f"  no design claim: {', '.join(bare)}")
            if unmeasured:
                out.append(f"  and no contract either: {', '.join(unmeasured)}")
        out.append("")
    return out


def _requirement_lines(decl: Declarations) -> list[str]:
    """Each requirement traced to the need it states: an axiom names the goal in goals.yaml whose
    requirement it is. One that names none is a requirement no need asked for -- or one whose
    need was never written down, which is the case worth seeing."""
    if not decl.goal_ids or not decl.axioms:
        return []
    by_goal: dict[str, list[str]] = {}
    for aid, axm in sorted(decl.axioms.items()):
        for goal in axm.goals:
            by_goal.setdefault(goal, []).append(aid)
    untraced = sorted(aid for aid, axm in decl.axioms.items() if not axm.goals)
    out = [f"requirements traced to goals ({len(decl.axioms) - len(untraced)} of {len(decl.axioms)} axioms):"]
    for gid in sorted(decl.goal_ids):
        out.append(f"  {gid}: {', '.join(by_goal.get(gid, [])) or 'no axiom states a requirement of it'}")
    if untraced:
        out.append(f"  tracing to no goal: {', '.join(untraced)}")
    out.append("")
    return out


def view_component_audit(ctx: Context, component_id: str) -> str:
    """What a component's designs rest on.

    Axioms, definitions and lemmas carry no subject -- they are the ground every design shares --
    so a component reaches them only through its branches. This walks that closure: the branches
    that govern the component, everything they rest on, and which other components rest on the
    same ground, which is what a restatement there would disturb.
    """
    branches = sorted(nid for nid, n in ctx.dag.nodes.items() if n.subject == component_id)
    if not branches:
        return (f"{component_id} has no branch: no design is declared over it, so it rests on no "
                "axiom. status(view=\"coverage\") lists it under undeclared design or planned.")

    slices = {s.target_id: s for s in ctx.slices}
    ground: dict[str, list[str]] = {}
    for bid in branches:
        for anc in ctx.dag.ancestors(bid):
            ground.setdefault(anc, []).append(bid)

    def others_on(node_id: str) -> list[str]:
        return sorted({n.subject for d in ctx.dag.descendants(node_id)
                       if (n := ctx.dag.nodes[d]).kind == "branch"
                       and ctx.decl.subject_known(n.subject) and n.subject != component_id})

    comp = ctx.decl.components.get(component_id)
    lines = [f"What {component_id} rests on"]
    if comp:
        lines.append(f"  {len(comp.code)} code path(s)"
                     + (f" · contracts: {', '.join(comp.contracts)}" if comp.contracts else " · no contract"))
        scored = [(cid, d) for cid, (_r, d) in sorted(comp.rules.items()) if d]
        if scored:
            lines.append("  contracts scoring a definition: "
                         + ", ".join(f"{cid} -> {d}" for cid, d in scored))
    lines.append("")
    lines.append(f"branches governing it ({len(branches)}):")
    lines += [f"  {bid} {slice_badge(slices.get(bid))}" for bid in branches]

    for kind, title in (("axiom", "axioms"), ("definition", "definitions"), ("lemma", "lemmas")):
        ids = sorted(i for i in ground if ctx.dag.nodes[i].kind == kind)
        if not ids:
            continue
        lines += ["", f"{title} it rests on ({len(ids)}):"]
        for nid in ids:
            via = ", ".join(sorted(set(ground[nid])))
            shared = others_on(nid)
            tail = f"  [also: {', '.join(shared)}]" if shared else "  [only this component]"
            lines.append(f"  {nid}{tail}")
            lines.append(f"      via {via}")

    unused = sorted(i for i, n in ctx.dag.nodes.items()
                    if n.kind in ("axiom", "definition") and i not in ground
                    and not ctx.dag.descendants(i))
    if unused:
        lines += ["", f"declared and reached by nothing at all ({len(unused)}): " + ", ".join(unused)]
    return envelope("\n".join(lines), basis_line(ctx.slices))


def view_audit(ctx: Context, subject: str | None = None) -> str:
    if not subject:
        return ("Supply subject=<node_id> for a blast radius, or subject=<CMP-id> for what a "
                "component's designs rest on.")
    if ctx.decl.subject_known(subject):
        return view_component_audit(ctx, subject)

    node = ctx.dag.get(subject)
    if not node:
        return f"Unknown node {subject!r}"

    radius = ctx.dag.blast_radius(subject)
    ancestors = sorted(ctx.dag.ancestors(subject))

    lines = [
        f"Audit Report for {subject} [{node.kind.upper()}]:",
        f"Statement: {node.statement}",
        f"Transitive Premises ({len(ancestors)}): {', '.join(ancestors) or '(root/none)'}",
        f"Downstream Blast Radius ({len(radius)} nodes invalidated if modified):",
    ]
    if radius:
        lines.append(bullet(radius))
    else:
        lines.append("  (Leaf node — no downstream dependents)")

    return envelope("\n".join(lines), basis_line(ctx.slices))


def view_cycle(ctx: Context) -> dict[str, Any]:
    return {
        "nodes": {
            nid: {
                "kind": n.kind,
                "statement": n.statement,
                "premises": list(n.premises),
                "derivation_rule": n.derivation_rule,
            }
            for nid, n in ctx.dag.nodes.items()
        },
        "slices": [
            {
                "target_id": s.target_id,
                "kind": s.kind,
                "state": s.state,
                "n_trials": s.n_trials,
                "n_passed": s.n_passed,
                "n_min": s.n_min,
                "counterexamples": s.counterexamples,
                "gaps": s.gaps,
                "issues": s.issues,
                "staged": s.staged,
                "n_superseded": s.n_superseded,
                "n_stale": s.n_stale,
                "waiting_on": [list(w) for w in s.waiting_on],
                "certified_by": s.certified_by,
            }
            for s in ctx.slices
        ],
        "open_obligations_count": sum(1 for s in ctx.slices if s.state == OBLIGATION),
        "refuted_count": sum(1 for s in ctx.slices if s.state == REFUTED),
        "proven_count": sum(1 for s in ctx.slices if s.state == PROVEN),
        "conditional_count": sum(1 for s in ctx.slices if s.state == CONDITIONAL),
    }
