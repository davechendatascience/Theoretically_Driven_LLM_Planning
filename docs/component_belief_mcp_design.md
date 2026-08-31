# Component Belief-Update MCP: Design

Implements `component_belief_mcp_design_rules.md`. §12 maps every rule to the
mechanism that enforces it; §11 states the cost budget the design is held to.

## 0. Two commitments

**Correctness.** An LLM agent is the primary caller, and the agent is a fluent
producer of *plausible* numbers and *plausible* causal stories. The rules forbid
both from reaching the belief layer (10.4, 4.5). So: **the agent has no write
path to a belief.** No `set_belief`, no free-text field a belief model reads.
Beliefs are a pure function of `(belief-eligible evidence, declared priors,
model version)`. This is enforced by provenance classes (§3) — a missing write
path, not a prompt instruction.

**Cost.** A gate that costs more than the work it gates gets routed around.
The competing baseline is "the agent just runs pytest and tells you it passed,"
which is one tool call and zero ceremony. This design must land within a small
multiple of that or it will be bypassed, and a bypassed gate is worse than no
gate because it still looks like coverage. §11 states the budget in tool calls
and tokens; every simplification below exists to meet it.

## 1. The split that makes it cheap

Everything the rules require falls into one of two classes, and conflating them
is what makes belief-tracking systems expensive to use:

| | Declarations | Runtime |
|---|---|---|
| Components, interfaces, contracts, tests, priors, policies | Evidence, beliefs, diagnoses, decisions |
| Change rarely, need human review (10.5) | Change constantly, must be mechanical |
| **Checked-in files** | **6 MCP tools** |
| Approved by `git commit` | Appended to `.belief/` |

The original draft of this document made declarations into tools —
`declare_component`, `declare_contract`, `register_test`, `propose_change`,
`approve_change`. That put a human roundtrip *inside the agent's loop* and cost
six calls before the first measurement counted. Moving them to a reviewed file
removes eight tools, removes the pending-approval queue, removes the
approval-gate machinery, and makes the audit trail `git log` — which is
stronger than a queue, not weaker.

**The approval gate, for free.** The server loads declarations from **git HEAD,
not the working tree.** An agent that edits `belief.yaml` changes nothing:
until a human commits, the edit shows up in `status` as `pending` and no
evidence is scored against it. Rule 10.5 is satisfied with zero tools and zero
roundtrips. (Caveat, stated honestly: this is exactly as strong as your commit
discipline. If agents can commit unattended, require signed commits or a
CODEOWNERS rule on `belief.yaml` — see §13.)

## 2. Declarations — one file

`belief.yaml`, checked in. A complete small example, which is also the entire
declaration schema:

```yaml
components:
  - id: CMP-grasp-planner
    purpose: Choose a grasp pose from a segmented point cloud
    inputs:  [IFC-perception__grasp]
    outputs: [IFC-grasp__controller]
    testable_capability: Produces a kinematically reachable pose for a segmented object
    failure_modes:
      - {id: FM-unreachable, observable: IK solver returns no solution}
      - {id: FM-collision,   observable: planned pose intersects scene mesh}
    remediation: Retune approach-vector sampling; fall back to top-down grasp

interfaces:
  - id: IFC-perception__grasp
    producer: CMP-perception
    consumer: CMP-grasp-planner
    semantics: Object-frame point cloud, downsampled
    units: metres
    frame: camera_optical
    timing: {rate_hz: 10, staleness_tolerance_ms: 150}
    producer_guarantees: [points are in camera_optical, NaNs stripped]
    consumer_assumptions: [points are in camera_optical, cloud covers full object]

contracts:
  - id: CTR-grasp-reachable
    subject: CMP-grasp-planner
    claim_type: capability
    metrics: [{id: ik_success, unit: bool}]
    acceptance: {rule: "ik_success == true"}
    exclusions: [objects under 2cm, transparent objects]
    conditions:                        # declared buckets, never inferred
      - {id: normal,   when: "lighting == 'normal'"}
      - {id: low_light, when: "lighting == 'low'"}
    compatibility_key: [model_revision, calibration_state]
    evaluable_by: [TST-grasp-ik]
    sufficiency: {n_min: 8, max_ci_width: 0.35}

tests:
  - id: TST-grasp-ik
    layer: component                   # component | interface | e2e
    targets: [CMP-grasp-planner]
    run: pytest tests/test_grasp_ik.py -q --json=$OUT
    metrics: [ik_success]
    capture: [lighting, model_revision, calibration_state, seed]

priors: []                             # {contract, alpha, beta, rationale}
policies:
  - id: POL-release
    criteria:
      - {slice: CTR-grasp-reachable, require: supported}
      - {safety_gates: all_passed}
    weights: null                      # visible if a scalar utility is used (9.4)
```

