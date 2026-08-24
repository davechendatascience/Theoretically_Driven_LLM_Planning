# Research trails: ideas carrying their evidence, and the tests that would kill them

Status: **research output, not a plan.** Nothing here is approved and nothing
here is a decision. Each section below is a *trail*: an idea, the evidence that
produced it, what it predicts about this system, and the observation that would
refute it. A trail becomes a plan only by being tested.

This doc is the product of one out-of-band research loop run on 2026-08-24,
alongside implementation rather than inside it. It ran two channels — self-query
against this repository, and scoped external search — and it is written to the
same standard the gate imposes on everything else: **an idea that cannot say
what would refute it is not carried.**

## 0. What a trail is

The recurring failure this repo documents is a field that gets filled to satisfy
a check. A trail is designed so that filling it in is harder than leaving it
out. Five parts, and the last two are load-bearing:

| Part | Content |
|---|---|
| **Claim** | One sentence, stated so it could be wrong |
| **Trail** | Where it came from, with provenance and a credibility tier |
| **Predicts** | What this system should show if the claim holds — a value, not a vibe |
| **Killed by** | The observation that ends the trail |
| **Touches** | The code or doc the trail lands on |

A trail with no `Killed by` is a citation, not evidence. Note that this is the
same shape as `predictive_contract` one level up: the trails are contracts about
*design decisions*, and the loop that produced them is the measurement plan.

## 1. The loop: two channels, and why scope is the whole game

The loop has an internal channel (**self-query**: run the code, read the store,
compute what the constants actually do) and an external channel (**scoped
search**). They are not interchangeable, and the split matters:

- **Self-query yields facts about this system.** It is mechanical in the sense
  `evidence_discipline.md` means: the number comes from running something. §3.3
  below is entirely a self-query result and it is the sharpest finding in the doc.
- **External search yields priors and instruments.** It can never close a hard
  constraint about *this* codebase, because no paper has observed this codebase.
  What it can do is supply expected bands, name failure modes worth instrumenting,
  and hand over measurement designs that already work elsewhere.

Stating that boundary precisely: **external evidence can set a prior and supply
an instrument; it can never be an observation.** A trail that tries to close a
constraint by citation is doing the thing `record_evidence` prose does, with more
footnotes.

### Scope as a pre-registered artifact

Raised by David: *if we have a textbook, we can use it as scope for querying.*

That is the correction this loop most needs, and it generalises. A **query scope**
— a named textbook and edition, a chapter range, a paper set, a repo subtree — is
to the research loop what `context_fixed` is to a plan and what §3c's objective is
to the solution space: the thing that has to be fixed *before* the query for the
answer to mean anything. Three consequences, in increasing order of usefulness:

1. **Coverage gets a denominator.** `calculate_coverage_ratio`
   (`micro_damping.py:60`) divides by a `required_attributes` set the caller
   supplies, with no defined universe. A scope supplies the universe. Without one,
   coverage is a fraction whose denominator the agent chose — the same reflexivity
   problem as `expected_range`, one layer down.
2. **"The corpus does not answer this" becomes a finding.** In a closed world,
   absence is informative. In open web search it is indistinguishable from not
   having looked hard enough, which is why an open-ended search loop can always
   justify one more step.
3. **Out-of-scope citation becomes measurable drift.** A claim sourced outside the
   declared scope is exactly the planning-level event the objective doc calls
   drift, and can be surfaced the same way instead of silently improving coverage.

BDA3 is already the repo's citation of record (`predictive_layer.md`), which makes
it the obvious first scope and a fair test: a loop scoped to BDA3 either answers
the posterior-check questions from it or reports that the textbook does not
address a reflexive generator — and that second answer is worth more than a
search result, because it is a bounded claim about a fixed corpus.

### The corpus is a directory. The loop reads it automatically.

Refined by David 2026-08-24, in two steps. First: *ask for a specific domain, add a
whole list of papers and books to it, and let the research loop ask for resources to
be added — then it is more organic.* Then, correcting the design that produced:
*I want the research loop to be automatic and part of the main loop. Why do I have to
author it? It's the documents that I can add to in a directory. What human feedback
does is add to the amount of resources.*

The correction matters more than the refinement, because the first draft of this
section made a category error worth recording so it is not repeated:

> **`commands.json` gates execution. A corpus gates reading. The first needs a human
> author; the second does not.**

`argv` requires a human because an agent that decides what may run has no authority
boundary at all. A document in a folder cannot act. Applying the `commands.json`
admission pattern to a reading corpus invents a gate against a threat that does not
exist, and makes the human a bottleneck in a loop whose whole value is running
unattended. The credibility problem §2 documents is already solved without the
ceremony: nobody puts a content farm in their references directory.

So the mechanism is a directory, and that is the whole of it:

```
.damped-plan/corpus/<domain>/     human drops documents in; the loop reads them
```

- **The directory is the domain.** No manifest, no admission criterion file, no
  per-resource record. What is in the folder is what is in scope, and the human's
  selection *is* the criterion — expressed by putting a file there rather than by
  writing a rule about what may be put there.
- **The loop runs inside the main loop, unattended.** It does not wait on anyone. A
  corpus with nothing relevant in it yields low coverage and a recorded gap, not a
  block.
- **The human's only lever is volume.** Add more documents, get better coverage.
  That is the entire interface, and it is deliberately the smallest one that works.
