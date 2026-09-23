# Theoretically Driven LLM Planning

Two MCP servers that hold an LLM agent's design work to account: one asks whether the reasons
for a design **follow**, the other whether the built thing **works**. They are paired — a branch
in the design ledger names the component it governs in the component ledger — so neither a proof
about nothing nor code nobody justified can hide.

```
                         THEORETICALLY DRIVEN LLM PLANNING
                                         │
                 ┌───────────────────────┴───────────────────────┐
                 ▼                                               ▼
     consistency-belief (Deductive)                  component-belief (Empirical)
  • Grounded in: Declared Axioms                  • Grounded in: Executable Test Trials
  • Representation: Deductive Proof DAG           • Representation: Component System Graph
  • Verification: LLM Falsification Probes        • Verification: Mechanical Test Execution
    (counterexample search, gap detection)          (exit codes, captured artifacts, hashes)
  • Model: Lean-style Proof Obligations           • Model: Beta-Binomial Credible Intervals
  • Storage: .consistency/ (append-only)          • Storage: .belief/ (append-only)
                 └──────────────► subject ◄──────────────┘
                     a branch governs a declared component
```

## The Commitment

An LLM agent is the primary caller, and an agent is a fluent producer of *plausible* numbers and assertions. Therefore, **in both MCPs, the agent has no write path to a belief**:
* In `component-belief`, there is no `set_belief`. Beliefs are a pure function of `(belief-eligible evidence, declared priors, model version)`.
* In `consistency-belief`, there is no `set_consistent`. Consistency is a pure function of `(axiomatic reachability, topological acyclicity, falsification probe outcomes)`.

This discipline is enforced by **missing tools**, not prompt instructions.

## The Systems-Engineering View

Read as a V-model, the pair covers definition down to component test, joined by traceability and
configuration control. Analysis stages live in `consistency-belief`, Test stages in
`component-belief`, and the join is a branch's `subject` naming a declared component.

| Stage | Artifact in the pair | Method |
|---|---|---|
| Requirements | axioms and definitions in `consistency.yaml` | Inspection, at commit |
| Architecture | components and interfaces in `belief.yaml`; lemmas | Analysis by probe; set difference for unbacked assumptions |
| Component design | branches, each with premises and `evidence: CTR-...` in its derivation rule | Analysis by `verify_step`, from the declarations only |
| Build | `code:` claims per component; `status(view="artifacts")` | Inspection |
| Component, integration, system test | contracts and tests by `layer`; `run_test`; `.belief/` | Test |
| Traceability | a branch's `subject` names a component and its derivation rule names the contract; `status(view="coverage")` on both sides | mechanical |
| Configuration control | declarations from git HEAD; `sw_revision` on every trial; evidence goes stale once claimed code changes; every decision names its revision | mechanical |
| Change control | `audit_change` (recorded), STALE on restatement, `amend`, `decide(approver=)` | mechanical, plus a human approver |
| Independence | the verifier reads `status(view="probe")` and nothing else; the `consistency-verifier` agent cannot open a file | structural |
| Release gate | `POL-consistency-gate` requires each branch proven **and** its cited contract supported | both ledgers |

Not represented yet: needs and validation (nothing sits above an axiom), interface-level design
claims (`IFC-` is not an admissible subject), and a failure-mode-to-metric check.

| Channel | Tool | Epistemic Weight |
|---|---|---|
| Server ran a declared test | `component_belief.run_test` | Measured empirical evidence (artifact + hash captured) |
| Server ran a falsification probe | `consistency_belief.verify_step` | Deductive verification trial (counterexample / entailment probe) |
| External import | `component_belief.ingest` | Imported evidence (requires source + artifact) |
| Agent or human statement | `note` (both servers) | **Zero weight** — recorded as `provenance=asserted` (testimony) |

---

## 1. `consistency-belief`: Deductive Proof Consistency (Lean-Style)