Validation runs on load, once, and reports to `status`:

- A component missing `testable_capability`, `failure_modes`, or `remediation`
  is `NOT_A_NODE` and is dropped from the graph (1.4).
- A contract with empty `evaluable_by`, or naming a test that does not produce
  the metrics its acceptance rule references, is `NOT_EVALUABLE` and accepts no
  evidence (2.6). A contract nobody can measure is not a contract; it's a wish.
- A `capability` claim whose rule references implementation internals (a private
  symbol, a file path) is rejected (2.3).
- A `consumer_assumption` with no matching `producer_guarantee` on the same
  interface is reported as `unbacked_assumption` — a set difference, free to
  compute, and the most common integration bug.

**Test versioning is automatic (3.5).** A test's version is the hash of its
`run` line plus metric spec. Editing the command mints `TST-grasp-ik@v2`, and
beliefs do not pool across versions without an `equivalent_to` entry carrying a
rationale. This is what stops "we improved the test and the number went up"
from reading as progress — and because tests live in the reviewed file, it also
removes the need for an edit-blocking hook, which the earlier draft had.

## 3. Provenance classes

Three channels reach the server. Two are belief-eligible.

| Channel | Tool | Belief-eligible | Backed by |
|---|---|---|---|
| Server ran a declared test | `run_test` | **yes** | Server executed `run:`, captured exit code + artifact + hash |
| External import | `ingest` | **yes** | Pre-registered `source`, artifact + hash |
| Agent or human statement | `note` | **no** | Nothing. It is testimony. |

`note` is the sanctioned home for the qualitative judgement rule 4.5 permits —
hunches, context, "this looked jittery on the bench." It attaches to any
subject, appears in reports labelled as an annotation, and no belief model can
read it. The agent isn't silenced; it's *typed*.

The other two doors for judgement are equally explicit and both live in
`belief.yaml`: `priors` (attributed, with a rationale, named in every belief
that used one) and `policies.weights` (visible and editable, never buried in a
scoring function).

**The escape hatch that isn't one.** The only route to getting a number into
the belief layer is to declare a test that produces it and run it. The cost of
getting a number counted is the cost of making it reproducible.

## 4. Runtime — six tools

```
status(view, subject?, since?, set?)   # graph|coverage|belief|diagnose|plan|cycle|trace
run_test(test_id, conditions?, repro?)      -> {run_id, n_trials, outcome_counts}
ingest(records[], source, artifact_uri)     # external results; provenance=imported
note(subject, text)                         # inert channel; never scored
amend(evidence_id, validity?, supersede_with?, reason)   # corrections, append-only
decide(change_id, policy_id, approver?)     # evaluate + record
```

Six, down from twenty-five. Tool schemas are standing context in every session
in this project, so tool count is a permanent tax paid whether or not the
server is used — this is the single biggest lever on §11's budget.

**Compact responses.** The earlier draft attached a nested `basis` object with
id arrays to every response. That's the most-repeated payload in the system, so
it gets the compression:

```
CTR-grasp-reachable [normal, mrev=v3] supported 0.91 [0.84,0.96] n=34
CTR-grasp-reachable [low_light, mrev=v3] insufficient n=3 (need 5 more)
basis: evidence×34 set=a3f9c1 · model bb-1 · prior none
next: run_test TST-grasp-ik conditions={lighting:low}  # closes the thin slice
```

`derived_from` is always named (10.3) and `next` is capped at one action.

**The `set=` handle is the load-bearing part.** It is a hash of the exact
evidence-id set the estimate was computed from, and `status(view="trace",
set=a3f9c1)` returns that list in full. An id *range* would have been cheaper
still, and wrong: a slice routinely uses a non-contiguous subset — invalid
trials dropped, other buckets excluded — so `EV-0112..EV-0149` is a citation
the agent could quote falsely. A count plus a set hash costs about the same,
cannot misstate its own contents, and is verifiable after the fact: a summary
carrying `set=a3f9c1` can be re-checked against a recomputation, which turns
narration-dependence from an unfalsifiable worry into a detectable defect.

