# Tool contracts

The server is bound to one target project via `DAMPED_PLAN_DATA_DIR` (its
`.damped-plan/` directory), so no tool takes a `project_id`. All entity
payloads are forgiving: missing optional structure degrades a plan to
`draft`/`under_specified` with repair instructions instead of erroring; IDs
and timestamps are auto-generated; enums are coerced case-insensitively.
Every result carries a `human_summary`.

## register_project(project: dict) -> ProjectSummary

Create or merge the project state. Minimal call: `{"name": "my-project"}`.

- `goals`: strings or `{statement, metric_name, target, evaluation_protocol,
  priority, met}`. Goals without metric/target produce a warning and make
  linked plans `under_specified`.
- `constraints`: strings (become **hard**, status **unknown**) or
  `{id, statement, kind: hard|soft, severity, status}`. A hard constraint
  registered as `sat` without evidence is downgraded to `unknown`.
- `failure_modes`: strings or `{symptom, severity, subsystem}`.
- `facts`, `available_resources`, `forbidden_actions`, `current_baseline`.

Idempotent merge by id: re-registering updates statements and adds items,
never deletes, and never changes a recorded constraint status (that requires
`update_constraint_status`).

## get_project_snapshot() -> ProjectSnapshot

Goals (+`met`), constraint statuses, plan index, open unknowns, top blockers,
`recommended_next_action`, and whether the gate is open.

## create_plan(plan: dict) -> PlanEvaluation

Create a plan — or repair one by calling again with the same `id` while it is
`draft`/`under_specified`/`blocked`. Approved and terminal plans cannot be
edited (create a follow-up plan with `parent_plan_id`).

Minimal call: `{"title": "...", "kind": "measurement|implementation|repair|rollback"}`.
`kind` cannot be defaulted: it decides which gate rules apply.

Auto-population: plan id (`P-000N`), timestamps, `goal_ids` (defaults to all
unmet goals), and a constraint-audit skeleton seeded from the project's
recorded constraint statuses. An audit entry claiming `sat` for a hard
constraint the project records otherwise is downgraded (no self-certification);
an audit entry may scope a constraint out with `not_applicable` plus a reason.

The plan is evaluated immediately; the returned evaluation contains:

- `plan_status`: `under_specified` | `blocked` | `ready_for_review` | ...
- `executable`: true = meets every gate condition; becomes `executable` on
  human approval.
- `blockers[]`: `{code, message, constraint_id?}` — each message is a concrete
  repair instruction. Codes: `MISSING_GOAL`, `MISSING_METRIC`,
  `ORPHAN_INTERVENTION`, `MISSING_HYPOTHESIS`, `MISSING_INTERVENTION`,
  `MISSING_VALIDATION`, `HYPOTHESIS_UNTESTABLE`, `MISSING_DECISION_RULE`,
  `MISSING_ROLLBACK`, `UNRESOLVED_HARD_CONSTRAINT`, `UNSAT_HARD_CONSTRAINT`.
- `residuals`, `warnings`, `recommended_next_action`, `human_summary`.

Closure requires: linked goal with metric, failure-mode link **or** unmet-goal
link, causal hypothesis, scoped intervention (list `allowed_files` — the gate
hook enforces them), required validation step, `decision_rule` with both
`adopt_if` and `reject_if`, and rollback (or reversible intervention;
measurement plans are exempt).

Hard-constraint rule: an implementation/repair plan is `blocked` while any
hard constraint is not `sat`/`not_applicable`. A **measurement** plan may
proceed with `unknown` hard constraints only if its audit entry for each one
carries a non-empty `evidence` text explaining that this plan measures it,
the intervention is reversible, and nothing is `unsat`.

## evaluate_plan(plan_id: str) -> PlanEvaluation

Deterministic re-evaluation; persists any status transition and rewrites the
gate. Safe to call any time.

## get_plan(plan_id: str) -> {plan, evaluation}

## approve_plan(plan_id, approver, approval_note="") -> {plan, gate_open, human_summary}

Records the human's approval of a `ready_for_review` plan and promotes it to
`executable` (gate opens for its `allowed_files`). `approver` must be the
human's name/handle as stated by them; values like "claude"/"assistant"/"ai"
are refused. This is an honor-system audit trail: the real approval happens
in the conversation, and the tool records who gave it.

## run_validation(plan_id, validation_step_id) -> {run, passed, evidence, human_summary}

Executes an **approved** plan's validation step through the allowlisted
command registry and converts the captured result into evidence
automatically — the mechanical alternative to narrating command output into
`record_evidence`.

The registry is `.damped-plan/commands.json` in the target project:

```json
{
  "unit_tests": {
    "allowed": true,
    "argv": ["uv", "run", "pytest", "-q"],
    "timeout_s": 300,
    "source_type": "test",
    "description": "full unit suite"
  }
}
```

Rules: argv arrays only (`shell=False`, no interpolation or templating);
timeout enforced (default 600 s, cap 3600 s); working directory pinned to the
project root; full stdout/stderr written to an immutable artifact under
`.damped-plan/artifacts/`. The validation step's `command` field must name a
registered id (set it before approval — approved plans cannot be edited), and
the plan must be `approved`/`executable`/`executing`; the first run promotes
`executable` → `executing`.

Evidence polarity is mechanical: exit 0 → `supports`, non-zero or timeout →
`refutes`, linked to the plan with the artifact as provenance. A failing
required validation means repair or reject — never `validated`.

Honest limit: the registry is allowlist-by-convention (plain JSON in the data
dir), not a security boundary — its job is reviewable provenance, and a human
should treat `commands.json` changes like code review. Read it via the
`damped://project/current/commands` resource.

## record_evidence(evidence: dict) -> {evidence, human_summary}

Minimal call: `{"summary": "what was observed"}`. Optional: `source_type`
(`test|benchmark|simulation|log|manual_review|paper|commit|profiling|solver`,
default `manual_review`), `polarity` (`supports|refutes|neutral`),
`artifact_uri`, `linked_constraint_ids`, `linked_hypothesis_ids`,
`linked_plan_id`. One record may back several constraints. The response hints
which `unknown` hard constraints this evidence could resolve.

## update_constraint_status(constraint_id, status, rationale, evidence_ids?) -> {constraint, plan_transitions, human_summary}

Marking a **hard** constraint `sat` requires at least one existing evidence id
plus a rationale (`unknown` is never coerced to `sat`). Marking `unsat` needs
no evidence — reporting a violation must stay low-friction. Afterwards every
open plan is re-evaluated; `plan_transitions` lists status changes (e.g.
`blocked -> ready_for_review`).

## record_plan_outcome(plan_id, outcome, summary, evidence_ids?) -> {plan, gate_open, recommended_next_action, human_summary}

`outcome`: `validated` (requires `evidence_ids` — never report "validated"
without a recorded validation), `rejected`, or `rolled_back`. Terminal; closes
the gate contribution of that plan.

## Resources

| URI | Contents |
|---|---|
| `damped://project/current/state` | Full snapshot (same as get_project_snapshot) |
| `damped://project/current/constraints` | Constraints with statuses and evidence |
| `damped://project/current/plans` | Plan index |
| `damped://project/current/plans/{plan_id}` | Plan + evaluation |
| `damped://project/current/gate` | Gate snapshot (what the hook reads) |
| `damped://project/current/commands` | Allowlisted command registry |
| `damped://project/current/decision-log` | Last 200 events |

## Prompts

`compile_project_state`, `draft_feasible_plan`, `review_plan_blockers`,
`postmortem_update` — reusable planning-discipline instructions.