Design rules in [`docs/consistency_belief_mcp_design_rules.md`](docs/consistency_belief_mcp_design_rules.md).
Declarations in [`consistency.yaml`](consistency.yaml).

Axiom-to-branch design consistency for architectures, specifications, and planning:
* **Axiomatic Grounding**: Components, contracts, and design mutations must trace transitively back to declared root axioms (`AXM-...`). Ungrounded nodes are flagged as `UNGROUNDED`.
* **Mechanical DAG Kernel**: Enforces strict acyclicity before any semantic reasoning. Circular dependencies ($A \implies B \implies A$) are rejected immediately with cycle traces.
* **Open Proof Obligations (`sorry`)**: Any derived lemma or contract with fewer than $n_{\min}$ verification trials is surfaced as an open `OBLIGATION`.
* **Topological Blast Radii**: Modifying an upstream axiom or lemma invalidates all downstream dependents, marking them `STALE` until re-verified.
* **Trials Are Bound to What They Verified**: Every trial records a fingerprint of its target's statement and premises and of every premise upstream. Restating a node sets its earlier trials aside (they are reported, not counted); restating anything upstream marks the node `STALE` until it is re-verified. A revised claim keeps its id instead of needing a new one to escape old verdicts.
* **Staged Proposals**: `propose_branch` stages a branch in the ledger. It persists across calls, `verify_step` can target it and later proposals can cite it as a premise at once, and it shows as `· STAGED` in every view. It supports `decide()` only once the same id is declared in `consistency.yaml` at git HEAD; trials recorded while staged carry over if the declared statement is the same.
* **LLM Measurement via Falsification Probes**: The LLM measures consistency through adversarial probes (`verify_step`), searching for concrete counterexamples or unstated assumptions rather than merely affirming belief.
* **Only a Counterexample Refutes**: A probe with outcome `falsified` makes a node `REFUTED`. A `gap` -- a missing premise, an unproven step -- leaves it unproven: it counts against consensus (so the node reads `DOUBTED` once it has enough trials) and is listed under *Entailment Gaps* in `status(view="contradictions")`, whatever evidence text it carries.
* **The Verifier Reasons From Declarations Alone**: A trial establishes entailment from the axioms, definitions, premises and claims — never from the source. A clause that cannot be judged without opening the code *is* the finding: the claim leans on a fact it does not cite. Implementation fidelity is the implementer's duty and lands in component-belief, cited here by id.

### The Loop
```
status(view="probe")  →  verify_step(target, trials=[...])  →  status(view="tree")
```

`probe` serves every open obligation with all a verifier may use -- the claim, each premise's
statement, the derivation rule, the three strategies and the call that records them -- so the
verifier assembles nothing and has no reason to open a file. One call records one pass
(counterexample, entailment, negation). Independence is counted as distinct (strategy, actor)
pairs: the same strategy repeated by the same actor is recorded but does not close an
obligation. `.claude/agents/consistency-verifier.md` runs this loop in a context whose tool list
cannot open a file, and `.claude/skills/consistency-belief/SKILL.md` says when to hand it work.

### The Eight Tools
* `status`: 9 views (`tree`, `branches`, `axioms`, `obligations`, `probe`, `contradictions`, `coverage`, `audit`, `cycle`).
* `propose_branch`: Stages new contracts or lemmas (declared or staged premises); validates acyclicity and premise validity; re-proposing a staged id restates it; warns when a claim names a file, a class or a call instead of what must hold of any implementation.
* `verify_step`: Records falsifiable verification trials (counterexample search, entailment, negation), each bound to the statement it verified; `trials=[...]` records one pass in one call.
* `amend`: Reclassifies a mis-recorded trial (`invalid`, `quarantined`, `superseded`) by appending an amendment; the original record and the reason stay in the ledger.
* `withdraw`: Retires a staged proposal -- a design that will not be built, or whose component is gone. Refused for a declaration (delete it from `consistency.yaml` and commit) and for anything a declared node cites. The proposal, its trials and the withdrawal stay in the ledger; re-proposing the id revives it.
* `audit_change`: Calculates the topological blast radius of modifying an axiom or lemma, and records the audit as an event so impact, approval and re-verification form one chain.
* `note`: Qualitative annotation (inert channel, zero proof weight).
* `decide`: Evaluates consistency policy; a criterion with `evidence: supported` also requires the contracts the branch cites to be supported in component-belief (the one gate over both ledgers); enforces human approval for `ADOPT`; records the git revision the decision was taken at.

