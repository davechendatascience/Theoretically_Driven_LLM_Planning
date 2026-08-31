"""The `status` views — every read the agent has.

Merged behind one tool because tool schemas are standing context in every
session in the project, paid whether or not the server is used. Seven views on
one tool cost a fraction of seven tools.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import MODEL_VERSION
from .declarations import Declarations, load
from .decide import active_policy, evaluate_policy
from .diagnose import diagnose
from .ids import set_hash
from .model import compute_slices, unobserved_contracts
from .planning import plan_round
from .render import basis_line, bullet, envelope, slice_dict, slice_line
from .store import Store

VIEWS = ("graph", "coverage", "belief", "diagnose", "plan", "cycle", "trace")


@dataclass
class Context:
    root: Path
    store: Store
    decl: Declarations

    @classmethod
    def build(cls, root: Path) -> "Context":
        return cls(root=root, store=Store(root), decl=load(root))

    def trials(self) -> list[dict[str, Any]]:
        return self.store.effective_trials()

    def slices(self, subject: str | None = None):
        contract_ids = None
        if subject:
            if subject in self.decl.contracts:
                contract_ids = [subject]
            else:
                contract_ids = [c.id for c in self.decl.contracts_for_subject(subject)]
        return compute_slices(self.decl, self.trials(), contract_ids)


def _declaration_header(decl: Declarations) -> str:
    if decl.source == "none":
        return (
            "declarations: NONE IN EFFECT (no belief.yaml at git HEAD)\n"
            "  Declarations load from git HEAD, not the working tree — commit "
            "belief.yaml for it to take effect."
        )
    line = f"declarations: git HEAD · {len(decl.components)} components, " \
           f"{len(decl.contracts)} contracts, {len(decl.tests)} tests"
    if decl.pending:
        line += "\n  PENDING: working tree differs from HEAD; uncommitted edits are not in effect"
    return line


def view_graph(ctx: Context, since: str | None = None) -> str:
    decl = ctx.decl
    active = decl.active_components()
    lines = [_declaration_header(decl), "", "components:"]
    for cid, comp in sorted(active.items()):
        contracts = [c.id for c in decl.contracts_for_subject(cid)]
        lines.append(f"  {cid}  contracts={contracts or '[]'}  {comp.purpose}")
    dropped = [i for i in decl.issues if i.code == "NOT_A_NODE"]
    if dropped:
        lines += ["", "dropped (not independently testable nodes):"]
        lines.append(bullet(i.render() for i in dropped))

    lines += ["", "interfaces:"]
    for iid, iface in sorted(decl.interfaces.items()):
        lines.append(f"  {iid}  {iface.producer} -> {iface.consumer}  ({iface.units or 'no units'})")

    unbacked = [i for i in decl.issues if i.code == "UNBACKED_ASSUMPTION"]
    lines += ["", "unbacked assumptions:", bullet(i.render() for i in unbacked)]

    fatal = [i for i in decl.issues if i.code not in ("UNBACKED_ASSUMPTION", "NOT_A_NODE", "PENDING")]
    if fatal:
        lines += ["", "declaration issues:", bullet(i.render() for i in fatal)]

    return envelope("\n".join(lines), f"basis: declarations · source {decl.source} · model {MODEL_VERSION}")


def view_coverage(ctx: Context) -> str:
    decl, trials = ctx.decl, ctx.trials()
    slices = ctx.slices()

    counts: dict[str, int] = {}
    provenance: dict[str, int] = {}
    for trial in trials:
        counts[trial.get("validity", "valid")] = counts.get(trial.get("validity", "valid"), 0) + 1
        provenance[trial.get("provenance", "?")] = provenance.get(trial.get("provenance", "?"), 0) + 1

    uncovered = unobserved_contracts(decl, slices)
    unscorable = [cid for cid in decl.contracts if not decl.is_scorable(cid)]
    notes = ctx.store.notes()

    lines = [
        _declaration_header(decl), "",
        f"evidence: {len(trials)} trial records",
        f"  validity:   {counts or '{}'}",
        f"  provenance: {provenance or '{}'}  (only measured/imported are belief-eligible)",
        f"  notes:      {len(notes)} annotation(s) — never scored",
        "",
        "test versions:",
    ]
    for tid, test in sorted(decl.tests.items()):
        flag = " [mandatory]" if test.mandatory else ""
        lines.append(f"  {test.ref}  layer={test.layer}  cost={test.cost}{flag}")

    lines += ["", "contracts with no belief-eligible evidence:", bullet(uncovered)]
    if unscorable:
        lines += ["", "contracts accepting no evidence (declaration invalid):", bullet(
            f"{cid}: {'; '.join(i.message for i in decl.issues_for(cid))}" for cid in unscorable
        )]
    return envelope("\n".join(lines), basis_line(slices, derived_from="evidence"))


def view_belief(ctx: Context, subject: str | None = None, since: str | None = None) -> str:
    decl = ctx.decl
    slices = ctx.slices(subject)
    if not slices:
        body = "no belief-eligible evidence for that subject"
        uncovered = unobserved_contracts(decl, ctx.slices())
        if uncovered:
            body += "\nunobserved contracts:\n" + bullet(uncovered)
        return envelope(body, basis_line([], derived_from="evidence"),
                        "run_test on a test whose contract you need")

    lines = [slice_line(sl) for sl in slices]
    prior_ids = [sl.prior_id for sl in slices if sl.prior_id]
    thin = [sl for sl in slices if sl.missing.get("trials_needed")]
    next_action = None
    if thin:
        target = thin[0]
        tests = decl.tests_for(target.contract_id)
        if tests:
            next_action = (
                f"run_test {tests[0].id} conditions={{{target.bucket}}} "
                f"# closes the thin slice"
            )
    return envelope("\n".join(lines), basis_line(slices, prior_ids=prior_ids), next_action)


def view_diagnose(ctx: Context, subject: str | None = None, policy_id: str | None = None) -> str:
    decl = ctx.decl
    trials = ctx.trials()
    slices = compute_slices(decl, trials)
    result = diagnose(decl, slices, trials, run_id=subject if subject and subject.startswith("RUN-") else None,
                      policy_id=policy_id)

    lines = []
    if not result.ranked:
        lines.append("no candidate bottlenecks: every observed component is supported")
    for candidate in result.ranked:
        flag = " decision-relevant" if candidate.decision_relevant else ""
        lines.append(
            f"{candidate.subject:<24} {candidate.status:<18} "
            f"score={candidate.score:.2f} confidence={candidate.confidence}{flag}"
        )
        lines.append(f"    {candidate.reason}")
        if candidate.evidence_ids:
            lines.append(f"    evidence×{len(candidate.evidence_ids)}")

    if result.coverage_limited:
        lines += ["", "COVERAGE LIMITED — no optimisation recommendation is produced.",
                  "Instrumentation is the binding constraint, not performance."]
    if result.discriminating_test:
        d = result.discriminating_test
        lines += ["", f"discriminating test: {d['test_id']} observes {d['observes']} of {d['separates']}"]
    if result.instrumentation_gaps:
        lines += ["", "instrumentation gaps:", bullet(result.instrumentation_gaps)]

    basis = basis_line(slices, derived_from="evidence" if slices else "assumption",
                       assumptions=[] if result.policy_id else ["no policy declared; relevance not evaluated"])
    return envelope("\n".join(lines), basis, result.recommendation)


def view_plan(ctx: Context, budget: float | None = None, policy_id: str | None = None) -> str:
    decl = ctx.decl
    slices = ctx.slices()
    plan = plan_round(decl, slices, budget=budget, policy_id=policy_id)

    lines = [
        f"policy: {plan['policy'] or '(none declared)'}   budget: {plan['budget']}   cost: {plan['spent']}",
        "", "mandatory (scheduled regardless of information gain):",
        bullet(f"{item['test_id']} ({item['layer']}, cost {item['cost']})" for item in plan["mandatory"]),
        "", "selected:",
        bullet(f"{item['test_id']} ({item['layer']}, cost {item['cost']}) -> {item['contracts']}"
               for item in plan["selected"]),
        "", "skipped (every test considered, with its reason):",
        bullet(f"{item['test_id']}: {item['reason']} — {item['detail']}" for item in plan["skipped"]),
    ]
    if plan["imbalance"]:
        lines += ["", f"IMBALANCE: no {plan['imbalance']} test scheduled this round"]
    return envelope("\n".join(lines), basis_line(slices))


def view_cycle(ctx: Context, policy_id: str | None = None) -> dict[str, Any]:
    """The seven required outputs (rules §11), in full form with complete
    chains — this is where rule 10.1 applies."""
    decl = ctx.decl
    trials = ctx.trials()
    slices = compute_slices(decl, trials)
    result = diagnose(decl, slices, trials, policy_id=policy_id)
    policy = active_policy(decl, policy_id)
    verdict = evaluate_policy(decl, policy, slices) if policy else None

    e2e_tests = {t.id for t in decl.tests.values() if t.layer == "e2e"}
    e2e_runs: dict[str, dict[str, Any]] = {}
    for trial in trials:
        if trial.get("test_id") in e2e_tests:
            run = e2e_runs.setdefault(trial.get("run_id", "?"), {"outcomes": {}, "linked_local": []})
            run["outcomes"][trial.get("outcome", "?")] = run["outcomes"].get(trial.get("outcome", "?"), 0) + 1
    for trial in trials:
        run_id = trial.get("run_id")
        if run_id in e2e_runs and trial.get("test_id") not in e2e_tests:
            e2e_runs[run_id]["linked_local"].append(trial.get("id"))
    for run_id, run in e2e_runs.items():
        run["linked"] = bool(run["linked_local"])

    return {
        "1_graph": {
            "components": sorted(decl.active_components()),
            "interfaces": sorted(decl.interfaces),
            "dropped": [i.render() for i in decl.issues if i.code == "NOT_A_NODE"],
            "declaration_source": decl.source,
            "pending_uncommitted": decl.pending,
        },
        "2_coverage": {
            "n_trials": len(trials),
            "validity": _tally(trials, "validity"),
            "provenance": _tally(trials, "provenance"),
            "uncovered_contracts": unobserved_contracts(decl, slices),
            "unbacked_assumptions": [i.render() for i in decl.issues if i.code == "UNBACKED_ASSUMPTION"],
            "test_versions": {t.id: t.version for t in decl.tests.values()},
        },
        "3_beliefs": [slice_dict(s) for s in slices],
        "4_e2e": e2e_runs,
        "5_bottlenecks": {
            "ranked": [
                {
                    "subject": c.subject, "status": c.status, "score": round(c.score, 3),
                    "decision_relevant": c.decision_relevant, "confidence": c.confidence,
                    "reason": c.reason, "evidence_ids": c.evidence_ids,
                }
                for c in result.ranked
            ],
            "coverage_limited": result.coverage_limited,
            "instrumentation_gaps": result.instrumentation_gaps,
        },
        "6_recommendation": {
            "action": result.recommendation,
            "discriminating_test": result.discriminating_test,
            "plan": plan_round(decl, slices, policy_id=policy_id),
        },
        "7_decision": {
            "policy": policy.id if policy else None,
            "status": verdict.status if verdict else "no_policy_declared",
            "reasons": verdict.reasons if verdict else [],
            "conditions": verdict.conditions if verdict else [],
            "missing": verdict.missing if verdict else [],
            "risks": verdict.risks if verdict else [],
            "blockers": [i.render() for i in decl.issues if i.code in
                         ("NOT_EVALUABLE", "UNKNOWN_REF", "CAPABILITY_REFERENCES_IMPLEMENTATION", "UNCOMMITTED")],
            "recorded_decisions": ctx.store.decisions()[-5:],
        },
        "model_version": MODEL_VERSION,
    }


def view_trace(ctx: Context, set_ref: str | None = None, subject: str | None = None) -> str:
    """Expand a `set=` handle into the exact evidence records behind it.

    Two kinds of handle resolve here: a single slice's own hash, and the union
    hash a multi-slice `basis:` line prints. Every handle the agent is ever
    shown must be resolvable — an unresolvable citation is worse than none,
    because it looks like provenance while providing none.
    """
    slices = ctx.slices(subject)
    union = set_hash(sorted({e for s in slices for e in s.evidence_ids}))
    if set_ref is not None and set_ref == union and slices:
        matched = slices
    else:
        matched = [s for s in slices if set_ref is None or s.set_hash == set_ref]
    if not matched:
        return envelope(
            f"no slice carries set={set_ref!r}. Known handles:\n"
            + bullet(f"{s.set_hash}  {s.contract_id} [{s.condition_label()}]" for s in slices),
            "basis: assumption · nothing matched",
        )

    by_id = {t.get("id"): t for t in ctx.trials()}
    lines: list[str] = []
    for sl in matched:
        lines.append(f"{sl.contract_id} [{sl.condition_label()}] set={sl.set_hash} n={sl.n_valid}")
        for eid in sl.evidence_ids:
            trial = by_id.get(eid, {})
            lines.append(
                f"  {eid}  {trial.get('test_ref', '?')}  {trial.get('outcome', '?')}  "
                f"run={trial.get('run_id', '?')}  metrics={trial.get('metrics', {})}  "
                f"artifact={trial.get('artifact_uri', '-')}"
            )
    return envelope("\n".join(lines), basis_line(matched))


def _tally(records: list[dict[str, Any]], field: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for record in records:
        key = str(record.get(field, "?"))
        out[key] = out.get(key, 0) + 1
    return out
