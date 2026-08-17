# How critical damping translates to qualitative project state

The project's origin is a control idea: critically damped adjustment resolves
a subtask as fast as possible without overshoot or ringing. Generalizing it —
every subtask a constraint to be satisfied — raises the obvious objection:
most project measures are qualitative. There is no numeric error signal, no
derivative, no damping coefficient to tune.

The blueprint's §5 answer, and this implementation's, is: do not quantify the
qualitative. Replace each ingredient of the control loop with a **discrete
observable that carries the same control intent**.

## The core move: qualitative → categorical + provenance

The system never asks "how satisfied is this constraint, 0 to 1?" It asks
"**what recorded evidence lets you claim which of four states?**" —
`sat / unsat / unknown / not_applicable`. A qualitative judgment becomes
tractable for a controller not by scoring it but by making it a **falsifiable
state transition with an audit trail**:

- "Do we trust the rollout harness?" (embodied_ai) is as qualitative as it
  gets. It became constraint C-0002 with a discrete refutation procedure:
  *assert `len(successes) == 15` and print the raw return before any
  extraction*. Trust was operationalized as a check that can fail.
- "The module respects the architecture boundary" (robot_alert_module's
  `contract-only`) — a code-quality judgment — became `sat` via a test suite
  that cannot pass if the module imports simulator internals.
- Where no mechanical check exists, `manual_review` evidence is allowed — but
  the judgment must be written down *before it is used*, linked to constraint
  ids, and the `sat` transition still requires it (`constraint_service.py`
  refuses `sat` on a hard constraint without evidence ids). The discipline is
  not "measure numerically"; it is "commit to the claim in a form that can
  later be pointed at, and refuted."

## Where each damping behavior lives, without a damping coefficient

The "error" is a **count vector of unmet discrete obligations**
(`ResidualReport`: hard-constraint gap, evidence gap, validation gap), and the
dynamics are read off **event structure**, not values:

| Control concept | Discrete mechanism |
|---|---|
| Overshoot (premature commitment) | The gate: implementation plans cannot leave `blocked` while any hard constraint ≠ `sat` — you cannot move further than your evidence (`plan_validation.derive_status`) |
| Oscillation (repair loops) | Recurrence *without new information*: ≥ 2 rejected/rolled-back sibling plans with no evidence recorded since → `escalate` (`decision_policy.repeated_noninformative_failure`) |
| Overdamping (endless analysis) | The measurement exception: a safe measurement plan is the *only* thing allowed through a closed gate, and `measure` is the recommended action whenever an unknown blocks — the system's pressure always points at the cheapest information-gaining act |
| Critical damping (right-sized step) | The lexicographic policy: rollback > measure > repair > escalate > implement — the smallest evidence-supported action addressing the dominant unresolved residual, with hard constraints at absolute priority |
| Velocity / ringing signal | The event log: plan versions, status transitions, evidence timestamps. Qualitative *content*, quantitative *dynamics* — flip and rework rates are countable regardless of what the plans are about |

Note the consequence for the "each subtask is a constraint" generalization:
the oscillation detector never compares subtask *outcomes* quantitatively. It
only notices that state transitions recur while the evidence set is not
growing. That is why it survives qualitative domains.

## The second discipline: pre-registration

The other entry point for qualitative judgment is "did this intervention
work?" The system handles it not with metrics but by **binding the judgment
before execution**: `decision_rule.adopt_if` / `reject_if` may be qualitative
sentences ("gains disappear under the frozen protocol"), but they are stated
at plan time, and `record_plan_outcome(validated)` requires evidence recorded
against them. Post-hoc rationalization of an outcome into success is blocked
because the criteria predate the result — the qualitative analogue of a
setpoint. The same discipline reaches individual validation steps through the
`expected_result` warning.

## What is honestly not captured

- **No gain.** The policy chooses the *category* of the next action, never its
  size. "Smallest reversible intervention" is enforced only through
  `allowed_files` scoping — nothing stops a plan whose scope is technically
  listed but too large.
- **Dominant residual is lexicographic, not magnitude-based.** With three
  unknowns, the system does not know which measurement buys the most
  information. That is the deferred Bayesian-prioritization extension (§27) —
  the one place a real number might eventually earn its way in.
- **`manual_review` sat is only as strong as the review.** The system records
  the claim with provenance but cannot verify it. The audit trail makes
  dishonesty visible later, which is weaker than making it impossible — the
  honest limit of a deterministic substrate.

The summary: the achievement is not quantifying the qualitative. It is
replacing "magnitude of error" with "membership in an unresolved set,"
replacing "derivative of state" with "structure of the event history," and
letting the damping policy operate on those — which is why a project full of
degree-measurements and a project full of architectural judgments run through
the identical controller.
