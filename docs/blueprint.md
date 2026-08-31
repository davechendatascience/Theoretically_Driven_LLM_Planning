# Damped Plan MCP
## Blueprint for a Constraint-Closure Substrate for LLM Planning

## 1. Purpose

`plan-auto` is a local Model Context Protocol (MCP) server that converts an LLM's free-form plan into a structured, auditable project state. It evaluates whether a plan is sufficiently closed to execute, identifies blockers, and recommends the next permissible action.

The system is not intended to be a universal planner, a general autonomous researcher, or a learned policy. Its first purpose is narrower and high leverage:

> An LLM may retrieve knowledge and propose candidate actions freely, but it may not declare a nontrivial plan executable until the plan has an explicit goal, measurable outcome, hard-constraint audit, causal hypothesis, minimal intervention, validation path, and adopt/reject criteria.

The design operationalizes a project-level analogue of critically damped adjustment:

- Avoid unsupported commitment and premature scope expansion.
- Avoid repeated local repair loops that do not change the causal hypothesis.
- Avoid over-analysis when a cheap, safe discriminative measurement is available.
- Prefer the smallest evidence-supported action that reduces the dominant unresolved project residual.

## 2. Problem Statement

LLMs frequently generate technically plausible plans that fail to align their knowledge with a project's actual goals, constraints, evidence, dependencies, and execution environment. The model can mention constraints in prose while quietly violating them later.

Examples:

- Propose RL, a VLM, or a world model without showing that the observed failure requires it.
- Recommend a method that needs annotations, compute, interfaces, or hardware not available in the project.
- Modify an algorithm without stating whether it is exact, approximate, or heuristic.
- Change a model and its evaluation protocol in the same iteration, invalidating comparison.
- Repeat local code tweaks after the real problem has become a representation, objective, interface, or causal-diagnosis issue.

The substrate makes plan closure and feasibility explicit.

## 3. Scope

### 3.1 What v0 does

- Stores explicit project goals, constraints, evidence, failure modes, unknowns, resources, plans, validators, and outcomes.
- Validates plan completeness with deterministic rules.
- Enforces `SAT`, `UNSAT`, and `UNKNOWN` statuses for constraints.
- Blocks ordinary implementation plans with unresolved hard constraints.
- Permits safe measurement-only plans that directly resolve an unknown.
- Computes residuals and blockers.
- Detects repeated non-informative repair patterns and scope drift.
- Provides MCP tools, resources, and prompts for Claude Code or another MCP host.
- Runs allowlisted validation commands only.
- Records evidence and plan outcomes with provenance.

### 3.2 What v0 does not do

Do not implement these in the initial version:

- Universal natural-language planning.
- Fully autonomous coding or deployment.
- Arbitrary shell command execution.
- Direct robot hardware control.
- A learned RL policy over project trajectories.
- A vector database or hosted data service.
- A general SAT/SMT encoding of all project semantics.
- Automatic causal discovery or proof of research claims.

## 4. Design Principle

The core operational loop is:

\[
\text{knowledge}
\rightarrow
\text{structured state}
\rightarrow
\text{feasibility check}
\rightarrow
\text{minimal executable action}
\rightarrow
\text{observation}
\rightarrow
\text{state update}.
\]

The LLM proposes semantic content. The computable substrate enforces commitments.

\[
\text{LLM proposes semantics};
\qquad
\text{substrate enforces commitments.}
\]

A project state at time \(t\) is:

\[
\mathcal{P}_t =
\left(
G,
C_h,
C_s,
S_t,
B_t,
A_t,
D_t,
E_t,
R_t
\right),
\]

where:

- \(G\): global goals and measurable success conditions.
- \(C_h\): hard constraints.
- \(C_s\): soft constraints or preferences.
- \(S_t\): current system/project state.
- \(B_t\): beliefs, hypotheses, and uncertainty.
- \(A_t\): available interventions.
- \(D_t\): dependency graph.
- \(E_t\): accumulated evidence.
- \(R_t\): unresolved residuals.

The server does not initially optimize over all actions. It determines whether a candidate plan is feasible and what category of action is permitted next.

## 5. Critical-Damping Interpretation

This design should not claim that project planning literally follows a physical second-order system. Critical damping is an organizing analogy that becomes useful only when translated into observable project behavior.

| Control concept | Project-planning analogue |
|---|---|
| State \(x_t\) | Structured project state: facts, code, metrics, constraints, evidence |
| Desired state \(x^\star\) | Goal and acceptance criteria |
| Error \(e_t\) | Goal, feasibility, evidence, interface, or evaluation residual |
| Velocity \(\dot{x}_t\) | Rate/direction of plan changes, edits, experiments, and scope expansion |
| Overshoot | Premature architecture expansion or commitment before constraints are verified |
| Oscillation | Hypothesis flipping, reverting changes, repeated local patches, contradictory plans |
| Overdamping | Endless analysis despite a cheap, safe diagnostic experiment |
| Disturbance | New logs, failing tests, changed requirements, simulation failures |
| Stability | Constraints remain satisfied while evidence accumulates |
| Desired behavior | Fastest reliable reduction of unresolved residual without scope/action oscillation |

The residual vector can be represented as:

