# Damped Plan MCP with Bayesian Workflow
## Scope, Architecture, and Gelman-Loop Integration

## 1. Decision

Build **one MCP server** and **one canonical project-state store**:

```text
damped-plan-mcp
```

Do not build a separate Bayesian MCP in the first version.

Implement the system internally as three separable layers:

```text
feasibility layer  → can this plan safely proceed?
predictive layer   → did its causal model survive evidence?
control layer      → what should happen next?
```

This preserves a single state and evidence history while keeping the code modular enough to extract a standalone Bayesian workflow component later.

## 2. Why One MCP

The damping/constraint-closure system and Gelman's Bayesian workflow operate on the same core entities:

| Shared entity | Constraint-closure role | Bayesian-workflow role |
|---|---|---|
| Goal | Defines required project state | Defines decision-relevant outcome |
| Constraint | Feasibility boundary | Defines admissible context/model space |
| Failure mode | Source of project residual | Observed anomaly requiring explanation |
| Hypothesis | Candidate causal explanation | Working model to check and revise |
| Plan | Controlled project action | Intervention under a causal model |
| Metric | Progress/acceptance criterion | Observable prediction |
| Validation | Evidence of feasibility/correctness | Observation process |
| Evidence | Updates constraint status | Updates model adequacy/belief |
| Decision | Approve, block, repair, rollback | Expand/revise model after mismatch |

Splitting these into two servers too early would create a synchronization problem. The system would need to manually pass plan IDs, hypothesis IDs, metric definitions, fixed experimental context, artifacts, constraint versions, evaluation protocol versions, and outcomes from one MCP to the other.

That handoff is where an LLM can lose constraints, forget assumptions, or reinterpret evidence after the fact.

Use a single SQLite event store, a single dependency graph, and a single project-state schema in v0.

## 3. Product Goal

The MCP is a local, auditable substrate that stops an LLM from turning broad knowledge into unsupported execution.

> The LLM may propose semantics, methods, and candidate actions. The substrate decides whether the candidate is sufficiently specified, feasible, testable, and evidence-grounded to execute.

The server should produce one of these next actions:

```text
MEASURE
IMPLEMENT
REPAIR
ROLLBACK
ESCALATE
STOP
```

The system does not need to find the globally optimal project strategy. Its first job is to identify a **feasible and falsifiable next action**.

## 4. Three-Layer Architecture

```text
                         ┌────────────────────────────┐
                         │ Claude Code / MCP host      │
                         │ proposes plans and changes  │
                         └─────────────┬──────────────┘
                                       │
                         ┌─────────────▼──────────────┐
                         │ Damped Plan MCP             │
                         │ canonical project state     │
                         └─────────────┬──────────────┘
                                       │
      ┌────────────────────────────────┼────────────────────────────────┐
      │                                │                                │
┌─────▼──────────┐              ┌──────▼──────────┐              ┌──────▼──────────┐
│ Feasibility    │              │ Predictive      │              │ Control /       │
│ layer          │              │ layer           │              │ damping layer   │
│                │              │                 │              │                 │
│ constraints    │              │ hypotheses      │              │ residuals       │
│ closure        │              │ predictions     │              │ drift           │
│ dependencies   │              │ prior checks    │              │ escalation      │
│ safety         │              │ posterior checks│              │ next action     │
└─────┬──────────┘              └──────┬──────────┘              └──────┬──────────┘
      │                                │                                │
      └────────────────────────────────┴────────────────────────────────┘
                                       │
                         ┌─────────────▼──────────────┐
                         │ plan decision               │
                         │ measure / implement / etc.  │
                         └────────────────────────────┘
```

### 4.1 Feasibility layer

The feasibility layer checks whether a plan may proceed.

It evaluates:

- Goal linkage.
- A measurable success metric.
- Hard constraints.
- API, data, compute, safety, simulator, and evaluation requirements.
- Dependencies and required prerequisites.
- Validation and rollback obligations.
- Whether a proposed intervention is linked to a recorded failure mode.

Its core rule is:

\[
\texttt{implementation plan executable}
\Rightarrow
\bigwedge_{c \in C_h} c = \texttt{SAT}.
\]

For ordinary implementation plans:

\[
\texttt{UNKNOWN hard constraint}
\Rightarrow
\texttt{BLOCKED}.
\]

The exception is a safe **measurement plan** whose direct purpose is resolving that unknown.

### 4.2 Predictive layer

The predictive layer is where Gelman's model-building and model-checking loop enters the system.

It asks:

