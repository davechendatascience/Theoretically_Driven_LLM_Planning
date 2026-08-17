"""Result models returned by services and MCP tools.

Every tool-facing result carries `human_summary` so hosts that render only
text still convey the verdict.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .enums import ConstraintStatus, NextAction, PlanKind, PlanStatus


class Blocker(BaseModel):
    code: str
    message: str
    constraint_id: str | None = None


class ClosureReport(BaseModel):
    goal_defined: bool
    metric_defined: bool
    hard_constraints_resolved: bool
    failure_linked: bool
    hypothesis_testable: bool
    intervention_defined: bool
    validation_defined: bool
    decision_rule_defined: bool
    rollback_defined: bool

    def complete(self) -> bool:
        return all(self.model_dump().values())

    def structurally_complete(self) -> bool:
        """Complete except possibly for hard-constraint resolution."""
        items = self.model_dump()
        items.pop("hard_constraints_resolved")
        return all(items.values())


class ResidualReport(BaseModel):
    goal_gap: int = 0
    hard_constraint_gap: int = 0
    evidence_gap: int = 0
    validation_gap: int = 0
    dependency_gap: int = 0
    oscillation_risk: int = 0
    scope_risk: int = 0
    blockers: list[str] = Field(default_factory=list)
    recommended_next_action: NextAction = NextAction.STOP
    rationale: list[str] = Field(default_factory=list)


class PlanEvaluation(BaseModel):
    plan_id: str
    plan_status: PlanStatus
    executable: bool
    closure: ClosureReport
    blockers: list[Blocker] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    residuals: ResidualReport
    recommended_next_action: NextAction
    human_summary: str = ""


class ConstraintView(BaseModel):
    id: str
    statement: str
    kind: str
    severity: str
    status: ConstraintStatus
    evidence_ids: list[str] = Field(default_factory=list)


class PlanIndexEntry(BaseModel):
    plan_id: str
    title: str
    kind: PlanKind
    status: PlanStatus


class ProjectSummary(BaseModel):
    project_id: str
    name: str
    goal_count: int
    constraint_count: int
    failure_mode_count: int
    plan_count: int
    human_summary: str = ""


class GatePlanEntry(BaseModel):
    plan_id: str
    kind: PlanKind
    status: PlanStatus
    allowed_files: list[str] = Field(default_factory=list)


class GateSnapshot(BaseModel):
    schema_version: int = 1
    generated_at: str
    project_id: str
    gate_open: bool
    open_plans: list[GatePlanEntry] = Field(default_factory=list)
    always_allowed: list[str] = Field(
        default_factory=lambda: [".damped-plan/**", "docs/**", "*.md"]
    )
    unresolved_hard_constraints: list[str] = Field(default_factory=list)
    recommended_next_action: NextAction = NextAction.STOP
    deny_message: str = ""


class ProjectSnapshot(BaseModel):
    project_id: str
    name: str
    goals: list[dict]
    constraints: list[ConstraintView]
    failure_modes: list[dict]
    plans: list[PlanIndexEntry]
    open_unknowns: list[str] = Field(default_factory=list)
    top_blockers: list[Blocker] = Field(default_factory=list)
    recommended_next_action: NextAction = NextAction.STOP
    gate_open: bool = False
    current_baseline: str | None = None
    human_summary: str = ""
