# Redesign

Status: **design draft for human review.** Nothing here is approved. Every claim
carries its evidence or is marked unmeasured.

## 0. What the evidence says

Measured during the audit of 2026-08-31, on this repo and the five live stores:

| Finding | Evidence |
|---|---|
| Three inference components ship and are wired to nothing | `micro_damping.py` (248 LOC) is reachable only via `workspace.record_evidence_bundle`, absent from `server.py`'s 13 registrations; `prior_contract_check` (`services/predictive.py:150`) has callers only in tests, and says so in its own docstring; `residual_variance`/`aggregate_credibility` (`residuals.py:107-108`) are read by no branch of `decision_policy.py` |
| The gate does not discriminate here | `outcome_profile` reads `theatre_signature`: 3/3 terminal plans validated, 0 of 13 evidence records refuting |
| ...but that is **not** the schema's fault | `robot-navigation-planning` holds **18 of 47** refuting records under the identical v1 object model (EV-0015) |
| Goals cannot express distance | `Goal.target` is `str` (`models/project.py:20`) with no baseline field, so the current value is inlined into the target prose |
| A hard constraint can be waved through uncited | A plan's `not_applicable` audit entry overrides a project `UNKNOWN` (`plan_validation.py:45-55`) and its `evidence` string is never validated — that read happens only for `UNKNOWN`, at `:146` |
| Ordering is not lexicographic, as the docs claim | `workspace.py:147-152` assigns inside an unguarded loop: the answer is whichever plan is iterated last |
| The value claim has never been tested against a control | A 3-task A/B harness exists; the damped arm recorded 61201→1501, 12001→4001, 138839→659 ops with zero golden mismatches. **The three plain arms were never run.** |

## 1. The root cause, corrected

The first draft of this redesign blamed the plan-centred object model for the
absence of refutations. That hypothesis is **refuted** by EV-0015: another
project on the same schema refutes constantly.

The actual cause:

> **This project has no manipulable quantity.** It measures its own planning
> process rather than a produced artifact. No observation could have come out
> otherwise, regardless of schema.

That reframes the whole redesign. The primary defect is not the data model. It
is that nothing here is *produced* and then *checked against what it was
supposed to produce*. Fixing the schema without fixing that would have bought a
rewrite at the price of a rewrite.

## 2. The correction: the repo is the model

- **The model is the developed repository itself.** Not a hypothesis about it.
- **The belief is what the code is expected to produce.**
- **The evidence is what it actually produces.**
- **Effectiveness is the agreement between them**, measured over a workload.

Two consequences follow immediately, and both matter more than any schema change.

### 2.1 The framework's product is not better code

It is a **lower rate of claiming success while the code fails to produce what
was expected**. Call it `false_success_rate`: the fraction of completed tasks
where the arm reported done while a golden output mismatched or a pre-registered
invariant moved.

That is the number the whole framework should be judged on. It is currently
**unmeasured for both arms**.

### 2.2 The reviewer becomes able to produce evidence

Today the reviewer attacks plan *structure* — "your decision rule is
unfalsifiable", "your sample is too small". Those are good catches that can
never enter the ledger, which is exactly why the ledger read 0 refutations.

Under this framing the reviewer attacks a **claimed output**: *"you say this
produces X; for input Z I claim it produces Y."* That is runnable. It terminates
in a fact, and the fact lands as a `refutes` record.

**Reviewer objections become pre-registered counterexamples, added to the golden
set before either arm runs.** This is the single highest-value change in the
document, and it needs no new mathematics.

## 3. Object model

The first draft proposed three objects — Model, Change, Outcome. That failed
review on inspection of the stored schemas: `Goal`, `Constraint` and `Fact` have
no home in any of the three. A hard constraint is a **normative gate**, not a
causal claim, an intervention, or an observation.

The fix is to stop collapsing two layers that update by different rules.

### Layer A — Commitments (human-authored, never inferred)

| Object | Notes |
|---|---|
| `Objective` | The terminal goal. Human-only, editable by no agent. Closes the gap the README names as deepest: without it, "closer" has no referent |
| `Goal` | Typed `baseline` and `target`, so distance is arithmetic. Revision requires an explicit call recording before/after — never a silent rebuild from payload |
| `Constraint` | Normative gate, four-valued status. `not_applicable` requires a citation exactly as `sat` does, or is removed entirely |

**Update rule: these change only by human edit, logged with before and after.**
Evidence never moves them.

### Layer B — The loop (where belief lives)

| Object | Notes |
|---|---|
| `Change` | An authorised intervention. Carries `allowed_files` and its `Expectation` |
| `Expectation` | What the change is expected to produce, stated **before** it runs, drawn from a published grammar (see §6) |
| `Outcome` | What was actually produced. Mechanically captured, paired to exactly one `Expectation` |

**Update rule: `Expectation` vs `Outcome`.** No change, no expectation, no
evidence. A test run against unchanged code is *state*, not evidence — it could
not have come out otherwise.

### Layer C — Enforcement (mechanism, updates never)

Ported from v1 essentially unchanged, because it is the part with a track record:
the PreToolUse scope hook, human-only approval, the reviewer with no mutating
tools, `run_validation`'s mechanical capture, and the append-only event log.

