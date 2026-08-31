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


class EvidenceClaim(BaseModel):
    """DEPRECATED read-path passthrough.

    Retained solely so stored records written before the micro-damping engine
    was removed stay loadable: three records in the robot-navigation-planning
    store carry `claims` (EV-0014). `credibility_score` and `coverage_ratio`
    are preserved on read and consumed by no decision path.
    """

    claim_id: str = Field(default_factory=generate_id)
    target_subtask_id: str
    assertion_statement: str
    observed_payload: dict[str, Any] = Field(default_factory=dict)
    source_provenance: str
    credibility_score: float = Field(ge=0.0, le=1.0, default=1.0)
    coverage_ratio: float = Field(ge=0.0, le=1.0, default=1.0)
    step_index: int = 0
    is_terminal: bool = False


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
    # Deprecated passthrough; see EvidenceClaim.
    claims: list[EvidenceClaim] = Field(default_factory=list)
    created_at: datetime
