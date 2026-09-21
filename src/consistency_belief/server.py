"""FastMCP server for consistency-belief: axiomatic proof consistency for architectures and planning."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from .decide import ADOPT, active_policy, evaluate_consistency_policy
from .graph import ProofNode
from .model import compute_consistency
from .probes import STRATEGIES, STRATEGY_COUNTEREXAMPLE, build_probe_prompt, parse_probe_result
from .render import basis_line, bullet, envelope
from .store import Store
from .views import (
    VIEWS,
    Context,
    no_declarations_next,
    view_audit,
    view_axioms,
    view_branches,
    view_contradictions,
    view_cycle,
    view_no_declarations,
    view_obligations,
    view_tree,
)

INSTRUCTIONS = """\
Deductive, axiom-to-branch design consistency for LLM planning and architectures.

Axioms, definitions, and policies live in a checked-in consistency.yaml and load
from git HEAD, not the working tree — editing that file changes nothing until a human commits it.

The loop: status(view="obligations") -> verify_step(...) -> status(view="tree").

Four rules:
1. Every component, contract, and change must ground transitively in declared Axioms.
2. Verification trials are falsifiable probes (counterexample search, entailment, negation) — never ungrounded assertion.
3. Mutating an upstream node invalidates its downstream blast radius as STALE until re-verified.
4. Escalate to the human for decide(), never approve on their behalf.
"""

mcp = FastMCP("consistency-belief", instructions=INSTRUCTIONS)


def project_root() -> Path:
    return Path(os.environ.get("CONSISTENCY_PROJECT_ROOT", os.environ.get("BELIEF_PROJECT_ROOT", os.getcwd()))).resolve()


def _actor() -> str:
    return os.environ.get("CONSISTENCY_ACTOR", os.environ.get("BELIEF_ACTOR", "agent"))


@mcp.tool()
def status(
    view: str = "tree",
    subject: str | None = None,
    policy: str | None = None,
) -> str:
    """Read the proof and consistency state.

    view:
      tree           - ASCII proof DAG showing Axioms -> Lemmas -> Branches with proof badges
      branches       - detailed status per branch: claim, premises, axiomatic roots, trial counts
      axioms         - root axioms, domains, and lists of all downstream dependents
      obligations    - open proof obligations (Lean-style `sorry`s) needing verification
      contradictions - refuted claims, discovered counterexamples, or ungrounded branches
      audit          - blast radius report for a given subject (nodes invalidated if modified)
      cycle          - full state as structured JSON
    """
    root = project_root()
    ctx = Context.build(root)
    if view not in VIEWS:
        return f"unknown view {view!r}; expected one of {', '.join(VIEWS)}"
    if ctx.decl.source == "none" and view not in ("axioms",):
        return view_no_declarations(ctx, view)

    if view == "tree":
        return view_tree(ctx)
    if view == "branches":
        return view_branches(ctx, subject)
    if view == "axioms":
        return view_axioms(ctx)
    if view == "obligations":
        return view_obligations(ctx)
    if view == "contradictions":
        return view_contradictions(ctx)
    if view == "audit":
        return view_audit(ctx, subject)
    if view == "cycle":
        return json.dumps(view_cycle(ctx), indent=2, default=str)

    return view_tree(ctx)


@mcp.tool()
def propose_branch(
    id: str,
    subject: str,
    premises: list[str],
    claim: str,
    rationale: str,
    branch_type: str = "contract",
) -> str:
    """Propose a new component contract, lemma, or architectural change.

    The server checks acyclicity and verifies that all premises are recognized
    nodes in the graph. If valid, the branch is staged as an open proof obligation.
    """
    root = project_root()
    ctx = Context.build(root)

    node = ProofNode(
        id=id,
        kind="branch" if branch_type == "contract" else "lemma",
        statement=claim,
        premises=list(premises),
        derivation_rule=rationale,
        subject=subject,
    )
    errors = ctx.dag.add_node(node)
    if errors:
        return f"rejected proposal {id!r}:\n" + bullet(errors)

    ctx.store.append_event("propose_branch", {
        "id": id,
        "subject": subject,
        "premises": premises,
        "claim": claim,
        "rationale": rationale,
        "branch_type": branch_type,
    }, actor=_actor())

    grounded, ground_issues = ctx.dag.is_grounded(id)
    ground_status = "GROUNDED" if grounded else f"UNGROUNDED ({'; '.join(ground_issues)})"

    return envelope(
        f"Branch {id} proposed on subject {subject!r} [{ground_status}].\n"
        f"Premises: {', '.join(premises)}\n"
        f"Claim: {claim}\n"
        f"Next: call verify_step({id!r}) to run falsification probes.",
        basis_line(ctx.slices)
    )


@mcp.tool()
def verify_step(
    target_id: str,
    strategy: str = "counterexample",
    outcome: str = "sound",
    rationale: str = "",
    counterexample: str | None = None,
    repro: dict[str, Any] | None = None,
) -> str:
    """Record an LLM verification probe trial against a branch or lemma.

    This is how consistency is measured: via falsifiable adversarial trials
    (counterexample search, entailment gap detection, or negation symmetry).

    target_id:      the lemma or branch being verified.
    strategy:       "counterexample" | "entailment" | "negation" | "contradiction".
    outcome:        "sound" | "falsified" | "gap" | "inconclusive".
    counterexample: concrete counter-scenario if falsified, otherwise null.
    repro:          reproducibility metadata (e.g. {"model": "gemini", "seed": 42}).
    """
    root = project_root()
    ctx = Context.build(root)
    node = ctx.dag.get(target_id)
    if not node:
        return f"unknown target {target_id!r}"

    if strategy not in STRATEGIES:
        return f"unknown strategy {strategy!r}; expected one of {', '.join(STRATEGIES)}"

    # Normalize passed flag
    parsed = parse_probe_result({
        "outcome": outcome,
        "counterexample": counterexample,
        "reasoning": rationale,
    })

    trial_record = {
        "target_id": target_id,
        "strategy": strategy,
        "outcome": parsed["outcome"],
        "passed": parsed["passed"],
        "counterexample": parsed["counterexample"],
        "reasoning": parsed["reasoning"],
        "repro": repro or {"actor": _actor()},
        "validity": "valid",
    }

    trial_id = ctx.store.append_trial(trial_record)
    ctx.store.append_event("verify_step", {
        "target_id": target_id,
        "trial_id": trial_id,
        "passed": parsed["passed"],
        "strategy": strategy,
    }, actor=_actor())

    # Recompute updated context
    fresh = Context.build(root)
    target_slice = next((s for s in fresh.slices if s.target_id == target_id), None)
    slice_line = f"{target_id} [{target_slice.state.upper()}] {target_slice.n_passed}/{target_slice.n_trials} trials" if target_slice else target_id

    lines = [
        f"Trial {trial_id} recorded for {target_id} (strategy={strategy}, outcome={parsed['outcome']}).",
        f"Updated status: {slice_line}",
    ]
    if parsed["counterexample"]:
        lines.append(f"FALSIFIED: counterexample recorded: {parsed['counterexample']}")

    return envelope("\n".join(lines), basis_line(fresh.slices))


@mcp.tool()
def audit_change(
    target_id: str,
    proposed_statement: str = "",
    proposed_premises: list[str] | None = None,
    reason: str = "",
) -> str:
    """Calculate the blast radius of modifying or invalidating an axiom or branch.

    Reports all downstream lemmas, contracts, and components that will be marked STALE
    and require re-verification if the change is executed.
    """
    root = project_root()
    ctx = Context.build(root)
    node = ctx.dag.get(target_id)
    if not node:
        return f"unknown node {target_id!r}"

    blast = ctx.dag.blast_radius(target_id)
    anc = sorted(ctx.dag.ancestors(target_id))

    lines = [
        f"Blast radius analysis for modifying {target_id} [{node.kind.upper()}]:",
        f"Current: {node.statement}",
    ]
    if proposed_statement:
        lines.append(f"Proposed: {proposed_statement}")
    if reason:
        lines.append(f"Reason: {reason}")

    lines.append(f"Upstream premises ({len(anc)}): {', '.join(anc) or '(none)'}")
    lines.append(f"Downstream blast radius ({len(blast)} nodes will become STALE):")
    if blast:
        lines.append(bullet(blast))
    else:
        lines.append("  (Zero downstream dependents)")

    return envelope("\n".join(lines), basis_line(ctx.slices))


@mcp.tool()
def note(subject: str, text: str) -> str:
    """Record qualitative engineering notes or commentary.

    Inert channel: stored with provenance=asserted. Does NOT count towards
    proof obligations or verification trial sufficiency.
    """
    root = project_root()
    ctx = Context.build(root)
    rec = ctx.store.append_note(subject, text, actor=_actor())
    ctx.store.append_event("note", {"subject": subject}, actor=_actor())
    return envelope(
        f"Note recorded on {subject} at {rec['timestamp']}.\n"
        f"provenance=asserted — inert channel, zero proof weight.",
        "basis: assumption · qualitative annotation · no verification trial created"
    )


@mcp.tool()
def decide(
    change_id: str,
    policy_id: str | None = None,
    approver: str | None = None,
) -> str:
    """Evaluate architectural and design consistency against declared policies.

    Accepts or rejects a proposed design change. If ADOPT, requires a human approver.
    """
    root = project_root()
    ctx = Context.build(root)
    policy = active_policy(ctx.decl, policy_id)
    if not policy:
        return "no consistency policy declared in consistency.yaml at git HEAD"

    verdict = evaluate_consistency_policy(ctx.dag, policy, ctx.slices, target_id=change_id if ctx.dag.get(change_id) else None)

    needs_approval = verdict.status == ADOPT
    if needs_approval and not approver:
        body = (
            f"ADOPT — NOT RECORDED: this outcome requires a human approver.\n"
            f"All proof obligations are closed and grounded in axioms.\n"
            f"Call decide() again with approver=<name> after human review."
        )
    else:
        rec = ctx.store.append_decision({
            "change_id": change_id,
            "status": verdict.status,
            "policy_id": policy.id,
            "approver": approver,
            "trial_ids": verdict.trial_ids,
            "reasons": verdict.reasons,
        })
        ctx.store.append_event("decide", {
            "change_id": change_id,
            "status": verdict.status,
            "approver": approver,
        }, actor=_actor())
        body = f"{verdict.status.upper()} recorded as {rec['id']} under policy {policy.id}"

    lines = [body]
    if verdict.reasons:
        lines += ["", "reasons:", bullet(verdict.reasons)]
    if verdict.refutations:
        lines += ["", "refutations:", bullet(verdict.refutations)]
    if verdict.obligations:
        lines += ["", "open obligations:", bullet(verdict.obligations)]

    return envelope("\n".join(lines), basis_line(ctx.slices) + f" · policy {policy.id}")


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
