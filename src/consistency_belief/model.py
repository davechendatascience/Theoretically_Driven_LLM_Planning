"""Consistency Belief Model.

Computes the verification state of each branch and lemma in the Proof DAG
from graph topology and immutable verification trials.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .graph import ProofDAG
from .ids import set_hash

PROVEN = "proven"
REFUTED = "refuted"
OBLIGATION = "obligation"
STALE = "stale"
UNGROUNDED = "ungrounded"
DOUBTED = "doubted"

STATES = (PROVEN, REFUTED, OBLIGATION, STALE, UNGROUNDED, DOUBTED)


@dataclass
class ConsistencySlice:
    target_id: str
    kind: str
    statement: str
    premises: list[str]
    axiomatic_basis: list[str]
    state: str
    n_trials: int
    n_passed: int
    consensus_rate: float
    n_min: int
    min_consensus: float
    counterexamples: list[str] = field(default_factory=list)
    trial_ids: list[str] = field(default_factory=list)
    set_handle: str = "000000"
    issues: list[str] = field(default_factory=list)
    staged: bool = False            # proposed, not declared at git HEAD: cannot support decide()
    n_superseded: int = 0           # trials that verified an earlier statement of this node
    n_stale: int = 0                # trials recorded before a premise upstream was restated

    @property
    def is_sound(self) -> bool:
        return self.state == PROVEN


def compute_consistency(
    dag: ProofDAG,
    trials: list[dict[str, Any]],
    targets: list[str] | None = None,
    stale_ancestors: set[str] | None = None,
) -> list[ConsistencySlice]:
    """Compute verification status slices for all targetable nodes."""
    stale_set = stale_ancestors or set()
    valid_trials = [t for t in trials if t.get("validity") == "valid"]

    # Index trials by target
    by_target: dict[str, list[dict[str, Any]]] = {}
    for t in valid_trials:
        target = t.get("target_id")
        if target:
            by_target.setdefault(target, []).append(t)

    candidate_ids = targets or [
        nid for nid, node in dag.nodes.items()
        if node.kind in ("lemma", "branch", "change")
    ]

    slices: list[ConsistencySlice] = []

    for target_id in sorted(candidate_ids):
        node = dag.get(target_id)
        if not node:
            continue

        grounded, ground_issues = dag.is_grounded(target_id)
        anc = dag.ancestors(target_id)
        axioms = sorted(dag.axiomatic_basis(target_id))
        target_trials, n_superseded, stale_trials = _partition(dag, node, by_target.get(target_id, []))
        restated = _restated_premises(dag, target_id, stale_trials)

        n_trials = len(target_trials)
        n_passed = sum(1 for t in target_trials if t.get("passed", False))
        consensus_rate = (n_passed / n_trials) if n_trials > 0 else 0.0

        n_min = int(node.metadata.get("n_min", 3))
        min_consensus = float(node.metadata.get("min_consensus", 0.8))

        counterexamples = [
            t["counterexample"]
            for t in target_trials
            if t.get("counterexample")
        ]

        trial_ids = sorted(t["id"] for t in target_trials if "id" in t)
        handle = set_hash(trial_ids)

        # Determine state
        if not grounded:
            state = UNGROUNDED
            issues = ground_issues
        elif any(a in stale_set for a in anc) or target_id in stale_set:
            state = STALE
            issues = [f"ancestor in {sorted(anc & stale_set)} was modified or invalidated"]
        elif counterexamples or any(t.get("outcome") == "falsified" for t in target_trials):
            state = REFUTED
            issues = [f"falsified by counterexample: {counterexamples[0]}" if counterexamples else "falsified by probe"]
        elif stale_trials and n_trials < n_min:
            state = STALE
            issues = [f"{len(stale_trials)} trial(s) verified it before {', '.join(restated)} was restated; "
                      f"re-verify ({n_trials}/{n_min} under the current premises)"]
        elif n_trials < n_min:
            state = OBLIGATION
            issues = [f"insufficient verification trials: {n_trials}/{n_min} completed"]
            if n_superseded:
                issues.append(f"{n_superseded} earlier trial(s) verified a previous statement and no longer count")
        elif consensus_rate < min_consensus:
            state = DOUBTED
            issues = [f"consensus rate {consensus_rate:.2f} below required {min_consensus:.2f}"]
        else:
            state = PROVEN
            issues = []

        slices.append(ConsistencySlice(
            target_id=target_id,
            kind=node.kind,
            statement=node.statement,
            premises=sorted(node.premises),
            axiomatic_basis=axioms,
            state=state,
            n_trials=n_trials,
            n_passed=n_passed,
            consensus_rate=consensus_rate,
            n_min=n_min,
            min_consensus=min_consensus,
            counterexamples=counterexamples,
            trial_ids=trial_ids,
            set_handle=handle,
            issues=issues,
            staged=node.staged,
            n_superseded=n_superseded,
            n_stale=len(stale_trials),
        ))

    return slices


def _partition(dag: ProofDAG, node, trials: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int, list[dict[str, Any]]]:
    """Split a node's trials into those that vouch for it as it stands now, a count of those
    that verified an earlier statement, and those recorded before a premise upstream was
    restated. Trials recorded before fingerprints existed carry none and count as current."""
    current_statement = node.fingerprint()
    current_basis = dag.basis_fingerprints(node.id)
    current, superseded, stale = [], 0, []
    for t in trials:
        if "statement_sha" not in t:
            current.append(t)
        elif t["statement_sha"] != current_statement:
            superseded += 1
        elif t.get("basis") is not None and t["basis"] != current_basis:
            stale.append(t)
        else:
            current.append(t)
    return current, superseded, stale


def _restated_premises(dag: ProofDAG, node_id: str, stale_trials: list[dict[str, Any]]) -> list[str]:
    current = dag.basis_fingerprints(node_id)
    changed: set[str] = set()
    for t in stale_trials:
        recorded = t.get("basis") or {}
        changed |= {k for k in set(recorded) | set(current) if recorded.get(k) != current.get(k)}
    return sorted(changed)