Full chains live in `view="cycle"`, which is where rule 10.1 actually applies —
reports must trace; interactive reads must declare a basis (10.3) and make the
chain *reachable*. The handle is what makes reachable ≠ omitted. Over-applying
10.1's full expansion to every call was pure cost; dropping to a lossy citation
would have been a correctness bug. This is the middle.

## 5. Storage

Append-only JSONL, reviewable with `git diff`, recomputable from scratch:

```
belief.yaml                   # declarations — human-owned, git-approved
.belief/
  evidence.jsonl              # trial-level; the source of truth (3.1)
  artifacts/<run_id>/...      # immutable captures
  decisions.jsonl
  events.jsonl                # every mutation: {actor, session, tool, ts}
  cache/beliefs.json          # DERIVED — safe to delete
```

An evidence record carries: `id, contract_id, test_id@version, run_id,
timestamp, system_version, provenance, outcome, metrics{}, conditions{bucket,
raw}, repro{sw_revision, model_revision, hw_id, calibration_state, environment,
dataset_revision, seed}, validity, validity_reason, artifact_uri,
artifact_hash, supersedes` (3.2, 3.4).

`outcome` and `validity` are separate (3.6). A trial that failed because the
robot was mis-calibrated is `outcome: fail, validity: invalid` — not evidence
against the component, and marking it so is a recorded event, not a deletion.
Corrections never edit; `amend` appends a superseding record (3.3).

`cache/beliefs.json` is a materialised cache, deletable and regenerable from
evidence + declarations at a given `model_version` (4.6, 10.2). Incremental
update (5.1) is an optimisation over that function; a `--verify` CLI flag
recomputes in batch and reports divergence as a defect. Not an agent-facing
tool — it's a maintenance concern, and agent-facing surface is the scarce
resource.

## 6. Belief model

**Beta-Binomial per slice (5.2).** Slice key is
`(contract, condition_bucket, compat_group)` (4.2), where `compat_group` hashes
the contract's `compatibility_key` fields from the evidence `repro` block.
Trials differing on any compatibility field land in different slices and are
never silently averaged (5.6); merging requires an `equivalent_to`-style entry
in `belief.yaml` with a rationale — a reviewed modelling decision.

Posterior `Beta(α₀+passes, β₀+fails)` over valid trials; point estimate is the
posterior mean, interval is the equal-tailed 94% credible interval. Graded
contracts reduce to a pass indicator via the contract's own rule, while raw
metric values are always retained so a distributional model can replace the
reduction later without re-running anything (4.6, 5.3).

**States:** `supported` (interval entirely above threshold), `refuted`
(entirely below), `contested` (straddles), `insufficient_evidence`.

**`insufficient_evidence` is a state, not a low number (5.7).** Returned when
`n_valid < n_min` or `ci_width > max_ci_width`. In that state no verdict is
issued and no adopt criterion can be satisfied — sparse data yields "we don't
know," loudly, with the shortfall named. This closes the likeliest failure of
an agent-driven loop: declaring victory on n=2.

Every estimate is returned inseparably from its `applicable_conditions`, so a
caller cannot quote the number without them (4.3, 4.4).

**Regressions (5.5).** `status(view="belief", since=<version>)` compares slices
sharing a `compat_group`. Slices whose groups differ come back as
`not_comparable` with the differing fields named — never as "no regression."

## 7. Diagnosis

Four status classes, and the distinction is the point (7.2):

- `confirmed_failure` — a valid failing observation against its own contract.
- `suspected` — no local failure, but upstream of one, or slice is `contested`.
- `unobserved` — no belief-eligible evidence under the failing run's conditions.
- `blocked_downstream` — inputs came from a `confirmed_failure`, so this run's
  evidence is uninformative and is *excluded*, not counted.

Ranking is by decision relevance, not lowest score (7.3). The concrete
estimator — which the earlier draft left open — is cheap: evaluate the active
policy at the slice's optimistic and pessimistic interval endpoints. **If the
decision differs between the endpoints, the uncertainty is decision-relevant.**
No new modelling, no information-theoretic machinery, reuses the policy you
already declared. Rank by that flag, then by suspicion, then by inverse cost.

Three required behaviours fall out:

- A well-measured weak component (low estimate, tight interval) ranks *below*
  an `unobserved` one of similar suspicion — its endpoints agree, so resolving
  it changes nothing.
