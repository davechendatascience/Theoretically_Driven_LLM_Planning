# v1 -> v2 field map

Status: **design draft.** Produced from the stored schemas *before* the migrator
is written, because the reviewer established this is decidable today — and
deferring it is what let the earlier three-object model fail at validation time
instead of design time.

Layers: **A** = Commitments (human-authored, changed only by human edit) ·
**B** = The loop (Change / Expectation / Outcome) · **C** = Enforcement (mechanism, holds no data).

## Why three layers and not three objects

The earlier draft proposed Model / Change / Outcome. `Goal`, `Constraint` and
`Fact` have no home in any of the three: **a hard constraint is a normative gate,
not a causal claim, an intervention, or an observation.** Collapsing a
commitment into a belief is what broke it. The layers update by different rules
and must stay separate.

## Goal -> A.Goal

| v1 field | Lands as | Note |
|---|---|---|
| `id`, `statement`, `metric_name` | same | |
| `target: str` | `baseline` + `target`, typed | The split that makes distance arithmetic. v1 inlines the current value into target prose |
| `evaluation_protocol` | same | |
| `priority: int` | same | Currently read by nothing. Must gain a reader or be dropped under I5 |
| `met: bool` | **derived, not stored** | Storing it is the cause of `F-met-flag-drift` |

## Constraint -> A.Constraint

All fields carry over. Two behaviour changes: `not_applicable` requires a
citation exactly as `sat` does (closing `F-na-unvalidated`), and `validator_ids`
points at the Expectation forms that discharge it.

## Fact -> A.Given

`id`, `statement`, `evidence_ids` carry. `truth_status` becomes the same
four-value lattice as Constraint. **`confidence: float | None` is dropped** — a
free numeric parameter with no calibration path, which is the v0 pathology in
miniature.

## FailureMode -> A.FailureMode

Carries unchanged. It is a standing statement of what counts as a problem, which
makes it a commitment.

## Plan -> B.Change

| v1 field | Lands as | Note |
|---|---|---|
| `id`, `project_id`, `title`, `status`, `kind` | same | |
| `goal_ids`, `addresses_failure_ids` | references into A | |
| `hypothesis.statement` | `Expectation.rationale` | Under "the repo is the model", the causal story is the expectation's reason |
| `hypothesis.linked_failure_ids` | on Change | Closes `F-hypothesis-linkage-unchecked` by making it the only linkage |
| `hypothesis.alternative_hypothesis_ids` | **competing Expectations** | v1 counts these as a residual *penalty* (`residuals.py:39`). Carried as live candidates instead |
| `intervention.allowed_files`, `reversible`, `kind` | merge into Change | |
| `intervention.expected_api_changes` | an **E6** Expectation | |
| `intervention.estimated_cost` | **dropped** | No reader |
| `constraint_audit` | **removed entirely** | A Change *references* constraints; it does not re-audit them. This deletes the uncited `not_applicable` escape by construction rather than by a new check |
| `assumptions` | references to A.Given | |
| `unknowns` | Constraints/Givens with status `unknown` | Not a parallel list |
| `validation_steps.expected_result: str` | a typed **Expectation** | The prose field becomes checkable. Biggest single win in the map |
| `validation_steps.command` | the named instrument | Required, not optional |
| `decision_rule` | same | Works; pre-registered criteria are the highest-value v1 mechanic |
| `predictive_contract.predictions` | **E1 / E2** Expectations, or **Intent** | |
| `predictive_contract.disconfirming_patterns` | competing Expectations whose satisfaction refutes | |
| `predictive_contract.context_fixed` | Expectation preconditions | |
| `predictive_contract.metric_relations` | input to `prior_contract_check` | Ported and finally wired |
| `rollback_description`, `parent_plan_id`, `approved_by`, `approval_note`, `version`, timestamps | same | |
| `outcome_summary` | **dropped** | Prose superseded by Outcomes |

## EvidenceRecord -> B.Outcome

| v1 field | Lands as | Note |
|---|---|---|
| `id`, `project_id`, `source_type`, `artifact_uri`, `summary`, `created_at` | same | |
| `polarity` | **derived, not stored** | Computed by comparing the Outcome to its paired Expectation. Storing it is what allowed 13 records to read `supports` with nothing to support |
| `linked_hypothesis_ids` | `expectation_id` | The pairing |
| `linked_plan_id` | `change_id` | |
| `linked_constraint_ids` | same | |
| `observations` | the Outcome payload | |
| `observed_pattern_ids` | references to satisfied competing Expectations | |
| `claims` (`EvidenceClaim`) | **retained, deprecated passthrough** | 3 live records in robot-navigation-planning. `credibility_score` and `coverage_ratio` are carried and read by nothing |
| `subtask_bundle` | **dropped** | 0 live records carry a non-null value |

## The two problems this map resolves

**Retrospective demotion** (`redesign.md` §6.3). A record with no paired
Expectation cannot have a derived polarity. It migrates as **A.Given**, not
B.Outcome, with its stored polarity preserved as `asserted_polarity` and marked
`unverified`. Roughly four fifths of stored records take this path. Nothing is
destroyed and nothing is laundered as evidence.

**The seven unfailable predictions** (`redesign.md` §6.2). They migrate as
**Intent**, not Expectation. Preserved, flagged, never counted.

Both are lossless. `stores_migrated_without_field_loss == 5` and
`expectations_that_cannot_fail == 0` are therefore **jointly satisfiable** — the
conflict the reviewer found was created by having only one kind available.

## Fields with no home — the honest list

`Goal.met` and `EvidenceRecord.polarity` (derived, not migrated) ·
`Fact.confidence`, `Intervention.estimated_cost`, `Plan.outcome_summary`
(dropped, no reader) · `EvidenceClaim.credibility_score` and `coverage_ratio`
(carried as deprecated, read by nothing).

Every one is either derivable or unread. **`DP-model-too-small` does not fire.**