\[
r_t =
\begin{bmatrix}
r_{\mathrm{goal}} \\
r_{\mathrm{feasibility}} \\
r_{\mathrm{evidence}} \\
r_{\mathrm{interface}} \\
r_{\mathrm{evaluation}} \\
r_{\mathrm{risk}}
\end{bmatrix}.
\]

For v0, use explainable categorical/count-based residuals rather than pretending to estimate a scientifically meaningful continuous damping coefficient.

## 6. System Architecture

```text
                 ┌────────────────────────────────┐
                 │ Claude Code / MCP host          │
                 │                                │
                 │ - reads resources               │
                 │ - calls planning tools          │
                 │ - edits only after gate         │
                 └───────────────┬────────────────┘
                                 │ MCP over stdio
                 ┌───────────────▼────────────────┐
                 │ Damped Plan MCP Server          │
                 │                                │
                 │ 1. State store                  │
                 │ 2. Schema validator             │
                 │ 3. Constraint evaluator         │
                 │ 4. Dependency graph             │
                 │ 5. Residual/drift analyzer      │
                 │ 6. Validator runner             │
                 │ 7. Decision policy              │
                 └───────┬───────────────┬────────┘
                         │               │
           ┌─────────────▼───┐     ┌────▼────────────────┐
           │ Local artifacts │     │ External validators  │
           │ YAML/JSON/SQLite│     │ pytest, ruff, sim,   │
           │ plans/logs/docs │     │ benchmarks, IK, SMT  │
           └─────────────────┘     └─────────────────────┘
```

### 6.1 Initial transport and persistence

- Use local stdio transport first.
- Use local project storage first.
- Use SQLite as the canonical mutable store.
- Use YAML or JSON as import/export and human-review formats.
- Keep all project state in a repository-local `.plan-auto/` directory.

Example:

```text
your-robotics-project/
├── .plan-auto/
│   ├── project.sqlite
│   ├── artifacts/
│   ├── exports/
│   └── events.jsonl
├── docs/
├── src/
└── CLAUDE.md
```

## 7. Repository Layout

```text
plan-auto/
├── README.md
├── pyproject.toml
├── uv.lock
├── src/
│   └── plan_auto/
│       ├── __init__.py
│       ├── server.py
│       ├── config.py
│       ├── models/
│       │   ├── __init__.py
│       │   ├── enums.py
│       │   ├── project.py
│       │   ├── plan.py
│       │   ├── evidence.py
│       │   ├── constraint.py
│       │   ├── obligation.py
│       │   └── result.py
│       ├── store/
│       │   ├── __init__.py
│       │   ├── repository.py
│       │   ├── json_store.py
│       │   └── sqlite_store.py
│       ├── services/
│       │   ├── __init__.py
│       │   ├── plan_validation.py
│       │   ├── constraint_evaluation.py
│       │   ├── dependency_graph.py
│       │   ├── residuals.py
│       │   ├── decision_policy.py
│       │   ├── command_runner.py
│       │   └── evidence_service.py
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── project_tools.py
│       │   ├── plan_tools.py
│       │   ├── validation_tools.py
│       │   └── analysis_tools.py
│       ├── resources/
│       │   ├── __init__.py
│       │   └── project_resources.py
│       ├── prompts/
│       │   ├── __init__.py
│       │   └── planning_prompts.py
│       └── render/
│           ├── __init__.py
│           └── reports.py
├── tests/
│   ├── unit/
│   │   ├── test_plan_validation.py
│   │   ├── test_constraints.py
│   │   ├── test_residuals.py
│   │   └── test_decision_policy.py
│   ├── integration/
│   │   ├── test_mcp_tools.py
│   │   └── test_end_to_end_plan_gate.py
│   └── fixtures/
│       ├── valid_project.yaml
│       ├── valid_plan.yaml
│       ├── under_specified_plan.yaml
│       └── invalid_plan.yaml
├── examples/
│   ├── robotics_project/
│   │   ├── project.yaml
│   │   ├── plans/
│   │   └── evidence/
│   └── algorithm_project/
│       ├── project.yaml
│       ├── plans/
│       └── evidence/
├── scripts/
│   ├── run_server.py
│   ├── validate_plan.py
│   └── demo_end_to_end.py
└── docs/
    ├── architecture.md
    ├── state_model.md
    ├── decision_policy.md
    ├── tool_contracts.md
    └── claude_code_integration.md
```

## 8. Dependencies

Use the following initial stack:

- Python 3.12+
- `mcp` official Python SDK
- Pydantic v2
- `networkx`
- `pytest`
- `hypothesis`
- `pyyaml` for import/export only
- Standard-library `sqlite3` for v0 persistence
- Optional: `typer` for a CLI

Avoid adding LLM SDKs, agent frameworks, web frontends, remote databases, message queues, and ML libraries in v0.

## 9. Domain Model

### 9.1 Enumerations

```python
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
```

### 9.2 Project state models

```python
from datetime import datetime
from pydantic import BaseModel, Field


class Goal(BaseModel):
    id: str
    statement: str
    metric_name: str
    target: str
    evaluation_protocol: str | None = None
    priority: int = 1


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
    goals: list[Goal]
    constraints: list[Constraint]
    facts: list[Fact] = Field(default_factory=list)
    failure_modes: list[FailureMode] = Field(default_factory=list)
    available_resources: list[str] = Field(default_factory=list)
    forbidden_actions: list[str] = Field(default_factory=list)
    current_baseline: str | None = None
    version: int = 1
```

