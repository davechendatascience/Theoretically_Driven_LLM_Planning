"""Evidence model (blueprint §9.4)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..ids import generate_id
from .enums import EvidencePolarity
from .predictive import MetricObservation

EvidenceSourceType = Literal[
    "test",
    "benchmark",
    "simulation",
    "log",
    "manual_review",
    "paper",
    "commit",
    "profiling",
    "solver",
]

DampingStatus = Literal["converged", "exhausted_budget", "diminishing_returns"]


class EvidenceClaim(BaseModel):
    """Claim-level evidence with provenance and credibility (v0.4.0 micro-damping)."""

    claim_id: str = Field(default_factory=generate_id)
    target_subtask_id: str
    assertion_statement: str
    observed_payload: dict[str, Any] = Field(default_factory=dict)
    source_provenance: str  # e.g., "tool:ast_parser", "search:github_api"
    credibility_score: float = Field(ge=0.0, le=1.0, default=1.0)
    coverage_ratio: float = Field(ge=0.0, le=1.0, default=1.0)
    step_index: int = 0
    is_terminal: bool = False


class SubtaskEvidenceBundle(BaseModel):
    """Aggregated evidence bundle across a micro-query subtask loop."""

    subtask_id: str
    claims: list[EvidenceClaim] = Field(default_factory=list)
    aggregate_credibility: float = Field(ge=0.0, le=1.0, default=1.0)
    total_coverage: float = Field(ge=0.0, le=1.0, default=0.0)
    damping_status: DampingStatus = "converged"
    residual_variance: float = 0.0


class EvidenceRecord(BaseModel):
    id: str
    project_id: str
    source_type: EvidenceSourceType
    artifact_uri: str | None = None
    summary: str
    polarity: EvidencePolarity
    linked_hypothesis_ids: list[str] = Field(default_factory=list)
    linked_constraint_ids: list[str] = Field(default_factory=list)
    linked_plan_id: str | None = None
    # Structured observations enable deterministic posterior predictive
    # checks against a plan's contract; free-text summaries alone cannot.
    observations: list[MetricObservation] = Field(default_factory=list)
    # Declares that a contract's disconfirming pattern was observed.
    observed_pattern_ids: list[str] = Field(default_factory=list)
    # Claim-level evidence contracts & micro-query damping bundles (v0.4.0)
    claims: list[EvidenceClaim] = Field(default_factory=list)
    subtask_bundle: SubtaskEvidenceBundle | None = None
    created_at: datetime

