# Tempering, pre-registration, and the harness as model structure

Status: **design draft for discussion.** Not a plan. Nothing here is approved,
and the three parts below should become three plans, in the order given.

This document responds to one observation: plan-auto's generative process
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
`.plan-auto/preregistrations/<plan_id>.jsonl`.

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
(`data_dir.parent`) and writes `.plan-auto/harness.json`:

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

## 3b. The missing parent model (raised 2026-08-20, not built)

Every plan carries a `predictive_contract` — a mechanism-level claim about one
intervention. Nothing carries the **project's** mechanism-level claim. That is
the gap.

`ProjectState` holds `goals`, `constraints`, `facts`, `failure_modes`,
`available_resources`, `forbidden_actions`, `current_baseline`. Read the list
again: those are **targets and limits**, not a generative description. There is
no statement of what the project believes the system *is*, what mechanism it is
operating on, or what is held fixed across the whole programme of work.

The consequence is structural, not cosmetic:

> Each plan's contract is a local model with **no parent model** to be
> consistent with. Drift from the project's model is undetectable because there
> is no project model to drift from.

In the Gelman framing this document opens with, that is the real omission. Every
plan is a little M being checked and expanded, and there is no M above them.
Expansion is therefore always local: a mismatch can only ever suggest a
narrower or different intervention, never a revision of what the project thinks
it is doing.

### One concrete defect feeding the same failure

`normalize.py:369-374`: when `goal_ids` is omitted, the plan is auto-linked to
**every unmet goal**, with a warning and nothing else. `closure.goal_defined`
then passes without the author having chosen a goal at all. A plan linked to
everything is linked to nothing — which is exactly how a plan comes out
"drafted vaguely" while satisfying the gate.

### What a goal document would have to do to be worth adding

Not a prose preamble. It has to be **checkable**, or it becomes the next thing
that gets written to satisfy a field:

- a **metric registry** — the metric_ids this project measures. A plan
  predicting a metric outside it is either drift or a registry update, and
  either way should be surfaced rather than silent.
- a **project-level `context_fixed`** — what is held constant across all plans.
  A plan whose local `context_fixed` contradicts it is moving the measuring
  stick, which is already a BLOCKING finding at plan level and currently has no
  project-level equivalent.
- a **mechanism statement** — what the project believes it is operating on, so
  a `mismatch` can escalate to "the project model is wrong" rather than only
  "this intervention was wrong."
- **goal selection made explicit** — remove the auto-link-to-everything
  default, or make it a blocker rather than a warning.

### The caution that applies here as everywhere

The recurring trap in this codebase applies with full force: *require a goal
document and you will get a filler goal document.* A mandatory prose field that
nothing checks is worse than no field, because it looks like the project has a
model when it has a paragraph. Every element above is proposed as something a
plan can be **compared against**, not something an author must fill in.

### Amended by §3c (2026-08-21)

This section calls the missing parent model "the real omission". §3c revises
that: the model is missing because the **objective** is, and the objective is
what defines the space this model would be a model of. The defect and the
requirements above stand; their ordering does not. Read §3c first.

## 3c. The ultimate goal has no protected home (raised 2026-08-21, not built)

Raised by David: driving the Gelman loop *toward* something requires each
plan's goal to be measured against an **ultimate goal** — a terminal objective
for the project that lives in `.plan-auto/` and that **only a human may
edit**.

### Why this is upstream of §3b, not beside it

The tempting reading is that §3b is the missing parent *model* and this is the
missing parent *objective* — two gaps on two axes. That reading is wrong, and
the correction matters for what gets built.

The data generating process the Gelman loop is observing **is the solution
space that completes the ultimate goal.** A plan is a probe of that space; the
metrics a validation records are the draws; the posterior predictive check asks
whether the project's model of that space survived contact with them. So the
objective is not a second artifact sitting alongside the mechanism statement —
it is what *carves out the space the mechanism statement is a model of*.

That makes the dependency one-directional. Without the ultimate goal there is
no well-posed DGP, so §3b's parent model has nothing to be a model of, and
§3b's symptom follows immediately: each plan samples from its own implicit,
private solution space, the samples are not commensurable across plans, and
drift is undetectable not merely because no parent model is written down but
because there is no shared space in which "drift" would be a movement. "Closer"
is incoherent for the same reason — a distance needs the space before it needs
a metric.

