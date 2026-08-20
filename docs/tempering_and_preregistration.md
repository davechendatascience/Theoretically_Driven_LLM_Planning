# Tempering, pre-registration, and the harness as model structure

Status: **design draft for discussion.** Not a plan. Nothing here is approved,
and the three parts below should become three plans, in the order given.

This document responds to one observation: damped-plan's generative process
**reads its own model before producing data**. Gelman's workflow does not have
this property — nature does not read your priors. Everything below follows from
taking that seriously.

## 0. The problem this addresses

A posterior predictive check assumes the data-generating process is indifferent
to the prediction. Here it is not: the agent writes `expected_range`, then
produces the number that lands inside it. A green check is therefore ambiguous
between two hypotheses:

- **M1**: the mechanism worked.
- **M2**: the agent steered to satisfy the band.

Nothing in the current system distinguishes them. Stated as a rule:

> **A contract that the same agent both writes and satisfies is not a check.**

Three defenses exist. Two are built:

| Defense | Status |
|---|---|
| Separate writer from scorer | **Done** — `services/predictive.py:58` scores deterministically |
| Separate writer from executor | **Partial** — `run_validation` captures argv/exit code mechanically; `record_evidence` does not |
| Pre-register before the data exists | **Absent** |

Part 1 builds the third. Part 2 addresses a different failure — committing hard
in an unprobed direction. Part 3 closes a hole the first two assume shut.

## 1. Pre-registration (tamper-evidence)

### Mechanism

On every `create_plan`, hash each **contract-critical field** and record
`{field_path, sha256, first_set_at, plan_version}` to an append-only
`.damped-plan/preregistrations/<plan_id>.jsonl`.

Contract-critical fields:

- `predictive_contract.predictions[*]` — `metric_id`, `direction`, `expected_range`
- `predictive_contract.context_fixed`
- `predictive_contract.disconfirming_patterns[*]`
- `decision_rule.adopt_if` / `reject_if`
- `validation_steps[*].expected_result`

On a repair round, a changed hash appends a `field_revised` event carrying both
hashes. The revision is **recorded, never blocked** — decided 2026-08-20. A
`revised_post_data` plan still warns loudly at every surface, but it does not
refuse a `validated` outcome. Blocking an outcome sits close enough to
`C-advisory-quality`'s line that taking it would have meant arguing the
constraint down, and the warning already reaches the reviewer, who is the
party that acts on it.

### The signal

The interesting quantity is not *whether* a field was revised but *when*,
relative to the arrival of data:

```
preregistration_status ∈ {
  clean,              # no contract-critical field revised
  revised_pre_data,   # revised before any evidence linked to this plan existed
  revised_post_data   # revised after — the band moved once the numbers were visible
}
```

`revised_pre_data` is ordinary and healthy: that is what repair rounds are for.
`revised_post_data` is the thing worth seeing. It is surfaced in
`evaluate_plan`, in `get_plan`, and in `human_summary`, and it is the first
thing the reviewer should attack.

### Honest limit

This is tamper-**evidence**, not tamper-proofing. An agent with filesystem
access can rewrite the store; the append-only log is append-only by convention.
Its job is exactly `commands.json`'s job — reviewable provenance, so that
dishonesty must be committed in writing rather than in silence.

### A cheap companion

Under a reflexive generator, `no_change` invariances carry more epistemic
weight than directional predictions, because satisfying one requires **not
moving** something you were not tracking — much harder to steer toward than a
band you chose. Proposal: require at least one `no_change` prediction in every
contract, alongside the existing structural checks.

## 2. The commitment ladder (tempering)

### What is missing, precisely

`alternative_hypothesis_ids` exists on `CausalHypothesis` (`models/plan.py:28`).
Its only use anywhere in the codebase is `services/residuals.py:39`, where
competing hypotheses are **counted** to increment a residual. An alternative is
a penalty term, not a carried candidate. The structure for an ensemble
half-exists and is wired to a scalar — the same pathology as `observations`.

Commitment is currently binary: approved (gate open, files writable, full
weight) or not (zero). β in a power posterior exists to stop a sampler locking
into the first mode it finds; the plan-space analogue is refusing to spend the
whole write budget on the first hypothesis that closes.

The system already has two rungs and does not name them: a **measurement plan
is the only thing allowed through a closed gate**. That is β<1 in everything
but vocabulary.

### Rungs, not a continuous β

Continuous β is false precision — there is no sampler and nothing to anneal
smoothly. Three rungs:

