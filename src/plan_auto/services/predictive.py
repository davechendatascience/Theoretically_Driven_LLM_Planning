"""Deterministic predictive checks (Bayesian-workflow blueprint §8, v0).

Posterior predictive checking without numeric inference: a prediction with an
expected_range is judged against structured MetricObservations recorded in
evidence linked to the plan; a disconfirming pattern counts as observed only
when evidence explicitly declares its id. Direction-only predictions with no
range are reported inconclusive rather than guessed — UNKNOWN stays a
first-class answer here too.
"""

from __future__ import annotations

from ..models import (
    EvidenceRecord,
    Plan,
    PredictiveCheck,
    PredictiveContract,
)
from ..models.predictive import PriorCheck, RelationFinding


def contract_structural_gaps(contract: PredictiveContract | None) -> list[str]:
    """Repair instructions for an incomplete contract (blueprint Phase B)."""
    if contract is None:
        return [
            'Add predictive_contract: {"context_fixed": [...], "predictions": '
            '[{"metric_id": ..., "direction": increase|decrease|no_change, '
            '"expected_range": [lo, hi]}], "disconfirming_patterns": '
            '[{"description": ..., "suggested_model_expansion": ...}]}.'
        ]
    gaps: list[str] = []
    if not contract.predictions:
        gaps.append(
            "predictive_contract has no predictions: state at least one observable "
            "the causal hypothesis says should move (or stay invariant)."
        )
    if not contract.context_fixed:
        gaps.append(
            "predictive_contract.context_fixed is empty: name what is held fixed "
            "(eval protocol, scenes/seeds, budget, API) so the comparison is valid."
        )
    if not contract.disconfirming_patterns:
        gaps.append(
            "predictive_contract has no disconfirming_patterns: state at least one "
            "observable pattern that would show the causal story is wrong."
        )
    has_expansion = bool(contract.next_expansions) or any(
        p.suggested_model_expansion for p in contract.disconfirming_patterns
    )
    if not has_expansion:
        gaps.append(
            "Name a mismatch-to-expansion path: set next_expansions or a "
            "suggested_model_expansion on a disconfirming pattern, so failure "
            "points at the next model component instead of generic retry."
        )
    return gaps


def posterior_check(plan: Plan, evidence: list[EvidenceRecord]) -> PredictiveCheck:
    contract = plan.predictive_contract
    if contract is None:
        return PredictiveCheck(plan_id=plan.id, status="not_ready")

    linked = [e for e in evidence if e.linked_plan_id == plan.id]
    if not linked:
        return PredictiveCheck(plan_id=plan.id, status="not_ready")

    # Latest structured observation per metric wins.
    observed: dict[str, float] = {}
    for record in sorted(linked, key=lambda e: e.created_at):
        for obs in record.observations:
            observed[obs.metric_id] = obs.value

    known_patterns = {p.id: p for p in contract.disconfirming_patterns}
    observed_patterns = sorted(
        {
            pid
            for record in linked
            for pid in record.observed_pattern_ids
            if pid in known_patterns
        }
    )

    matched: list[str] = []
    violated: list[str] = []
    inconclusive: list[str] = []
    notes: list[str] = []
    for prediction in contract.predictions:
        value = observed.get(prediction.metric_id)
        if value is None or prediction.expected_range is None:
            inconclusive.append(prediction.id)
            continue
        low, high = prediction.expected_range
        if low <= value <= high:
            matched.append(prediction.id)
        else:
            violated.append(prediction.id)
            notes.append(
                f"{prediction.metric_id}={value} outside expected "
                f"[{low}, {high}] ({prediction.direction})"
            )
    for pid in observed_patterns:
        notes.append(f"disconfirming pattern {pid} observed: "
                     f"{known_patterns[pid].description}")

    if violated or observed_patterns:
        status = "mismatch"
    elif matched:
        status = "consistent"
    elif observed:
        status = "inconclusive"
    else:
        # Evidence exists but carries no structured observations.
        status = "inconclusive"

    recommended = None
    if status == "mismatch":
        for pid in observed_patterns:
            if known_patterns[pid].suggested_model_expansion:
                recommended = known_patterns[pid].suggested_model_expansion
                break
        if recommended is None and contract.next_expansions:
            recommended = contract.next_expansions[0]

    return PredictiveCheck(
        plan_id=plan.id,
        status=status,
        observed_evidence_ids=[e.id for e in linked],
        matched_prediction_ids=matched,
        violated_prediction_ids=violated,
        observed_pattern_ids=observed_patterns,
        inconclusive_prediction_ids=inconclusive,
        discrepancy_summary="; ".join(notes),
        recommended_expansion=recommended,
    )


