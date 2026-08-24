"""Critically damped micro-query engine & evidence calibration (v0.4.0).

Transforms exploratory diagnostic probes and diagnostic tool invocations into
a minimum-step evidence collection subproblem governed by an explicit mathematical
stopping invariant (zeta = 1.0).

Joint evidence quality:
    Phi(E_k) = (w_c * C_k + (1 - w_c) * R_k) * exp(-gamma * (k / k_max))

Stopping condition:
    Phi(E_k) >= tau_evidence OR Delta Phi(E_k) < epsilon_threshold
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Literal

from ..models.evidence import DampingStatus, EvidenceClaim, SubtaskEvidenceBundle

DEFAULT_PROVENANCE_VERACITY: dict[str, float] = {
    "tool:ast_parser": 1.00,
    "tool:type_checker": 0.95,
    "tool:unit_test": 0.95,
    "test": 0.95,
    "tool:linter": 0.90,
    "simulation": 0.85,
    "log": 0.85,
    "profiling": 0.85,
    "solver": 0.85,
    "benchmark": 0.80,
    "search:grep": 0.75,
    "search:ripgrep": 0.75,
    "search:symbol": 0.75,
    "search:github_api": 0.70,
    "commit": 0.70,
    "paper": 0.65,
    "search:web": 0.60,
    "manual_review": 0.50,
    "heuristic": 0.50,
}


def lookup_provenance_veracity(provenance: str) -> float:
    """Look up default veracity score for a given source provenance string."""
    prov_lower = provenance.strip().lower()
    if prov_lower in DEFAULT_PROVENANCE_VERACITY:
        return DEFAULT_PROVENANCE_VERACITY[prov_lower]
    for prefix, veracity in DEFAULT_PROVENANCE_VERACITY.items():
        if prov_lower.startswith(prefix) or prefix in prov_lower:
            return veracity
    return 0.70


def calculate_coverage_ratio(
    observed_attributes: Iterable[str],
    required_attributes: Iterable[str],
) -> float:
    """Fraction of required fields / target attributes resolved by query returns.

    C_k = |Observed Target Attributes intersect Required Target Attributes| / |Required Target Attributes|
    """
    req_set = {str(a).strip() for a in required_attributes if str(a).strip()}
    if not req_set:
        return 1.0
    obs_set = {str(a).strip() for a in observed_attributes if str(a).strip()}
    resolved = obs_set.intersection(req_set)
    return len(resolved) / len(req_set)


def aggregate_credibility(
    claims: list[EvidenceClaim] | list[float],
    method: Literal["weighted_mean", "noisy_or", "product"] = "weighted_mean",
) -> float:
    """Aggregate claim credibility scores into a composite Credibility Index R_k in [0, 1]."""
    if not claims:
        return 1.0

    scores: list[float] = [
        float(c.credibility_score) if isinstance(c, EvidenceClaim) else float(c)
        for c in claims
    ]

    if method == "noisy_or":
        comp = 1.0
        for s in scores:
            clamped = max(0.0, min(1.0, s))
            comp *= (1.0 - clamped)
        return 1.0 - comp

    if method == "product":
        prod = 1.0
        for s in scores:
            prod *= max(0.0, min(1.0, s))
        return prod

    # Default: weighted_mean / arithmetic average
    return max(0.0, min(1.0, sum(scores) / len(scores)))


def compute_joint_quality(
    coverage_ratio: float,
    credibility_index: float,
    step_index: int,
    max_steps: int = 10,
    w_c: float = 0.5,
    gamma: float = 0.15,
) -> float:
    """Joint Evidence Quality Metric Phi(E_k) with exponential step penalty for critical damping.

    Phi(E_k) = (w_c * C_k + (1 - w_c) * R_k) * exp(-gamma * (k / k_max))
    """
    c_k = max(0.0, min(1.0, coverage_ratio))
    r_k = max(0.0, min(1.0, credibility_index))
    k = max(0, step_index)
    k_max = max(1, max_steps)

    step_penalty = math.exp(-gamma * (k / k_max))
    base_quality = (w_c * c_k) + ((1.0 - w_c) * r_k)
    return max(0.0, min(1.0, base_quality * step_penalty))


def evaluate_stopping_invariant(
    quality_history: list[float],
    current_quality: float,
    step_index: int,
    max_steps: int = 10,
    tau_evidence: float = 0.85,
    epsilon_threshold: float = 0.05,
    min_steps: int = 2,
) -> tuple[bool, DampingStatus | Literal["continue"]]:
    """Check critical damping stopping invariant (zeta approx 1.0).

    Halts if:
    1. Hard quota exceeded: k >= max_steps -> 'exhausted_budget'
    2. Warmup met (k >= min_steps) and Phi(E_k) >= tau_evidence -> 'converged'
    3. Warmup met (k >= min_steps) and Delta Phi(E_k) < epsilon_threshold -> 'diminishing_returns'
    """
    if step_index >= max_steps:
        return True, "exhausted_budget"

    # Enforce warmup steps so discrete initial probes don't halt prematurely
    if step_index < min_steps:
        return False, "continue"

    if current_quality >= tau_evidence:
        return True, "converged"

    if quality_history:
        delta_phi = current_quality - quality_history[-1]
        if delta_phi < epsilon_threshold:
            return True, "diminishing_returns"

    return False, "continue"


def build_subtask_bundle(
    subtask_id: str,
    claims: list[EvidenceClaim],
    required_attributes: Iterable[str] | None = None,
    max_steps: int = 10,
    tau_evidence: float = 0.85,
    epsilon_threshold: float = 0.05,
    min_steps: int = 2,
    w_c: float = 0.5,
    gamma: float = 0.15,
) -> SubtaskEvidenceBundle:
    """Evaluate a sequence of claims for a subtask and assemble a SubtaskEvidenceBundle."""
    if not claims:
        return SubtaskEvidenceBundle(
            subtask_id=subtask_id,
            claims=[],
            aggregate_credibility=1.0,
            total_coverage=0.0,
            damping_status="converged",
            residual_variance=0.0,
        )

    # Sort claims by step_index
    sorted_claims = sorted(claims, key=lambda c: c.step_index)
    req_attrs = set(required_attributes) if required_attributes else set()

    # Track cumulative observed attributes
    observed_attrs: set[str] = set()
    quality_history: list[float] = []
    final_status: DampingStatus = "converged"

    for idx, claim in enumerate(sorted_claims):
        if claim.observed_payload:
            observed_attrs.update(claim.observed_payload.keys())

        # Compute running coverage & credibility
        cov = (
            calculate_coverage_ratio(observed_attrs, req_attrs)
            if req_attrs
            else max(c.coverage_ratio for c in sorted_claims[: idx + 1])
        )
        cred = aggregate_credibility(sorted_claims[: idx + 1], method="weighted_mean")
        q = compute_joint_quality(
            coverage_ratio=cov,
            credibility_index=cred,
            step_index=claim.step_index or (idx + 1),
            max_steps=max_steps,
            w_c=w_c,
            gamma=gamma,
        )

        should_stop, status = evaluate_stopping_invariant(
            quality_history=quality_history,
            current_quality=q,
            step_index=claim.step_index or (idx + 1),
            max_steps=max_steps,
            tau_evidence=tau_evidence,
            epsilon_threshold=epsilon_threshold,
            min_steps=min_steps,
        )
        quality_history.append(q)

        if should_stop:
            final_status = status if status != "continue" else "converged"
            if claim.is_terminal:
                break
        elif claim.is_terminal:
            final_status = "converged"
            break

    total_cov = (
        calculate_coverage_ratio(observed_attrs, req_attrs)
        if req_attrs
        else (sorted_claims[-1].coverage_ratio if sorted_claims else 1.0)
    )
    agg_cred = aggregate_credibility(sorted_claims, method="weighted_mean")

    # Residual variance: variance of quality spread across trajectory
    if len(quality_history) > 1:
        mean_q = sum(quality_history) / len(quality_history)
        variance = sum((q - mean_q) ** 2 for q in quality_history) / len(quality_history)
    else:
        variance = 0.0

    return SubtaskEvidenceBundle(
        subtask_id=subtask_id,
        claims=sorted_claims,
        aggregate_credibility=agg_cred,
        total_coverage=total_cov,
        damping_status=final_status,
        residual_variance=variance,
    )
