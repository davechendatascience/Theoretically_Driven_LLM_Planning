"""Three layers, not three objects.

Layer A  Commitments  — human-authored; evidence never moves them.
Layer B  The loop     — Change / Expectation / Outcome; the only place belief updates.
Layer C  Enforcement  — mechanism, holds no data (see invariants.py).

The collapse that broke the earlier draft: a hard constraint is a *normative
gate*, not a causal claim, an intervention, or an observation. Layers A and B
update by different rules and must not share an object.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

Status = Literal["sat", "unsat", "unknown", "not_applicable"]
# How a Given came to be known. Deliberately NOT the Constraint lattice:
# Constraint.status is normative (is the gate satisfied), Given.provenance is
# epistemic (how do we know). v1 collapsed them; live stores carry "assumed"
# and "observed", neither of which means "sat".
Provenance = Literal["observed", "inferred", "assumed", "unknown"]
Severity = Literal["critical", "high", "medium", "low"]
ChangeStatus = Literal["draft", "authorised", "executing", "adopted", "rejected", "rolled_back"]

SEVERITY_RANK: dict[str, int] = {"critical": 0, "high": 1, "medium": 2, "low": 3}
STATUS_RANK: dict[str, int] = {"unsat": 0, "unknown": 1, "sat": 2, "not_applicable": 3}


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# Layer A — Commitments
# --------------------------------------------------------------------------

class Objective(BaseModel):
    """The terminal goal. Human-only; no agent may author or amend it.

    Without it "closer" has no referent and drift is not a movement.
    """

    id: str
    statement: str
    owner: str
    created_at: datetime = Field(default_factory=_now)


class Goal(BaseModel):
    """Typed baseline and target, so distance is arithmetic.

    `met` is deliberately absent: it is derived (see `is_met`). Storing it is
    what caused goal-flag drift in v1.
    """

    id: str
    statement: str
    metric_name: str = ""
    baseline: float | None = None
    target: float | None = None
    target_note: str = ""
    evaluation_protocol: str | None = None
    priority: int = 1

    def is_met(self, current: float | None) -> bool | None:
        if current is None or self.target is None:
            return None
        if self.baseline is None or self.target >= self.baseline:
            return current >= self.target
        return current <= self.target

    def distance(self, current: float | None) -> float | None:
        if current is None or self.target is None:
            return None
        return abs(self.target - current)


class Constraint(BaseModel):
    """A normative gate. Leaving `unknown` requires a citation — including for
    `not_applicable`, which in v1 was the one uncited escape."""

    id: str
    statement: str
    severity: Severity = "high"
    status: Status = "unknown"
    citations: list[str] = Field(default_factory=list)
    rationale: str | None = None


class Given(BaseModel):
    """A recorded observation no intervention produced: state, not evidence.

    Migrated v1 Facts land here, and so does every evidence record with no
    paired Expectation — it could not have come out otherwise, so it cannot
    corroborate or refute. Its stored polarity is preserved but marked
    unverified rather than laundered.
    """

    id: str
    statement: str
    provenance: Provenance = "unknown"
    citations: list[str] = Field(default_factory=list)
    asserted_polarity: str | None = None
    verified: bool = False


class FailureMode(BaseModel):
    id: str
    symptom: str
    severity: Severity = "medium"
    subsystem: str | None = None
    citations: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Layer B — The loop
# --------------------------------------------------------------------------

ExpectationForm = Literal["range", "invariance", "golden", "exit", "witness", "membership"]


class Expectation(BaseModel):
    """What a Change is expected to produce, stated before it runs.

    Admitted only if `grammar.can_fail` holds. The universal logic form
    ("F never returns null for any input in class X") is NOT admitted: it is
    undecidable in general and must be reduced to a finite witness set.
    """

    id: str
    change_id: str
    form: ExpectationForm
    metric_id: str = ""
    lo: float | None = None
    hi: float | None = None
    baseline: float | None = None
    unit_ref: str = ""
    inputs: list[str] = Field(default_factory=list)
    golden_ref: str = ""
    expected_output: str | None = None
    command: str = ""
    allowed_set: list[str] = Field(default_factory=list)
    instrument: str = ""
    rationale: str = ""
    author: str = ""
    frozen_hash: str = ""
    created_at: datetime = Field(default_factory=_now)


class Intent(BaseModel):
    """A stated direction with no check attached. Preserved, flagged, never
    counted as evidence. This is where v1 predictions with no range and no
    pattern land, so migration stays lossless without admitting an
    expectation that cannot fail."""

    id: str
    change_id: str
    metric_id: str = ""
    direction: str = ""
    note: str = ""


class Change(BaseModel):
    """An authorised intervention.

    It *references* the commitments it depends on rather than auditing all of
    them — which is what deletes the uncited `not_applicable` escape by
    construction. An unreferenced constraint simply does not bind.
    """

    id: str
    title: str
    status: ChangeStatus = "draft"
    allowed_files: list[str] = Field(default_factory=list)
    reversible: bool = True
    references: list[str] = Field(default_factory=list)
    goal_ids: list[str] = Field(default_factory=list)
    failure_ids: list[str] = Field(default_factory=list)
    adopt_if: str = ""
    reject_if: str = ""
    rollback: str = ""
    approved_by: str | None = None
    parent_change_id: str | None = None
    created_at: datetime = Field(default_factory=_now)


class Outcome(BaseModel):
    """What was actually produced. Paired to exactly one Expectation.

    `polarity` is absent by design: it is derived by comparing this Outcome to
    its Expectation. Storing it is what let v1 hold records reading `supports`
    with nothing to support.
    """

    id: str
    expectation_id: str
    change_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    value: float | None = None
    artifact_uri: str | None = None
    captured_at: datetime = Field(default_factory=_now)
