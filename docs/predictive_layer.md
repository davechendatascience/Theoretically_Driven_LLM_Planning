# The predictive layer

Blueprint: [plan-auto-bayesian-scope.md](plan-auto-bayesian-scope.md).
This doc describes what is implemented (Phases B–D, deterministic; Phase E —
numeric inference — deliberately deferred until repeated structured
measurements exist).

The feasibility gate answers *may this plan proceed*. The predictive layer
answers a different question: *did the causal story behind the plan survive
contact with evidence?* It borrows the discipline of the Bayesian workflow —
explicit models, predictive checks, discrepancy-driven revision — without
numeric inference: a model is checked by whether replicated observations
resemble the real ones, and the *shape* of a mismatch identifies which model
component needs expansion (posterior predictive checking; Gelman et al.,
*Bayesian Data Analysis*, ch. 6).

## The predictive contract

Every **new** `implementation` or `repair` plan (schema v2 — plans created
before this layer are grandfathered and evaluate under the original rules
forever) must carry a `predictive_contract` inside its `create_plan` payload:

```json
"predictive_contract": {
  "context_fixed":  ["frozen eval protocol", "pinned scenes", "same budget"],
  "context_varied": ["policy architecture"],
  "predictions": [
    {"metric_id": "placement_success_rate", "direction": "increase",
     "expected_range": [0.47, 0.60], "confidence": "medium"},
    {"metric_id": "action_feasibility_rate", "direction": "no_change",
     "expected_range": [0.95, 1.0]}
  ],
  "disconfirming_patterns": [
    {"id": "D-1", "description": "Gain disappears on the held-out split",
     "implication": "overfitting, not the claimed mechanism",
     "suggested_model_expansion": "leakage/regularization diagnostic"}
  ],
  "next_expansions": ["oracle-pick conditioning test"]
}
```

Structural closure (blockers `MISSING_PREDICTIVE_CONTRACT` /
`INCOMPLETE_PREDICTIVE_CONTRACT`) requires: at least one prediction, a
non-empty `context_fixed`, at least one disconfirming pattern, and a named
mismatch-to-expansion path. The distinct jobs rule: the contract is
**mechanism-level** (what moves, what stays invariant, what failure
signatures mean); `decision_rule` stays **decision-level** (the thresholds
that trigger adopt/reject). `no_change` predictions — invariances — are the
most valuable entries: they are what plain adopt/reject criteria never state.

## Structured observations

Posterior checks are deterministic, so numbers must enter the store
structurally, not as prose. The intended door is `record_run_metrics`:

```text
record_run_metrics("P-0007", {"placement_success_rate": 0.43})
```

It writes the values into `observations`, links the record to the plan, and
returns the recomputed evaluation in the same call — so the verdict
(`consistent` | `mismatch` | `inconclusive`) is visible at the moment of
recording, along with which contract metrics remain unobserved.

A plan-linked record whose summary states numerals while `observations` stays
empty now comes back with a warning naming the metrics the contract is waiting
on. It warns and never refuses: a mandatory field is satisfiable by
fabricating a value, and `predictive_status: inconclusive` already prevents an
honest `validated`. See [evidence_discipline.md](evidence_discipline.md).

`record_evidence` still accepts the same structure directly, which is what
`record_run_metrics` builds:

```json
"observations": [
  {"metric_id": "placement_success_rate", "value": 0.43,
   "seed_values": [0.42, 0.44, 0.43]}
],
"observed_pattern_ids": ["D-1"]
```

`observed_pattern_ids` explicitly declares that a contract's disconfirming
pattern was seen — the honest channel for "the failure signature happened."

## The posterior check

`evaluate_plan` runs it whenever a contract exists; the result appears as
`predictive_status`, `predictive`, `dominant_residual`, and
`model_expansion_target` in the evaluation:

- a prediction with an `expected_range` and a recorded observation is
  **matched** or **violated**;
- a declared disconfirming pattern is a **mismatch** regardless of ranges;
- direction-only predictions without ranges, or evidence without structured
  observations, are **inconclusive** — never guessed (UNKNOWN stays a
  first-class answer here too);
- no linked evidence at all → **not_ready**.

Any mismatch drives `recommended_next_action: escalate` with the mismatch as
`dominant_residual: causal_model` and the contract's own expansion as the
named next step. This is the layer's central move: a failed prediction is not
a generic negative result — it points at the smallest missing model
component, and the follow-up plan should carry `parent_plan_id` back to the
mismatched one.

Prior predictive checks (§7 of the blueprint) reuse existing machinery:
validation steps marked `"phase": "prior"` (smoke tests, small oracles,
profiling via the Phase 4 command runner) run before implementing, and a
refuting prior result recommends REPAIR/MEASURE rather than proceeding.

## Migration

Purely additive. Existing plans keep `schema_version: 1` and their exact
pre-refactor closure semantics; terminal plans are never re-evaluated;
evidence, constraints, events, and gates are untouched. Verified against
copies of all three live project stores: 26 plans, zero status changes, zero
new events.

## References

- Gelman, A., Carlin, J. B., Stern, H. S., Dunson, D. B., Vehtari, A., and
  Rubin, D. B. *Bayesian Data Analysis*, 3rd edition. CRC Press, 2013. —
  the source of the model-checking discipline this layer operationalizes,
  in particular posterior predictive checking (ch. 6): compare observed data
  to replications under the model, and treat discrepancy as information
  about which model dimension is inadequate.
- Gelman, A., Vehtari, A., Simpson, D., et al. "Bayesian Workflow."
  arXiv:2011.01808, 2020. — the iterative model-building/checking/expansion
  loop mirrored by the contract → check → expansion cycle.