### 9.3 Plan models

```python
class CausalHypothesis(BaseModel):
    id: str
    statement: str
    linked_failure_ids: list[str]
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
    expected_result: str
    required: bool = True


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
    goal_ids: list[str]
    addresses_failure_ids: list[str]
    hypothesis: CausalHypothesis | None = None
    intervention: Intervention | None = None
    constraint_audit: list[PlanConstraintAudit] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    validation_steps: list[ValidationStep] = Field(default_factory=list)
    decision_rule: DecisionRule | None = None
    rollback_description: str | None = None
    parent_plan_id: str | None = None
    created_at: datetime
    updated_at: datetime
```

### 9.4 Evidence model

```python
from typing import Literal


class EvidenceRecord(BaseModel):
    id: str
    project_id: str
    source_type: Literal[
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
    artifact_uri: str | None = None
    summary: str
    polarity: EvidencePolarity
    linked_hypothesis_ids: list[str] = Field(default_factory=list)
    linked_constraint_ids: list[str] = Field(default_factory=list)
    linked_plan_id: str | None = None
    created_at: datetime
```

## 10. Core Invariants

### 10.1 Execution invariant

A normal implementation plan is executable only if:

\[
\texttt{plan.status = EXECUTABLE}
\Rightarrow
\left(
\bigwedge_{c \in C_h} c.\texttt{status} = \texttt{SAT}
\right)
\land
\texttt{goal exists}
\land
\texttt{metric exists}
\land
\texttt{intervention exists}
\land
\texttt{validation exists}
\land
\texttt{decision rule exists}.
\]

For ordinary implementation plans:

\[
\texttt{UNKNOWN hard constraint}
\Rightarrow
\texttt{plan is not executable}.
\]

The only exception is a safe measurement-only plan that directly resolves that unknown and has no unrelated unresolved hard prerequisite.

### 10.2 Plan closure predicate

Define:

\[
\operatorname{Complete}(P) =
G
\land
M
\land
C_h
\land
F
\land
H
\land
I
\land
V
\land
D
\land
R,
\]

where:

- \(G\): at least one valid goal is linked.
- \(M\): that goal has a metric and target.
- \(C_h\): hard-constraint status is acceptable for plan kind.
- \(F\): plan addresses a registered failure mode.
- \(H\): plan states a causal hypothesis.
- \(I\): plan includes a scoped intervention.
- \(V\): plan includes required validation steps.
- \(D\): plan includes adoption and rejection criteria.
- \(R\): plan has rollback or is explicitly reversible.

### 10.3 No unknown-to-satisfied coercion

The system must never automatically convert `UNKNOWN` to `SAT`.

Changing a hard constraint to `SAT` requires:

- one or more evidence IDs;
- a rationale;
- optionally, a completed validator result;
- an append-only event log entry.

## 11. Deterministic Closure Rules

### 11.1 Unresolved hard constraints

```python
def unresolved_hard_constraints(plan: Plan, project: ProjectState) -> list[str]:
    audit = {item.constraint_id: item for item in plan.constraint_audit}
    unresolved: list[str] = []

    for constraint in project.constraints:
        if constraint.kind != ConstraintKind.HARD:
            continue

        item = audit.get(constraint.id)
        if item is None or item.status != ConstraintStatus.SAT:
            unresolved.append(constraint.id)

    return unresolved
```

For implementation plans:

```python
if unresolved_hard_constraints(plan, project):
    plan.status = PlanStatus.BLOCKED
```

For measurement plans, unresolved constraints are allowed only when the plan safely and directly measures the unresolved item.

### 11.2 Failure linkage

```python
def has_failure_link(plan: Plan, project: ProjectState) -> bool:
    known_failure_ids = {failure.id for failure in project.failure_modes}
    return bool(set(plan.addresses_failure_ids) & known_failure_ids)
```

This rejects orphan interventions such as “add a VLM” without a recorded failure mode that the intervention addresses.

### 11.3 Testable hypothesis

```python
def hypothesis_is_testable(plan: Plan) -> bool:
    return (
        plan.hypothesis is not None
        and bool(plan.validation_steps)
        and any(step.required for step in plan.validation_steps)
    )
```

### 11.4 Decision rule

```python
def has_decision_rule(plan: Plan) -> bool:
    return bool(
        plan.decision_rule
        and plan.decision_rule.adopt_if
        and plan.decision_rule.reject_if
    )
```

### 11.5 Safe rollback

```python
def has_safe_rollback(plan: Plan) -> bool:
    if plan.kind == PlanKind.MEASUREMENT:
        return True
    return bool(plan.rollback_description) or (
        plan.intervention is not None and plan.intervention.reversible
    )
```

## 12. Residual Model

Start with transparent counts and categorical blockers.

```python
class ResidualReport(BaseModel):
    goal_gap: int
    hard_constraint_gap: int
    evidence_gap: int
    validation_gap: int
    dependency_gap: int
    oscillation_risk: int
    scope_risk: int
    blockers: list[str]
    recommended_next_action: NextAction
    rationale: list[str]
```

Initial definitions:

\[
r_{\text{hard}} =
\#\{\text{hard constraints not SAT}\}
\]