- When top candidates overlap and a declared test separates them, that test is
  returned as `discriminating_test` and recommended over optimising any of
  them (7.4).
- When the top candidate is `unobserved` because no test targets it,
  `coverage_limited: true` and **no optimisation recommendation is produced at
  all** (7.5). The recommendation is instrumentation.

E2E outcomes never attribute to components on their own (6.4). An e2e run
updates component beliefs only through component/interface observations
captured in the same run and linked by `run_id` (6.6). A run that captured no
local observations leaves its components `unobserved` — the honest answer, and
the one that drives the instrumentation recommendation above.

## 8. Rounds and decisions

**`status(view="plan")`** — deliberately not an optimiser. It reuses the
decision-relevance flag from §7 and returns three lists: `mandatory` (safety
and release-gate tests, selected unconditionally before value is considered,
8.5), `selected` (decision-relevant tests, cheapest first, until budget is
spent), and `skipped` — every test considered, with a reason: `not_decision_relevant`
(both endpoints agree — this is 8.3, redundant confirmation, made mechanical),
`over_budget`, or `no_instrumentation`. If the selection misses a layer, an
`imbalance` line names it (8.4). A round that quietly truncates reads as full
coverage; this one can't (8.6).

**`decide(change_id, policy_id, approver?)`** — acceptance criteria live in the
policy, observed metrics live in the evidence, and they are joined at
evaluation time, never stored merged (9.1). Statuses: `adopt`, `reject`,
`hold`, `rollback`, `conditional_deploy`, `more_testing` (9.2).

When a contract's slices disagree across buckets — `supported` under `normal`,
`refuted` under `low_light` — the result is `conditional_deploy` with the
operating envelope attached (9.5). There is no averaging path. A policy
referencing an `insufficient_evidence` slice returns `more_testing` with the
missing trials named. Release decisions require `approver`; every decision
records policy version, evidence ids, assumptions, and unresolved risks (9.6).

## 9. Cycle report

`status(view="cycle")` emits the seven outputs rule §11 requires, each with its
full basis chain: graph and changes since last cycle; coverage and validity
summary (valid/invalid/quarantined/superseded counts, uncovered contracts,
`unbacked_assumptions`); belief state with uncertainty and applicable
conditions; e2e outcomes and their linked local observations, including runs
listed as `unlinked`; ranked bottlenecks, regressions, `not_comparable` pairs;
recommended next tests with rationale and skipped reasons; decision status and
remaining release/safety blockers.

Every line resolves to contract ids, test versions, evidence ids, prior ids,
and a model version (10.1). A line that can't produce that chain is a bug.

## 10. Harness integration

One skill, no hooks. The loop:

```
status(view="diagnose") → run_test(...) → status(view="belief")
```

The skill's content is four rules, not a workflow diagram: diagnose before
optimising; never narrate a result you didn't `run_test`; `insufficient` is an
answer, report it as one; escalate to the human for `decide`, never approve.

What the harness cannot do, structurally: write a belief (no tool); make an
assertion count (`note` is inert); approve its own contracts, thresholds,
priors, or weights (they live in git HEAD); pool incompatible evidence; or
quietly change the measuring stick (editing a test's `run` line mints a new
version and stops pooling).

A `belief-auditor` subagent is optional and read-only: it reviews the
`belief.yaml` diff before a human commits — is `evaluable_by` real, is the
threshold derived from recorded baselines or picked to be reachable, would the
prior dominate the likelihood at `n_min`. It returns a verdict; it never
commits.

## 11. Cost budget

The design is held to these. Call counts are exact (countable from §4); token
figures are **estimates to be measured, not measurements** — recording them as
anything else would violate the discipline this server exists to enforce.

| | This design | Earlier draft | Baseline ("just run pytest") |
|---|---|---|---|
| Tools in standing context | 6 | 25 | 0 |
| Est. standing schema cost | ~1.2k tok | ~4k tok | 0 |
| Calls: cold start → first counted measurement | **1** (`run_test`, after one commit of `belief.yaml`) | 6 + human roundtrip | 1 |
| Calls: steady-state loop iteration | **3** | 5–7 | 1 |
| Est. tokens: typical belief read | ~120 | ~800 | — |
| Human roundtrips inside the agent loop | **0** | 1 per contract change | 0 |