| Rung | Admission test (server-derived) | Approval | Concurrency |
|---|---|---|---|
| **β₀ probe** | reversible **and** no `allowed_files` ∩ `evaluation_paths` **and** cost under threshold **and** writes confined to a scratch path | **Server-admitted** | K simultaneous, distinct hypotheses |
| **β₁ bounded** | reversible **and** no evaluation-path intersection | Human | one per failure mode |
| **β₂ committed** | anything else — irreversible, evaluation machinery, high cost | Human **and** a recorded reviewer verdict **and** a β₀/β₁ ancestor via `parent_plan_id` | one |

That last cell is the annealing schedule made structural:

> **You cannot reach β₂ without a lower-rung ancestor in your lineage.**

No large step in a direction nothing has probed. This is the damping story
stated as a gate condition rather than as an aspiration, and it gives
`parent_plan_id` — currently null across every dogfooding plan (failure mode
`F-lineage-unused`) — a job it cannot be ignored for.

### Two non-negotiables

1. **The rung is derived, never declared.** The agent supplies facts
   (`reversible`, `allowed_files`, cost); the server computes β. An agent that
   could assert its own tier would assert β₀ for everything.
2. **`adopt_if`/`reject_if` are required at every rung.** Per direct feedback,
   this is the single highest-value mechanic in the system; every
   unfalsifiable-criterion catch traces to it. β₀ may relax rollback (trivially
   "discard scratch"), the full constraint audit, and the
   disconfirming-pattern requirement. It never relaxes the decision rule.

Note that rung derivation is robust for a reason already in place: an agent
that under-declares `allowed_files` to stay at β₀ cannot then write outside
them, because the PreToolUse gate hook denies it. The existing enforcement
makes the derived tier honest.

### Multi-hypothesis probing