> If the causal story behind this plan is correct, what should happen after we run it, what should remain unchanged, and what observable pattern would show that the story is wrong?

It stores:

- Causal hypothesis.
- Fixed experimental context.
- Variables intentionally changed.
- Expected metric changes or ranges.
- Expected invariances.
- Disconfirming patterns.
- Candidate model expansion if the prediction fails.

This layer does not initially require numeric Bayesian inference. It implements the **Bayesian workflow discipline**: explicit models, predictive checks, discrepancy-driven revision, and targeted model expansion.

### 4.3 Control/damping layer

The control layer monitors the trajectory of planning itself.

It decides whether the dominant residual is:

- A hard feasibility blocker.
- Missing evidence.
- A failed validation.
- A causal-model mismatch.
- Repeated non-informative repair.
- Uncontrolled scope expansion.
- A completed objective.

It enforces stable progress:

```text
Hard constraint unresolved → MEASURE or ESCALATE.
Competing hypotheses → lowest-cost discriminative MEASUREMENT.
Supported hypothesis → smallest reversible IMPLEMENTATION.
Prediction mismatch → targeted model expansion.
Repeated local failures → ESCALATE abstraction level.
Regression/constraint violation → ROLLBACK.
Goal and required validation closed → STOP.
```

## 5. Gelman's Bayesian Workflow

## 5.1 What is being borrowed

Gelman's Bayesian workflow is not just posterior computation. The relevant loop is:

```text
model building
    ↓
inference / expectation formation
    ↓
model checking
    ↓
discrepancy discovery
    ↓
model expansion or revision
    ↓
repeat
```

A model is not accepted because it can fit data or produce a posterior. It is checked by asking whether it can generate replicated observations resembling the real observations.

For a statistical model \(M\):

\[
\theta \sim p(\theta \mid y, M),
\qquad
y_{\mathrm{rep}} \sim p(y_{\mathrm{rep}} \mid \theta, M).
\]

Then compare observed data \(y\) to replicated data \(y_{\mathrm{rep}}\). The mismatch identifies dimensions in which the model is inadequate.

In this MCP, the equivalent question is:

> Given the plan's causal hypothesis, intervention, and fixed context, does the observed system response look like the response that hypothesis predicted?

## 5.2 Translation into project planning

| Bayesian workflow concept | MCP equivalent |
|---|---|
| Generative model \(p(y \mid \theta, M)\) | Causal project model: intervention, mechanism, context, expected observables |
| Prior | Existing evidence, prior project beliefs, domain knowledge, confidence labels |
| Observed data \(y\) | Tests, benchmarks, rollouts, logs, profiler output, metrics, counterexamples |
| Posterior/update | Updated support for hypotheses and constraint statuses |
| Prior predictive check | Before implementation: simulate or estimate whether plan outputs are plausible/feasible |
| Posterior predictive check | After execution: compare predicted and observed outcome patterns |
| Model misfit | Causal story behind plan does not explain observed response |
| Model expansion | Add the smallest missing variable, mechanism, constraint, interaction, or subsystem |
| Model comparison | Compare competing causal hypotheses under frozen evaluation |
| Sensitivity analysis | Test whether a decision changes over seeds, scenarios, priors, environments, or budgets |

## 5.3 Why this matters to damping

The damping layer alone can prevent uncontrolled action selection:

```text
observe failure → feasible intervention → execute → check → next action
```

But it can still wander among feasible interventions if it does not know whether its **internal causal model** is wrong.

The Bayesian workflow adds a model-checking loop:

```text
observe failure
→ state causal hypothesis
→ predict signature of success/failure
→ run minimal feasible test
→ compare prediction with observation
→ revise or expand only the implicated part of the model
→ choose next action
```

This turns stable trial-and-error into targeted, discrepancy-driven learning.

## 6. Predictive Contract

Every nontrivial implementation plan should include a `predictive_contract`.

