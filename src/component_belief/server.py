"""MCP server — six tools.

Note what is absent: there is no tool that writes a belief. That is not an
oversight to be fixed later, it is the design (10.4). An agent's only route to
moving a posterior is to declare a test that produces the number and let the
server run it.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from .decide import ADOPT, ROLLBACK, active_policy, evaluate_policy
from .declarations import GOALS_FILE
from .goals import ratification_gap, view_goals
from .project import project_root as resolve_root
from .render import basis_line, bullet, envelope
from .runner import _git_revision, _sha256, run_test as execute_test
from .store import VALIDITY, Store
from .views import (
    view_artifacts,
    VIEWS,
    Context,
    view_belief,
    view_coverage,
    view_cycle,
    view_diagnose,
    view_graph,
    view_no_declarations,
    no_declarations_next,
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
    return resolve_root("BELIEF_PROJECT_ROOT")


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
  artifacts - every file with what made it, what ran it, and whether live evidence rests
              on it; prune candidates are the code nothing claims, runs or supports.
              `subject` narrows to one directory
      cycle     - the full evaluation-cycle report as JSON, with complete chains
      trace     - expand a `set=` citation handle into its exact evidence records
      goals     - the human's goals.yaml: each goal and interface met or not, the agent's proposals
                  on them, and any agent commit to the goal set since the human's last

    subject: a component or contract id to narrow to (or a RUN- id for diagnose).
    set:     the citation handle from a `basis:` line, for view="trace".
    budget:  cost ceiling for view="plan".
    """
    root = project_root()
    ctx = Context.build(root)
    if view not in VIEWS:
        return f"unknown view {view!r}; expected one of {', '.join(VIEWS)}"
    if ctx.decl.source == "none" and view not in ("graph", "coverage"):
        return view_no_declarations(ctx, view)
    if view == "graph":
        return view_graph(ctx, since)
    if view == "coverage":
        return view_coverage(ctx)
    if view == "diagnose":
        return view_diagnose(ctx, subject, policy)
    if view == "plan":
        return view_plan(ctx, budget, policy)
    if view == "artifacts":
        return view_artifacts(ctx, subject)
    if view == "trace":
        return view_trace(ctx, set, subject)
    if view == "cycle":
        return json.dumps(view_cycle(ctx, policy), indent=2, default=str)
    if view == "goals":
        return view_goals(ctx)
    return view_belief(ctx, subject, since)