At β₀, allow K live plans against one failure mode, each with a distinct
hypothesis, plus a **discriminative** marker naming the observation whose value
differs across them. This implements `blueprint.md:793` ("if competing
hypotheses imply different interventions") rather than merely counting the
alternatives.

**Say plainly what this is not.** With no posterior and no `θ`, evidence does
not reweight candidates — each probe's `decision_rule` either kills its
hypothesis or leaves it standing. This is sequential elimination under
pre-registered criteria, not Bayesian model averaging. Calling it reweighting
would be the same overclaim as calling the range check a posterior predictive
check.

### Where autonomy lives

β₀ is the answer to autonomous operation, and it is a principled boundary
rather than a relaxed one. `approve_plan` must keep refusing AI approvers, so
β₀ needs a separate entry point — `admit_probe(plan_id)` — which succeeds only
if the server itself verifies the β₀ predicate. The human gate is not weakened;
it is **reserved for commitments that deserve it** instead of levied uniformly.

### The condition on it (decided 2026-08-20)

Server admission is permitted **only if human approval is itself inside the
Gelman loop rather than beside it.** Today approval is an unmodelled step: it
happens, it is logged, and no part of the system ever asks whether it did any
work. That is an assumption wearing a gate's clothing.

Concretely, every plan records its `admission_path` (`human` | `server`), and
the project snapshot reports outcome profiles by path:

```
admission_path=human   →  validated N | rejected N | rolled_back N
admission_path=server  →  validated N | rejected N | rolled_back N
```

This makes the value of the human gate falsifiable at each rung:

- If server-admitted β₀ probes show the same outcome profile as human-approved
  ones, the gate was not doing discriminative work there, and the rung is
  justified on evidence rather than on argument.
- If they show more `rolled_back`, the β₀ predicate is too wide and must shrink.
- If they show *neither* rollbacks **nor** refuting evidence, that is its own
  finding: a rung that never kills a hypothesis is not tempering, it is
  theatre, and the probes are too trivial to be informative.

Ordering consequence, and it is a hard one: **the instrumentation ships before
the first server-admitted probe, not after.** Autonomy is earned by being
measurable. A ladder that cannot report on itself is exactly the unsupported
commitment the whole system exists to prevent.

## 3. The harness is model structure

If hooks, tool allowlists, and agent definitions shape what the agent can
produce, they are part of the generative process. Changing one mid-experiment
is evaluation drift in exactly the way changing a metric is — and
`context_fixed` currently cannot express it.

This is not hypothetical. On 2026-08-20 a single session changed the reviewer's
tool allowlist and registered a new `Bash` PreToolUse hook across four
projects. No plan's `context_fixed` could have caught it, because the harness
configuration appears nowhere in any ledger.

### Mechanism

At approval time the server reads what it can from the project root
(`data_dir.parent`) and writes `.damped-plan/harness.json`:

- registered hook commands from `.claude/settings.json`
- agent `tools:` frontmatter from `.claude/agents/*.md`
- MCP server names from `.mcp.json`

Hash it. `context_fixed` may then carry `harness:<sha>`. During `executing`,
`evaluate_plan` compares the live hash to the approved one and warns when they
diverge: *the harness moved under this experiment.*

### Model identity is the wrong target (revised 2026-08-20)

An earlier draft treated model identity as a confounder to capture. That framing
is withdrawn — not because it is hard, but because it is the wrong requirement.

> **If you need to know which model produced a piece of evidence in order to
> interpret it, the evidence is weak.**

Useful evidence lets different readers reach the same conclusion. That is a
property of the *artifact*, not of the generator, and it is the property worth
enforcing. Recording the generator would let us control for a confound that
good evidence should not have in the first place; it treats a symptom of
under-determined artifacts as a fact of life.

This gives a sharper quality criterion than provenance ever could:

> **Evidence is sufficient when a fresh reader, given only the artifact,
> reaches the conclusion recorded in the summary.**

And the system already has that reader. `agents/plan-reviewer.md` runs with
fresh context by construction and is instructed to check summaries against
artifacts. It has been a model-invariance check the whole time without being
labelled one. When a reviewer cannot reproduce a conclusion from the artifact,
the correct finding is not "the reviewer disagrees" — it is **the evidence was
narration-dependent**, and that is a defect in the record.

Two consequences worth carrying forward:

- The reviewer's disagreement rate with recorded summaries is a measurable
  property of *evidence quality*, and belongs in the same instrumentation as
  `admission_path` (Part 2).
- Structured `observations` (Part 0 of the queue, `P-observations-default`) are
  model-invariant by construction: a number in a field means the same thing to
  every reader, while the same number in prose does not. That plan turns out to
  serve this criterion directly, not only the posterior check.

### What the harness should capture instead

What remains worth hashing is the **environment**, not the generator: the
registered hook commands, the agent tool allowlists, and the MCP server list.
Those change what the agent is *permitted* to do, and a change to them mid-plan
is evaluation drift regardless of who is reading. That is the whole of Part 3.

For the record, model identity is mechanically capturable if it is ever wanted
for a different purpose: a hook payload carries `transcript_path`,
`permission_mode`, and `effort` (CLI 2.1.237, the `$y` payload builder), and
the transcript records `message.model` per assistant message — verified on this
repo's live transcript (`claude-opus-5`, `bypassPermissions`, `high`). It is
available, it is just not the measurement we need. Building it would answer a
question we should not have to ask.

Remaining blind spot: user-level `~/.claude/settings.json`, and anything that
shapes what the agent may do but never reaches a hook payload.

## 4. What none of this fixes

- **Mode generation.** Tempering explores a given space better; it does not
  invent new modes. The hypothesis generator is still the LLM, and no rung
  schedule repairs a blind spot in what it can imagine proposing. This is the
  M-open limit, and it is the strongest argument for keeping a human at β₂
  specifically, rather than as a uniform tax on all work.
- **Tamper-proofing.** See Part 1.
- **Actual Bayesian inference.** There is still no `θ`, no prior, no posterior,
  and no `y_rep`. The system remains pre-registration plus deterministic
  interval checking, and `models/predictive.py` should keep saying so.

## 5. Decisions taken, and what is still open

Resolved 2026-08-20:

| # | Question | Decision |
|---|---|---|
| 1 | Does server-admitted β₀ violate the spirit of human approval? | **Permitted, conditionally** — only if approval enters the loop as a measured variable (`admission_path` + outcome profiles). Instrumentation ships first. |
| 2 | Should `revised_post_data` block a `validated` outcome? | **Warn only.** `C-advisory-quality` stays `sat`; no constraint surgery. |
| 5 | Where does model identity get declared? | **Nowhere, and it is not captured either.** Needing the generator's identity to interpret evidence is a defect in the evidence. The criterion is model-invariance: a fresh reader reaches the same conclusion from the artifact alone — which the plan-reviewer already tests. Part 3 hashes the environment, not the generator. |

Still open:

3. **Rungs or continuous β?** This draft argues rungs, on the grounds that
   there is no sampler and nothing to anneal smoothly. The counter-argument is
   that cost is genuinely continuous, and any threshold invites gaming at the
   boundary — a plan sized to sit just under the β₀ ceiling.
4. **Require at least one `no_change` invariance per contract?** Cheap, and
   under a reflexive generator the invariances carry most of the epistemic
   weight. The cost is that some genuine plans have nothing meaningful to hold
   fixed, and a forced invariance would be filler — the same fabrication
   pressure that argued against refusing free-text evidence.