## 4. What is enforced vs advisory

| Enforced mechanically | Advisory |
|---|---|
| A change may not write outside its declared scope | Ordering suggestions |
| Only a human authorises a change | Narrative quality of a hypothesis |
| No change without an `Expectation` that could fail | — |
| No `Outcome` counts as evidence unless paired to an `Expectation` | — |
| A `Constraint` leaves `UNKNOWN` only with a citation | — |
| Every state change appends to an immutable log | — |
| Nothing is computed that no reader consumes | — |

The last row is the anti-v0 invariant and ships as a **test**, not a principle.

## 5. Prune list

Concrete, and independently valuable regardless of the rest of this document.

**Remove:** `services/micro_damping.py`; `workspace.record_evidence_bundle`;
`SubtaskEvidenceBundle`; `DampingStatus`; `DEFAULT_PROVENANCE_VERACITY`;
`residual_variance`, `aggregate_credibility`, `oscillation_risk`,
`dependency_gap` from `ResidualReport`; the tests targeting only these.

**Retain:** `EvidenceClaim` as a deprecated read-path passthrough — three live
records in `robot-navigation-planning` carry `claims` (EV-0014). Removing it
breaks a real store.

**Move, not copy:** `prior_contract_check` from `services/predictive.py` into the
new kernel and wire it to a caller. Copying leaves the original dead and makes
"zero dead components" unreachable.

**Fix while in there:** `workspace.py:147-152`, which returns the last-iterated
plan's recommendation.

## 6. Open questions — unresolved, and marked as such

1. **Is the `Expectation` grammar decidable?** The rule "no expectation that
   cannot fail" is only demonstrably decidable for numeric ranges — v1's own
   `prior_contract_check` flags exactly `no_change` with no range. Whether a
   logic-level claim ("`F` cannot return null for input class X") is mechanically
   checkable is **unknown**. The grammar must be published *before* kernel code
   is written, or the implementer defines the set they are measured on.
2. **Seven live predictions carry `expected_range: null` and no pattern**, one on
   a plan recorded `validated`. Migration must either carry them as a distinct
   non-Expectation kind or reject them — and rejecting them is field loss. Decide
   before writing the migrator, not during.
3. **Retrospective demotion.** Under the new rule roughly 18 of 99 stored records
   across all stores still qualify as evidence. `polarity` has no meaning on an
   `Outcome` with no `Expectation`. Where the rest go is undecided.
4. **Is scoring ever warranted?** Unmeasured. `C-deterministic-first` forbids it
   until a real planning failure the deterministic layer cannot handle is
   demonstrated. Note the constraint is itself recorded `sat` on EV-0001, a
   store-compatibility record that does not mention scoring.
5. **The name.** Deferred deliberately. `deciban` and `gittins` name mathematics
   the system does not perform and would pre-commit the answer to (4).
   `corroborate` is the honest fit if a name is needed now — Popperian
   corroboration is explicitly not a probability.

## 7. Deliberately absent

| Not in this design | Why |
|---|---|
| Instrument reliability / sensitivity / specificity | The pre-stated expectation carries the discrimination; the check is binary |
| Beta calibration of instruments | Nothing left to calibrate; no free parameter remains |
| Value-of-information ranking | Replaced by a cheaper rule: a change whose outcome you are certain of tests nothing |
| Any damping or control vocabulary | There is no second-order system, no state, no velocity term |
| Posterior predictive checking | There is no posterior. Range membership against a self-authored band is not inference |

## 8. Order of work

1. **Measure effectiveness.** Complete the three plain arms, pre-register the
   expected outputs, count `false_success_rate` in both arms. This decides
   whether the framework is worth keeping and is the only step that must happen.
2. **Prune.** Independently valuable, independently reversible, blocked by nothing.
3. **Publish the `Expectation` grammar and the field-by-field migration map.**
   Both are decidable today from the stored schemas.
4. Only then, the kernel.

Steps 1 and 2 do not depend on each other and neither depends on the rest.

## 9. Kill criteria

Pre-registered, because the predecessor of this document had no way to be wrong.

- `false_success_rate_damped >= false_success_rate_plain`, or both arms score
  zero false successes → the gate does not discriminate on real work. Keep the
  pruned enforcement layer, abandon the kernel.
- The migration map finds `Goal`, `Constraint` or `Fact` unplaceable **again**
  after the three-layer split → the unification does not exist at this scope.
  Ship the pruned v1 and stop.
- Any computed field ships with no reader → the redesign reproduced the failure
  it exists to fix at birth. Stop rather than trim.

## 10. Honest summary

The parts of v1 that work — the scope hook, human approval, `adopt_if`/`reject_if`
stated before execution, the reviewer with its tools removed, mechanical capture,
the audit log — are all instances of one thesis: **separate the party who asserts
from the party who checks, and make assertions expensive to fake.**

None of them compute a number. The mathematical layer that did compute numbers is
unreachable, unread, or unwired. That is the finding, and this redesign is mostly
the work of admitting it — plus the one genuine addition, which is giving the
project something it actually produces, so that being wrong becomes possible.