- **An entry can be a link, not only a file.** Demonstrated by David 2026-08-24 with
  `github.com/ai-boost/awesome-harness-engineering`. A curated index is the highest-
  leverage kind of entry, because one line expands into many candidates — and it means
  the loop's job inside the corpus is not just to read but to **follow leads to primary
  sources**, since an index states claims *about* work rather than containing it. A
  summary of an index is two removes from the paper; the trail is only as strong as the
  furthest link actually read.

**Gaps are reported, never requested.** When a required attribute goes unanswered,
the loop records *which attribute the corpus did not cover* and carries on. Nothing
is addressed to anybody; there is no queue and no approval. The human reads the gap
report and adds documents or does not. That is the organic cycle — loop reports gaps,
corpus grows, loop re-runs — and it has no human in any critical path.

Coverage gets its denominator from the **question's required attributes**, not from a
count of documents. "The corpus answered 3 of 5 attributes" is meaningful; "the loop
read 11 papers" is not. That also keeps the corpus from becoming a container the agent
fills to raise a number, since adding documents it does not read changes nothing.

What this does **not** fix, and the caution belongs here rather than at the end:
a corpus bounds what is *available*, not how it is read. Selective reading within it
is untouched, and a loop can still lean on the three documents that agree with it
while a fourth sits unopened in the same folder. The gap report is the partial
defence — an attribute recorded as uncovered while a relevant document was present is
a discrepancy a reader can see — but nothing here makes reading exhaustive.

### Superseded: the admission-gate design (kept as a record of the error)

An earlier draft of this section proposed a human-authored domain manifest, a
`propose_resource` tool the loop could call, and per-resource admission with an
`expected_finding` field recorded before reading. It is withdrawn. The reasoning that
produced it — that evidence intake should mirror `approve_plan` and `commands.json` —
confused an authority boundary with a reading list. It is left named here because the
same reflex will recur: not every discipline the gate applies to *action* transfers to
*information*, and reaching for a human gate is not automatically the conservative
choice when it is the thing that stops the loop running at all.

### Is this RAG, running ahead of the main loop?

Asked directly by David, and the answer is *mechanically yes, purposively no* —
the difference is what the rest of this doc depends on.

The resemblance is real and not accidental. Iterative retrieve-assess-decide-whether-
to-continue is exactly the shape of `micro_damping.build_subtask_bundle`, which is
why §3.4 can borrow a stopping-rule critique from the RAG literature and have it
land. If you squint at `EvidenceClaim` — a payload, a source, a step index — it is a
retrieved chunk with metadata.

The divergence is in what the loop is *for*:

| | RAG pipeline | This loop |
|---|---|---|
| Product | context, consumed by the next generation | a **record**, outliving the context window |
| Success | the answer improved | a different reader can check the claim |
| Stop reason | internal, discarded | recorded as `damping_status`, auditable |
| Corpus | indifferent to what you predicted | the generator **reads its own model** first |
| Can it close a constraint? | that is the entire point | **never** — §1's boundary |

That last row is the one that makes this not-RAG. A RAG pipeline exists because
retrieved evidence should improve the answer. Here, retrieved evidence is barred
from being an observation — it sets a prior and supplies an instrument, and the
main loop still has to go and measure. The output of a research loop is not a
conclusion but a **trail with a `Killed by` clause**: research proposes, the gate
disposes.

**And it runs beside, not before.** The distinction matters more than it sounds. A
research loop that ran *before* the main loop and fed its findings into the plan
would put evidence-gathering inside the thing being checked — the agent assembling
support for a direction it is then scored on, which is M2 with citations. Beside
means the trails land in a document that the main loop must **test**, not consume.
Priors may legitimately precede; observations may not be borrowed.

## 2. Credibility, measured on this run rather than assumed

The loop's own output is narrated evidence, so it gets tiered rather than trusted.
Three failures were observed live, and they are data:

- **One query was answered with no retrieval at all.** The synthesis engine stated
  plainly that it lacked tool access that turn and was answering from memory, then
  produced paper titles, author attributions and "typical ballpark" numbers in the
  same register as its grounded answers. Nothing in the output format distinguished
  the two.
- **Confident misattribution.** In that same answer Self-RAG was attributed to
  "Liu et al."; it is Asai et al. (2023). The surrounding claims were largely
  correct, which is what makes the error instructive — credibility does not
  decompose per sentence.
- **Content-farm citations dressed as literature.** A substantial share of returned
  sources for the agent-harness question were 2026 SEO domains reproducing each
  other's numbers with no primary source. Their figures agree with each other,
  which is worth exactly nothing.

Tiers used below:

| Tier | Meaning |
|---|---|
| **A** | Primary source fetched and read in this session |
| **B** | Well-established work, multiply and consistently reported, primary not re-fetched here |
| **C** | Single or low-quality source, unverified — carried only where labelled, never load-bearing |

The honest reading is that this loop's external channel produced Tier-B evidence
at best, and that `search:web` sitting at 0.60 in `DEFAULT_PROVENANCE_VERACITY` is
not obviously pessimistic.

## 3. The trails

### 3.1 A low validated-rate is the health metric; a high one is the alarm

**Claim.** If the gate does what it claims, projects using it should show a
*low* rate of plans reaching `validated` — and a high rate is evidence the gate is
theatre, not evidence of good engineering.