```
AXM-damage-nonneg [AXIOM]
└── LMA-combat-health-monotonicity [PROVEN 2/2]
    └── BRN-combat-resolver [PROVEN 2/2]

basis: verification_trials×14 set=a1b1f9 · proven=7 obligations=0 refuted=0
```

---

## 2. `component-belief`: Empirical Evidence Grounding

Design rules in [`docs/component_belief_mcp_design_rules.md`](docs/component_belief_mcp_design_rules.md),
design in [`docs/component_belief_mcp_design.md`](docs/component_belief_mcp_design.md).
Declarations in [`belief.yaml`](belief.yaml).

Evidence-grounded belief state for a system modeled as components and interfaces:
* **Declared Contracts**: Slices defined per component/interface, operating condition, and compatibility key.
* **Trial-Level Granularity**: Stores individual trials from pytest or telemetry into `.belief/`.
* **Beta-Binomial Statistics**: Computes uncertainty intervals; rejects premature verdicts on sparse data (`insufficient_evidence`).
* **Regressions & Bottlenecks**: Surfaces regressions and ranks bottlenecks by decision relevance without blaming unobserved components.
* **Components Claim Their Code**: `code:` lists the files a component owns. A file no component claims is unowned; a claimed path that no longer exists is `MISSING_CODE_PATH`; a component with no `code:` at all is *planned*.
* **Every File Stamped**: `status(view="artifacts")` joins git (added, last changed), the run ledger (which runs invoked it, when), the declarations (what claims or names it) and the filesystem (generated output under the declared `artifacts:` roots). Each stamp carries its source, because "RUN-0140 invoked it at 04:44" is a fact and "its mtime is three weeks old" is a hint. A file nothing claims, nothing has run, and no belief-eligible evidence rests on is a prune candidate — pruning stops being a memory exercise.
* **Runs Record What They Read**: every `run_test` installs an audit hook through `sitecustomize`, so the run itself reports each file it opened under the project root. A generated artifact then carries a verdict rather than a date: *kept* (live evidence or a declared test reads it), *prunable* (every run that opened it has superseded evidence), or *undecidable* (nothing instrumented ever opened it). Files a non-Python child opens are declared with `reads:` on the test; the hook narrows that gap and the view says which case it is reporting.
* **Gate Contracts**: a deterministic procedure -- a pytest suite -- is declared `kind: gate`. Its belief is read from its latest run: every case passing is `supported`, any case failing is `refuted`, and there is no interval to straddle and no `n_min` that reruns of the same result must climb. A rate contract is for a stochastic process.
* **Evidence Goes Stale With Its Code**: every measured trial carries the revision it ran at (`sw_revision`, plus `sw_dirty` when the tree had uncommitted edits), and every component claims its `code:`. Once a claimed path has changed since a trial's revision, that trial is `stale`: still on record and cited, not counted. A slice with nothing current reads `stale` with the change named, cannot satisfy an adopt criterion, and `diagnose` says which test to run again. This is the empirical counterpart of a `STALE` proof node.

### The Loop
```
status(view="diagnose")  →  run_test(...)  →  status(view="belief")
```

### The Six Tools
* `status`: 8 views (`graph`, `coverage`, `belief`, `diagnose`, `plan`, `artifacts`, `cycle`, `trace`).
* `run_test`: Executes declared test commands, captures artifacts, extracts trials.
* `ingest`: Imports external evidence with provenance.
* `amend`: Corrects or invalidates trials without destructive mutations.
* `note`: Qualitative annotation (inert channel).
* `decide`: Evaluates policy against observed evidence; requires human approver for `ADOPT`/`ROLLBACK`; records the git revision the decision was taken at.

