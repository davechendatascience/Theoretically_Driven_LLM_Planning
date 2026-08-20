---
name: damped-plan
description: Gate nontrivial changes through the damped-plan MCP — structured plans, constraint closure, measurement before commitment. Use before implementing any multi-file change, new algorithm/model/dependency, data or evaluation change, or after repeated failed fix attempts.
---

# Damped-plan workflow

You are working in a project gated by the damped-plan MCP server. For any
nontrivial change — multi-file edits, a new algorithm/model/loss/planner, a
new dependency or module, a data/evaluation/simulator change — follow this
loop instead of editing immediately:

## 1. Read state first

Call `get_project_snapshot`. If no project is registered yet, compile one with
`register_project`: goals **with metric_name and target**, hard constraints
(compute, data, interfaces, safety, evaluation protocol), observed failure
modes, and facts. Leave a hard constraint's status `unknown` unless you can
point at evidence — `unknown` is a first-class, useful answer.

## 2. Draft one structured plan

Call `create_plan` with exactly one candidate plan:

- `kind: "measurement"` if any hard constraint you depend on is `unknown` —
  the smallest safe, reversible experiment that resolves it. Its
  `constraint_audit` entry for the target constraint must say `status:
  "unknown"` with an `evidence` note explaining that this plan measures it.
- `kind: "implementation"` otherwise, with: linked `goal_ids` and failure
  mode, a causal `hypothesis` (why the failure happens), an `intervention`
  with exact `allowed_files`, required `validation_steps` that could refute
  the hypothesis, a `decision_rule` with both `adopt_if` and `reject_if`, and
  a rollback story.
- Implementation and repair plans also require a `predictive_contract`: the
  mechanism-level claim. State `context_fixed` (what is held constant so the
  comparison is valid), predictions for observables that should move AND ones
  that must stay invariant (`direction: no_change` — the most valuable kind),
  at least one `disconfirming_pattern` (what you would see if the causal
  story is wrong), each with a `suggested_model_expansion`. When recording
  results, call `record_run_metrics(plan_id, {"metric_id": value, ...})` so
  the posterior check runs deterministically, and declare any observed
  failure signature via `observed_pattern_ids`. A `mismatch` verdict means
  escalate to the named expansion — not another local patch.

The tool returns an evaluation immediately. Partial plans are fine — every
blocker message is a concrete repair instruction; apply them with another
`create_plan` call using the same plan id.

When a plan follows from another plan's findings — an implementation built on
a measurement's evidence, a follow-up after a rejection, a split mandated by
a replan decision — set `parent_plan_id` to that plan's id. Lineage recorded
structurally (not just in prose) keeps the audit trail traceable and feeds
future drift analysis.

## 3. Respect the gate

- `blocked` on `UNRESOLVED_HARD_CONSTRAINT`: do NOT argue the constraint is
  probably fine. Create the measurement plan, or record evidence and
  `update_constraint_status`.
- `ready_for_review`: present the plan to the user and ask for approval. Call
  `approve_plan` only with the user's name after they explicitly approve.
  Never approve on their behalf.
- `executable`: implement, touching only the plan's `allowed_files`.

## 4. Close the loop

After running validations, record what you observed through the right door:

- `run_validation` when a registered command produced it — mechanical, with
  an immutable artifact and polarity from the exit code.
- `record_run_metrics(plan_id, {"metric_id": value, ...})` for every number
  the contract predicted. Values land in `observations`, the only field the
  posterior check reads, and the verdict comes back in the same call. A
  number narrated into a summary scores nothing.
- `record_evidence` when the observation is not a number — a process record,
  a paper, a commit, a qualitative failure. Not weaker evidence, a different
  kind of record; never invent a `metric_id` to satisfy a field. A
  plan-linked summary stating numerals with empty `observations` comes back
  with a warning naming the metrics the contract is waiting on.

Then `update_constraint_status` for anything resolved, and
`record_plan_outcome` (`validated` requires evidence ids; use `rejected` or
`rolled_back` honestly). Never report "fixed", "working", or "validated"
without a recorded validation.

## 5. Stop repeating repairs

If a plan for the same failure mode has already failed twice with no new
evidence, the server recommends `escalate`: stop local patches, change the
causal hypothesis / representation / interface / oracle, or ask the user for
direction.