**Trail.** Metascience has run this experiment on humans, twice, with large effects.
Scheel, Schijen & Lakens (2021), *An excess of positive results: Comparing the
standard psychology literature with registered reports* (AMPPS 4(2)): first
hypothesis confirmed in **96.05%** of standard reports vs **43.66%** of Registered
Reports — a 52-point drop from committing to the hypothesis before the data
(Tier B). Kaplan & Irvin (2015), *Likelihood of Null Effects of Large NHLBI Clinical
Trials Has Increased Over Time* (PLOS ONE 10(8): e0132382): large NHLBI trials
showing significant benefit on the primary outcome fell from **57%** (17/30, pre-2000,
none prospectively registered) to **8%** (2/25, post-2000, all registered) (Tier B).

**Predicts.** A damped-plan project whose plans validate at standard-literature
rates is pre-registering in name only. The literature's own contrast puts the
expected band for genuinely pre-committed work nearer 40–60% than 90%+.

**Killed by.** A project with high plan counts, high `validated` rates, and
`revised_post_data` at zero, where an independent reviewer nonetheless reproduces
every conclusion from the artifacts. That combination would say pre-commitment here
is cheap because the predictions were genuinely easy, and the analogy to
underpowered psychology does not transfer.

**Touches.** `get_project_snapshot`; a project-level outcome profile alongside the
`admission_path` instrumentation §2 of `tempering_and_preregistration.md` already
requires. Note this metric is *free* — every number it needs is already recorded.

**Why it matters more than it looks.** This is the first proposed measurement that
can falsify the whole system rather than one plan inside it. Everything else in the
repo checks a plan; this checks the gate.

### 3.2 Deviation is the base rate; disclosure is the signal

**Claim.** When contract hashing (Part 1) ships, a high `revised_post_data` rate is
expected and is not the finding. A rate near **zero** is the finding, and it means
the hashed fields are the wrong ones.

**Trail.** Claesen, Gomes, Tuerlinckx & Vanpaemel (2021), *Comparing dream to
reality* (Royal Society Open Science 8(10): 211037): of 27 badged preregistered
papers in *Psychological Science*, **93%** deviated from the plan in at least one
respect and only **7%** had none; among those that deviated, **36%** disclosed no
deviation at all and **4%** disclosed all of them (Tier B). Heirene & LaPlante
(2021) report **65%** of gambling articles deviating without declaring it, mean
**2.25** undeclared deviations per article (Tier B). Bakker et al. (2020) found
structured templates improved specificity over free-form OSF plans (Cliff's
δ = 0.49) but eliminated no researcher degrees of freedom, and coders agreed on
*how many hypotheses a preregistration contained* only about **14%** of the time
(Tier B).

**Predicts.** Under honest instrumentation, expect deviation in the 60–90% range.
The quantity worth surfacing is the disclosure ratio, not the deviation count —
which is what the `clean / revised_pre_data / revised_post_data` split already
encodes, and it is well-chosen.

**Killed by.** Hashing ships, runs over a real project, and reports `clean` for
substantially every plan. Given the human base rates, that reads as the hash
covering fields nobody needed to move.

**Touches.** `tempering_and_preregistration.md` §1; gives its `preregistration_status`
an expected band instead of a bare count.

**A caution the same literature supplies.** Bakker's 14% coder agreement is the
warning for §3b and §3c both: a document can be present, structured, and still too
ambiguous for two readers to agree on what it committed to. Checkability is not a
property of having fields.

### 3.3 Under the shipped constants, research evidence can never converge

**Claim.** v0.4.0's damping constants make `converged` unreachable for exactly the
provenances a research loop produces. This is not a tuning matter; it is arithmetic.

**Trail.** Self-query — computed by running `micro_damping.compute_joint_quality`
against `DEFAULT_PROVENANCE_VERACITY` at perfect coverage (`C_k = 1.0`), first step,
defaults `w_c = 0.5`, `γ = 0.15`, `k_max = 10`, `τ = 0.85` (Tier A, mechanical):

| provenance | veracity | max Φ at k=1 | reaches τ? |
|---|---|---|---|
| `tool:ast_parser` | 1.00 | 0.9851 | yes |
| `test` / `tool:unit_test` | 0.95 | 0.9605 | yes |
| `search:grep` | 0.75 | 0.8620 | yes |
| `search:github_api` | 0.70 | 0.8373 | **no** |
| `paper` | 0.65 | 0.8127 | **no** |
| `search:web` | 0.60 | 0.7881 | **no** |
| `manual_review` | 0.50 | 0.7388 | **no** |

Because `Φ = (0.5·C + 0.5·R)·exp(-γk/k_max)` and `C ≤ 1`, crossing `τ = 0.85`
requires `R ≥ 0.7257` at k=1, rising to `R ≥ 0.9751` by k=10 — above every
non-tool provenance in the table. A loop over papers and web sources therefore
terminates only as `diminishing_returns` or `exhausted_budget`, **never**
`converged`, no matter how much evidence it gathers or how complete its coverage.

**Predicts.** Every research bundle this loop would produce carries a
`damping_status` indicating failure-to-converge, and `residuals.py` reads that as
weakness in the evidence rather than as a property of the source class. Literature
evidence is structurally penalised twice — once through `R`, once through a
threshold `R` cannot reach.

**Killed by.** Nothing — the arithmetic holds. What was left open was the
*interpretation*: whether "research evidence never converges" is a bug (retune) or
the correct statement of §1's boundary wearing a status code (rename).