\[
r_{\text{evidence}} =
\#\{\text{assumptions or competing hypotheses lacking validation}\}
\]

\[
r_{\text{validation}} =
\#\{\text{required obligations missing or failed}\}
\]

\[
r_{\text{dependency}} =
\#\{\text{nodes with unsatisfied prerequisites}\}
\]

\[
r_{\text{scope}} =
\#\{\text{new modules or dependencies without a linked hypothesis}\}.
\]

A simple closure score may be:

\[
R(p) =
r_{\text{hard}}
+
r_{\text{evidence}}
+
r_{\text{validation}}
+
r_{\text{dependency}}.
\]

Do not use this scalar score to override hard constraints. Hard constraints have lexicographic priority:

\[
r_{\text{hard}} > 0
\Rightarrow
\text{ordinary implementation cannot execute}.
\]

## 13. Decision Policy

The decision policy must be deterministic, inspectable, and conservative.

```python
def recommend_next_action(
    plan: Plan,
    project: ProjectState,
    residuals: ResidualReport,
) -> NextAction:
    if has_critical_unsat_constraint(plan, project):
        return NextAction.ROLLBACK

    if has_unresolved_hard_constraint(plan, project):
        if plan.kind == PlanKind.MEASUREMENT and safely_resolves_blocker(plan):
            return NextAction.MEASURE
        return NextAction.ESCALATE

    if missing_required_structure(plan):
        return NextAction.REPAIR

    if repeated_noninformative_failure(plan, project):
        return NextAction.ESCALATE

    if required_validation_failed(plan):
        return NextAction.REPAIR

    if plan.status in {PlanStatus.APPROVED, PlanStatus.EXECUTABLE}:
        return NextAction.IMPLEMENT

    return NextAction.STOP
```

### 13.1 Operational damping policy

```text
If a hard constraint is UNSAT:
    rollback, block, or redesign.

If a hard constraint is UNKNOWN:
    measure it safely or escalate; do not implement an ordinary plan.

If competing hypotheses imply different interventions:
    select the lowest-cost discriminative measurement.

If one causal hypothesis is sufficiently supported:
    choose the smallest reversible intervention.

If the same residual persists after repeated repairs:
    escalate the abstraction level and inspect representation, interface,
    objective, evaluation, or causal hypothesis.

If a plan introduces unsupported scope:
    block or require explicit causal/evidence linkage.
```

## 14. Dependency Graph

Represent project completeness as a directed graph:

\[
\mathcal{D} = (\mathcal{V}, \mathcal{E}).
\]

### 14.1 Node types

- Goal
- Metric
- Constraint
- Fact
- Failure mode
- Hypothesis
- Plan
- Intervention
- Module
- Interface
- Validator
- Evidence artifact
- Decision
- Resource

### 14.2 Edge types

```text
goal ──requires──> metric
goal ──decomposes_to──> subgoal
failure ──blocks──> goal
hypothesis ──explains──> failure
plan ──tests──> hypothesis
plan ──addresses──> failure
plan ──requires──> constraint
plan ──modifies──> module
module ──depends_on──> interface
validator ──verifies──> claim
evidence ──supports/refutes──> hypothesis
evidence ──supports/refutes──> constraint
unknown ──blocks──> plan
```

### 14.3 Graph diagnostics

#### Orphan intervention

\[
\operatorname{orphan}(a)
\iff
\not\exists f \in \mathcal{F}:
a \xrightarrow{\text{addresses}} f.
\]

#### Unsupported claim

\[
\operatorname{unsupported}(q)
\iff
\neg \exists e:
e \xrightarrow{\text{supports or verifies}} q.
\]

#### Broken global chain

Each global goal should have a trace:

```text
goal → subgoal/failure → intervention → validation → metric
```

#### Constraint conflict

\[
a \xrightarrow{\text{requires}} r
\land
r \xrightarrow{\text{violates}} C_h
\Rightarrow
\operatorname{infeasible}(a).
\]

## 15. Drift and Oscillation Detection

The server should detect behavior that resembles project-level ringing.

### 15.1 Initial metrics

\[
\operatorname{HypothesisFlipRate}
=
\frac{
\#\text{changes of dominant hypothesis}
}{
\#\text{planning iterations}
}.
\]

\[
\operatorname{ReworkRate}
=
\frac{
\#\text{reverted or superseded changes}
}{
\#\text{changes}
}.
\]

\[
\operatorname{UnverifiedCommitmentRate}
=
\frac{
\#\text{claims/actions with UNKNOWN prerequisites}
}{
\#\text{claims/actions}
}.
\]

\[
\operatorname{ScopeExpansionRate}
=
\frac{
\#\text{new modules/dependencies introduced}
}{
\#\text{validated causal hypotheses}
}.
\]

\[
\operatorname{DiagnosticLatency}
=
\text{time from identifying an uncertainty to running its first discriminative test}.
\]

### 15.2 Escalation rule

After two failed repair attempts, the next proposal must introduce at least one of:

- a new causal hypothesis;
- a new test/oracle;
- a changed representation or state definition;
- a changed interface/contract under explicit review;
- a new evidence artifact;
- a different subsystem diagnosis.

Otherwise, return `ESCALATE` rather than permitting another local patch.

## 16. MCP Interface

### 16.1 Resources

