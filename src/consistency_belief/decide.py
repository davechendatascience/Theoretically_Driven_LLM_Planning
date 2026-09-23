"""Decision engine for consistency-belief.

Evaluates design branches, component contracts, and architectural changes
against declared consistency policies.
Requires explicit human approver for ADOPT decisions.

A criterion may also carry `evidence: <state>`: the contracts the branch's derivation rule
cites must then be in that state in component-belief. That is the one gate over both
ledgers -- a design proven over a refuted measurement is proven of nothing, and one proven
over no measurement is argued, not built.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .declarations import Declarations, Policy
from .graph import ProofDAG
from .model import PROVEN, REFUTED, UNGROUNDED, ConsistencySlice

ADOPT = "adopt"
REJECT = "reject"
MORE_TESTING = "more_testing"

DECISION_STATUSES = (ADOPT, REJECT, MORE_TESTING)

_CONTRACT = re.compile(r"\bCTR-[A-Za-z0-9][A-Za-z0-9-]*\b")


@dataclass
class DecisionVerdict:
    status: str
    reasons: list[str] = field(default_factory=list)
    obligations: list[str] = field(default_factory=list)
    refutations: list[str] = field(default_factory=list)
    trial_ids: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)    # contract states the verdict rested on


def active_policy(decl: Declarations, policy_id: str | None = None) -> Policy | None:
    if policy_id and policy_id in decl.policies:
        return decl.policies[policy_id]
    if decl.policies:
        return next(iter(decl.policies.values()))
    return None


def cited_contracts(dag: ProofDAG, node_id: str) -> list[str]:
    node = dag.get(node_id)
    return sorted(set(_CONTRACT.findall(node.derivation_rule or ""))) if node else []


def evaluate_consistency_policy(
    dag: ProofDAG,
    policy: Policy,
    slices: list[ConsistencySlice],
    target_id: str | None = None,
    beliefs: dict[str, str] | None = None,
) -> DecisionVerdict:
    reasons: list[str] = []
    obligations: list[str] = []
    refutations: list[str] = []
    all_trials: list[str] = []
    evidence: list[str] = []
    absent: set[str] = set()      # named by the decision or the policy, and not in the graph

    # If target_id specified, evaluate target and its full transitive premise chain. A target that
    # is declared or staged and not in the graph failed admission -- a premise it cites is unknown,
    # removed or on a cycle -- and has no slice, so there is nothing about it to adopt.
    needed_ids: set[str] | None = None
    if target_id:
        if dag.get(target_id) is None:
            absent.add(target_id)
            obligations.append(f"{target_id} is declared but not in the proof graph: a premise it "
                               "cites is unknown, removed or on a cycle, so there is nothing to decide on")
            needed_ids = {target_id}
        else:
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
        elif s.staged:
            obligations.append(f"{s.target_id} is STAGED ({s.state.upper()}, {s.n_trials}/{s.n_min} trials): "
                               "declare it in consistency.yaml and commit before it can support a decision")
        elif s.state != PROVEN:
            obligations.append(f"{s.target_id} is {s.state.upper()} ({s.n_independent}/{s.n_min} independent trials)")

    for criterion in policy.criteria:
        branch = criterion.get("target") or criterion.get("branch")
        if not branch or (needed_ids is not None and branch not in needed_ids):
            continue
        # Every node the policy names must be in the graph. One that left it has no slice, and a
        # policy that skipped it would adopt on what is left.
        if dag.get(branch) is None:
            if branch not in absent:
                absent.add(branch)
                obligations.append(f"{branch}: the policy requires it, and it is not in the proof "
                                   "graph (a premise it cites is unknown, removed or on a cycle)")
            continue
        # The joint gate, for criteria that ask for it.
        required = criterion.get("evidence")
        if not required:
            continue
        cited = cited_contracts(dag, branch)
        if not cited:
            obligations.append(f"{branch} cites no contract: the design is argued, not measured "
                               f"(the policy requires its evidence {required})")
            continue
        if beliefs is None:
            obligations.append(f"{branch} rests on {', '.join(cited)}, and component-belief's ledger "
                               "is not readable from here")
            continue
        for contract in cited:
            state = beliefs.get(contract, "not declared")
            evidence.append(f"{contract}={state}")
            if state == required:
                continue
            if state == "refuted":
                refutations.append(f"{branch} rests on {contract}, which is REFUTED: the measurement "
                                   "contradicts the design")
            else:
                obligations.append(f"{branch} rests on {contract}, which is {state} "
                                   f"(policy requires {required})")

    if not relevant_slices and not obligations and not refutations:
        obligations.append("no lemma or branch is in scope of this decision; adopting on nothing "
                           "would adopt nothing")

    if refutations:
        status = REJECT
        reasons.append(f"Rejected: {len(refutations)} node(s) failed or ungrounded")
    elif obligations:
        status = MORE_TESTING
        reasons.append(f"More verification needed: {len(obligations)} open proof obligation(s)")
    else:
        status = ADOPT
        reasons.append(f"All {len(relevant_slices)} relevant node(s) verified and grounded in axioms")
        if evidence:
            reasons.append("Every cited contract is in the required state: " + ", ".join(evidence))

    return DecisionVerdict(
        status=status,
        reasons=reasons,
        obligations=obligations,
        refutations=refutations,
        trial_ids=sorted(set(all_trials)),
        evidence=evidence,
    )