The steady-state loop is 3 calls against a baseline of 1, and the two extra
calls buy diagnosis-before-optimisation and a belief update that survives
audit. That ratio is defensible. Six-plus calls and a blocking human roundtrip
was not, which is why §1 exists.

## 12. Rule → mechanism traceability

| Rules | Mechanism |
|---|---|
| 1.1–1.3, 1.5 | `belief.yaml` components/interfaces; interfaces first-class; ids carry no version |
| 1.4 | `NOT_A_NODE` on load — capability + failure mode + remediation required |
| 2.1, 2.6 | Evidence requires `contract_id`; `NOT_EVALUABLE` on load |
| 2.2–2.5 | Contract fields; `claim_type` check; producer/consumer split on interfaces |
| 3.1–3.2 | Trial-level `evidence.jsonl` as source of truth; field validation on ingest |
| 3.3 | Append-only; `amend` supersedes; `events.jsonl` |
| 3.4 | `repro` block required |
| 3.5 | Test version = hash of `run` + metrics; no pooling without `equivalent_to` |
| 3.6 | `validity` orthogonal to `outcome` |
| 4.1, 4.6 | Declarations / evidence / derived cache separated; cache deletable; raw retained |
| 4.2 | Slice key `(contract, bucket, compat_group)` |
| 4.3, 4.4 | Uncertainty, n, and `applicable_conditions` inseparable from the estimate |
| 4.5 | `priors`, `policies.weights`, contracts, `note` — the only four doors |
| 5.1–5.3 | Beta-Binomial MVP; raw metrics retained for later models |
| 5.4, 5.6 | Declared condition buckets; `compat_group`; reviewed pooling only |
| 5.5 | `since=` comparison with explicit `not_comparable` |
| 5.7 | `insufficient_evidence` blocks verdicts and adopt criteria |
| 6.1–6.3 | `test.layer` ∈ component/interface/e2e; `plan` imbalance check |
| 6.4–6.6 | No e2e attribution; `run_id` linking; `blocked_downstream` exclusion |
| 7.1–7.6 | §7 endpoint-disagreement ranking; four status classes; `discriminating_test`; `coverage_limited` |
| 8.1–8.6 | §8 mandatory-first, decision-relevant selection, full `skipped` with reasons |
| 9.1–9.6 | §8 policy/evidence split; six statuses; visible weights; conditional envelope |
| 10.1–10.3 | Full chain in `view="cycle"`; compact `basis:` line with a `set=` hash on every response, expandable via `view="trace"` |
| 10.4 | Provenance classes; no belief write path |
| 10.5 | Declarations load from **git HEAD**; commit is the approval |
| 10.6 | Append-only; prior belief states preserved across model changes |
| 10.7 | Single capped `next:` line; diagnosis returns actions, not model internals |
| 11.1–11.7 | §9 `status(view="cycle")` |

## 13. Open questions and what was dropped

**Deliberately dropped from the earlier draft**, all to meet §11: eight
declaration tools (→ `belief.yaml`); the `propose_change`/`approve_change`
queue (→ git HEAD); the edit-blocking `PreToolUse` hook (→ automatic test
versioning made it redundant); the nested per-response `basis` object (→ one
compact line); `recompute_beliefs` as an agent tool (→ CLI flag); the knapsack
round optimiser (→ endpoint-disagreement ranking, ~30 lines).

**Deferred past MVP:** hierarchical partial pooling across buckets;
distributional models for graded metrics; telemetry-query tests.

**Still open:**

1. **Git-as-approval is only as strong as commit discipline.** An agent with
   shell access can commit `belief.yaml` itself. Mitigation options, in
   increasing cost: CODEOWNERS on the file, required signed commits, or a
   server-side check that the HEAD commit's author differs from the session
   actor recorded in `events.jsonl`. The third is cheap and worth trying first.
2. **`imported` evidence is trusted on an artifact the server didn't
   produce** — a real weakening of §3, since an agent with shell access could
   write an artifact and import it. Same root cause as (1). Decide whether
   `ingest` requires a pre-registered source token.
3. **`equivalent_to` is the one route around test-version isolation.** If it
   becomes routine, the isolation is theatre. Track its usage rate as a health
   metric of the process itself.
4. **Endpoint-disagreement relevance (§7) is untested.** It's cheap and
   policy-grounded, but it inherits every flaw in the declared policy, and it
   returns "irrelevant" for any uncertainty the policy doesn't reference.
   Validate against one real project before trusting the ranking.