Read that way, §3b is not a separate item to schedule but the thing that
becomes buildable once this exists. It also sets the acceptance bar here: an
ultimate goal that does not constrain what counts as a candidate solution has
not specified a space, and is therefore not an objective in the sense this
section means, whatever it says.

### Why human-only

The "only human may edit" half is not a nicety. It is the same principle the
gate already enforces for approval — `approve_plan` refuses AI self-approval —
applied one level up. An agent that can edit the objective it is measured
against does not need to reach the objective; it can move it. Approval is
protected today. The objective is not.

Under the framing above the stake is larger than goalpost-moving. If the
objective defines the solution space, then an agent that can rewrite the
objective can redefine **the data generating process it is being checked
against** — and a posterior predictive check against a DGP the checked party
chose is not a check. Every guarantee downstream of the Gelman loop inherits
that, which is why this belongs with `approve_plan`'s refusal rather than with
ordinary state the agent maintains.

### What the current code actually permits

`register_project` is an ordinary agent-callable MCP tool, and
`_normalize_goal` (`normalize.py:215-233`) rebuilds each goal **entirely from
the incoming payload** — unlike `_normalize_constraint`, which is passed
`existing_by_id` and merges. Re-stating a goal id therefore replaces it
wholesale. Measured against a scratch data dir:

```text
original:             {'id': 'G-0001', 'metric_name': 'p99_ms', 'target': '<= 120', 'met': False}
after target rewrite: {'id': 'G-0001', 'metric_name': 'p99_ms', 'target': '<= 400', 'met': False}
after bare re-state:  {'id': 'G-0001', 'metric_name': '',       'target': '',       'met': False}
after met=True:       {'id': 'G-0001', 'metric_name': '',       'target': '',       'met': True}
```

Three distinct ways to satisfy a goal without moving the system:

- **Loosen the target.** `<= 120` becomes `<= 400` for the asking. The
  `project_updated` event carries `warnings: []` and no before/after values, so
  the loosening is not reconstructable from `events.jsonl`.
- **Erase the measure.** Re-stating a goal with only a statement silently drops
  `metric_name` and `target`. The goal survives as an unmeasurable sentence,
  and `normalize.py:170-173` only warns.
- **Declare victory.** `met: True` is accepted straight from the payload, with
  no evidence id and no validation record — in a system whose stated rule is
  that `validated` outcomes require recorded evidence.

There is also nowhere safe to put such a document today. The gate's
`always_allowed` defaults to `[".plan-auto/**", "docs/**", "*.md"]`
(`results.py:113-115`), so the directory where the objective would naturally
live is precisely the one the enforcement hook never guards.

### What it would have to do to be worth adding

The `commands.json` precedent is the right shape: a file the human writes and
the server only ever **reads**. Applied here:

- **Server-read-only.** No MCP tool writes the objective. `register_project`
  gains goals; it does not get to redefine the terminal target.
- **Out of `always_allowed`.** Carve the objective path out of the default, so
  the PreToolUse hook denies agent edits to it rather than waving them through
  with the rest of `.plan-auto/**`.
- **A stated solution space, not a stated aspiration.** The objective has to say
  what counts as a candidate solution — which metrics are the coordinates, what
  admissibility conditions a solution must satisfy, what is out of bounds. This
  is the load-bearing requirement: it is what turns the objective into a DGP the
  loop can observe, and everything below assumes it.
- **Goal-to-objective linkage, checkable.** Each goal names which objective
  criterion it advances, and by how much — that is, which region of the space it
  probes. A goal advancing nothing is the planning-level analogue of a plan
  linked to every goal, and §3b's auto-link defect (`normalize.py:369`) sits
  directly underneath this.
- **Movement measured against it, not against the last plan.** "Closer" should
  be a distance in that space, computable by a posterior check, so successive
  plans that each improve a local metric while the objective stays put are
  visible as such. Plans probing outside the space are drift, and should be
  surfaced as drift rather than scored as progress.
- **Goal edits become events with before/after.** Whatever stays mutable should
  at minimum record what it was and what it became, so a loosened target is
  reviewable rather than silent.

### The caution that applies here as everywhere

Identical to §3b, and worth restating because an "ultimate goal" invites prose
more than most fields: *require an objective document and you will get a filler
objective document.* An aspirational paragraph that nothing computes against is
worse than nothing, because the project then looks like it has a direction when
it has a mission statement. Every element above is proposed as something a plan
or goal can be **compared against**. If the objective cannot be used to compute
whether the last ten plans moved the project closer, it is decoration.

