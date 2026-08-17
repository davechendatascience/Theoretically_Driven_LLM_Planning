"""Evidence model (blueprint §9.4)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from .enums import EvidencePolarity

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
    created_at: datetime
