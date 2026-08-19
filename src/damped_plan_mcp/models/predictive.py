"""Predictive-layer models (Bayesian-workflow blueprint §10).

A predictive contract is the mechanism-level claim of a plan: which
observables should move, which must stay invariant, under what fixed context,
and which observed patterns would show the causal story is wrong — each
mapped to the smallest justified model expansion. It complements, not
replaces, the plan's decision_rule (the decision-level thresholds).

The discipline is Gelman's model-checking loop (posterior predictive checks;
Gelman et al., Bayesian Data Analysis, 3rd ed., ch. 6): a model is checked by
whether replicated observations resemble real ones, and mismatch identifies
the model dimension needing expansion. v0 keeps checks deterministic —
ranges, declared patterns — with no numeric inference.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

PredictionDirection = Literal["increase", "decrease", "no_change", "non_monotonic"]
PredictiveStatus = Literal["not_ready", "consistent", "mismatch", "inconclusive"]


class Prediction(BaseModel):
    id: str = ""
    metric_id: str
    direction: PredictionDirection
    expected_range: tuple[float, float] | None = None
    expected_pattern: str = ""
    confidence: Literal["low", "medium", "high"] = "medium"
    rationale: str = ""


class DisconfirmingPattern(BaseModel):
    id: str = ""
    description: str
    implication: str = ""
    suggested_model_expansion: str | None = None


class PredictiveContract(BaseModel):
    context_fixed: list[str] = Field(default_factory=list)
    context_varied: list[str] = Field(default_factory=list)
    predictions: list[Prediction] = Field(default_factory=list)
    disconfirming_patterns: list[DisconfirmingPattern] = Field(default_factory=list)
    next_expansions: list[str] = Field(default_factory=list)


class MetricObservation(BaseModel):
    metric_id: str
    value: float
    unit: str | None = None
    seed_values: list[float] = Field(default_factory=list)


class PredictiveCheck(BaseModel):
    plan_id: str
    status: PredictiveStatus
    observed_evidence_ids: list[str] = Field(default_factory=list)
    matched_prediction_ids: list[str] = Field(default_factory=list)
    violated_prediction_ids: list[str] = Field(default_factory=list)
    observed_pattern_ids: list[str] = Field(default_factory=list)
    inconclusive_prediction_ids: list[str] = Field(default_factory=list)
    discrepancy_summary: str = ""
    recommended_expansion: str | None = None