The framing above gives that caution a sharper test than "is it checkable?".
The objective's job is to specify a solution space. So: *can two plans be told
apart by where they sit in it?* A statement that admits every candidate has
carved out nothing, defines no DGP, and leaves the loop observing exactly what
it observes today — one plan at a time, against itself.

## 3d. The command registry has no sanctioned author (raised 2026-08-21, not built)

Raised by David: the workflow tells agents to prefer `run_validation`, but
gives them no sanctioned way to register a command — so the only route to
compliance is to reach into the store and write the allowlist themselves.

Confirmed, and the mechanism is worse than "a missing tool". The system's own
error messages instruct the agent to author the allowlist, and the enforcement
hook permits the write.

### The squeeze

`evidence_discipline.md` and `SKILL.md` both rank the channels: `run_validation`
is **mechanical** (argv, exit code, immutable artifact, polarity from the exit
code), while `record_evidence` is the narrated path the reviewer is told to
distrust. `workspace.py:509` and `:521` then offer the fallback explicitly —
"run the command yourself and record_evidence manually". So an agent on a fresh
project faces exactly two options: produce the evidence the reviewer distrusts,
or create `commands.json` itself. There is no third door, because none of the
11 MCP tools writes the registry.

### Three messages, three different answers to "who may write this"

| Branch | Message | Who it addresses |
|---|---|---|
| `load_registry`, no file (`command_runner.py:59`) | "**Create it** with entries like `{"unit_tests": {"allowed": true, ...}}`" | the caller — and it supplies `allowed: true` in the template |
| `resolve_command`, unknown id (`:84`) | "**Add it** to `<path>` with `"allowed": true` and an argv array." | the caller |
| `resolve_command`, `allowed: false` (`:90`) | "**A human must** set `"allowed": true`" | a human |

Only the third names a human, and it is the only branch an agent never has to
enter. `allowed` functions as a human gate solely when the entry *already
exists* in a not-allowed state — which requires someone else to have authored
it first. An agent following the first two messages literally writes
`allowed: true` from the start and never trips the third. The discipline is
stated in the branch you reach second and undercut in the branch you reach
first.

### The gate permits the write

`always_allowed` defaults to `[".plan-auto/**", "docs/**", "*.md"]`
(`results.py:113-115`), so `.plan-auto/commands.json` is waved through by the
PreToolUse hook — the same defect §3c found for the objective document, on the
file that decides what may execute.

`command_runner.py`'s docstring already concedes the registry is
"allowlist-by-convention, not a security boundary against an actor who can
write files." The unstated premise is that the file-writing actor is the human.
By default it is also the agent.

### What the human actually approved

`run_validation` requires an approved plan (`workspace.py:504`), so the sequence
reads as gated. It is not: the human approved a **plan**, and the agent then
authors the **command** that plan's step names. Approval covers which files may
change and what the decision rule is; nothing in it covers the argv that will
run. `shell=False`, the timeout, and the pinned cwd all still hold — this is not
arbitrary shell — but "what may run" stops being the reviewable artifact the
module says it is.

### What a fix would have to do

- **A registration tool that cannot self-approve.** `propose_command` writes the
  entry with `allowed: false` and records an event; enabling it stays a human
  edit. That makes the third message the real path instead of the unreachable
  one, and turns proposals into something reviewable.
- **Align the first two messages with the third.** They should point at the
  proposal route, not hand over a template containing `allowed: true`.
- **Carve `commands.json` out of `always_allowed`,** so the hook denies direct
  agent edits rather than permitting them by default.
- **Make the fallback honest.** If registration is genuinely unavailable,
  `record_evidence` is the correct channel and should not read as the
  second-class option; the reviewer's distrust of narrated numbers is calibrated
  for a world where the mechanical path is actually reachable.

### The caution that applies here as everywhere

The failure mode this section describes is not an agent behaving badly — it is
an agent following the instructions it was given, in the order it encounters
them. A rule that only appears in the branch a compliant agent never reaches is
not a rule, and adding a strongly-worded sentence to `SKILL.md` will not change
that. Either registration has a sanctioned route with a human in it, or the
allowlist is documentation of what ran rather than a decision about what may.

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
