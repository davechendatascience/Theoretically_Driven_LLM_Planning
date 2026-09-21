"""Decision engine for consistency-belief.

Evaluates design branches, component contracts, and architectural changes
against declared consistency policies.
Requires explicit human approver for ADOPT decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .declarations import Declarations, Policy
from .graph import ProofDAG
from .model import PROVEN, REFUTED, UNGROUNDED, ConsistencySlice

ADOPT = "adopt"
REJECT = "reject"
MORE_TESTING = "more_testing"

DECISION_STATUSES = (ADOPT, REJECT, MORE_TESTING)


@dataclass
class DecisionVerdict:
    status: str
    reasons: list[str] = field(default_factory=list)
    obligations: list[str] = field(default_factory=list)
    refutations: list[str] = field(default_factory=list)
    trial_ids: list[str] = field(default_factory=list)


def active_policy(decl: Declarations, policy_id: str | None = None) -> Policy | None:
    if policy_id and policy_id in decl.policies:
        return decl.policies[policy_id]
    if decl.policies:
        return next(iter(decl.policies.values()))
    return None


def evaluate_consistency_policy(
    dag: ProofDAG,
    policy: Policy,
    slices: list[ConsistencySlice],
    target_id: str | None = None,
) -> DecisionVerdict:
    slice_map = {s.target_id: s for s in slices}
    reasons: list[str] = []
    obligations: list[str] = []
    refutations: list[str] = []
    all_trials: list[str] = []

    # If target_id specified, evaluate target and its full transitive premise chain
    if target_id:
        needed_ids = {target_id} | dag.ancestors(target_id)
        relevant_slices = [s for s in slices if s.target_id in needed_ids]
    else:
        relevant_slices = slices

    for s in relevant_slices:
        all_trials.extend(s.trial_ids)
        if s.state == REFUTED:
            refutations.append(f"{s.target_id} is REFUTED: {'; '.join(s.counterexamples or ['falsified by probe'])}")
        elif s.state == UNGROUNDED:
            refutations.append(f"{s.target_id} is UNGROUNDED: {'; '.join(s.issues)}")
        elif s.state != PROVEN:
            obligations.append(f"{s.target_id} is {s.state.upper()} ({s.n_trials}/{s.n_min} trials)")

    if refutations:
        status = REJECT
        reasons.append(f"Rejected: {len(refutations)} node(s) failed or ungrounded")
    elif obligations:
        status = MORE_TESTING
        reasons.append(f"More verification needed: {len(obligations)} open proof obligation(s)")
    else:
        status = ADOPT
        reasons.append(f"All {len(relevant_slices)} relevant node(s) verified and grounded in axioms")

    return DecisionVerdict(
        status=status,
        reasons=reasons,
        obligations=obligations,
        refutations=refutations,
        trial_ids=sorted(set(all_trials)),
    )
