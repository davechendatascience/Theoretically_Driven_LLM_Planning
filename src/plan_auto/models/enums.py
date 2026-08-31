"""Enumerations (blueprint §9.1, verbatim)."""

from enum import StrEnum


class TruthStatus(StrEnum):
    OBSERVED = "observed"
    INFERRED = "inferred"
    ASSUMED = "assumed"
    UNKNOWN = "unknown"


class ConstraintStatus(StrEnum):
    SAT = "sat"
    UNSAT = "unsat"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class ConstraintKind(StrEnum):
    HARD = "hard"
    SOFT = "soft"


class PlanStatus(StrEnum):
    DRAFT = "draft"
    UNDER_SPECIFIED = "under_specified"
    BLOCKED = "blocked"
    READY_FOR_REVIEW = "ready_for_review"
    APPROVED = "approved"
    EXECUTABLE = "executable"
    EXECUTING = "executing"
    VALIDATED = "validated"
    REJECTED = "rejected"
    ROLLED_BACK = "rolled_back"
    SUPERSEDED = "superseded"


TERMINAL_PLAN_STATUSES = frozenset(
    {
        PlanStatus.VALIDATED,
        PlanStatus.REJECTED,
        PlanStatus.ROLLED_BACK,
        PlanStatus.SUPERSEDED,
    }
)

GATE_OPEN_STATUSES = frozenset(
    {PlanStatus.APPROVED, PlanStatus.EXECUTABLE, PlanStatus.EXECUTING}
)


class PlanKind(StrEnum):
    MEASUREMENT = "measurement"
    IMPLEMENTATION = "implementation"
    REPAIR = "repair"
    ROLLBACK = "rollback"


class NextAction(StrEnum):
    MEASURE = "measure"
    IMPLEMENT = "implement"
    REPAIR = "repair"
    ROLLBACK = "rollback"
    ESCALATE = "escalate"
    STOP = "stop"


class ValidatorKind(StrEnum):
    SCHEMA = "schema"
    COMMAND = "command"
    PYTHON = "python"
    SAT_SMT = "sat_smt"
    SIMULATION = "simulation"
    BENCHMARK = "benchmark"
    MANUAL = "manual"


class EvidencePolarity(StrEnum):
    SUPPORTS = "supports"
    REFUTES = "refutes"
    NEUTRAL = "neutral"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