```yaml
predictive_contract:
  causal_hypothesis:
    id: H-pick-place-coupling
    statement: >
      Terminal fold failures are mainly caused by placement prediction lacking
      explicit conditioning on the selected pick and local post-pick state.

  context_fixed:
    - Frozen held-out garment split
    - Fixed simulator version and physics configuration
    - Same action API
    - Same training budget
    - Same baseline evaluation script

  context_varied:
    - Placement perturbation magnitude
    - Policy architecture: baseline vs pick-conditioned placement head

  expected_observables:
    - metric: placement_robustness
      prediction: >
        Improvement should increase with placement-perturbation magnitude while
        pick feasibility remains approximately unchanged.
      direction: increase
      confidence: medium

    - metric: action_feasibility_rate
      prediction: >
        No material decline relative to baseline is expected.
      direction: no_change
      confidence: medium

    - metric: one_step_pick_success
      prediction: >
        Little or no improvement is expected because the intervention targets
        placement dependence rather than pick selection.
      direction: no_change
      confidence: high

  disconfirming_patterns:
    - id: D-generalization-failure
      pattern: >
        Improvement appears only in the training distribution and disappears on
        the held-out garment split.
      implication: >
        The apparent gain may be overfitting rather than evidence for the
        pick-place coupling hypothesis.

    - id: D-oracle-pick-no-gain
      pattern: >
        Baseline and conditioned policies fail similarly when supplied an
        oracle pick point.
      implication: >
        Missing pick-conditioning is unlikely to be the main causal mechanism.

    - id: D-eval-drift
      pattern: >
        The primary gain appears only after an evaluation-protocol change.
      implication: >
        The result is not comparable to baseline and cannot support the claim.

  next_model_expansion_if_failed:
    - condition: Oracle-pick conditioning does not improve placement.
      expansion: Test visual-state ambiguity with an oracle state or segmentation intervention.

    - condition: One-step effect exists but terminal benefit disappears.
      expansion: Test long-horizon rollout or contact-dynamics mismatch.
```

The predictive contract prevents a plan from being merely:

> Add a method and see whether the aggregate score improves.

Instead, it requires:

> Under hypothesis \(H\), this intervention should change these observables in these directions, leave these others unchanged, and produce these recognizable failure signatures if \(H\) is wrong.

## 7. Prior Predictive Checks

A prior predictive check is performed before committing to a full implementation or expensive experiment.

It asks:

> Under the proposal's assumptions, can it plausibly produce valid outputs and satisfy the known hard constraints?

### 7.1 Examples

| Plan type | Prior predictive check |
|---|---|
| New ML architecture | Parameter count, target-batch VRAM profile, one-batch forward/backward smoke test, expected training-time estimate |
| New loss/reward | Evaluate reward and gradient distributions on logged trajectories; inspect degenerate optima/reward hacking |
| New algorithm | Exhaustive small-instance oracle, invariant checks, asymptotic scaling test |
| New planner | Tiny synthetic cases with known feasible or optimal solutions |
| New robotics action | Offline IK, collision, workspace, action-limit, and force-limit check |
| Simulator modification | Replay baseline trajectory and quantify state/action distribution shift |
| Dataset transformation | Label integrity, identity preservation, split leakage, class balance, distribution checks |
| New evaluation metric | Verify behavior on known successful and known failing examples |

### 7.2 Plan status implication

If a prior predictive check indicates that the proposal cannot fit memory, violates action/API constraints, has invalid reward geometry, fails a small oracle, or creates impossible trajectories, the system should not proceed to full implementation.

```text
Prior predictive failure → REPAIR, MEASURE, or ROLLBACK.
```

## 8. Posterior Predictive Checks

A posterior predictive check happens after the intervention is run and evidence is recorded.

It asks:

> Did actual behavior match the outcome signature predicted by the plan's causal model?

For a plan model \(M\), intervention \(a\), fixed context \(x\), and observed result \(y\):

\[
p(y_{\mathrm{rep}} \mid y, M, a, x)
\]

is conceptually the distribution of expected replicated results. In v0, approximate this with directional predictions, expected numeric ranges, and stratified comparison rather than full posterior sampling.

### 8.1 Initial qualitative implementation

```yaml
prediction:
  metric: heldout_placement_robustness
  baseline_value: 0.42
  expected_range: [0.47, 0.60]
  expected_direction: increase
  confidence: medium

observation:
  metric: heldout_placement_robustness
  observed_value: 0.43
  seed_values: [0.42, 0.44, 0.43]
  artifact: evidence/EV-018-frozen-eval.json

predictive_check:
  status: mismatch
  mismatch_type: no_targeted_effect
  interpretation: >
    The intervention did not produce the predicted placement-robustness effect.
    Do not treat pick-place representation coupling as supported.
```

### 8.2 Later quantitative implementation

Once repeated measurements exist, compare observed statistics to replicated distributions:

\[
T(y_{\mathrm{obs}})
\quad \text{versus} \quad
\left\{T\left(y_{\mathrm{rep}}^{(s)}\right)\right\}_{s=1}^{S}.
\]

Potential statistics \(T\):