@mcp.tool()
def run_test(
    test_id: str,
    conditions: dict[str, Any] | None = None,
    repro: dict[str, Any] | None = None,
) -> str:
    """Run a declared test and record its trials as measured evidence.

    The server executes the command and captures the artifact itself; nothing
    is transcribed. The command may write structured trials to $OUT, one JSON
    file: {"trials": [{"metrics": {...}, "conditions": {...}}]}, a list of
    trials, or one {"metrics": ...}. If it does not, one trial is synthesised
    from the exit code and the reply says what was wrong with $OUT.

    conditions: captured metadata for bucketing, e.g. {"lighting": "low"}.
    repro:      reproducibility fields, e.g. {"model_revision": "v3", "seed": 7}.
    """
    root = project_root()
    ctx = Context.build(root)
    test = ctx.decl.tests.get(test_id)
    if test is None:
        if ctx.decl.source == "none":
            return f"unknown test {test_id!r}: no tests are declared. next: {no_declarations_next(ctx.decl)}"
        known = ", ".join(sorted(ctx.decl.tests)) or "(none declared at git HEAD)"
        return f"unknown test {test_id!r}. Declared tests: {known}"
    if not test.run:
        return f"{test_id} has no run command"

    result = execute_test(root, ctx.store, ctx.decl, test, conditions, repro, actor=_actor())

    fresh = Context.build(root)
    slices = fresh.slices(contract_ids=result["contracts"])
    lines = [
        f"{result['run_id']} {result['test']} exit={result['exit_code']} "
        f"trials={result['n_trials']} records={result['n_records']}",
        f"outcomes: {result['outcome_counts']}",
        f"artifact: {result['artifact_uri']} sha={result['artifact_hash']}",
    ]
    if result["synthesized_from_exit_code"]:
        lines.append(
            f"note: {result['result_problem']} — one trial synthesised from the exit code. "
            "$OUT takes one JSON file: {\"trials\": [...]}, a list of trials, or one "
            "{\"metrics\": ...}. Contracts needing declared metrics will exclude it rather "
            "than score it."
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


def _local_file(root: Path, uri: str) -> tuple[Path | None, str]:
    """The file an import names -- a path in the project, or an absolute one -- or what it names
    instead. The server copies and hashes one file, so a URL, a directory or several paths in one
    string import nothing; each is named, because each is fixed differently."""
    if "://" in uri:
        return None, "it is a URL; download the artifact into the project first"
    path = Path(uri)
    path = (path if path.is_absolute() else root / path).resolve()
    if path.is_file():
        return path, ""
    if path.is_dir():
        return None, ("it is a directory; name the one file the records were read from, merging "
                      "the files into one if they came from several")
    parts = [p for p in re.split(r"[\s;,]+", uri) if p]
    if len(parts) > 1 and any((root / p).exists() or Path(p).exists() for p in parts):
        return None, ("it names more than one path; ingest each file's records in a call of its "
                      "own, or merge the files into one")
    return None, "nothing exists at that path"


@mcp.tool()
def ingest(
    records: list[dict[str, Any]],
    source: str,
    artifact_uri: str,
) -> str:
    """Import belief-eligible evidence produced outside this server (CI,
    telemetry, a robot log).

    artifact_uri: the file the records were read from -- a path in the project
    or an absolute path on this machine, never a URL. The server copies it into
    the run's artifact directory and hashes the copy itself, so the ledger
    audits on any clone and a later edit to the original changes nothing. Any
    artifact_hash a record carries is ignored.

    Each record needs: contract_id, test_id (a test the contract lists in
    evaluable_by), outcome, metrics, and a repro block. Records missing
    required fields are rejected rather than stored partially, because a record
    you cannot compare is not evidence (3.4).
    """
    root = project_root()
    ctx = Context.build(root)
    if not artifact_uri:
        return "rejected: artifact_uri is required for imported evidence"
    original, problem = _local_file(root, artifact_uri)
    if original is None:
        # DEF-belief-eligible: an import is brought in with an artifact *and its hash*. A hash
        # the caller supplies is testimony; the server can only vouch for bytes it has read.
        return (f"rejected: artifact_uri {artifact_uri!r} is not a file on this machine: {problem}. "
                "The server copies and hashes the one file the records came from itself")

    required = ("contract_id", "test_id", "outcome")
    accepted, rejected = [], []
    run_id = ctx.store.next_run_id()

    for index, record in enumerate(records):
        problems = [f"missing {f}" for f in required if not record.get(f)]
        contract = ctx.decl.contracts.get(record.get("contract_id", ""))
        if contract is None:
            problems.append("contract_id is not declared")
        elif not ctx.decl.is_scorable(contract.id):
            problems.append(f"{contract.id} is not scorable")
        elif record.get("test_id") and record["test_id"] not in contract.evaluable_by:
            # Only a declared test can measure a contract (DEF-belief-eligible); an import is
            # evidence from one of them, run somewhere the server could not run it.
            problems.append(f"test_id {record['test_id']} is not a test {contract.id} lists in "
                            f"evaluable_by ({', '.join(contract.evaluable_by)})")
        if not isinstance(record.get("repro"), dict):
            problems.append("missing repro")
        if problems:
            rejected.append(f"record {index}: {'; '.join(problems)}")
            continue
        test = ctx.decl.tests[record["test_id"]]
        accepted.append({
            "subject": contract.subject,
            "contract_id": contract.id,
            "test_id": test.id,
            "test_ref": record.get("test_ref") or test.ref,
            "run_id": run_id,
            "system_version": record["repro"].get("sw_revision", ""),
            "provenance": "imported",
            "source_system": source,
            "outcome": record["outcome"],
            "metrics": record.get("metrics", {}),
            "conditions": {"raw": record.get("conditions", {})},
            "repro": record["repro"],
            "validity": "valid",
        })

    if accepted:
        # Copied only once something will rest on it, so a rejected import leaves no directory.
        copy = ctx.store.artifact_dir(run_id) / original.name
        shutil.copyfile(original, copy)
        stored = {"artifact_uri": copy.relative_to(root).as_posix(),
                  "artifact_hash": _sha256(copy),
                  "source_artifact": str(original)}
        accepted = [{**record, **stored} for record in accepted]
    ids = ctx.store.append_trials(accepted) if accepted else []
    ctx.store.append_event("ingest", {
        "source": source, "accepted": len(ids), "rejected": len(rejected), "run_id": run_id,
    }, actor=_actor())

    lines = [f"ingested {len(ids)} record(s) from {source!r} as provenance=imported"]
    if accepted:
        lines.append(f"artifact: {stored['artifact_uri']} sha={stored['artifact_hash']} "
                     f"(copied from {original})")
    if rejected:
        lines += ["", "rejected:", bullet(rejected)]
    fresh = Context.build(root)
    slices = fresh.slices(contract_ids=sorted({r["contract_id"] for r in accepted}) or None)
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
    evidence_id: str = "",
    validity: str | None = None,
    supersede_with: str | None = None,
    reason: str = "",
    evidence_ids: list[str] | None = None,
) -> str:
    """Correct an evidence record without editing it.

    `evidence_ids` reclassifies many at once under one reason, reading the ledger once instead of
    once per record. A correction that takes hours does not get made, and evidence that should
    have been set aside goes on supporting decisions.

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
    targets = list(evidence_ids or ([evidence_id] if evidence_id else []))
    if not targets:
        return "supply evidence_id= or evidence_ids="
    known = {t.get("id") for t in ctx.store.effective_trials()}
    unknown = [e for e in targets if e not in known]
    if len(targets) > 1 and unknown:
        return (f"rejected: {len(unknown)} of {len(targets)} ids are not in the ledger, "
                f"starting with {', '.join(unknown[:3])}")
    if evidence_id and evidence_id not in known:
        return f"unknown evidence id {evidence_id!r}"

    for target in targets:
        ctx.store.append_amendment(
            target, validity=validity, supersede_with=supersede_with,
            reason=reason, actor=_actor(),
        )
    ctx.store.append_event("amend", {
        "target": targets[0] if len(targets) == 1 else f"{len(targets)} records",
        "targets": len(targets), "validity": validity, "supersede_with": supersede_with,
    }, actor=_actor())

    fresh = Context.build(project_root())
    slices = fresh.slices()
    return envelope(
        f"amended {targets[0] if len(targets) == 1 else str(len(targets)) + ' records'}: "
        f"validity={validity or 'superseded'} — {reason}\n"
        f"the original record{'' if len(targets) == 1 else 's are'} retained; this appended an "
        f"amendment{'' if len(targets) == 1 else ' each'}",
        basis_line(slices),
    )


@mcp.tool()
def decide(change_id: str, policy_id: str | None = None, approver: str | None = None) -> str:
    """Evaluate a change against a declared policy, and record the decision.

    Acceptance criteria come from the policy, observed metrics from the
    evidence; they are joined here and never stored merged (9.1). An
    insufficient_evidence slice cannot satisfy an adopt criterion — the verdict
    comes back more_testing with the shortfall named.

    approver: required to record an adopt or rollback -- except under a policy
    declared in goals.yaml, whose criteria the human approved by committing them,
    while the agent has not changed the goal set since. Supply the human's name
    only after they have explicitly approved. Never approve on their behalf.
    """
    root = project_root()
    ctx = Context.build(root)
    policy = active_policy(ctx.decl, policy_id)
    if policy is None:
        if ctx.decl.source == "none":
            return f"no declarations in effect, so no policy to decide against. next: {no_declarations_next(ctx.decl)}"
        return ("no policy declared in belief.yaml at git HEAD; "
                "a decision without visible criteria is not a decision")

    slices = ctx.slices()
    verdict = evaluate_policy(ctx.decl, policy, slices)
    head = _git_revision(root)

    consequential = verdict.status in (ADOPT, ROLLBACK)
    # The human's commit of goals.yaml approved this policy's criteria, if the policy and all it
    # measures by are declared there and the agent has not touched the goal set since.
    gap = ratification_gap(root, ctx.decl, policy.id) if consequential else None
    needs_approval = consequential and gap is not None
    recorded = None
    if needs_approval and not approver:
        why = (f"\nNot covered by your {GOALS_FILE}: {gap}."
               if ctx.decl.goal_owned & set(ctx.decl.policies) else "")
        body = (
            f"{verdict.status.upper()} — NOT RECORDED: this outcome requires a human approver.{why}\n"
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
            # the approval an adoption rests on when no approver is named: this blob of goals.yaml
            "criteria_committed": ({GOALS_FILE: ctx.decl.goals_blob}
                                   if consequential and gap is None else None),
            "head": head,
            "evidence_ids": verdict.evidence_ids,
            "reasons": verdict.reasons,
            "conditions": verdict.conditions,
            "missing": verdict.missing,
            "risks": verdict.risks,
            "model_version": __import__("component_belief").MODEL_VERSION,
        })
        ctx.store.append_event("decide", {
            "change_id": change_id, "status": verdict.status, "approver": approver, "head": head,
        }, actor=_actor())
        body = (f"{verdict.status.upper()} recorded as {recorded['id']} under policy {policy.id} "
                f"at HEAD {head or '?'}")
        if consequential and gap is None:
            body += (f"\ncriteria approved by your commit of {GOALS_FILE} "
                     f"(blob {ctx.decl.goals_blob[:7]}); no approver needed")

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