def _parse_relation(text: str) -> tuple[str, list[str]] | None:
    """Parse `X = Y + Z` or `X = Y`. Anything else is unparseable, never guessed."""
    if text.count("=") != 1:
        return None
    lhs, rhs = text.split("=")
    target = lhs.strip()
    operands = [part.strip() for part in rhs.split("+")]
    if not target or len(operands) > 2 or not all(operands):
        return None
    return target, operands


def prior_contract_check(contract: PredictiveContract | None) -> PriorCheck:
    """Decide whether a contract's own bands admit any solution, before data exists.

    P-0001 measured that a jointly unsatisfiable contract returns `consistent`
    posteriorly: once data exists every value sits inside its own band, so no
    posterior check can catch it. This decides it beforehand, by interval
    arithmetic over declared metric_relations.

    Per relation, for `X = Y + Z` with Y in [ylo,yhi] and Z in [zlo,zhi], the
    induced interval for X is [ylo+zlo, yhi+zhi]. Disjoint from X's declared
    band means no solution exists. Any metric lacking an expected_range makes
    the relation undecidable and it is reported inconclusive rather than
    guessed — UNKNOWN stays first-class here as it does posteriorly.

    Aggregation precedence: UNSATISFIABLE > INCONCLUSIVE > SATISFIABLE. One
    impossible constraint suffices. A contract with no relations is satisfiable
    by vacuity. An unparseable relation aggregates as inconclusive and is also
    reported in `unparseable_relations`, never silently dropped: dropping one
    would make an impossible contract look satisfiable.

    KNOWN INCOMPLETE (preregistered in P-0003): per-relation propagation misses
    contradictions that only appear when relations share a variable, and a
    marginal overlap returns satisfiable while still permitting the posterior
    pathology. This is sound but not complete.

    Pure: reads only the contract, wired into no caller.
    """
    if contract is None:
        return PriorCheck(status="inconclusive", summary="no contract to check")

    bands = {p.metric_id: p.expected_range for p in contract.predictions}
    unenforceable = [
        p.id
        for p in contract.predictions
        if p.direction == "no_change" and p.expected_range is None
    ]

    findings: list[RelationFinding] = []
    unparseable: list[str] = []

    for raw in contract.metric_relations:
        parsed = _parse_relation(raw)
        if parsed is None:
            unparseable.append(raw)
            findings.append(
                RelationFinding(
                    relation=raw,
                    status="unparseable",
                    detail="grammar is 'X = Y + Z' or 'X = Y'",
                )
            )
            continue

        target, operands = parsed
        involved = [target, *operands]
        missing = [m for m in involved if bands.get(m) is None]
        if missing:
            findings.append(
                RelationFinding(
                    relation=raw,
                    status="inconclusive",
                    detail=f"no expected_range for {', '.join(sorted(set(missing)))}",
                )
            )
            continue

        induced_lo = sum(bands[m][0] for m in operands)
        induced_hi = sum(bands[m][1] for m in operands)
        declared_lo, declared_hi = bands[target]
        overlaps = induced_lo <= declared_hi and declared_lo <= induced_hi
        findings.append(
            RelationFinding(
                relation=raw,
                status="satisfiable" if overlaps else "unsatisfiable",
                induced_range=(induced_lo, induced_hi),
                declared_range=(declared_lo, declared_hi),
                detail=(
                    f"induced [{induced_lo}, {induced_hi}] "
                    f"{'overlaps' if overlaps else 'is disjoint from'} "
                    f"declared [{declared_lo}, {declared_hi}]"
                ),
            )
        )

    statuses = {f.status for f in findings}
    if "unsatisfiable" in statuses:
        status = "unsatisfiable"
    elif "inconclusive" in statuses or "unparseable" in statuses:
        status = "inconclusive"
    else:
        status = "satisfiable"

    notes = [f.detail for f in findings if f.detail]
    if unenforceable:
        notes.append(
            f"unenforceable invariances (no_change with no expected_range): "
            f"{', '.join(unenforceable)}"
        )
    if not contract.metric_relations:
        notes.append("no metric_relations declared: satisfiable by vacuity")

    return PriorCheck(
        status=status,
        relation_findings=findings,
        unenforceable_invariances=unenforceable,
        unparseable_relations=unparseable,
        summary="; ".join(notes),
    )