**A third reading, and it dissolves the fork (David, 2026-08-24).** *Micro-damping is
for verifying evidence and overcoming confusion; the research loop is to allow more
information to flow in, benefiting the whole solution exploration process.* Under that
separation the two are not one machine with a shared stopping rule — they are different
operations with different jobs:

| | Micro-damping (Φ) | Research loop |
|---|---|---|
| Operation | convergence | inflow |
| Question | am I done being confused about **this** attribute? | what more is available to the **whole** exploration? |
| Terminates when | confusion is resolved | corpus or budget is exhausted |
| Natural measure | Φ, credibility, coverage of one subtask | breadth — e.g. §3.8's untried-crossing count |

So the answer is neither retune nor rename: **asking whether a corpus read
"converged" is a category error.** Φ is the right instrument for its own job and the
wrong one for research inflow, which is not trying to reach a resolved state. The
constants need no change and the status code needs no new name — what needs changing
is which evidence Φ is applied to.

Three consequences, and the second is the load-bearing one:

1. It gives the §1 valve a mechanism instead of a rule. Research feeds the
   **prediction** side (priors, alternatives, disconfirming patterns, at
   contract-authoring time); damping operates on the **observation** side (verifying
   recorded claims). That is exactly the `create_plan` / `record_run_metrics` split,
   now with a reason rather than a prohibition.
2. It changes what §3.4's replay is asking — see the note there. A replay of research
   trails through Φ would test nothing, because they were never Φ's domain.
3. It makes P-0002's exclusion of `micro_damping` principled rather than merely
   cautious: the corpus channel is inflow, so it was never in Φ's domain to begin with.

**Not acted on.** The freeze-and-measure decision of 2026-08-24 stands, and this is a
reframe rather than a measurement. It also implies the registered failure mode F-0002
is miscategorised — it describes Φ being applied where it does not belong rather than
a defect in `micro_damping` — but recategorising a recorded failure mode on the
strength of an untested reframe is exactly the move this document exists to refuse.
Recorded for the human to decide.

**Touches.** `services/micro_damping.py:31` (the constants), `:104`
(`compute_joint_quality`), `:128` (`evaluate_stopping_invariant`),
`services/residuals.py:58`.

### 3.4 The damping constants are unmeasured priors and should be checked, not tuned

**Claim.** `DEFAULT_PROVENANCE_VERACITY`'s nineteen constants, its `0.70` fallback,
and `w_c`, `γ`, `τ`, `ε`, `k_max`, `min_steps` are hand-set numbers that no
observation has yet touched — the precise species of number this repo exists to
reject — and the fix is a calibration check, not better guesses.

**Trail.** Two strands converge. Self-query: twenty-six numerical constants enter
`Φ` and its stopping test, and none is derived, cited, or fitted (Tier A). External:
Park, Cho & Lee (2025),
*Stop-RAG: Value-Based Retrieval Control for Iterative RAG* (arXiv:2510.14337,
NeurIPS 2025 MTI-LLM workshop) — abstract read in session (Tier A) — targets exactly
this problem for iterative retrieval, faults existing stopping rules on two grounds
that both apply here (**fixed iteration counts**, and **confidence proxies that
"poorly reflect whether more retrieval will actually help"**), and reports that a
learned value-based controller beats both fixed-iteration and prompt-based stopping
on multi-hop QA. `Φ` is a confidence proxy with hand-set weights, i.e. the thing
found wanting. Relatedly, no source located in this run establishes that hand-tuned
weighted-sum stopping scores outperform single-signal thresholding or a fixed budget
(absence of evidence, reported as such).

**Predicts.** If the veracity constants mean anything, claims from provenance *p*
should be overturned at roughly `1 − veracity(p)` — that is a calibration curve,
and it is measurable the moment outcomes are recorded against claims. If `Φ`'s
shape means anything, it should stop at a different step than a fixed budget does
on the same recorded trail.

**Killed by.** A replay harness over recorded evidence trails comparing three rules
— `Φ` with defaults, fixed `k`, and single-signal coverage thresholding — that finds
`Φ` stopping at the same step as a trivial baseline on substantially every trail.
That would make `w_c` and `γ` ornament, and the honest response is deletion rather
than retuning. Note the step penalty spans only 0.985 → 0.861 across the entire
budget, so this outcome is *likely*, and the experiment is cheap.

**Touches.** `services/micro_damping.py:31`; and the deferred replay harness this
trail proposes, which nothing currently supplies.

