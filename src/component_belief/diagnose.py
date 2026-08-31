"""Diagnosis: rank what to investigate, and refuse to recommend optimising
something you cannot see.

The four status classes are the point (7.2). Collapsing `unobserved` into
"looks fine" is the single most expensive mistake this module exists to
prevent, because it converts missing instrumentation into apparent health.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .declarations import Declarations
from .decide import active_policy, decision_relevant
from .model import (
    STATE_CONTESTED,
    STATE_INSUFFICIENT,
    STATE_REFUTED,
    Slice,
)

CONFIRMED = "confirmed_failure"
SUSPECTED = "suspected"
UNOBSERVED = "unobserved"
BLOCKED = "blocked_downstream"
OK = "ok"

_SUSPICION = {
    CONFIRMED: 1.0,
    UNOBSERVED: 0.55,
    SUSPECTED: 0.4,
    BLOCKED: 0.1,
    OK: 0.0,
}


@dataclass
class Candidate:
    subject: str
    status: str
    suspicion: float
    decision_relevant: bool
    confidence: str
    reason: str
    evidence_ids: list[str] = field(default_factory=list)
    contracts: list[str] = field(default_factory=list)
    cost: float = 1.0

    @property
    def score(self) -> float:
        weight = 2.0 if self.decision_relevant else 1.0
        return weight * self.suspicion / max(self.cost, 0.01)


@dataclass
class Diagnosis:
    ranked: list[Candidate]
    discriminating_test: dict[str, Any] | None
    coverage_limited: bool
    instrumentation_gaps: list[str]
    recommendation: str
    policy_id: str | None


def _downstream(decl: Declarations, origin: str) -> set[str]:
    """Components reachable by following interfaces forward from `origin`."""
    edges: dict[str, list[str]] = {}
    for iface in decl.interfaces.values():
        if iface.producer and iface.consumer:
            edges.setdefault(iface.producer, []).append(iface.consumer)
    seen: set[str] = set()
    stack = list(edges.get(origin, []))
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        stack.extend(edges.get(node, []))
    return seen


def _upstream(decl: Declarations, origin: str) -> set[str]:
    edges: dict[str, list[str]] = {}
    for iface in decl.interfaces.values():
        if iface.producer and iface.consumer:
            edges.setdefault(iface.consumer, []).append(iface.producer)
    seen: set[str] = set()
    stack = list(edges.get(origin, []))
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        stack.extend(edges.get(node, []))
    return seen


def _tests_targeting(decl: Declarations, subject: str) -> list[Any]:
    return [t for t in decl.tests.values() if subject in t.targets]


def diagnose(
    decl: Declarations,
    slices: list[Slice],
    trials: list[dict[str, Any]],
    run_id: str | None = None,
    policy_id: str | None = None,
) -> Diagnosis:
    components = decl.active_components()
    policy = active_policy(decl, policy_id)

    run_trials = [t for t in trials if run_id is None or t.get("run_id") == run_id]
    failing_in_run: set[str] = set()
    for trial in run_trials:
        if trial.get("outcome") == "fail" and trial.get("validity") == "valid":
            contract = decl.contracts.get(trial.get("contract_id", ""))
            if contract:
                failing_in_run.add(contract.subject)

    by_subject: dict[str, list[Slice]] = {}
    for sl in slices:
        contract = decl.contracts.get(sl.contract_id)
        if contract:
            by_subject.setdefault(contract.subject, []).append(sl)

    # First pass: local status from this component's own evidence only.
    # E2E outcomes never attribute here (6.4) — they reach a component solely
    # through the local observations linked by run_id.
    statuses: dict[str, tuple[str, str]] = {}
    for cid in components:
        component_slices = by_subject.get(cid, [])
        contracts = decl.contracts_for_subject(cid)

        if cid in failing_in_run:
            statuses[cid] = (CONFIRMED, "failing observation against its own contract in this run")
        elif any(s.state == STATE_REFUTED for s in component_slices):
            statuses[cid] = (CONFIRMED, "belief slice refuted against the contract target rate")
        elif not contracts:
            statuses[cid] = (UNOBSERVED, "no contract declared for this component")
        elif not component_slices:
            statuses[cid] = (UNOBSERVED, "no belief-eligible evidence under these conditions")
        elif any(s.state == STATE_INSUFFICIENT for s in component_slices):
            statuses[cid] = (UNOBSERVED, "evidence too sparse to support any verdict")
        elif any(s.state == STATE_CONTESTED for s in component_slices):
            statuses[cid] = (SUSPECTED, "interval straddles the target rate")
        else:
            statuses[cid] = (OK, "supported under all observed conditions")

    # Second pass: topology. Downstream of a confirmed failure is blocked —
    # its evidence from this run is uninformative and is excluded, not counted
    # against it. Upstream of one is suspected.
    confirmed = {c for c, (s, _) in statuses.items() if s == CONFIRMED}
    for cid, (status, reason) in list(statuses.items()):
        if cid in confirmed:
            continue
        blockers = confirmed & _upstream(decl, cid)
        if blockers:
            statuses[cid] = (
                BLOCKED,
                f"inputs come from {sorted(blockers)}; this run's evidence is uninformative",
            )
            continue
        if status in (OK, SUSPECTED) and confirmed & _downstream(decl, cid):
            downstream_failures = sorted(confirmed & _downstream(decl, cid))
            statuses[cid] = (SUSPECTED, f"upstream of failing {downstream_failures}")

    candidates: list[Candidate] = []
    for cid, (status, reason) in statuses.items():
        if status == OK:
            continue
        contracts = [c.id for c in decl.contracts_for_subject(cid)]
        component_slices = by_subject.get(cid, [])
        relevant = False
        if policy is not None:
            relevant = any(decision_relevant(decl, policy, slices, c) for c in contracts)
        tests = _tests_targeting(decl, cid)
        cost = min((t.cost for t in tests), default=1.0)
        candidates.append(Candidate(
            subject=cid,
            status=status,
            suspicion=_SUSPICION[status],
            decision_relevant=relevant,
            confidence=_confidence(status, component_slices),
            reason=reason,
            evidence_ids=sorted({e for s in component_slices for e in s.evidence_ids}),
            contracts=contracts,
            cost=cost,
        ))

    candidates.sort(key=lambda c: (-c.score, c.subject))

    gaps = sorted(cid for cid in components if not _tests_targeting(decl, cid))
    top = candidates[0] if candidates else None

    coverage_limited = bool(
        top is not None
        and top.status == UNOBSERVED
        and not _tests_targeting(decl, top.subject)
    )

    discriminating = None if coverage_limited else _discriminating(decl, candidates)

    if coverage_limited:
        # Rule 7.5 — do not recommend optimisation when instrumentation is the
        # limiting factor. No optimisation recommendation is produced at all.
        recommendation = (
            f"instrument {top.subject}: no registered test targets it, so its "
            f"suspicion cannot be resolved by any measurement you currently have"
        )
    elif discriminating:
        recommendation = (
            f"run {discriminating['test_id']} — it separates "
            f"{discriminating['separates']} before optimising any of them"
        )
    elif top is not None:
        recommendation = f"investigate {top.subject} ({top.status}): {top.reason}"
    else:
        recommendation = "no bottleneck identified; all observed components are supported"

    return Diagnosis(
        ranked=candidates,
        discriminating_test=discriminating,
        coverage_limited=coverage_limited,
        instrumentation_gaps=gaps,
        recommendation=recommendation,
        policy_id=policy.id if policy else None,
    )


def _confidence(status: str, slices: list[Slice]) -> str:
    if status == UNOBSERVED:
        return "low"
    if status == CONFIRMED:
        return "high" if slices else "medium"
    if not slices:
        return "low"
    tightest = min((s.ci_width for s in slices), default=1.0)
    return "high" if tightest < 0.2 else "medium"


def _discriminating(decl: Declarations, candidates: list[Candidate]) -> dict[str, Any] | None:
    """A test that splits the ambiguous leaders (7.4).

    "Ambiguous" means the top candidates score closely enough that the ranking
    is not really telling you which to attack. A test targeting a strict,
    non-empty subset of them turns that ambiguity into an observation, which
    beats optimising any one of them on a guess.
    """
    if len(candidates) < 2:
        return None
    top_score = candidates[0].score
    if top_score <= 0:
        return None
    tied = [c.subject for c in candidates if top_score - c.score <= 0.25 * top_score]
    if len(tied) < 2:
        return None
    tied_set = set(tied)
    best: dict[str, Any] | None = None
    for test in decl.tests.values():
        covered = tied_set & set(test.targets)
        if covered and covered != tied_set:
            candidate = {
                "test_id": test.id,
                "separates": sorted(tied_set),
                "observes": sorted(covered),
                "cost": test.cost,
            }
            if best is None or test.cost < best["cost"]:
                best = candidate
    return best
