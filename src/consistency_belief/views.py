"""Views for consistency-belief: status reports across proof dimensions."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .declarations import COMPONENT_ID, Declarations, contract_beliefs, load as load_declarations
from .graph import ProofDAG, ProofNode
from .model import PROVEN, REFUTED, OBLIGATION, STALE, UNGROUNDED, ConsistencySlice, compute_consistency
from .render import basis_line, bullet, envelope, render_ascii_dag, slice_badge
from .store import Store

VIEWS = ("tree", "branches", "axioms", "obligations", "contradictions", "coverage", "audit", "cycle")


@dataclass
class Context:
    root: Path
    store: Store
    decl: Declarations
    dag: ProofDAG
    slices: list[ConsistencySlice]
    staged_issues: list[str] = field(default_factory=list)

    @classmethod
    def build(cls, root: Path, staged_nodes: list[Any] | None = None) -> Context:
        store = Store(root)
        decl = load_declarations(root)
        dag = ProofDAG.from_declarations(decl)

        staged = [staged_node(p) for p in store.staged_proposals() if p["id"] not in dag.nodes]
        staged_issues = _add_in_dependency_order(dag, staged + list(staged_nodes or []))

        trials = store.effective_trials()
        slices = compute_consistency(dag, trials)
        return cls(root=root, store=store, decl=decl, dag=dag, slices=slices, staged_issues=staged_issues)


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


def view_tree(ctx: Context) -> str:
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
    header.append("")
    tree_text = render_ascii_dag(ctx.dag, ctx.slices)
    return envelope("\n".join(header) + "\n" + tree_text, basis_line(ctx.slices))


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
        lines.append(f"  verification trials: {s.n_passed}/{s.n_trials} passed (n_min={s.n_min}, set={s.set_handle})")
        if s.n_superseded or s.n_stale:
            lines.append(f"  not counted: {s.n_superseded} verified an earlier statement, "
                         f"{s.n_stale} predate a restated premise")
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
        lines.append(f"  downstream dependents ({len(downstream)}): {', '.join(downstream) or '(none)'}")
        lines.append("")
    return envelope("\n".join(lines).rstrip(), basis_line(ctx.slices))


def view_obligations(ctx: Context) -> str:
    open_obs = [s for s in ctx.slices if s.state in (OBLIGATION, UNGROUNDED, STALE)]
    if not open_obs:
        return envelope("No open proof obligations. All derived branches are verified or axiomatic.", basis_line(ctx.slices))

    lines = [f"Open Proof Obligations ({len(open_obs)}):", ""]
    for s in open_obs:
        lines.append(f"• {s.target_id} [{s.state.upper()}{' · STAGED' if s.staged else ''}]: {s.statement}")
        lines.append(f"    premises: {', '.join(s.premises) or '(none)'}")
        lines.append(f"    progress: {s.n_trials}/{s.n_min} trials (need {max(0, s.n_min - s.n_trials)} more)")
        if s.issues:
            lines.append(f"    blocker: {'; '.join(s.issues)}")
        lines.append("")
    return envelope("\n".join(lines).rstrip(), basis_line(ctx.slices))


def view_contradictions(ctx: Context) -> str:
    refuted = [s for s in ctx.slices if s.state == REFUTED]
    ungrounded = [s for s in ctx.slices if s.state == UNGROUNDED]
    gapped = [s for s in ctx.slices if s.gaps and s.state not in (REFUTED, UNGROUNDED, PROVEN)]

    if not refuted and not ungrounded and not gapped:
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
    designs: dict[str, list[str]] = {}
    removed: list[str] = []          # subject was a component id; belief.yaml no longer declares it
    unattached: list[str] = []       # subject is prose: the design was never bound to a component
    for nid, node in ctx.dag.nodes.items():
        if node.kind not in ("branch", "lemma") or not node.subject:
            continue
        if node.subject in decl.components:
            designs.setdefault(node.subject, []).append(nid)
        elif COMPONENT_ID.fullmatch(node.subject):
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
        return head + "  · " + "; ".join(f"{r} [{beliefs.get(r, 'not declared')}]" for r in refs)

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
        lines += [f"no design, no code ({len(bare)}):", "  " + ", ".join(bare), ""]
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
        "BROKEN -- the component is gone from belief.yaml; these designs govern nothing", removed)
    lines += subject_block(
        "unattached -- the subject is prose, not a component id", unattached)

    issues = [i for i in decl.issues
              if i.code in ("REMOVED_SUBJECT", "UNATTACHED_SUBJECT", "UNKNOWN_EVIDENCE",
                            "REMOVED_COMPONENT", "UNLISTED_SUBJECT", "MISSING_EVIDENCE",
                            "UNKNOWN_DEFINITION", "THRESHOLD_DRIFT")]
    if issues:
        lines += [f"link issues ({len(issues)}):", bullet(i.render() for i in issues), ""]

    nxt = ("repoint or prune the designs whose component is gone" if removed else
           "declare or prune the undeclared designs" if undeclared else
           "attach every design to a component" if unattached else
           "every implemented component has a declared design")
    return envelope("\n".join(lines).rstrip(),
                    f"basis: consistency.yaml@{decl.source} × belief.yaml@{decl.components_source} · next: {nxt}")


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
                       and n.subject in ctx.decl.components and n.subject != component_id})

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
    if subject in ctx.decl.components:
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
            }
            for s in ctx.slices
        ],
        "open_obligations_count": sum(1 for s in ctx.slices if s.state == OBLIGATION),
        "refuted_count": sum(1 for s in ctx.slices if s.state == REFUTED),
        "proven_count": sum(1 for s in ctx.slices if s.state == PROVEN),
    }