```
CTR-grasp-reachable [normal, model_revision=v3] supported 0.91 [0.84,0.96] n=34
CTR-grasp-reachable [low, model_revision=v3] insufficient n=3 (need 5 more)
basis: evidence×37 set=a3f9c1 · model bb-1 · prior none
next: run_test TST-grasp-ik conditions={low}  # closes the thin slice
```

---

## 3. The Join: `subject`

`consistency.yaml` opens with the components its designs govern, and each branch names one of them:

```yaml
# consistency.yaml                       # belief.yaml
components:                              components:
  - {id: CMP-motion, note: the gate} ───►  - id: CMP-motion
                                             purpose: Plan motion
branches:                                    code: [motion.py]
  - id: BRN-motion-gate                      ...
    subject: CMP-motion          ───────►
    premises: [AXM-safety]                 contracts:
    derivation_rule: "motion.py,           - id: CTR-motion-clear
      evidence: CTR-motion-clear" ───────►   subject: CMP-motion
```

The `components:` list is an import, not a copy: belief.yaml owns each component, and this file
says which of them its designs speak for. A listed id belief.yaml no longer declares is
`REMOVED_COMPONENT`; a branch whose subject is missing from the list is `UNLISTED_SUBJECT`.

consistency-belief reads `belief.yaml` at git HEAD — one way, read-only — and checks both ends of
that arrow. `status(view="coverage")` then sorts every component by what each ledger knows:

| | a declared branch | no declared branch |
|---|---|---|
| **has `code:`** | **governed** — built, and the design says why | **undeclared design** — prune the code, or declare the design |
| **no `code:`** | **planned** — design ahead of implementation, which is allowed | a name in `belief.yaml`, nothing more |

Two faults are reported separately, because they are different mistakes:

* **BROKEN** (`REMOVED_SUBJECT`) — the subject *is* a `CMP-` id and `belief.yaml` no longer declares
  it: the component was removed or renamed and its designs now govern nothing. Repoint them,
  re-declare the component, or prune the branches.
* **unattached** (`UNATTACHED_SUBJECT`) — the subject is prose, so the design was never bound to a
  component at all.
* `UNKNOWN_EVIDENCE` — a `derivation_rule` citing a `CMP-`/`CTR-` id that `belief.yaml` does not
  declare.

All three are advisory: a design keeps its place in the proof DAG, because whether a claim follows
from its premises has nothing to do with whether anyone built it. `propose_branch` says the same
thing at staging time rather than letting a stale subject through in silence.

A project with no `belief.yaml` keeps working — subjects simply go unchecked, and the coverage
view says so instead of reporting an empty graph.

---

## Declarations Live in Git, Not in Tools

Declarations (`consistency.yaml` and `belief.yaml`) load from **git HEAD, not the working tree**:
* Editing a declaration file changes nothing until a human commits it.
* Uncommitted edits show as `PENDING` in status.
* Neither a threshold change nor a weakened axiom in the working tree can flip a verdict without a human git commit.
* A staged proposal (consistency-belief) is reviewable before that commit -- it can be verified and cited -- but it cannot support a decision until it is declared and committed.

> Caveat: This is exactly as strong as your commit discipline. If agents can commit unattended, add CODEOWNERS on `consistency.yaml` and `belief.yaml` or require signed commits.

---

## Install & Register

```bash
pip install -e .
```

Register both servers with Claude Code or Antigravity via `.mcp.json`. Point both at the **same**
project root: the join is only available when the two ledgers describe one repository.

