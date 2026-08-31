"""MCP server — six tools.

Note what is absent: there is no tool that writes a belief. That is not an
oversight to be fixed later, it is the design (10.4). An agent's only route to
moving a posterior is to declare a test that produces the number and let the
server run it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from .decide import ADOPT, ROLLBACK, active_policy, evaluate_policy
from .model import compute_slices
from .render import basis_line, bullet, envelope
from .runner import run_test as execute_test
from .store import VALIDITY, Store
from .views import (
    VIEWS,
    Context,
    view_belief,
    view_coverage,
    view_cycle,
    view_diagnose,
    view_graph,
    view_plan,
    view_trace,
)

INSTRUCTIONS = """\
Evidence-grounded belief state for a system graph.

Declarations (components, interfaces, contracts, tests, priors, policies) live
in a checked-in belief.yaml and load from git HEAD, not the working tree —
editing that file changes nothing until a human commits it.

The loop: status(view="diagnose") -> run_test(...) -> status(view="belief").

Four rules: diagnose before optimising; never report a result you did not
obtain through run_test or ingest; "insufficient" is an answer, report it as
one; escalate to the human for decide(), never approve on their behalf.
"""

mcp = FastMCP("component-belief", instructions=INSTRUCTIONS)


def project_root() -> Path:
    return Path(os.environ.get("BELIEF_PROJECT_ROOT", os.getcwd())).resolve()


def _actor() -> str:
    return os.environ.get("BELIEF_ACTOR", "agent")


@mcp.tool()
def status(
    view: str = "belief",
    subject: str | None = None,
    since: str | None = None,
    set: str | None = None,
    budget: float | None = None,
    policy: str | None = None,
) -> str:
    """Read the current state. Every read the server offers lives here.

    view:
      graph     - components, interfaces, unbacked assumptions, declaration issues
      coverage  - evidence validity/provenance tallies, test versions, uncovered contracts
      belief    - one line per belief slice with its state, interval, and n
      diagnose  - ranked bottlenecks, discriminating test, coverage limits
      plan      - tests to run this round, and every test skipped with its reason
      cycle     - the full evaluation-cycle report as JSON, with complete chains
      trace     - expand a `set=` citation handle into its exact evidence records

    subject: a component or contract id to narrow to (or a RUN- id for diagnose).
    set:     the citation handle from a `basis:` line, for view="trace".
    budget:  cost ceiling for view="plan".
    """
    root = project_root()
    ctx = Context.build(root)
    if view not in VIEWS:
        return f"unknown view {view!r}; expected one of {', '.join(VIEWS)}"
    if view == "graph":
        return view_graph(ctx, since)
    if view == "coverage":
        return view_coverage(ctx)
    if view == "diagnose":
        return view_diagnose(ctx, subject, policy)
    if view == "plan":
        return view_plan(ctx, budget, policy)
    if view == "trace":
        return view_trace(ctx, set, subject)
    if view == "cycle":
        return json.dumps(view_cycle(ctx, policy), indent=2, default=str)
    return view_belief(ctx, subject, since)


@mcp.tool()
def run_test(
    test_id: str,
    conditions: dict[str, Any] | None = None,
    repro: dict[str, Any] | None = None,
) -> str:
    """Run a declared test and record its trials as measured evidence.

    The server executes the command and captures the artifact itself; nothing
    is transcribed. The command may write structured trials to $OUT as
    {"trials": [{"metrics": {...}, "conditions": {...}}]}; if it does not, one
    trial is synthesised from the exit code.

    conditions: captured metadata for bucketing, e.g. {"lighting": "low"}.
    repro:      reproducibility fields, e.g. {"model_revision": "v3", "seed": 7}.
    """
    root = project_root()
    ctx = Context.build(root)
    test = ctx.decl.tests.get(test_id)
    if test is None:
        known = ", ".join(sorted(ctx.decl.tests)) or "(none declared at git HEAD)"
        return f"unknown test {test_id!r}. Declared tests: {known}"
    if not test.run:
        return f"{test_id} has no run command"

    result = execute_test(root, ctx.store, ctx.decl, test, conditions, repro, actor=_actor())

    fresh = Context.build(root)
    slices = compute_slices(fresh.decl, fresh.trials(), result["contracts"])
    lines = [
        f"{result['run_id']} {result['test']} exit={result['exit_code']} "
        f"trials={result['n_trials']} records={result['n_records']}",
        f"outcomes: {result['outcome_counts']}",
        f"artifact: {result['artifact_uri']} sha={result['artifact_hash']}",
    ]
    if result["synthesized_from_exit_code"]:
        lines.append(
            "note: no $OUT file — one trial synthesised from the exit code. "
            "Contracts needing declared metrics will exclude it rather than score it."
        )
    if not result["contracts"]:
        lines.append(
            "warning: no scorable contract lists this test in evaluable_by, "
            "so nothing was recorded against a belief."
        )
    if slices:
        from .render import slice_line
        lines += ["", "updated:"] + [slice_line(s) for s in slices]
    return envelope("\n".join(lines), basis_line(slices))


@mcp.tool()
def ingest(
    records: list[dict[str, Any]],
    source: str,
    artifact_uri: str,
) -> str:
    """Import belief-eligible evidence produced outside this server (CI,
    telemetry, a robot log).

    Each record needs: contract_id, test_id, outcome, metrics, and a repro
    block. Records missing required fields are rejected rather than stored
    partially, because a record you cannot compare is not evidence (3.4).
    """
    root = project_root()
    ctx = Context.build(root)
    if not artifact_uri:
        return "rejected: artifact_uri is required for imported evidence"

    required = ("contract_id", "test_id", "outcome")
    accepted, rejected = [], []
    run_id = ctx.store.next_run_id()

    for index, record in enumerate(records):
        missing = [f for f in required if not record.get(f)]
        contract = ctx.decl.contracts.get(record.get("contract_id", ""))
        if contract is None:
            missing.append("contract_id (not declared)")
        elif not ctx.decl.is_scorable(contract.id):
            missing.append(f"contract_id ({contract.id} is not scorable)")
        if not isinstance(record.get("repro"), dict):
            missing.append("repro")
        if missing:
            rejected.append(f"record {index}: missing {', '.join(missing)}")
            continue
        accepted.append({
            "subject": contract.subject,
            "contract_id": contract.id,
            "test_id": record["test_id"],
            "test_ref": record.get("test_ref", record["test_id"]),
            "run_id": record.get("run_id", run_id),
            "system_version": record.get("repro", {}).get("sw_revision", ""),
            "provenance": "imported",
            "source_system": source,
            "outcome": record["outcome"],
            "metrics": record.get("metrics", {}),
            "conditions": {"raw": record.get("conditions", {})},
            "repro": record["repro"],
            "validity": "valid",
            "artifact_uri": artifact_uri,
            "artifact_hash": record.get("artifact_hash", ""),
        })

    ids = ctx.store.append_trials(accepted) if accepted else []
    ctx.store.append_event("ingest", {
        "source": source, "accepted": len(ids), "rejected": len(rejected), "run_id": run_id,
    }, actor=_actor())

    lines = [f"ingested {len(ids)} record(s) from {source!r} as provenance=imported"]
    if rejected:
        lines += ["", "rejected:", bullet(rejected)]
    fresh = Context.build(root)
    slices = compute_slices(fresh.decl, fresh.trials(),
                            sorted({r["contract_id"] for r in accepted}) or None)
    return envelope("\n".join(lines), basis_line(slices))


@mcp.tool()
def note(subject: str, text: str) -> str:
    """Record a qualitative observation.

    This is the sanctioned channel for engineering judgement (4.5) — hunches,
    context, "this looked jittery on the bench". It is stored with
    provenance=asserted and NO belief model can read it. It will never move a
    posterior, by construction. If you want a number counted, declare a test
    that produces it and run it.
    """
    ctx = Context.build(project_root())
    record = ctx.store.append_note(subject, text, actor=_actor())
    ctx.store.append_event("note", {"subject": subject}, actor=_actor())
    return envelope(
        f"annotation recorded on {subject} at {record['timestamp']}\n"
        f"provenance=asserted — not belief-eligible, will not move any posterior",
        "basis: assumption · annotation channel · no evidence created",
    )


@mcp.tool()
def amend(
    evidence_id: str,
    validity: str | None = None,
    supersede_with: str | None = None,
    reason: str = "",
) -> str:
    """Correct an evidence record without editing it.

    Appends an amendment that folds over the original (3.3); the trial as first
    recorded stays in the ledger with the reason it was reclassified. Validity
    is orthogonal to outcome (3.6) — a trial that failed because the rig was
    mis-calibrated is outcome=fail, validity=invalid, and is not evidence
    against the component.
    """
    ctx = Context.build(project_root())
    if validity and validity not in VALIDITY:
        return f"validity must be one of {', '.join(VALIDITY)}"
    if not validity and not supersede_with:
        return "supply validity= or supersede_with="
    if not reason:
        return "reason is required: an unexplained reclassification is not auditable"
    known = {t.get("id") for t in ctx.store.effective_trials()}
    if evidence_id not in known:
        return f"unknown evidence id {evidence_id!r}"

    ctx.store.append_amendment(
        evidence_id, validity=validity, supersede_with=supersede_with,
        reason=reason, actor=_actor(),
    )
    ctx.store.append_event("amend", {
        "target": evidence_id, "validity": validity, "supersede_with": supersede_with,
    }, actor=_actor())

    fresh = Context.build(project_root())
    slices = compute_slices(fresh.decl, fresh.trials())
    return envelope(
        f"amended {evidence_id}: validity={validity or 'superseded'} — {reason}\n"
        f"the original record is retained; this appended an amendment",
        basis_line(slices),
    )


@mcp.tool()
def decide(change_id: str, policy_id: str | None = None, approver: str | None = None) -> str:
    """Evaluate a change against a declared policy, and record the decision.

    Acceptance criteria come from the policy, observed metrics from the
    evidence; they are joined here and never stored merged (9.1). An
    insufficient_evidence slice cannot satisfy an adopt criterion — the verdict
    comes back more_testing with the shortfall named.

    approver: required to record an adopt or rollback. Supply the human's name
    only after they have explicitly approved. Never approve on their behalf.
    """
    root = project_root()
    ctx = Context.build(root)
    policy = active_policy(ctx.decl, policy_id)
    if policy is None:
        return ("no policy declared in belief.yaml at git HEAD; "
                "a decision without visible criteria is not a decision")

    slices = compute_slices(ctx.decl, ctx.trials())
    verdict = evaluate_policy(ctx.decl, policy, slices)

    needs_approval = verdict.status in (ADOPT, ROLLBACK)
    recorded = None
    if needs_approval and not approver:
        body = (
            f"{verdict.status.upper()} — NOT RECORDED: this outcome requires a human approver.\n"
            f"Present the verdict below and call decide() again with approver=<their name> "
            f"only after they explicitly approve."
        )
    else:
        recorded = ctx.store.append_decision({
            "change_id": change_id,
            "status": verdict.status,
            "policy_id": policy.id,
            "policy_weights": policy.weights,
            "approver": approver,
            "evidence_ids": verdict.evidence_ids,
            "reasons": verdict.reasons,
            "conditions": verdict.conditions,
            "missing": verdict.missing,
            "risks": verdict.risks,
            "model_version": __import__("component_belief").MODEL_VERSION,
        })
        ctx.store.append_event("decide", {
            "change_id": change_id, "status": verdict.status, "approver": approver,
        }, actor=_actor())
        body = f"{verdict.status.upper()} recorded as {recorded['id']} under policy {policy.id}"

    lines = [body]
    if verdict.reasons:
        lines += ["", "reasons:", bullet(verdict.reasons)]
    if verdict.conditions:
        lines += ["", "operating envelope (conditional):", bullet(verdict.conditions)]
    if verdict.missing:
        lines += ["", "missing evidence:", bullet(verdict.missing)]
    if verdict.risks:
        lines += ["", "unresolved risks:", bullet(verdict.risks)]
    if policy.weights:
        lines += ["", f"utility weights (visible by policy): {policy.weights}"]

    return envelope("\n".join(lines), basis_line(slices) + f" · policy {policy.id}")


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