| Resource URI | Contents |
|---|---|
| `damped://projects` | Registered project index |
| `damped://project/{project_id}/state` | Canonical project state |
| `damped://project/{project_id}/constraints` | Constraints, statuses, evidence |
| `damped://project/{project_id}/failures` | Failure taxonomy |
| `damped://project/{project_id}/plans` | Plan index |
| `damped://project/{project_id}/plans/{plan_id}` | Full plan |
| `damped://project/{project_id}/residuals` | Residual report |
| `damped://project/{project_id}/graph` | Dependency graph JSON |
| `damped://project/{project_id}/decision-log` | Decisions and outcomes |

### 16.2 Prompts

| Prompt | Purpose |
|---|---|
| `compile_project_state` | Extract goals, constraints, facts, unknowns; do not propose a method |
| `draft_feasible_plan` | Draft exactly one structured candidate plan |
| `review_plan_blockers` | Explain closure failures and request minimal repairs |
| `postmortem_update` | Convert results into evidence and update state |
| `escalate_repeated_failure` | Stop local edits and reframe the causal hypothesis |
| `algorithmic_review` | Require invariants, complexity, oracle, and correctness claim |

### 16.3 Tools

#### `register_project`

```text
register_project(project: ProjectState) -> ProjectSummary
```

Creates a project state from strict JSON/YAML input.

#### `get_project_snapshot`

```text
get_project_snapshot(project_id: str) -> ProjectSnapshot
```

Returns goals, hard constraints, active plan, open unknowns, baseline, failure modes, top blockers, and recommended next action.

#### `create_plan`

```text
create_plan(plan: Plan) -> Plan
```

Stores a candidate plan. It does not approve or execute it.

#### `evaluate_plan`

```text
evaluate_plan(
    project_id: str,
    plan_id: str,
    include_dependency_analysis: bool = True,
) -> PlanEvaluation
```

Returns plan closure, blockers, residuals, and recommended next action.

Example output:

```json
{
  "plan_status": "blocked",
  "executable": false,
  "closure": {
    "goal_defined": true,
    "metric_defined": true,
    "hard_constraints_resolved": false,
    "failure_linked": true,
    "hypothesis_testable": true,
    "validation_defined": true,
    "decision_rule_defined": true,
    "rollback_defined": true
  },
  "blockers": [
    {
      "code": "UNRESOLVED_HARD_CONSTRAINT",
      "constraint_id": "C-compute-budget",
      "message": "Peak VRAM remains UNKNOWN."
    }
  ],
  "residuals": {
    "hard_constraint_gap": 1,
    "evidence_gap": 1,
    "validation_gap": 0
  },
  "recommended_next_action": "measure",
  "recommended_measurement": {
    "description": "Run one profiling smoke test under target batch size.",
    "expected_artifact": "evidence/EV-017-vram-profile.json"
  }
}
```

#### `approve_plan`

```text
approve_plan(
    project_id: str,
    plan_id: str,
    approver: str,
    approval_note: str,
) -> Plan
```

State-changing tool. Reject approval when the plan is not ready for review or required hard constraints remain unresolved.

#### `run_validation`

```text
run_validation(
    project_id: str,
    plan_id: str,
    validation_step_id: str,
) -> ValidationResult
```

Runs allowlisted commands only. No arbitrary shell command execution in v0.

#### `record_evidence`

```text
record_evidence(
    project_id: str,
    evidence: EvidenceRecord,
) -> EvidenceRecord
```

> This section records the tool surface as originally designed. The shipped
> surface has since gained `record_run_metrics`, the metrics-first channel
> that feeds the posterior check; see
> [tool_contracts.md](tool_contracts.md) for the live reference.

#### `update_constraint_status`

```text
update_constraint_status(
    project_id: str,
    constraint_id: str,
    status: "sat" | "unsat" | "unknown",
    evidence_ids: list[str],
    rationale: str,
) -> Constraint
```

Requires evidence IDs to mark a hard constraint as `SAT`.

#### `record_plan_outcome`

```text
record_plan_outcome(
    project_id: str,
    plan_id: str,
    outcome: "validated" | "rejected" | "rolled_back",
    summary: str,
    evidence_ids: list[str],
) -> Plan
```

#### `analyze_drift`

```text
analyze_drift(
    project_id: str,
    window: int = 10,
) -> DriftReport
```

Detects repeated repairs, hypothesis flips, scope creep, absent new evidence, and evaluation drift.

## 17. Validator Execution

### 17.1 Command registry

Never permit arbitrary `bash` commands directly from an LLM in v0. Plans reference approved command IDs, not arbitrary shell strings.

```yaml
commands:
  unit_tests:
    allowed: true
    argv: ["uv", "run", "pytest", "-q"]

  placement_smoke:
    allowed: true
    argv:
      - "uv"
      - "run"
      - "python"
      - "scripts/smoke_rollout.py"
      - "--config"
      - "{config}"

  frozen_placement_eval:
    allowed: true
    argv:
      - "uv"
      - "run"
      - "python"
      - "scripts/evaluate.py"
      - "--config"
      - "configs/eval_frozen.yaml"
```

### 17.2 Command-runner requirements

