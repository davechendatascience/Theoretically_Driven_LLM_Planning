"""Was the loop followed, or worked around?

The ledgers cannot be argued with, but they can be steered: no tool writes a belief, and yet an
agent that reclassifies only the failures, or records an adoption itself, arrives at the same
place. Each check below is a pattern in the recorded history, not a verdict on anyone's intent --
a failure genuinely caused by a broken rig should be invalidated, and it is the *pattern* across
many amendments that says something. Findings name the records, so a human can read them.

  - reclassifications that remove only adverse results
  - an adoption or rollback with no approver, or approved by the actor that requested it
  - a decision resting on evidence measured on a dirty tree
  - an adoption whose evidence has gone stale since it was recorded
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from component_belief.declarations import load as load_components
from component_belief.staleness import CodeStaleness
from component_belief.store import STORE_DIR, Store

from . import BLOCK, INFO, WARN, Finding

DESIGN_DIR = ".consistency"
#: Outcomes that count against the claim, per ledger.
ADVERSE = {"evidence": {"fail"}, "design": {"falsified", "gap"}}
#: Below this many reclassifications a one-sided pattern is reported, not flagged.
ASYMMETRY_MIN = 3
#: Actor names that are the agent, not a human able to approve.
AGENT_ACTORS = {"agent", "claude", "assistant", "llm", ""}


def _read(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue           # audit reports unparsable lines; here they simply are not history
    return out


def workflow(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for ledger, directory in (("evidence", STORE_DIR), ("design", DESIGN_DIR)):
        records = _read(root / directory / "evidence.jsonl")
        events = _read(root / directory / "events.jsonl")
        decisions = _read(root / directory / "decisions.jsonl")
        _asymmetry(ledger, directory, records, findings)
        _approval(directory, decisions, events, findings)
    _decisions_on_evidence(root, findings)
    return findings


def _asymmetry(ledger: str, directory: str, records: list[dict], findings: list[Finding]) -> None:
    trials = {r["id"]: r for r in records if r.get("kind") == "trial" and "id" in r}
    removed = [(a, trials[a["target"]]) for a in records
               if a.get("kind") == "amendment" and a.get("validity") not in (None, "valid")
               and a.get("target") in trials]
    if not removed:
        return
    adverse = [(a, t) for a, t in removed if t.get("outcome") in ADVERSE[ledger]]
    base = sum(1 for t in trials.values() if t.get("outcome") in ADVERSE[ledger]) / len(trials)
    share = len(adverse) / len(removed)
    detail = (f"{len(adverse)} of {len(removed)} reclassification(s) removed an adverse result "
              f"(adverse results are {base:.0%} of this ledger)")
    if len(removed) >= ASYMMETRY_MIN and share == 1.0:
        findings.append(Finding("AMEND_ONLY_ADVERSE", WARN, directory,
                                detail + "; every reclassification moved the belief one way"))
    elif adverse:
        example, trial = adverse[0]
        reason = (example.get("reason") or "no reason recorded")[:140]
        findings.append(Finding("AMEND_ADVERSE", INFO, directory,
                                f"{detail}; e.g. {trial['id']} ({trial.get('outcome')}): {reason}"))


def _approval(directory: str, decisions: list[dict], events: list[dict], findings: list[Finding]) -> None:
    actors = {}
    for e in events:
        if e.get("tool") == "decide":
            payload = e.get("payload") or {}
            actors[(payload.get("change_id"), payload.get("status"), payload.get("approver"))] = e.get("actor", "")
    for d in decisions:
        if str(d.get("status", "")).lower() not in ("adopt", "rollback"):
            continue
        approver = str(d.get("approver") or "")
        actor = actors.get((d.get("change_id"), d.get("status"), d.get("approver")), "")
        subject = f"{directory}/{d.get('id')}"
        if not approver:
            findings.append(Finding("UNAPPROVED_ADOPTION", BLOCK, subject,
                                    f"{d.get('status')} recorded with no approver"))
        elif approver.lower() in AGENT_ACTORS or (actor and approver.lower() == str(actor).lower()):
            findings.append(Finding("SELF_APPROVAL", BLOCK, subject,
                                    f"{d.get('status')} approved by {approver!r}, the actor that "
                                    "requested it"))


def _decisions_on_evidence(root: Path, findings: list[Finding]) -> None:
    """Component decisions cite evidence ids, so what they rested on can be re-examined now."""
    decisions = _read(root / STORE_DIR / "decisions.jsonl")
    if not decisions:
        return
    store = Store(root)
    trials = {t["id"]: t for t in store.effective_trials()}
    decl = load_components(root)
    staleness = CodeStaleness(root)
    for d in decisions:
        cited = [trials[i] for i in d.get("evidence_ids") or [] if i in trials]
        subject = f"{STORE_DIR}/{d.get('id')}"
        dirty = [t["id"] for t in cited if (t.get("repro") or {}).get("sw_dirty")]
        if dirty:
            findings.append(Finding("DECISION_ON_DIRTY_EVIDENCE", WARN, subject,
                                    f"{d.get('status')} rests on {len(dirty)} trial(s) measured "
                                    f"with uncommitted edits ({', '.join(dirty[:3])})"))
        if str(d.get("status", "")).lower() != "adopt" or not cited:
            continue
        stale = []
        for t in cited:
            contract = decl.contracts.get(t.get("contract_id", ""))
            if contract and staleness.stale_reason(decl.code_paths_for_subject(contract.subject), t):
                stale.append(t)
        if stale:
            which = sorted({t.get("contract_id") for t in stale})
            findings.append(Finding(
                "ADOPTION_NOW_STALE", INFO, subject,
                f"adopted at {d.get('head') or 'an unrecorded revision'}; {len(stale)} of its "
                f"{len(cited)} trial(s) have gone stale since ({', '.join(which[:3])}) -- the "
                "decision stands as recorded, but no longer describes HEAD"))