- Mean and per-task held-out success.
- Per-garment variance.
- p95 terminal state error.
- Placement-perturbation robustness slope.
- Collision/feasibility rate.
- Peak VRAM and runtime.
- Sim-to-real performance gap.
- Objective-gap distribution for a heuristic.
- Test failure and recovery rate for coding-agent workflows.

## 9. Mismatch-to-Expansion Rules

The predictive layer should not respond to every failure with a generic request for a new architecture. It maps discrepancy patterns to the smallest justified model expansion.

| Predictive mismatch | Candidate missing model component | Next action |
|---|---|---|
| Outputs impossible before training | Resource model, API/shape contract, coordinate convention | Repair or measurement |
| Training metric improves but held-out metric does not | Data distribution, representation, regularization, leakage check | Diagnostic ablation |
| One-step behavior improves but multi-step behavior fails | Dynamics, compounding error, latent state, contact model | Rollout diagnostic |
| Simulation improves but real-world result does not | Sim-to-real observation, calibration, contact, sensing | Transfer diagnostic |
| Goal metric improves while feasibility/safety degrades | Objective omitted a constraint | Constraint-model expansion |
| Result varies strongly by seed or scenario | Hierarchical variation, uncertainty, instability | Multi-seed/stratified evaluation |
| Algorithm passes examples but fails exact oracle | Specification/invariant/edge-case model | Algorithmic repair |
| Same repair repeatedly fails | Wrong causal abstraction or subsystem boundary | Escalate |

This is the central Gelman-style contribution: model failure is informative. A mismatch is not merely a negative result; it points to which part of the project model needs expansion.

## 10. Shared Domain Model

Use one plan model with an optional predictive layer.

```python
from typing import Literal
from pydantic import BaseModel, Field


class Prediction(BaseModel):
    metric_id: str
    direction: Literal["increase", "decrease", "no_change", "non_monotonic"]
    expected_range: tuple[float, float] | None = None
    expected_pattern: str
    confidence: Literal["low", "medium", "high"]
    rationale: str


class DisconfirmingPattern(BaseModel):
    id: str
    description: str
    implication: str
    suggested_model_expansion: str | None = None


class PredictiveContract(BaseModel):
    context_fixed: list[str]
    context_varied: list[str]
    predictions: list[Prediction]
    disconfirming_patterns: list[DisconfirmingPattern]
    next_expansions: list[str] = Field(default_factory=list)


class PredictiveCheck(BaseModel):
    plan_id: str
    observed_artifact_ids: list[str]
    status: Literal["consistent", "mismatch", "inconclusive"]
    matched_prediction_ids: list[str]
    violated_prediction_ids: list[str]
    discrepancy_summary: str
    recommended_expansion: str | None = None
```

Extend the existing `Plan` schema:

```python
class Plan(BaseModel):
    # Existing plan fields...
    predictive_contract: PredictiveContract | None = None
```

For nontrivial implementation and experiment plans, require `predictive_contract`. For simple maintenance, formatting, or local bug fixes, keep it optional.

## 11. Internal Service Interfaces

Keep services modular even though they live in one MCP server.

```python
from typing import Protocol


class FeasibilityService(Protocol):
    def evaluate(self, plan: Plan, project: ProjectState) -> FeasibilityReport: ...


class PredictiveService(Protocol):
    def prior_check(self, plan: Plan, project: ProjectState) -> PredictiveCheck: ...

    def posterior_check(
        self,
        plan: Plan,
        observations: list[EvidenceRecord],
    ) -> PredictiveCheck: ...


class ControlService(Protocol):
    def decide(
        self,
        feasibility: FeasibilityReport,
        predictive: PredictiveCheck | None,
        drift: DriftReport,
    ) -> NextActionDecision: ...
```

This keeps the implementation testable and allows later extraction of a Bayesian workflow library or separate MCP if it becomes independently useful.

## 12. Integrated Tool Surface

### 12.1 Existing core tools

```text
register_project
get_project_snapshot
create_plan
evaluate_plan
approve_plan
run_validation
record_evidence
update_constraint_status
record_plan_outcome
analyze_drift
```

> As designed. The shipped surface adds `record_run_metrics` and does not yet
> implement `analyze_drift` (Phase 5); [tool_contracts.md](tool_contracts.md)
> is the live reference.

### 12.2 Bayesian-workflow augmentation tools

```text
define_predictive_contract
after_plan_prior_check
evaluate_predictive_check
recommend_model_expansion
```

### 12.3 Preferred integrated evaluation