```json
{
  "mcpServers": {
    "consistency-belief": {
      "command": "uv",
      "args": [
        "--directory", "/home/edge-host/Documents/GitHub/Theoretically_Driven_LLM_Planning",
        "run", "consistency-belief-mcp"
      ],
      "env": {
        "CONSISTENCY_PROJECT_ROOT": "/path/to/your/project",
        "CONSISTENCY_ACTOR": "agent"
      }
    },
    "component-belief": {
      "command": "uv",
      "args": [
        "--directory", "/home/edge-host/Documents/GitHub/Theoretically_Driven_LLM_Planning",
        "run", "component-belief-mcp"
      ],
      "env": {
        "BELIEF_PROJECT_ROOT": "/path/to/your/project",
        "BELIEF_ACTOR": "agent"
      }
    }
  }
}
```

Or run directly:
```bash
PYTHONPATH=src python -m consistency_belief.server
PYTHONPATH=src python -m component_belief.server
```

---

## Layout

```
consistency.yaml                                       # Axioms, definitions, lemmas, contracts (applied to itself)
belief.yaml                                            # Components, interfaces, contracts, tests (applied to itself)
docs/
  consistency_belief_mcp_design_rules.md               # 8 design rules for deductive consistency
  component_belief_mcp_design_rules.md                 # 11 design rules for empirical belief
  component_belief_mcp_design.md                       # Empirical model & architecture specification
src/
  consistency_belief/                                  # Deductive MCP server
    declarations.py                                    # Git-HEAD loader, schema validator, component join
    graph.py                                           # Proof DAG kernel (acyclicity, grounding, blast radius)
    model.py                                           # Verification state (PROVEN, REFUTED, OBLIGATION, STALE)
    probes.py                                          # LLM verification probe generators & parsers
    decide.py                                          # Consistency policy evaluation & human approval gate
    render.py / views.py                               # ASCII proof tree, status and coverage views
    server.py                                          # FastMCP server (8 tools)
    store.py                                           # Append-only JSONL ledger in .consistency/
  component_belief/                                    # Empirical MCP server
    declarations.py                                    # Git-HEAD loader, validation, code claims
    model.py                                           # Beta-Binomial belief slices; gate contracts
    staleness.py                                       # Evidence goes stale when claimed code changes
    diagnose.py                                        # Bottleneck ranking & discriminating tests
    decide.py                                          # Policy evaluation & human approval gate
    planning.py                                        # Round test selection
    runner.py                                          # Test execution and artifact capture
    views.py / render.py                               # Empirical status views
    server.py                                          # FastMCP server (6 tools)
    store.py                                           # Append-only JSONL ledger in .belief/
tools/pytest_trials.py                                 # pytest -> trials JSON adapter
tests/                                                 # the suites belief.yaml declares as tests; the ledger holds the count
.claude/
  agents/consistency-verifier.md                       # verifier subagent: only the consistency-belief tools, no file access
  skills/component-belief/SKILL.md                     # the empirical loop, four rules
  skills/consistency-belief/SKILL.md                   # the deductive loop, six rules, when to delegate
```

---

## Tests

```bash
PYTHONPATH=src python -m pytest tests -q
```

That is a shell run: it has no artifact and no provenance. The count the ledger vouches for is
`run_test` on each declared suite, read back through `status(view="coverage")`.

The test suite asserts the core epistemic invariants across both systems:
1. Asserted notes cannot move posteriors or close proof obligations.
2. Uncommitted threshold or axiom edits cannot alter verdicts.
3. Mechanical DAG checking detects and rejects circular dependencies.
4. Upstream mutations trigger exact topological blast radius invalidation.
5. Falsification probes capturing counterexamples immediately transition claims to `REFUTED`.
6. Final adoption decisions refuse to self-approve without a human approver.
7. A component removed from `belief.yaml` leaves its designs reported as broken, not as proven.
8. Three probes of one strategy by one actor do not close an obligation; a pass of three strategies does.
9. A gate contract is read from its latest run; evidence measured before a claimed file changed is stale and cannot satisfy an adopt criterion.
10. A falsification argued from a source file is refused before anything is recorded; a decision names the revision it was taken at.