- Use argument arrays, not shell interpolation.
- Enforce timeouts.
- Capture stdout, stderr, exit code, runtime, and artifact paths.
- Restrict working directory to the registered project root.
- Restrict parameter substitution to declared safe fields.
- Do not permit package installation, Git push, deployment, or robot actuation.
- Convert validation results into immutable evidence artifacts.

## 18. Plan Lifecycle

```text
DRAFT
  ↓ evaluate
UNDER_SPECIFIED ──repair──> DRAFT
BLOCKED ──measurement/escalation──> DRAFT
READY_FOR_REVIEW ──human approval──> APPROVED
APPROVED ──all gate conditions true──> EXECUTABLE
EXECUTABLE ──run approved work──> EXECUTING
EXECUTING ──validation passes──> VALIDATED
EXECUTING ──validation rejects hypothesis──> REJECTED
EXECUTING ──constraint violation/regression──> ROLLED_BACK
```

All transitions should be written to an append-only event log.

## 19. First User Flows

### 19.1 Feasibility-first research change

```text
User: Improve placement robustness.

Claude:
1. Reads current project state.
2. Compiles goals, failures, constraints, facts, and unknowns.
3. Creates a structured candidate plan.
4. Calls evaluate_plan.

Server:
- Finds GPU-memory budget UNKNOWN.
- Blocks the implementation plan.
- Recommends a safe memory-profiling measurement plan.

Claude:
- Presents the blocker and measurement plan.

After approval:
1. Runs the profiling plan.
2. Records evidence.
3. Updates compute constraint to SAT or UNSAT.
4. Creates and evaluates the smallest valid implementation plan.
```

### 19.2 Algorithmic implementation review

```text
User: Implement a route-ordering function.

Claude must state:
- Canonical problem class.
- Exact / approximation / heuristic / feasibility-only label.
- Claimed complexity.
- Constraints defining a valid route.
- Small-instance exact oracle.
- Approximation or objective-gap requirement if heuristic.

Only then does it implement and validate the algorithm.
```

### 19.3 Repeated repair prevention

```text
Claude has attempted two repairs without changing its causal model.

Claude calls analyze_drift.

Server returns:
- Repeated failure cluster.
- Shared unresolved assumption.
- Required escalation instruction.
- Suggested minimum discriminative measurement.

Claude stops local edits and requests direction or runs the approved diagnostic.
```

## 20. Phased Implementation Plan

### Phase 0: semantics and artifacts

Deliverables:

- `docs/state_model.md`
- `docs/decision_policy.md`
- `docs/tool_contracts.md`
- `examples/robotics_project/project.yaml`
- `examples/robotics_project/plans/P-001.yaml`

Acceptance criteria:

- A human can inspect a plan and explain why it is executable or blocked.
- `SAT`, `UNSAT`, and `UNKNOWN` semantics are unambiguous.
- Measurement plans and implementation plans are distinctly specified.
- Repeated failure escalation is defined.

### Phase 1: pure Python kernel

Implement before any MCP integration:

- Pydantic models.
- JSON store.
- Plan closure validator.
- Constraint audit.
- Residual report.
- Decision policy.
- Human-readable reports.
- Unit tests and fixtures.

Required test cases:

| Case | Expected result |
|---|---|
| Valid plan, all hard constraints SAT | `EXECUTABLE` |
| One hard constraint UNKNOWN | `BLOCKED` or `ESCALATE` |
| Safe measurement plan resolving the unknown | `READY_FOR_REVIEW` and `MEASURE` |
| Missing success metric | `UNDER_SPECIFIED` |
| Intervention without failure link | `UNDER_SPECIFIED` |
| Hypothesis without validation | `UNDER_SPECIFIED` |
| Validation failure | `REPAIR` |
| Three similar failed plans, no new evidence | `ESCALATE` |
| New module with no hypothesis link | scope-risk warning |
| Method and evaluation config changed together | evaluation-drift warning |

Do not build MCP server integration until this pure-Python kernel passes.

### Phase 2: read-only MCP

Implement:

- Read-only project resources.
- `get_project_snapshot`.
- `get_plan`.
- `evaluate_plan`.
- Planning prompts.

Acceptance criteria:

- An MCP host can read state and receive deterministic executable/blocked results.
- No state mutation occurs through the server in this phase.
- Tools can be invoked through MCP Inspector or an equivalent local test client.

### Phase 3: controlled mutation

Implement:

- `create_plan`.
- `approve_plan`.
- `record_evidence`.
- `update_constraint_status`.
- `record_plan_outcome`.

Safety requirements:

- Optimistic concurrency versions.
- Append-only event history.
- Evidence required for hard-constraint `SAT` status.
- Explicit human approver identity for plan approval.
- LLM cannot silently self-approve a plan.

### Phase 4: allowlisted validation execution

Implement:

- Command registry.
- Restricted command runner.
- Result capture.
- Validation-result-to-evidence conversion.

Start with:

- `pytest`
- `ruff`
- import/type checks
- deterministic smoke tests
- profiling scripts
- frozen benchmark/evaluation scripts

### Phase 5: dependency graph and drift

Implement:

- Graph construction.
- Orphan plan detection.
- Unsupported claim detection.
- Broken goal-to-metric-chain detection.
- Repeated failure escalation.
- Scope creep analysis.
- Evaluation protocol drift warnings.

### Phase 6: robotics adapters

After the generic substrate is stable, optionally add:

