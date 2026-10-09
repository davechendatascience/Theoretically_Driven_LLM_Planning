"""Consistency Belief Model.

Computes the verification state of each branch and lemma in the Proof DAG
from graph topology and immutable verification trials.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .graph import ProofDAG
from .ids import set_hash

PROVEN = "proven"
REFUTED = "refuted"
OBLIGATION = "obligation"
STALE = "stale"
UNGROUNDED = "ungrounded"
DOUBTED = "doubted"
#: Its own step is verified and a step beneath it is not: a proof modulo an open or refuted premise,
#: as a Lean theorem that uses a lemma proved by sorry. It keeps its trials and is never proven.
CONDITIONAL = "conditional"

STATES = (PROVEN, REFUTED, OBLIGATION, STALE, UNGROUNDED, DOUBTED, CONDITIONAL)

#: The order a conditional node names what it waits on: worst first, so a refuted premise leads.
_WAIT_ORDER = (REFUTED, UNGROUNDED, DOUBTED, STALE, OBLIGATION)

#: The probes one verification pass runs; listed here so an obligation can say which are untried.
PASS_STRATEGIES = ("counterexample", "entailment", "negation")


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
    gaps: list[str] = field(default_factory=list)   # entailment gaps: unproven, not refuted
    trial_ids: list[str] = field(default_factory=list)
    set_handle: str = "000000"
    issues: list[str] = field(default_factory=list)
    staged: bool = False            # proposed, not declared at git HEAD: cannot support decide()
    n_superseded: int = 0           # trials that verified an earlier statement of this node
    n_stale: int = 0                # trials recorded before a premise upstream was restated
    n_independent: int = 0          # distinct (strategy, actor) pairs among the counted trials
    strategies_tried: list[str] = field(default_factory=list)
    # The lemmas and branches beneath it whose step is not verified, with their states: what a
    # conditional node waits on. Empty for any other state.
    waiting_on: list[tuple[str, str]] = field(default_factory=list)
    # The id of the Lean certificate that currently certifies its claim, if one does. Shown beside
    # the state, never part of it: a certificate moves no proof state (DEF-lean-certificate).
    certified_by: str = ""

    @property
    def is_sound(self) -> bool:
        return self.state == PROVEN

    @property
    def untried(self) -> list[str]:
        return [s for s in PASS_STRATEGIES if s not in self.strategies_tried]


def _actor_of(trial: dict[str, Any]) -> str:
    return str(trial.get("actor") or (trial.get("repro") or {}).get("actor") or "")


def independent_trials(trials: list[dict[str, Any]]) -> tuple[int, list[str]]:
    """How many of these trials are independent, and which strategies they used.

    Rule 4.3 asks for n_min *independent* trials. Three counterexample probes from one actor are
    one probe run three times, so independence is counted as distinct (strategy, actor) pairs:
    a different attack on the same step, or the same attack by a different prober, adds to n;
    a repeat by the same actor is recorded and counts toward consensus, but not toward n.
    """
    pairs = {(str(t.get("strategy") or "counterexample"), _actor_of(t)) for t in trials}
    return len(pairs), sorted({strategy for strategy, _ in pairs})


def compute_consistency(
    dag: ProofDAG,
    trials: list[dict[str, Any]],
    targets: list[str] | None = None,
    stale_ancestors: set[str] | None = None,
    legacy: Callable[[str, str], tuple[str, dict[str, str]] | None] | None = None,
) -> list[ConsistencySlice]:
    """Compute verification status slices for the targetable nodes.

    Two passes. The first judges each lemma and branch's own step from its trials. The second reads
    a node whose step is verified as proven only when every lemma and branch beneath it has a
    verified step too, and as conditional otherwise (DEF-proof-state) -- so a premise refuted after
    its dependents were verified reaches them on the next read, whatever order the trials came in.
    """
    stale_set = stale_ancestors or set()
    valid_trials = [t for t in trials if t.get("validity") == "valid"]

    # Index trials by target
    by_target: dict[str, list[dict[str, Any]]] = {}
    for t in valid_trials:
        target = t.get("target_id")
        if target:
            by_target.setdefault(target, []).append(t)

    derived = [nid for nid, node in dag.nodes.items() if node.kind in ("lemma", "branch", "change")]
    candidate_ids = targets or derived
    # Every step beneath a target is judged too: whether the target is proven turns on them.
    judged = set(candidate_ids) | {a for t in candidate_ids if dag.get(t) for a in dag.ancestors(t)}
    candidate_ids = [nid for nid in derived if nid in judged] + [t for t in candidate_ids if t not in derived]

    slices: list[ConsistencySlice] = []

    for target_id in sorted(candidate_ids):
        node = dag.get(target_id)
        if not node:
            continue

        grounded, ground_issues = dag.is_grounded(target_id)
        anc = dag.ancestors(target_id)
        axioms = sorted(dag.axiomatic_basis(target_id))
        target_trials, n_superseded, stale_trials = _partition(dag, node, by_target.get(target_id, []), legacy)
        restated = _restated_premises(dag, target_id, stale_trials)

        n_trials = len(target_trials)
        n_passed = sum(1 for t in target_trials if t.get("passed", False))
        consensus_rate = (n_passed / n_trials) if n_trials > 0 else 0.0
        n_independent, strategies = independent_trials(target_trials)
        untried = [s for s in PASS_STRATEGIES if s not in strategies]

        # A proof rests on at least one trial: a declared minimum below one would let a node
        # with no trials at all come out proven.
        n_min = max(1, int(node.metadata.get("n_min", 3)))
        min_consensus = float(node.metadata.get("min_consensus", 0.8))

        # Only a falsified probe refutes. A gap -- a missing premise, an unproven step -- leaves
        # the claim unproven and counts against consensus, but it is not a counterexample,
        # whatever evidence text it carries.
        counterexamples = [
            t.get("counterexample") or t.get("reasoning") or "falsified by probe"
            for t in target_trials
            if t.get("outcome") == "falsified"
        ]
        gaps = [
            t.get("counterexample") or t.get("reasoning") or "entailment gap"
            for t in target_trials
            if t.get("outcome") == "gap"
        ]

        trial_ids = sorted(t["id"] for t in target_trials if "id" in t)
        handle = set_hash(trial_ids)

        def shortfall() -> str:
            hint = f"; untried: {', '.join(untried)}" if untried else ""
            repeats = n_trials - n_independent
            repeat_note = (f"; {repeats} repeat(s) of a strategy by the same actor do not add"
                           if repeats else "")
            return f"{n_independent}/{n_min} independent{hint}{repeat_note}"

        # Determine state
        if not grounded:
            state = UNGROUNDED
            issues = ground_issues
        elif any(a in stale_set for a in anc) or target_id in stale_set:
            state = STALE
            issues = [f"ancestor in {sorted(anc & stale_set)} was modified or invalidated"]
        elif counterexamples:
            state = REFUTED
            issues = [f"falsified by counterexample: {counterexamples[0]}"]
        elif stale_trials and n_independent < n_min:
            state = STALE
            issues = [f"{len(stale_trials)} trial(s) verified it before {', '.join(restated)} was restated; "
                      f"re-verify ({shortfall()} under the current premises)"]
        elif n_independent < n_min:
            state = OBLIGATION
            issues = [f"insufficient verification trials: {shortfall()}"]
            if n_superseded:
                issues.append(f"{n_superseded} earlier trial(s) verified a previous statement and no longer count")
        elif consensus_rate < min_consensus:
            state = DOUBTED
            issues = [f"consensus rate {consensus_rate:.2f} below required {min_consensus:.2f}"]
            if gaps:
                issues.append(f"entailment gap: {gaps[0]}")
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
            gaps=gaps,
            trial_ids=trial_ids,
            set_handle=handle,
            issues=issues,
            staged=node.staged,
            n_superseded=n_superseded,
            n_stale=len(stale_trials),
            n_independent=n_independent,
            strategies_tried=strategies,
        ))

    # Second pass: a verified step over an unverified one is a proof modulo that premise.
    step = {s.target_id: s.state for s in slices}
    for s in slices:
        if s.state != PROVEN:
            continue
        waiting = sorted(((a, step[a]) for a in dag.ancestors(s.target_id) if a in step and step[a] != PROVEN),
                         key=lambda w: (_WAIT_ORDER.index(w[1]) if w[1] in _WAIT_ORDER else len(_WAIT_ORDER), w[0]))
        if waiting:
            s.state = CONDITIONAL
            s.waiting_on = waiting
            s.issues = [f"its own step is verified; it rests on {len(waiting)} step(s) that are not: "
                        + ", ".join(f"{a} ({state})" for a, state in waiting)]
    wanted = set(targets) if targets else None
    return [s for s in slices if wanted is None or s.target_id in wanted]


def _partition(dag: ProofDAG, node, trials: list[dict[str, Any]],
               legacy: Callable[[str, str], tuple[str, dict[str, str]] | None] | None = None,
               ) -> tuple[list[dict[str, Any]], int, list[dict[str, Any]]]:
    """Split a node's trials into those that vouch for it as it stands now, a count of those
    that verified an earlier statement, and those recorded before a premise upstream was
    restated.

    A trial recorded before trials carried fingerprints is judged by the ones its target and
    its premises had in the build when it was made (DEF-current-trial), which `legacy`
    reconstructs from history; one whose target that build did not hold verified something
    that cannot be recovered, and is set aside like a superseded one. Without `legacy` -- no
    history to read -- such a trial counts as current, as it always had."""
    current_statement = node.fingerprint()
    current_read = dag.premise_statements(node.id)
    current_premises = {pid: dag.nodes[pid].fingerprint() for pid in node.premises if pid in dag.nodes}
    current, superseded, stale = [], 0, []
    for t in trials:
        if "statement_sha" not in t:
            if legacy is None:
                current.append(t)
                continue
            then = legacy(node.id, str(t.get("timestamp") or ""))
            if then is None:
                superseded += 1
                continue
            t = {**t, "statement_sha": then[0], "basis": then[1]}
        if t["statement_sha"] != current_statement:
            superseded += 1
        elif _premises_moved(t, current_read, current_premises):
            stale.append(t)
        else:
            current.append(t)
    return current, superseded, stale


def _premises_moved(trial: dict[str, Any], read: dict[str, str], premises: dict[str, str]) -> list[str]:
    """The premises the target cites whose statement is no longer the one the trial was judged
    from (DEF-current-trial). A trial that recorded statements is compared on them; one that
    recorded fingerprints, on its cited premises' fingerprints, which change with any restatement.
    Nothing further upstream is compared: the step never read it."""
    if trial.get("read") is not None:
        recorded = trial["read"]
        return sorted(pid for pid in read if recorded.get(pid) != read[pid])
    if trial.get("basis") is not None:
        recorded = trial["basis"]
        return sorted(pid for pid in premises if recorded.get(pid) != premises[pid])
    return []


def _restated_premises(dag: ProofDAG, node_id: str, stale_trials: list[dict[str, Any]]) -> list[str]:
    node = dag.nodes[node_id]
    read = dag.premise_statements(node_id)
    premises = {pid: dag.nodes[pid].fingerprint() for pid in node.premises if pid in dag.nodes}
    changed: set[str] = set()
    for t in stale_trials:
        changed |= set(_premises_moved(t, read, premises))
    return sorted(changed)
