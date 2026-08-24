"""Unit tests for the micro-damping engine (v0.4.0)."""

import math
import pytest

from damped_plan_mcp.models.evidence import EvidenceClaim, SubtaskEvidenceBundle
from damped_plan_mcp.services import micro_damping


def test_provenance_veracity_lookup():
    assert micro_damping.lookup_provenance_veracity("tool:ast_parser") == 1.00
    assert micro_damping.lookup_provenance_veracity("tool:unit_test") == 0.95
    assert micro_damping.lookup_provenance_veracity("test") == 0.95
    assert micro_damping.lookup_provenance_veracity("simulation") == 0.85
    assert micro_damping.lookup_provenance_veracity("search:grep") == 0.75
    assert micro_damping.lookup_provenance_veracity("manual_review") == 0.50
    # Fallback default for unknown tool
    assert micro_damping.lookup_provenance_veracity("custom:unknown") == 0.70


def test_coverage_ratio_calculation():
    required = ["ast_node", "symbol_type", "docstring", "parameters"]
    observed = ["ast_node", "symbol_type"]
    ratio = micro_damping.calculate_coverage_ratio(observed, required)
    assert ratio == 0.5

    # Full coverage
    ratio_full = micro_damping.calculate_coverage_ratio(
        ["ast_node", "symbol_type", "docstring", "parameters", "extra"],
        required,
    )
    assert ratio_full == 1.0

    # Empty required means full coverage by default
    assert micro_damping.calculate_coverage_ratio(["a"], []) == 1.0


def test_credibility_aggregation():
    claims = [
        EvidenceClaim(
            target_subtask_id="sub-1",
            assertion_statement="AST parsed",
            source_provenance="tool:ast_parser",
            credibility_score=1.0,
        ),
        EvidenceClaim(
            target_subtask_id="sub-1",
            assertion_statement="Type checked",
            source_provenance="tool:type_checker",
            credibility_score=0.9,
        ),
        EvidenceClaim(
            target_subtask_id="sub-1",
            assertion_statement="Code reviewed",
            source_provenance="manual_review",
            credibility_score=0.5,
        ),
    ]

    # Weighted mean
    agg_mean = micro_damping.aggregate_credibility(claims, method="weighted_mean")
    assert pytest.approx(agg_mean, 0.001) == (1.0 + 0.9 + 0.5) / 3.0

    # Noisy-OR
    agg_noisy_or = micro_damping.aggregate_credibility(claims, method="noisy_or")
    expected_noisy_or = 1.0 - (0.0 * 0.1 * 0.5)
    assert pytest.approx(agg_noisy_or, 0.001) == expected_noisy_or

    # Product
    agg_prod = micro_damping.aggregate_credibility(claims, method="product")
    expected_prod = 1.0 * 0.9 * 0.5
    assert pytest.approx(agg_prod, 0.001) == expected_prod


def test_joint_quality_metric_and_step_penalty():
    # step 0: no penalty -> exp(0) = 1.0
    q0 = micro_damping.compute_joint_quality(
        coverage_ratio=1.0,
        credibility_index=1.0,
        step_index=0,
        max_steps=10,
        w_c=0.5,
        gamma=0.15,
    )
    assert pytest.approx(q0, 0.001) == 1.0

    # step 10: exp(-0.15 * 10 / 10) = exp(-0.15) ≈ 0.8607
    q10 = micro_damping.compute_joint_quality(
        coverage_ratio=1.0,
        credibility_index=1.0,
        step_index=10,
        max_steps=10,
        w_c=0.5,
        gamma=0.15,
    )
    expected_penalty = math.exp(-0.15)
    assert pytest.approx(q10, 0.001) == expected_penalty

    # Quality decreases with higher steps (critical damping penalty)
    q5 = micro_damping.compute_joint_quality(1.0, 1.0, 5, 10, 0.5, 0.15)
    assert q0 > q5 > q10


def test_stopping_invariant():
    # Warmup check: step 1 with min_steps=2 should not stop even if quality is low
    stop, status = micro_damping.evaluate_stopping_invariant(
        quality_history=[],
        current_quality=0.3,
        step_index=1,
        max_steps=10,
        min_steps=2,
    )
    assert not stop
    assert status == "continue"

    # Step budget exhausted
    stop, status = micro_damping.evaluate_stopping_invariant(
        quality_history=[0.5, 0.6],
        current_quality=0.6,
        step_index=10,
        max_steps=10,
    )
    assert stop
    assert status == "exhausted_budget"

    # Convergence (Phi >= tau)
    stop, status = micro_damping.evaluate_stopping_invariant(
        quality_history=[0.5],
        current_quality=0.90,
        step_index=2,
        max_steps=10,
        tau_evidence=0.85,
    )
    assert stop
    assert status == "converged"

    # Diminishing returns (Delta Phi < epsilon)
    stop, status = micro_damping.evaluate_stopping_invariant(
        quality_history=[0.70],
        current_quality=0.72,
        step_index=3,
        max_steps=10,
        tau_evidence=0.85,
        epsilon_threshold=0.05,
    )
    assert stop
    assert status == "diminishing_returns"


def test_build_subtask_bundle():
    claims = [
        EvidenceClaim(
            claim_id="CLM-0001",
            target_subtask_id="sub-auth",
            assertion_statement="Found auth header parsing",
            observed_payload={"auth_header": True},
            source_provenance="search:grep",
            credibility_score=0.75,
            coverage_ratio=0.5,
            step_index=1,
        ),
        EvidenceClaim(
            claim_id="CLM-0002",
            target_subtask_id="sub-auth",
            assertion_statement="AST verified token verification function",
            observed_payload={"auth_header": True, "token_verify": True},
            source_provenance="tool:ast_parser",
            credibility_score=1.0,
            coverage_ratio=1.0,
            step_index=2,
            is_terminal=True,
        ),
    ]

    bundle = micro_damping.build_subtask_bundle(
        subtask_id="sub-auth",
        claims=claims,
        required_attributes=["auth_header", "token_verify"],
        max_steps=5,
        tau_evidence=0.80,
    )

    assert bundle.subtask_id == "sub-auth"
    assert len(bundle.claims) == 2
    assert bundle.total_coverage == 1.0
    assert bundle.aggregate_credibility > 0.8
    assert bundle.damping_status == "converged"