- `check_ik_feasibility`
- `check_collision_free`
- `run_simulation_smoke`
- `run_frozen_eval`
- `check_action_api`
- `check_dataset_provenance`
- `profile_training_memory`
- `run_small_exact_oracle`

For robotics plans, consider requiring:

- frozen initial-state distribution;
- action-space contract;
- episode horizon;
- simulator version and physics config hash;
- evaluation split;
- seed list;
- simulation-only vs real-world claim label;
- rollback/safety behavior.

## 21. Example Measurement Plan

```yaml
id: P-001
project_id: lehome
title: Profile placement-conditioned policy memory use
status: draft
kind: measurement

goal_ids:
  - G-final-fold-success

addresses_failure_ids:
  - F-placement-sensitivity

hypothesis:
  id: H-profile-feasibility
  statement: >
    A placement-conditioned action head can fit within the existing two-GPU
    memory budget at the target batch size.
  linked_failure_ids:
    - F-placement-sensitivity

intervention:
  id: I-vram-profile
  description: >
    Instantiate the candidate head and run a fixed three-step training smoke
    profile without changing the baseline training pipeline.
  kind: measurement
  allowed_files:
    - scripts/profile_placement_head.py
    - tests/test_profile_placement_head.py
  reversible: true

constraint_audit:
  - constraint_id: C-no-new-real-labels
    status: sat
    evidence: Existing demonstrations provide image and action tensors.
  - constraint_id: C-action-api
    status: sat
    evidence: The profiling path preserves pick/place outputs.
  - constraint_id: C-compute-budget
    status: unknown
    evidence: This plan exists to measure peak VRAM.
  - constraint_id: C-hardware-safety
    status: sat
    evidence: Simulation/training only; no physical execution.

assumptions:
  - Profiling at target batch size is representative of the full training path.

unknowns:
  - Peak allocated and reserved GPU memory.

validation_steps:
  - id: V-profile
    description: Run fixed-batch memory profile.
    kind: command
    command: profile_placement_head
    expected_result: Peak VRAM artifact is recorded.
    required: true

decision_rule:
  adopt_if:
    - Peak allocated GPU memory remains below 20 GB on each target GPU.
  reject_if:
    - Peak allocated GPU memory exceeds 22 GB or OOM occurs.

rollback_description: Delete profiling-only script; no production path is changed.
```

## 22. Example Implementation Plan

```yaml
id: P-002
project_id: lehome
title: Add pick-conditioned placement head
status: draft
kind: implementation

goal_ids:
  - G-final-fold-success

addresses_failure_ids:
  - F-placement-sensitivity

hypothesis:
  id: H-pick-place-coupling
  statement: >
    The placement prediction lacks explicit dependence on the selected pick
    point and local post-pick visual state.
  linked_failure_ids:
    - F-placement-sensitivity
  alternative_hypothesis_ids:
    - H-visual-ambiguity
    - H-contact-mismatch

intervention:
  id: I-conditioned-placement
  description: >
    Condition the placement head on selected pick coordinates and local visual
    features while preserving the current pick/place action API.
  kind: implementation
  allowed_files:
    - src/policy/placement_head.py
    - src/policy/model.py
    - configs/placement_conditioned.yaml
    - tests/test_placement_head.py
  expected_api_changes: []
  reversible: true
  estimated_cost: One short profile run plus one fixed-seed training run.

constraint_audit:
  - constraint_id: C-no-new-real-labels
    status: sat
    evidence: Uses recorded observations and action labels only.
  - constraint_id: C-action-api
    status: sat
    evidence: Output remains pick_xy and place_xy.
  - constraint_id: C-compute-budget
    status: sat
    evidence: EV-001 profile shows peak allocated VRAM 18.6 GB.
  - constraint_id: C-frozen-evaluation
    status: sat
    evidence: Evaluation uses configs/eval_frozen.yaml.
  - constraint_id: C-hardware-safety
    status: sat
    evidence: Simulation-only evaluation in this plan.

validation_steps:
  - id: V-unit
    description: Validate shape and API contract.
    kind: command
    command: unit_placement_head
    expected_result: All tests pass.
  - id: V-smoke
    description: Run deterministic one-episode rollout.
    kind: command
    command: placement_smoke
    expected_result: Valid pick/place outputs and no simulator assertion.
  - id: V-eval
    description: Evaluate frozen held-out split by placement perturbation bin.
    kind: command
    command: frozen_placement_eval
    expected_result: Metrics artifact generated.

decision_rule:
  adopt_if:
    - Held-out placement robustness improves by at least 5 percentage points.
    - Action feasibility remains within 1 percentage point of baseline.
  reject_if:
    - No measurable improvement under matched initial states.
    - Gains disappear under frozen evaluation protocol.
    - Oracle-pick comparison indicates visual ambiguity dominates.

rollback_description: Disable conditioned head via config and retain baseline checkpoint.
```

## 23. Claude Code Integration

Conceptual local MCP configuration:

```json
{
  "mcpServers": {
    "plan-auto": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/plan-auto",
        "run",
        "plan-auto"
      ],
      "env": {
        "PLAN_AUTO_DATA_DIR": "/absolute/path/to/your-project/.plan-auto"
      }
    }
  }
}
```

Use a repository-local policy in the target project `CLAUDE.md`:

