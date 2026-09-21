"""Views for consistency-belief: status reports across proof dimensions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .declarations import Declarations, load as load_declarations
from .graph import ProofDAG
from .model import PROVEN, REFUTED, OBLIGATION, STALE, UNGROUNDED, ConsistencySlice, compute_consistency
from .render import basis_line, bullet, envelope, render_ascii_dag, slice_badge
from .store import Store

VIEWS = ("tree", "branches", "axioms", "obligations", "contradictions", "audit", "cycle")


@dataclass
class Context:
    root: Path
    store: Store
    decl: Declarations
    dag: ProofDAG
    slices: list[ConsistencySlice]

    @classmethod
    def build(cls, root: Path, staged_nodes: list[Any] | None = None) -> Context:
        store = Store(root)
        decl = load_declarations(root)
        dag = ProofDAG.from_declarations(decl)

        # Merge staged nodes if any
        if staged_nodes:
            for n in staged_nodes:
                dag.add_node(n)

        trials = store.effective_trials()
        slices = compute_consistency(dag, trials)
        return cls(root=root, store=store, decl=decl, dag=dag, slices=slices)


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
    header = [
        f"Proof DAG: {len(ctx.dag.nodes)} nodes ({len(ctx.decl.axioms)} axioms, "
        f"{len(ctx.decl.lemmas)} lemmas, {len(ctx.decl.branches)} branches)",
        f"Source: {ctx.decl.source}{' [PENDING UNCOMMITTED EDITS]' if ctx.decl.pending else ''}",
        "",
    ]
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
        if s.issues:
            lines.append(f"  issues: {'; '.join(s.issues)}")
        lines.append(f"  verification trials: {s.n_passed}/{s.n_trials} passed (n_min={s.n_min}, set={s.set_handle})")
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
        lines.append(f"• {s.target_id} [{s.state.upper()}]: {s.statement}")
        lines.append(f"    premises: {', '.join(s.premises) or '(none)'}")
        lines.append(f"    progress: {s.n_trials}/{s.n_min} trials (need {max(0, s.n_min - s.n_trials)} more)")
        if s.issues:
            lines.append(f"    blocker: {'; '.join(s.issues)}")
        lines.append("")
    return envelope("\n".join(lines).rstrip(), basis_line(ctx.slices))


def view_contradictions(ctx: Context) -> str:
    refuted = [s for s in ctx.slices if s.state == REFUTED]
    ungrounded = [s for s in ctx.slices if s.state == UNGROUNDED]

    if not refuted and not ungrounded:
        return envelope("Zero contradictions or ungrounded branches detected.", basis_line(ctx.slices))

    lines = []
    if refuted:
        lines.append(f"Refuted Claims / Counterexamples ({len(refuted)}):")
        for s in refuted:
            lines.append(f"• {s.target_id}: {s.statement}")
            for cx in s.counterexamples:
                lines.append(f"    COUNTEREXAMPLE: {cx}")
        lines.append("")

    if ungrounded:
        lines.append(f"Ungrounded Branches ({len(ungrounded)}):")
        for s in ungrounded:
            lines.append(f"• {s.target_id}: {s.statement}")
            for iss in s.issues:
                lines.append(f"    ISSUE: {iss}")
        lines.append("")

    return envelope("\n".join(lines).rstrip(), basis_line(ctx.slices))


def view_audit(ctx: Context, subject: str | None = None) -> str:
    if not subject:
        return "Supply subject=<node_id> to compute topological blast radius and downstream dependencies."

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
                "issues": s.issues,
            }
            for s in ctx.slices
        ],
        "open_obligations_count": sum(1 for s in ctx.slices if s.state == OBLIGATION),
        "refuted_count": sum(1 for s in ctx.slices if s.state == REFUTED),
        "proven_count": sum(1 for s in ctx.slices if s.state == PROVEN),
    }
