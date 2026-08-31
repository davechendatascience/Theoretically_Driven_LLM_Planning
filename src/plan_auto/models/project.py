"""Project state models (blueprint §9.2).

Deviation from blueprint: `Goal.met` supports the relaxed failure-linkage
rule (a plan may target an unmet goal instead of a registered failure mode),
and `Goal.metric_name`/`target` default to "" so partial input is storable —
the closure validator, not the model, enforces their presence.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .enums import ConstraintKind, ConstraintStatus, Severity, TruthStatus


class Goal(BaseModel):
    id: str
    statement: str
    metric_name: str = ""
    target: str = ""
    evaluation_protocol: str | None = None
    priority: int = 1
    met: bool = False


class Constraint(BaseModel):
    id: str
    statement: str
    kind: ConstraintKind
    severity: Severity = Severity.HIGH
    status: ConstraintStatus = ConstraintStatus.UNKNOWN
    evidence_ids: list[str] = Field(default_factory=list)
    validator_ids: list[str] = Field(default_factory=list)
    rationale: str | None = None


class Fact(BaseModel):
    id: str
    statement: str
    truth_status: TruthStatus
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)


class FailureMode(BaseModel):
    id: str
    symptom: str
    severity: Severity
    subsystem: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class ProjectState(BaseModel):
    project_id: str
    name: str
    goals: list[Goal] = Field(default_factory=list)
    constraints: list[Constraint] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)
    failure_modes: list[FailureMode] = Field(default_factory=list)
    available_resources: list[str] = Field(default_factory=list)
    forbidden_actions: list[str] = Field(default_factory=list)
    current_baseline: str | None = None
    version: int = 1

    def goal_by_id(self, goal_id: str) -> Goal | None:
        return next((g for g in self.goals if g.id == goal_id), None)

    def constraint_by_id(self, constraint_id: str) -> Constraint | None:
        return next((c for c in self.constraints if c.id == constraint_id), None)

    def hard_constraints(self) -> list[Constraint]:
        return [c for c in self.constraints if c.kind == ConstraintKind.HARD]