```markdown
# Damped Plan MCP Policy

For any nontrivial change—multi-file edits, a new algorithm/model/loss/planner,
data/evaluation change, simulator change, or robotics behavior change:

1. Read `damped://project/current/state`.
2. Draft or update a structured plan through the `plan-auto` MCP.
3. Call `evaluate_plan`.
4. Do not edit source files until the plan is EXECUTABLE or the user explicitly
   approves a safe MEASUREMENT plan.
5. Implement only files listed in the approved plan.
6. Run registered validation tools through the MCP.
7. Record evidence and plan outcome.
8. If `analyze_drift` returns ESCALATE, stop local repair attempts and present
   the reported missing distinction or assumption.

Never report “fixed,” “working,” or “validated” without a completed validation
record linked to the active plan.
```

## 24. MVP Success Criteria

The MVP is successful when Claude Code can:

1. Load a project state with goals, constraints, failures, and baseline.
2. Create a structured candidate plan.
3. Receive a deterministic `EXECUTABLE`, `BLOCKED`, or `UNDER_SPECIFIED` result.
4. See the exact constraint or missing obligation that caused a block.
5. Receive a safe next action: measurement, repair, escalation, rollback, or implementation.
6. Run one allowlisted test/profile/benchmark through the MCP.
7. Record the resulting evidence.
8. Re-evaluate a plan and observe a valid status transition.
9. Detect repeated failed local repairs that did not change causal framing.
10. Preserve an auditable record of why an intervention was attempted, accepted, rejected, or rolled back.

The server does not need to find the best research direction. It succeeds if it prevents unjustified commitment and helps an LLM turn relevant knowledge into a feasible, testable next action.

## 25. Non-Negotiable Design Constraints

- Keep state local and portable.
- Make every decision reproducible from stored artifacts.
- Prefer deterministic logic over opaque learned scoring in v0.
- Treat `UNKNOWN` as a useful first-class result.
- Require evidence provenance before marking a hard constraint `SAT`.
- Separate plan drafting from approval.
- Separate LLM-generated semantic content from programmatically checked closure.
- Prefer minimal measurement to architecture expansion when causal uncertainty is high.
- Disable hardware actuation by default.
- Make plan-allowed files and validation commands explicit.
- Record every state transition in an append-only event log.

## 26. Initial Claude Implementation Prompt

```text
Build a local Python MCP server named `plan-auto`.

The server is a constraint-closure substrate for LLM plans. It must not act as
a generic autonomous planner. Its purpose is to store explicit project state,
validate structured plans, block unsupported implementation, run only allowlisted
validators, record evidence, and recommend the next permitted action.

Read this architecture blueprint exactly. Before coding:
1. Produce a file-level implementation plan.
2. Identify SDK/API assumptions requiring verification.
3. List the smallest first vertical slice.
4. Do not add autonomous loops, arbitrary shell execution, remote services,
   vector databases, web frontends, or ML dependencies.

Implement Phase 1 only:
- Python 3.12+, uv, Pydantic v2, pytest, Hypothesis.
- Implement models, JSON store, deterministic plan validator, residual report,
  and decision policy.
- Implement tests for valid, blocked, under-specified, and measurement-only plans.
- Create examples for a robotics project and an algorithm-review project.
- Do not implement MCP tools until the pure-Python kernel passes tests.

Definition of executable:
A normal implementation plan is EXECUTABLE only if:
- it names at least one goal with a metric;
- it addresses a registered failure mode;
- it contains a causal hypothesis;
- every hard constraint is explicitly SAT;
- it includes validation;
- it includes adopt/reject criteria;
- it includes rollback or is reversible.

UNKNOWN must never be treated as SAT.
A measurement plan may proceed with an UNKNOWN only when it safely and directly
measures that unknown and has no other unresolved hard constraints.

After implementing Phase 1:
- run tests;
- show exact commands and results;
- explain unresolved ambiguity;
- stop and wait for approval before adding MCP integration.
```

## 27. Future Extensions

Only consider these after the MVP is stable and useful in real projects:

- SQLite event sourcing with materialized state views.
- Git integration for commit/diff evidence.
- CI integration.
- Pydantic-generated JSON Schema for strict structured LLM output.
- SAT/SMT adapters for discrete constraint subproblems.
- PDDL/task-planning adapters.
- Code-coverage and static-analysis evidence adapters.
- Experiment tracker integration.
- Robotics adapters for IK, collision checking, simulation rollout, and frozen evaluation.
- A UI that visualizes plan dependencies, blockers, evidence, and drift.
- Learned or Bayesian prioritization over already-feasible candidate measurements.

Do not introduce learned scoring or optimization until the deterministic feasibility layer has been validated against real planning failures.

## 28. Final Principle

The target is not to make an LLM behave as a literal critically damped oscillator. The target is to create an external control architecture in which planning is constrained by goals, feasibility, evidence, dependencies, and executable checks.

The practical definition is:

> A hierarchical controller that drives a structured project state toward goal-and-constraint closure by selecting the smallest evidence-supported action that reduces unresolved residuals, while preventing unsupported commitments, scope oscillation, and repeated non-informative repair.

This is implementable now with an MCP server, explicit schemas, deterministic validators, a dependency graph, allowlisted checks, persistent evidence, and a disciplined Claude Code workflow.
