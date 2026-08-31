"""Decision policies.

Acceptance criteria live on the policy, observed metrics live on the evidence,
and the two are joined here at evaluation time — never stored merged (9.1).

The `overrides` parameter is what makes §7's decision-relevance estimator work:
evaluate the same policy with one contract's state pinned to what it would be
at each end of its credible interval, and see whether the decision moves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .declarations import Contract, Declarations, Policy
from .model import (
    STATE_CONTESTED,
    STATE_INSUFFICIENT,
    STATE_REFUTED,
    STATE_SUPPORTED,
    Slice,
)

ADOPT = "adopt"
REJECT = "reject"
HOLD = "hold"
ROLLBACK = "rollback"
CONDITIONAL = "conditional_deploy"
MORE_TESTING = "more_testing"


@dataclass
class Verdict:
    status: str
    reasons: list[str] = field(default_factory=list)
    conditions: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    policy_id: str = ""


def state_at_rate(contract: Contract, rate: float) -> str:
    """The state the slice would hold if the true pass rate were `rate`."""
    return STATE_SUPPORTED if rate > contract.target_rate else STATE_REFUTED


def evaluate_policy(
    decl: Declarations,
    policy: Policy,
    slices: list[Slice],
    overrides: dict[str, str] | None = None,
) -> Verdict:
    overrides = overrides or {}
    by_contract: dict[str, list[Slice]] = {}
    for sl in slices:
        by_contract.setdefault(sl.contract_id, []).append(sl)

    verdict = Verdict(status=ADOPT, policy_id=policy.id)
    conditional_envelope: list[str] = []

    for criterion in policy.criteria:
        if "safety_gates" in criterion:
            detail, blocking_state = _safety_gates(decl, by_contract, overrides)
            if detail:
                # A gate that is *unproven* is not a gate that *failed*. Both
                # block release, but calling an undemonstrated gate a rejection
                # tells the reader to go fix something that may be fine.
                outcome = REJECT if blocking_state == STATE_REFUTED else MORE_TESTING
                _weaken(verdict, outcome)
                verdict.reasons.append(f"safety gate not satisfied: {detail}")
            continue

        contract_id = criterion.get("slice")
        if not contract_id:
            continue
        contract = decl.contracts.get(contract_id)
        if contract is None:
            verdict.reasons.append(f"{contract_id}: not declared")
            verdict.status = HOLD
            continue

        required = criterion.get("require", STATE_SUPPORTED)
        contract_slices = by_contract.get(contract_id, [])
        override = overrides.get(contract_id)

        if override:
            # A hypothetical state supplied by the relevance probe. It is
            # authoritative even with no evidence, which is what lets the probe
            # ask "would knowing this change the answer?" about something that
            # has never been measured.
            states = {"(hypothetical)": override}
        elif not contract_slices:
            verdict.missing.append(f"{contract_id}: no evidence")
            _weaken(verdict, MORE_TESTING)
            continue
        else:
            states = {}
            for sl in contract_slices:
                states[sl.bucket] = sl.state
                verdict.evidence_ids.extend(sl.evidence_ids)

        if any(s == STATE_INSUFFICIENT for s in states.values()):
            thin = [b for b, s in states.items() if s == STATE_INSUFFICIENT]
            for bucket in thin:
                match = next(s for s in contract_slices if s.bucket == bucket)
                need = match.missing.get("trials_needed")
                detail = f" (need {need} more trials)" if need else ""
                verdict.missing.append(f"{contract_id}[{bucket}]{detail}")
            # Rule 5.7 with teeth: an insufficient slice cannot satisfy an
            # adopt criterion, no matter how good the point estimate looks.
            _weaken(verdict, MORE_TESTING)
            continue

        met = {b: s == required for b, s in states.items()}
        if all(met.values()):
            continue
        if any(met.values()):
            # Rule 9.5: disagreement across buckets returns an operating
            # envelope, not an average. There is no averaging path.
            passing = sorted(b for b, ok in met.items() if ok)
            failing = sorted(b for b, ok in met.items() if not ok)
            conditional_envelope.append(
                f"{contract_id}: holds under {passing}, not under {failing}"
            )
            _weaken(verdict, CONDITIONAL)
            continue

        failing_states = set(states.values())
        if failing_states == {STATE_REFUTED}:
            _weaken(verdict, REJECT)
            verdict.reasons.append(f"{contract_id}: refuted in every condition")
        elif failing_states <= {STATE_CONTESTED, STATE_INSUFFICIENT}:
            # Not demonstrated, not disproved. More trials would resolve it,
            # which is what the status should say.
            _weaken(verdict, MORE_TESTING)
            verdict.reasons.append(
                f"{contract_id}: contested — interval straddles the target rate"
            )
        else:
            _weaken(verdict, HOLD)
            verdict.reasons.append(
                f"{contract_id}: {sorted(failing_states)} does not meet required {required!r}"
            )

    if verdict.status == CONDITIONAL:
        verdict.conditions = conditional_envelope
    if verdict.status == MORE_TESTING and verdict.missing:
        verdict.reasons.append("insufficient evidence cannot satisfy an adopt criterion")

    verdict.evidence_ids = sorted(set(verdict.evidence_ids))
    verdict.risks = _risks(decl, by_contract)
    return verdict


_SEVERITY = {ADOPT: 0, CONDITIONAL: 1, MORE_TESTING: 2, HOLD: 3, REJECT: 4, ROLLBACK: 5}


def _weaken(verdict: Verdict, status: str) -> None:
    """A verdict only ever moves toward caution."""
    if _SEVERITY[status] > _SEVERITY[verdict.status]:
        verdict.status = status


def _safety_gates(
    decl: Declarations,
    by_contract: dict[str, list[Slice]],
    overrides: dict[str, str],
) -> tuple[str, str | None]:
    """Every contract measured by a mandatory test must be supported.

    A mandatory gate with no evidence fails; it does not pass by default.
    Returns (detail, blocking_state) — empty detail means satisfied. The state
    is returned so the caller can tell a refuted gate from an unproven one.
    """
    mandatory = [t for t in decl.tests.values() if t.mandatory]
    if not mandatory:
        return "", None
    gated: set[str] = set()
    for contract_id, contract in decl.contracts.items():
        if any(t.id in contract.evaluable_by for t in mandatory):
            gated.add(contract_id)
    for contract_id in sorted(gated):
        override = overrides.get(contract_id)
        if override:
            if override != STATE_SUPPORTED:
                return f"{contract_id} would be {override}", override
            continue
        contract_slices = by_contract.get(contract_id, [])
        if not contract_slices:
            return f"{contract_id} has no evidence", STATE_INSUFFICIENT
        for sl in contract_slices:
            if sl.state != STATE_SUPPORTED:
                return f"{contract_id}[{sl.bucket}] is {sl.state}", sl.state
    return "", None


def _risks(decl: Declarations, by_contract: dict[str, list[Slice]]) -> list[str]:
    risks: list[str] = []
    for contract_id, contract_slices in sorted(by_contract.items()):
        for sl in contract_slices:
            if sl.state == STATE_CONTESTED:
                risks.append(f"{contract_id}[{sl.bucket}] interval straddles the target rate")
            if sl.n_excluded:
                reasons = ", ".join(f"{k}×{v}" for k, v in sorted(sl.exclusions.items()))
                risks.append(f"{contract_id}[{sl.bucket}] excluded {sl.n_excluded} trials ({reasons})")
    for issue in decl.issues:
        if issue.code in ("UNBACKED_ASSUMPTION", "PENDING"):
            risks.append(issue.render())
    return risks


def decision_relevant(
    decl: Declarations,
    policy: Policy,
    slices: list[Slice],
    contract_id: str,
) -> bool:
    """§7's estimator, in full.

    Evaluate the declared policy at the slice's optimistic and pessimistic
    interval endpoints. If the decision differs between them, the uncertainty
    is worth resolving; if it doesn't, measuring again changes nothing no
    matter how wide the interval is.

    This is also rule 8.3 made mechanical — a test whose endpoints agree is
    redundant confirmation.
    """
    contract = decl.contracts.get(contract_id)
    if contract is None:
        return False
    relevant_slices = [s for s in slices if s.contract_id == contract_id]
    if not relevant_slices:
        # Never measured. Ask the same question, with the two hypothetical
        # states standing in for the interval endpoints. Going through the
        # policy rather than scanning criteria for a `slice:` key catches
        # contracts gated only through safety_gates.
        good = evaluate_policy(decl, policy, slices, {contract_id: STATE_SUPPORTED}).status
        bad = evaluate_policy(decl, policy, slices, {contract_id: STATE_REFUTED}).status
        return good != bad

    for sl in relevant_slices:
        optimistic = evaluate_policy(
            decl, policy, slices, {contract_id: state_at_rate(contract, sl.hi)}
        ).status
        pessimistic = evaluate_policy(
            decl, policy, slices, {contract_id: state_at_rate(contract, sl.lo)}
        ).status
        if optimistic != pessimistic:
            return True
    return False


def active_policy(decl: Declarations, policy_id: str | None = None) -> Policy | None:
    if policy_id:
        return decl.policies.get(policy_id)
    return next(iter(decl.policies.values()), None)