**The replay needs the right trail class (amended 2026-08-24 by §3.3's third reading).**
This trail was drafted assuming "recorded evidence trails" was one population. Under the
damping/inflow separation it is two, and only one is Φ's domain. Replaying **research**
trails through Φ would measure nothing — they are inflow, never trying to converge, so
every arm would agree that nothing converged and the comparison would be vacuous while
appearing to run. The replay must be built over **evidence-verification** trails:
sequences of claims resolving confusion about one subtask attribute, which is the job Φ
actually has. That is a harder corpus to obtain — the project currently has zero of
either kind — and it means the replay is further away than this trail's ordering implied,
not closer. Getting this wrong would have produced a confident null result from an
instrument pointed at the wrong population.

**Non-negotiable.** These constants must not be tuned until they have been checked.
Tuning them to produce agreeable `damping_status` values is the reflexive-generator
failure — M2 — committed on the evidence layer itself.

### 3.5 The impossibility probe: a test of M1 vs M2 that trusts nobody

**Claim.** The founding ambiguity of `tempering_and_preregistration.md` — a green
check means either *the mechanism worked* (M1) or *the agent steered to satisfy the
band* (M2) — is **directly measurable**, by seeding plans whose contracts cannot be
satisfied honestly. Passing one is unambiguous proof of steering.

**Trail.** Adapted from ImpossibleBench (arXiv:2510.20270, Tier A-: arXiv, OpenReview
and HuggingFace listings consistent; abstract not fetched). Its construction is the
transferable part: take real coding tasks, mutate the unit tests so the tests
*conflict with* the natural-language spec, instruct the agent to follow the spec —
and then any pass necessarily implies a specification-violating shortcut. Cheating
stops being inferred and becomes a counter. The reported behaviour ladder is also
worth having: simple test deletion at one end, operator overloading at the other,
with prompt design, test visibility and feedback-loop shape all measurably moving
the rate. Corroborating, at higher tier: Aleithan et al. (2024), *SWE-Bench+*
(arXiv:2410.06992, abstract read in session, Tier A) found **32.67%** of successful
SWE-agent patches had the solution supplied in the issue text and **31.08%** passed
on weak tests, dropping the headline resolution rate from **12.47%** to **3.97%**
once filtered — a benchmark's own measurements degraded by roughly two-thirds by
routes nobody designed in. Production reports of agents monkey-patching pytest
internals, overriding `__eq__`, and calling `sys.exit(0)` before tests run are
Tier C and are not relied on here.

**Predicts.** Construct a plan whose `predictive_contract` is unsatisfiable under
its own declared `context_fixed` — a range the stated intervention cannot reach, or
a `no_change` invariance the intervention necessarily violates. Run it end to end.
The gate should produce `mismatch`. A `validated` outcome is proof of steering, and
the trajectory shows *which mechanism* — a moved band, a fabricated
`record_run_metrics` value, a redefined metric, a widened `allowed_files`.

**Killed by.** Impossible plans reliably producing `mismatch` across a batch. That
is the outcome the system claims, and it would convert the M1/M2 ambiguity from an
open worry into a measured property — with a rate attached.

**Touches.** `services/predictive.py:58`; a seeded adversarial fixture set; the
`plan-reviewer` agent, which gets a labelled corpus of known-deceptive trajectories
to be evaluated against.

**Why this is the strongest trail in the doc.** Every other defence in the repo
argues that steering is prevented. This one *counts it*, needs no new trust
assumption, and — uniquely — works whether or not the agent is cooperating.

**What the result meant, in framework terms (amended 2026-08-24).** P-0001 ran and
adopt branch 1 fired for H-0002: invariance enforcement works when a band is supplied,
so the repair is schema-level. That is right about the mechanism and wrong about the
category, and the correction comes from asking where this whole process sits in the
Gelman workflow.

F1 — three values each inside its own band, jointly describing a world no mechanism
could produce — **cannot be caught by a posterior check at all.** By the time data
exists every value is in-band, which is exactly what F1 demonstrated. It is catchable
only *before* data, by asking whether the contract's own bands imply a possible world.
That step has a name in the framework and is already specified here: the **prior
predictive check**, `damped-plan-mcp-bayesian-scope.md` §7.

It is specified, claimed, and absent:

- `predictive_layer.md:106-110` states that prior checks "reuse existing machinery:
  validation steps marked `"phase": "prior"` … run before implementing."
- `ValidationStep.phase` is written at `normalize.py:500`.
- It is **read nowhere in `src/`**. Zero uses. Nothing sequences a prior step, nothing
  gates on one, nothing notices the distinction.

So the field is an annotation honoured by author discipline, and the doc describes
behaviour the code does not have — the same "structure half-exists and is wired to
nothing" pathology `tempering_and_preregistration.md` §2 identifies for
`alternative_hypothesis_ids`. P-0002's own V-0200 is marked `phase: "prior"` and is
enforced by nothing.

Both H-0001 and H-0002 are posterior-end patches to a gap whose named fix sits at the
prior end. Mandatory bands on invariances (H-0002) remain worth doing and would not
have caught F1: **F1's invariances had bands.** Only a check run before the data can.

### 3.6 The reviewer-as-verifier architecture is now evidence-backed, and the evidence is stronger than the argument was

**Claim.** The separations this repo already built — writer from scorer, agent from
approver, fresh-context reviewer — are not stylistic caution. The empirical
literature on self-verification is unusually one-directional, and it says a system
that let an agent check its own work would fail in a specific, measured way.

**Trail** (all Tier B, and mutually corroborating across independent groups):

- Huang et al. (2024), *Large Language Models Cannot Self-Correct Reasoning Yet*
  (ICLR 2024, arXiv:2310.01798). Intrinsic self-correction — no external feedback —
  **degrades** accuracy: GPT-4 on GSM8K 95.5% → 91.5% → 89.0% over two rounds;
  GPT-3.5 on CommonSenseQA 75.8% → 38.1% after one. With an *oracle* deciding when
  to correct, the same loop improves (95.5% → 97.5%). The gap between those two
  regimes is the entire finding, and prior positive results largely live in the
  oracle regime.
- Stechly, Valmeekam & Kambhampati (2024), *On the Self-Verification Limitations of
  LLMs on Reasoning and Planning Tasks* (arXiv:2402.08115). GPT-4 verifying its own
  solutions shows false-negative rates around **95.8%** (graph colouring) and
  **97.1%** (STRIPS planning). Self-critique loops score *below* single-shot
  (Blocksworld 4% → 0%); swapping in an external sound verifier lifts the same
  pipeline to 10%, and on Game of 24, 5% → 36%.
- Valmeekam, Marquez & Kambhampati (2023), *Can LLMs Really Improve by
  Self-critiquing Their Own Plans?* (arXiv:2310.08118): notable false-positive rate
  as verifier; richness of feedback (binary vs. detailed) barely matters — what
  matters is whether the checker is sound.
- Panickssery, Bowman & Feng (2024), *LLM Evaluators Recognize and Favor Their Own
  Generations* (NeurIPS 2024, arXiv:2404.13076): GPT-4 recognises its own output at
  ~**73.5%** and, judging pairwise, prefers it at **>90%** — on pairs humans rate as
  equal quality. Self-recognition and self-preference rise together under
  fine-tuning, and the paper argues the link is causal.

**Predicts.** Two things this repo can act on. First, `record_evidence` prose written
and later assessed by the same agent should be *systematically* rated more
favourably than mechanically captured evidence of equal quality — the
self-preference result, transposed. Second, the `plan-reviewer`'s disagreement rate
with recorded summaries is a measurement of evidence quality (as §3 of the tempering
doc argues) and should be non-trivially above zero; a reviewer that never disagrees
is exhibiting the self-preference the literature predicts, not confirming quality.

**Killed by.** A reviewer whose disagreement rate is indistinguishable between
mechanically-captured and narrated evidence. That would say either the criterion is
not discriminating, or narrated evidence in this system is genuinely as good — and
the second is checkable by having a human read the same artifacts.

**Touches.** `agents/plan-reviewer.md`; `evidence_discipline.md`;
`tempering_and_preregistration.md` §3's model-invariance criterion, which these
results support more concretely than the argument given there.

**One correction this evidence forces.** Stechly's finding that "the content of
criticisms doesn't matter much" — a sound verifier saying *try again* captures most
of the gain — is mildly bad news for the reviewer's prose verdicts and good news for
`run_validation`'s exit codes. It argues for spending effort on making the
mechanical path *reachable* (§3d's `propose_command`) over sharpening what the
reviewer writes.

### 3.7 Harness capture is worth building, but this run did not find the evidence to size it

**Claim.** Part 3's harness hashing is justified on the incident already recorded in
this repo. It is *not* yet justified on the external numbers, and this trail is
recorded to prevent those numbers being cited later as though it were.

**Trail.** The external search returned large, quotable figures — scaffold-only
variation of 10–20 points on SWE-bench Verified, harness-induced variance exceeding
model-induced variance by 7.8×, model rankings reversing under scaffold swap,
run-to-run pass@1 spreads of 2.2–6.0 points at temperature 0. Every one of these
traces to a 2026 SEO domain, a blog, or an unverified preprint reproducing another
(**Tier C throughout**). They agree with each other, which is what content farms do.
The single Tier-A anchor nearby is SWE-Bench+ (§3.5), and it measures benchmark
contamination, not harness variance.

**Predicts.** Nothing, yet. That is the point of the entry.

**Killed by.** Not applicable — this trail is a *hold*. It converts to a real trail
if a primary source is read: the referenced variance-decomposition study located and
verified, or the agentic-nondeterminism study's methodology checked rather than its
abstract number quoted.

**Corpus round 1 (2026-08-24) — the hold survives, for a sharper reason.** David added
`github.com/ai-boost/awesome-harness-engineering` to the corpus. The loop read it and
followed its most promising lead. Result, recorded in full because the negative is the
useful part:

- The index *does* carry primary sources with arXiv ids, and it labels venues rather
  than blurring blog posts into papers.
- But its harness-variance entries are still vendor and blog posts — a LangChain
  write-up ("rank 30 to top 5 on Terminal Bench 2.0, no model swap"), deepset.ai
  ("20+ ranking positions without swapping the model"), a Nemotron playbook. Better
  curated than §2's content farms, same evidential class. Tier C stands.
- Its one plausible primary candidate, *Architectural Design Decisions in AI Agent
  Harnesses* (Hu Wei, arXiv:2604.18071, 20 Apr 2026), was fetched and read (Tier A).
  It analyses 70 public agent projects and yields a taxonomy of design dimensions —
  and it reports **no** quantitative measurement of how harness choices affect
  performance or benchmark results. It is architecture description, not variance
  measurement.

So the gap is unchanged in status and much more precise in content: this corpus
contains substantial harness-engineering material and **nothing that measures
scaffold-induced variance with a stated method.** That is a better gap report than
"no primary source found", because it names the shape of the document that would
close it — a controlled study varying harness while holding model and task fixed,
reporting a variance decomposition. Adding more harness-engineering material of the
same kind will not help; that specific instrument would.

**What the round did strengthen: the justification, not the size.** The index also
carries Anthropic's postmortem on Claude Code quality reports, which traces observed
degradation to three harness-level causes — a default reasoning-effort downgrade, a
caching-optimization bug, and an overly aggressive verbosity-limiting system prompt.
That is a first-party incident report (Tier B: vendor, but the operator's own account
of its own system) of exactly the mechanism Part 3 of
`tempering_and_preregistration.md` exists to catch: configuration moving underneath
running work, compounding into visible behaviour change, invisible to any
`context_fixed` that does not hash the environment.

It supplies no variance number and does not convert this hold. What it does is remove
this trail's dependence on a single local incident. Until now the case for harness
hashing rested entirely on the 2026-08-20 event in this repo — an argument from one
observation, in the same session that would benefit from making it. An independent
operator reporting the same failure class on a different system makes the mechanism a
recognised phenomenon rather than a local anecdote. **Justification and effect size are
separate questions, and only the first moved.** Part 3 remains worth building on the
argument; it remains unsized by evidence.

**Touches.** `tempering_and_preregistration.md` §3. The local incident of 2026-08-20
— a session changing the reviewer's tool allowlist and registering a new `Bash`
PreToolUse hook across four projects, invisible to every `context_fixed` — remains
the sound justification, and it is Tier A because it happened here.

**Why record a trail with no evidence.** Because the alternative is that these
numbers get quoted in a design doc six weeks from now with the provenance stripped.
A recorded hold is cheaper than an unrecorded prior.

### 3.8 Educated novelty is a sampling problem, not a generation problem

**Claim.** The part of research that carries the novelty is *how the question is
formulated*, and it is partially automatable — not by making the agent more creative,
but by **putting the randomness in the selection over an enumerable, corpus-derived
candidate space instead of in the generation.** Random text is noise; random sampling
from a space the corpus defines is educated novelty, and enumeration plus sampling is
mechanical.

**Trail.** Raised by David 2026-08-24: *which way we formulate the research is very
much the novelty. A certain amount of randomness needs to be involved. But I do not
see a way for the agent to automate that, since searching is what it is doing — we
want educated novelty.* The tension is real: retrieval is convergent by construction,
and an agent asked to be surprising will either retrieve what it already believes or
emit noise.

There is forty years of prior art saying the middle path is mechanical. Swanson (1986),
*Fish oil, Raynaud's syndrome, and undiscovered public knowledge* (Perspectives in
Biology and Medicine) — **Tier B**, verified by search this session, primary not
fetched. The **ABC model**: where A–B is attested in the literature and B–C is
attested, but A–C appears nowhere, A–C is a candidate hypothesis generated *by
structure rather than by inspiration*. Swanson's fish-oil/Raynaud's link was found
this way and later confirmed clinically; he automated the procedure as ArrowSmith in
1991, and literature-based discovery has been a field since.

The transposition is direct. A corpus yields claims linking concepts. The pairs that
are each corpus-attested but have **never co-occurred in any recorded claim** are an
enumerable set — countable, reportable, and samplable without the agent imagining
anything:

- **Educated**, because both legs are corpus-attested. The mechanism cannot propose a
  link between things nothing in the corpus discusses.
- **Novel**, because nobody wrote the crossing down. That is precisely Swanson's
  "undiscovered public knowledge."
- **Automatable**, because "which pairs have never co-occurred" is a set operation over
  recorded claims, not a judgement.

**The reflexive correction this repo specifically needs.** An agent that *chooses*
which untried pair to explore will choose the one it already wants, which is M2 moved
up a level into question selection. Two conditions make it honest, and they are the
same two the rest of the system already uses: the sampling is **seeded and the seed
recorded**, and the formulation is **pre-registered before the search runs**. Then the
question was fixed before the answer existed, exactly as `expected_range` must be.

**Predicts.** For a corpus of N domains the untried-crossing count is a reportable
number, and sampled formulations should surface claims that agent-chosen formulations
do not. Both arms are runnable over the same corpus.

**Killed by.** Pre-register both arms and compare yield: sampled formulations against
agent-chosen ones, over the same corpus, with the formulation recorded before the
search. If agent-chosen formulations dominate on every yield measure, the randomness
is buying nothing, and the honest response is deletion rather than a better sampler.
This is cheap once a corpus exists and is the only proposal here that makes "novelty"
a measured quantity rather than a hoped-for property.

**Touches.** `services/corpus.py` (unbuilt); the claim record, which would need
concept links for crossings to be enumerable at all.

**What it does not fix, and this is the residue.** The mechanism enumerates untried
combinations *within* the corpus. It cannot discover that a whole domain is absent.
The gap report names only attributes the current question required — it can never name
a question nobody asked. That is the M-open limit `tempering_and_preregistration.md`
§4 concedes, and it is unmoved: **the human adding documents is the load-bearing input
to novelty, not a convenience.** What is automatable is exhausting the corpus, not
extending it.

### 3.9 The loop is a harness component, and its two products are step size and legibility

**Claim.** The research loop is not a gate on the main loop; it is **harness** — context
delivery with an audit trail — and it helps in two measurable ways: it lets plans take
**larger steps**, and it makes the agent's **search legible** rather than only its
conclusions.

**Trail.** Raised by David 2026-08-24: *don't think of it as taking the steering wheel
and interrupting your workflow. It's aiming to help. The attack is to take larger steps
in the search, or leave trails of research in the record so the internal thought process
can be better understood.*

Two corrections fall out, and the first is about this document's own author.

**Correction 1 — the reflex to build a gate.** §1's superseded admission design was a
gate. Corrected once, the corpus was then designed again as a *check* on provenance
rather than as context delivery. The repo's idiom is checking, so "add a check" is the
default move even where the helpful thing is not a check. Recorded as a standing bias,
not a fixed instance.

**Correction 2 — damping is not slowness.** A critically damped system reaches its
target *faster* than an underdamped one, because it does not oscillate. Every plan
here currently takes a small cautious step **because it has no prior**: with nothing
external informing a band, the only way to find the target is to probe toward it.
A corpus-grounded prior does not replace the observation — §1's boundary holds
absolutely — but it eliminates branches before a probe is spent on them. Fewer wrong
directions to rule out empirically is a larger step per unit of evidence.

**And the loop is harness by the definition the corpus itself supplied**: harness is
"context delivery, tool interfaces, planning artifacts, verification loops, memory
systems, sandboxes." A curated corpus with resolvable provenance is context delivery
with an audit trail — a memory system, not a research add-on.

**The legibility half, stated as the gap it closes:**

> Everything in `.damped-plan/` is a **commitment**. Nothing records the **search**.

Plans, evidence records, outcomes — all decisions. A reviewer given only commitments
can check them for consistency but cannot see what was considered and discarded. This
makes §3's model-invariance criterion harder than it needs to be: *a fresh reader
reaches the same conclusion from the artifact alone* is a tall order when the artifact
holds only the conclusion.

It unifies with Part 3 rather than competing with it. Two halves of one generative
process, each invisible for the same reason:

| Invisible input | Mechanism |
|---|---|
| what the agent was **permitted** to do (Part 3, §3.7) | hash the harness |
| what the agent actually **considered** (here) | record the search |

Neither is a gate. Both make an unrecorded part of the generative process legible.

**Predicts.** Two things, separately measurable:

1. *Step size.* Plans whose contracts cite corpus provenance should need fewer repair
   rounds before `ready_for_review`, and fewer sibling plans before a terminal outcome,
   than uncited ones. **P-0001 is the recorded baseline for the uncited arm: three
   adversarial review rounds, six blocking findings, zero corpus citations, no external
   source informing any band.**
2. *Legibility.* The `plan-reviewer`'s disagreement rate should fall when a plan carries
   its search trail, because a reviewer that can see what was rejected does not have to
   re-derive it.

**Killed by.** For (1), compare repair-round and sibling-plan counts across cited and
uncited plans; if cited plans need the same or more, the prior is buying no step size
and the corpus is not doing the work claimed here. For (2), compare reviewer
disagreement rates with and without a recorded search trail; if unchanged, the trail is
decoration and should be deleted rather than formalised. Both use counters the ledger
already produces.

**Touches.** `services/corpus.py` (unbuilt); the plan record, which currently has
nowhere to hold a search trail; `agents/plan-reviewer.md`, whose disagreement rate is
the instrument for (2) and is already argued for in
`tempering_and_preregistration.md` §3.

**The honest limit, and it is the same one as everywhere.** The loop cannot tell you
whether *your* harness works. Literature on harness variance is not variance here,
which is precisely why §3.7 remains a hold after reading a curated harness-engineering
corpus. It sharpens harness questions; it does not answer them about this system.

## 4. What the loop looked for and did not find

Reported because absence is a result, and an unrecorded absence becomes an
assumption:

- **No source establishes that hand-tuned weighted-sum stopping rules beat simple
  baselines.** Where adaptive stopping is shown to win, the weights are *learned*
  (Stop-RAG) or the rule is single-signal. This is the load-bearing absence behind §3.4.
- **No literature on reflexive predictive checks** — a generative process that reads
  the prediction before producing the data. The metascience treats it as fraud to be
  deterred; the RAG literature does not have the problem. §0 of the tempering doc
  appears to be describing something the surrounding fields have not formalised,
  which is either an opportunity or a sign the framing needs work.
- **No calibration data for evidence-source reliability weights** of the kind
  `DEFAULT_PROVENANCE_VERACITY` asserts. Evidence hierarchies in other fields rank
  source classes ordinally; none supplies the cardinal numbers that a weighted sum
  consumes. The ordering in the table looks defensible. The arithmetic done to it
  does not inherit that.
- **No prior art on scoped-corpus querying as a pre-registration device.** The
  components are ordinary; the combination — fix the corpus before the query, treat
  out-of-scope citation as drift — was not found stated anywhere. Treat §1 as
  untested rather than as standard practice.

## 5. Ordering, and what would make this document wrong

Ordered by evidence-per-unit-effort, not by ambition:

1. **§3.1** — a project-level validated-rate profile. Every input already exists; it
   is the only proposal here that can falsify the gate itself.
2. **§3.3 / §3.4** — the constants. §3.3 is settled arithmetic and needs a decision
   (retune or rename), not a study. §3.4's replay harness is small and its likely
   result is a deletion.
3. **§3.5** — the impossibility probe. Highest value in the doc and the most work;
   it needs seeded fixtures and an end-to-end run, and it is the only item that
   measures the thing the whole system is for.
4. **§3.2 / §3.6** — calibration bands for instrumentation already specified
   elsewhere. Cheap once that instrumentation exists; not worth pulling forward.
5. **§3.7** — held, pending a primary source.

This document is wrong if the trails are read as conclusions. Every external number
in it describes a *different system* — human researchers, RAG pipelines, coding
agents on public benchmarks — and transfers to this one only as a prior with a band
attached. The self-query results (§3.3, and the constant count in §3.4) are the only
observations here *about this codebase*, and they are the only claims that should be
allowed to close anything.

The caution that applies here as everywhere: *require an evidence trail and you will
get a filler evidence trail.* The defence is `Killed by`. A trail whose refutation
condition cannot be reached, or would never be checked, is a citation wearing a
contract's clothing — and this doc should be audited on that column first.