The main tool should combine both concepts:

```text
evaluate_plan(plan_id)
```

Before execution, return an integrated answer:

```json
{
  "execution_status": "blocked",
  "feasibility": {
    "hard_constraints": "unknown",
    "blockers": ["C-compute-budget"]
  },
  "predictive_status": "not_ready",
  "dominant_residual": "feasibility",
  "recommended_next_action": "measure",
  "required_measurement": "profile target-batch GPU memory"
}
```

After execution, return an integrated answer:

```json
{
  "execution_status": "validated",
  "feasibility": {
    "hard_constraints": "sat"
  },
  "predictive_status": "mismatch",
  "mismatch_type": "one_step_gain_no_terminal_gain",
  "dominant_residual": "causal_model",
  "recommended_next_action": "escalate",
  "model_expansion_target": "long-horizon transition/contact dynamics",
  "recommended_measurement": "compare one-step and H-step rollout error"
}
```

## 13. Implementation Order

### Phase A: constraint-closure kernel

Implement first:

- Project, constraint, plan, evidence, and validator schemas.
- `SAT` / `UNSAT` / `UNKNOWN` constraint audit.
- Plan closure validator.
- Measurement-plan exception.
- Residual report.
- Deterministic next-action policy.
- JSON or SQLite store.
- Unit tests.

### Phase B: predictive-contract schema

Add:

- `Prediction`.
- `DisconfirmingPattern`.
- `PredictiveContract`.
- Structural validation:
  - primary metric has a prediction;
  - context fixed/varied is stated;
  - at least one falsifying pattern exists;
  - a mismatch expansion is named.

Do not add numerical Bayesian inference yet.

### Phase C: qualitative predictive checks

Implement:

- Prior checks through allowlisted smoke tests, small oracles, profiling, simulation, and schema/API checks.
- Posterior checks through directional/range comparison against artifacts.
- `consistent`, `mismatch`, and `inconclusive` status.
- Mismatch-to-expansion rule table.

### Phase D: integrated control

Implement:

- Dominant residual selection.
- Repeated-failure escalation.
- Scope-drift and evaluation-drift detection.
- Unified `evaluate_plan` decision report.

### Phase E: numerical Bayesian analysis, only when warranted

Introduce a dedicated statistical module only after the project collects repeated, structured measurements.

Candidate later use cases:

- Success probability across garments, seeds, and policies.
- Rollout error versus horizon.
- Sim-to-real performance gaps.
- Training memory/runtime distributions.
- Algorithmic heuristic objective-gap distributions.

For example, a hierarchical success model could be:

\[
\operatorname{logit}(p_{g,m})
=
\alpha + \alpha_g + \beta_m + \gamma_{g,m},
\]

where \(g\) indexes garment/task family and \(m\) indexes intervention or method.

Do not make this a prerequisite for the MCP's everyday planning value.

## 14. When to Split Into a Separate MCP

Keep a single MCP unless one or more of these conditions holds:

- The predictive system is needed for statistical-analysis projects with no code/project-control component.
- Another team or host needs Bayesian experiment-design tools without source-code and project-state access.
- The predictive layer gains heavy independent dependencies such as Stan, PyMC, ArviZ, an experiment tracker, or remote compute.
- A generic predictive-check API has stabilized and is independently valuable.
- Data-security boundaries require separation between source/project-control state and research data.
- The combined server becomes difficult to test, deploy, or understand.

If a split occurs later, preserve shared IDs and schemas:

```text
damped-plan-mcp
    → PlanContext + EvidenceRef

bayesian-workflow-mcp
    → PredictiveCheck + ModelExpansionRecommendation
```

Do not create two competing project-state databases.

## 15. Final Recommendation

Build one server, one event log, one dependency graph, and one plan lifecycle.

The two concepts are not competing additions:

- The damping/closure layer determines whether an action is feasible, bounded, and non-oscillatory.
- Gelman's workflow determines whether the causal model behind that action is adequate and how it should expand after evidence disagrees.

The unified controller is:

\[
\text{constraint closure}
+
\text{predictive checking}
+
\text{targeted model expansion}
+
\text{anti-oscillation meta-control}.
\]

The immediate implementation target is simple:

> Add a predictive contract to every nontrivial plan. Require a hypothesis, predictions, fixed context, disconfirming patterns, and a mismatch-to-expansion path. Use the existing feasibility gate to determine whether the test can run, and use the observed-versus-predicted result to decide whether to implement, repair, escalate, roll back, or stop.
