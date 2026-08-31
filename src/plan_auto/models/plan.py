"""Plan models (blueprint §9.3).

Additive deviations: `approved_by`/`approval_note` record the human approval
on the plan itself (also event-logged), `outcome_summary` records the terminal
outcome, and `version` supports the store's internal concurrency bump.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .enums import ConstraintStatus, PlanKind, PlanStatus, ValidatorKind
from .predictive import PredictiveContract

# Plans stamped with this schema version (or later) must carry a
# predictive_contract when kind is implementation or repair. Plans created
# before the predictive layer existed default to 1 and are grandfathered:
# they evaluate under the original closure rules forever.
PLAN_SCHEMA_VERSION = 2


class CausalHypothesis(BaseModel):
    id: str
    statement: str
    linked_failure_ids: list[str] = Field(default_factory=list)
    alternative_hypothesis_ids: list[str] = Field(default_factory=list)


class Intervention(BaseModel):
    id: str
    description: str
    kind: PlanKind
    allowed_files: list[str] = Field(default_factory=list)
    expected_api_changes: list[str] = Field(default_factory=list)
    reversible: bool = True
    estimated_cost: str | None = None


class ValidationStep(BaseModel):
    id: str
    description: str
    kind: ValidatorKind
    command: str | None = None
    expected_result: str = ""
    required: bool = True
    phase: str = "posterior"  # "prior" steps run before implementing (§7)


class DecisionRule(BaseModel):
    adopt_if: list[str] = Field(default_factory=list)
    reject_if: list[str] = Field(default_factory=list)


class PlanConstraintAudit(BaseModel):
    constraint_id: str
    status: ConstraintStatus
    evidence: str | None = None
    blocker: str | None = None


class Plan(BaseModel):
    id: str
    project_id: str
    title: str
    status: PlanStatus = PlanStatus.DRAFT
    kind: PlanKind
    goal_ids: list[str] = Field(default_factory=list)
    addresses_failure_ids: list[str] = Field(default_factory=list)
    hypothesis: CausalHypothesis | None = None
    intervention: Intervention | None = None
    constraint_audit: list[PlanConstraintAudit] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    validation_steps: list[ValidationStep] = Field(default_factory=list)
    decision_rule: DecisionRule | None = None
    predictive_contract: PredictiveContract | None = None
    schema_version: int = 1
    rollback_description: str | None = None
    parent_plan_id: str | None = None
    approved_by: str | None = None
    approval_note: str | None = None
    outcome_summary: str | None = None
    version: int = 1
    created_at: datetime
    updated_at: datetime

    def audit_by_constraint(self) -> dict[str, PlanConstraintAudit]:
        return {item.constraint_id: item for item in self.constraint_audit}
