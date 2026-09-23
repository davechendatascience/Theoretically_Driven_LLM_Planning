# Theoretically Driven LLM Planning

Three MCP servers that hold an LLM agent's engineering work to account.

| Server | Asks | Grounded in | Ledger |
|---|---|---|---|
| **consistency-belief** | Do the reasons for a design **follow**? | declared axioms, checked by falsification probes | `.consistency/` |
| **component-belief** | Does the built thing **work**? | declared tests, run by the server itself | `.belief/` |
| **stamp-monitor** | Is the evidence still **current and intact**, and was the loop followed? | both ledgers, their stamps, and git | reads only |

The first two are paired: a design branch names the component it governs, and cites the contract
that measures it — so neither a proof about nothing nor code nobody justified can hide. The third
watches the joins between them and writes nothing.

```
     consistency-belief (deductive)                  component-belief (empirical)
  axioms → lemmas → branches                      components → contracts → tests
  verified by LLM falsification probes            verified by executing declared tests
  model: proof obligations                        model: gates, Beta-Binomial rates
                 └──────────────► subject ◄──────────────┘
                     a branch governs a declared component
                                    │
                             stamp-monitor
         change → component → contract → branch → policy · integrity · conformance
```

**Contents** — [Quick start](#quick-start) · [Principles](#principles) ·
[consistency-belief](#consistency-belief-does-the-design-follow) ·
[component-belief](#component-belief-does-it-work) ·
[stamp-monitor](#stamp-monitor-is-the-evidence-still-current) ·
[How the ledgers join](#how-the-ledgers-join) · [Systems-engineering view](#the-systems-engineering-view) ·
[Reference](#reference)

---

## Quick start

```bash
pip install -e .          # or: uv sync
```

Register the servers with Claude Code via `.mcp.json` (the included one registers all three, with
this repository's author's paths — replace them with yours). Point all three at the **same**
project root: the joins exist only when the ledgers describe one repository.

```json
{
  "mcpServers": {
    "consistency-belief": {
      "command": "uv",
      "args": ["--directory", "/path/to/Theoretically_Driven_LLM_Planning", "run", "consistency-belief-mcp"],
      "env": {"CONSISTENCY_PROJECT_ROOT": "/path/to/your/project", "CONSISTENCY_ACTOR": "agent"}
    },
    "component-belief": {
      "command": "uv",
      "args": ["--directory", "/path/to/Theoretically_Driven_LLM_Planning", "run", "component-belief-mcp"],
      "env": {"BELIEF_PROJECT_ROOT": "/path/to/your/project", "BELIEF_ACTOR": "agent"}
    },
    "stamp-monitor": {
      "command": "uv",
      "args": ["--directory", "/path/to/Theoretically_Driven_LLM_Planning", "run", "stamp-monitor-mcp"],
      "env": {"STAMP_MONITOR_ROOT": "/path/to/your/project"}
    }
  }
}
```

Or run them directly: `PYTHONPATH=src python -m consistency_belief.server` (likewise
`component_belief.server`, `stamp_monitor.server`).

Then declare your system in two committed files and work the loops:

| File | Declares | Loop |
|---|---|---|
| `consistency.yaml` | axioms, definitions, lemmas, branches, policies | `status(view="probe")` → `verify_step(...)` → `status(view="tree")` |
| `belief.yaml` | components, interfaces, contracts, tests, priors, policies | `status(view="diagnose")` → `run_test(...)` → `status(view="belief")` |

This repository declares itself in both files, so every example below is its own output.

---

## Principles

### 1. The agent has no write path to a belief

An LLM agent is the primary caller, and an agent is a fluent producer of *plausible* numbers and
assertions. So in both belief servers, belief is a pure function of what was measured:

* component-belief has no `set_belief`: a belief is a function of `(belief-eligible evidence, declared priors, model version)`.
* consistency-belief has no `set_consistent`: consistency is a function of `(axiomatic reachability, topological acyclicity, falsification probe outcomes)`.

This is enforced by **missing tools**, not prompt instructions. What an agent *can* record has a
fixed weight:

| Channel | Tool | Weight |
|---|---|---|
| Server ran a declared test | `component_belief.run_test` | measured evidence (artifact, hash and content stamp captured) |
| Server recorded a falsification probe | `consistency_belief.verify_step` | a deductive verification trial |
| External import | `component_belief.ingest` | imported evidence (requires source and artifact) |
| Agent or human statement | `note` (both servers) | **zero** — recorded as `provenance=asserted` |

### 2. Declarations live in git, not in tools

`consistency.yaml` and `belief.yaml` load from **git HEAD, not the working tree**:

* Editing a declaration changes nothing until a human commits it; uncommitted edits show as `PENDING`.
* A lowered threshold or weakened axiom in the working tree cannot flip a verdict.
* A staged proposal (consistency-belief) can be verified and cited before that commit, but cannot support a decision until it is declared and committed.

> This is exactly as strong as your commit discipline. If agents can commit unattended, add
> CODEOWNERS on `consistency.yaml` and `belief.yaml`, or require signed commits.

### 3. Evidence is bound to what it measured

A result stops counting the moment the thing it measured changes — and not before.

* A **proof trial** records a fingerprint of its target's statement, its premises, and every premise
  upstream. Restating a node sets its trials aside; restating anything upstream marks it `STALE`.
* A **test run** writes a content stamp: the git blob id of every file its evidence rests on, as the
  working tree actually stood. Once one of those files differs at HEAD, its trials are `stale`.

Stale evidence stays on record and cited; it is not counted, cannot satisfy an adopt criterion,
and the plan schedules the re-run. Nothing re-runs automatically.

### 4. "Insufficient" is an answer, and humans approve

Sparse data yields `insufficient_evidence`, never a verdict. An open proof step is an `OBLIGATION`,
never a pass. `decide` will not record an adoption or rollback without a human `approver=`.

---

## consistency-belief: does the design follow?

Rules in [`docs/consistency_belief_mcp_design_rules.md`](docs/consistency_belief_mcp_design_rules.md);
declarations in [`consistency.yaml`](consistency.yaml).

### Concepts

* **Axiomatic grounding.** Lemmas and branches must trace back to declared axioms (`AXM-`) and definitions; anything else is `UNGROUNDED`.
* **Mechanical DAG kernel.** Acyclicity is enforced before any semantic reasoning; a cycle ($A \implies B \implies A$) is rejected with its trace.
* **Open obligations (`sorry`).** A lemma or branch with fewer than $n_{\min}$ independent trials is an open `OBLIGATION`.
* **Only a counterexample refutes.** A probe with outcome `falsified` makes a node `REFUTED`. A `gap` — a missing premise, an unproven step — leaves it unproven, counts against consensus (so the node reads `DOUBTED` once it has enough trials), and is listed under *Entailment Gaps* in `status(view="contradictions")`.
* **Blast radius.** Restating an upstream axiom or lemma marks every dependent `STALE` until re-verified. A revised claim keeps its id rather than needing a new one to escape old verdicts.
* **Staged proposals.** `propose_branch` stages a branch that persists, can be verified, and can be cited at once; it shows as `· STAGED`. It supports `decide()` only once declared at HEAD, and trials recorded while staged carry over if the declared statement is the same.
* **The verifier reasons from declarations alone.** A trial establishes entailment from axioms, definitions, premises and claims — never from the source. A clause that cannot be judged without opening the code *is* the finding: the claim leans on a fact it does not cite. Implementation fidelity lands in component-belief, cited by contract id.

### The loop

```
status(view="probe")  →  verify_step(target, trials=[...])  →  status(view="tree")
```

`probe` serves every open obligation with everything a verifier may use — the claim, each premise's
statement, the derivation rule, the three strategies (counterexample, entailment, negation) and the
call that records them — so the verifier assembles nothing and has no reason to open a file.
Independence is counted as distinct (strategy, actor) pairs: one strategy repeated by one actor is
recorded but does not close an obligation. `.claude/agents/consistency-verifier.md` runs this loop
in a context that cannot open a file; `.claude/skills/consistency-belief/SKILL.md` says when to
hand it work.

### Tools (eight)

| Tool | Does |
|---|---|
| `status` | 9 views: `tree`, `branches`, `axioms`, `obligations`, `probe`, `contradictions`, `coverage`, `audit`, `cycle` |
| `propose_branch` | stages a branch or lemma; checks acyclicity and premises; warns when a claim names a file, class or call instead of what must hold of any implementation |
| `verify_step` | records one pass of falsification trials, each bound to the statement it verified |
| `amend` | reclassifies a mis-recorded trial (`invalid`, `quarantined`, `superseded`) by appending; the original and the reason stay |
| `withdraw` | retires a staged proposal; refused for a declaration or anything a declared node cites |
| `audit_change` | computes the blast radius of changing an axiom or lemma, and records the audit so impact, approval and re-verification form one chain |
| `note` | qualitative annotation; zero weight |
| `decide` | evaluates a policy; `evidence: supported` also requires each cited contract supported in component-belief; human approval for `ADOPT`; records the revision |

```
AXM-commit-is-approval [AXIOM]: A declaration takes effect only from the committed revision. …
├── BRN-consistency-declarations-gate [PROVEN 3/3]: Only the declarations at the head revision …
├── BRN-declarations-gate [PROVEN 3/3]: Only committed declarations reach the belief model; …
└── LMA-worktree-inert [PROVEN 3/3]: Making an edit to a declaration file, without committing it, …
    └── BRN-declarations-gate [PROVEN 3/3] (shown above)
```

---

## component-belief: does it work?

Rules in [`docs/component_belief_mcp_design_rules.md`](docs/component_belief_mcp_design_rules.md),
design in [`docs/component_belief_mcp_design.md`](docs/component_belief_mcp_design.md);
declarations in [`belief.yaml`](belief.yaml).

### Concepts

* **Declared contracts.** A contract states what a component or interface must do, sliced by operating condition and compatibility key; trials differing on a compatibility key are never pooled.
* **Trial-level evidence.** Each test case is a trial (`tools/pytest_trials.py` adapts any pytest suite), stored in `.belief/` with its artifact and hash.
* **Gates and rates.** A deterministic procedure — a pytest suite — is `kind: gate`: read from its latest run, every case passing is `supported`, any failing is `refuted`, with no interval and no `n_min` for reruns to climb. A stochastic process is a rate contract with a Beta-Binomial interval, and sparse data is `insufficient_evidence`.
* **Diagnosis before optimisation.** Bottlenecks are ranked by decision relevance, never by lowest score, and a component no test observes is reported as a coverage limit rather than blamed.
* **Components claim their code.** `code:` lists the files a component owns. A file no component claims is unowned; a claimed path that no longer exists is `MISSING_CODE_PATH`; a component with no `code:` is *planned*.
* **Content stamps.** Before a test's command starts, the runner records the git blob id of every file the evidence could rest on — the components' claimed `code:`, the files the test names on its `run:` line or in `reads:` — plus what the run opened. Every trial carries the stamp's digest. Content rather than revision, so evidence from uncommitted edits later discarded is stale, an amend or squash-merge that keeps the bytes keeps the evidence, and weakening the test itself stales what it produced. Trials recorded before stamps fall back to `git diff <sw_revision> HEAD`. Design: [`docs/stamp_monitor_mcp_design.md`](docs/stamp_monitor_mcp_design.md).
* **Runs record what they read.** Each `run_test` installs an audit hook through `sitecustomize` (chaining to any the environment already had), so the run reports each project file it opened for reading — an import from cached bytecode counts as reading its source. Files a non-Python child opens are declared with `reads:`.
* **Every file carries a verdict.** `status(view="artifacts")` joins git history, the run ledger, the declarations and the filesystem. A file nothing claims, nothing ran, and no live evidence rests on is a prune candidate; a generated artifact is *kept*, *prunable*, or *undecidable* — with the source of each fact named, because "RUN-0140 opened it" is a fact and "its mtime is three weeks old" is a hint.

### The loop

```
status(view="diagnose")  →  run_test(...)  →  status(view="belief")
```

### Tools (six)

| Tool | Does |
|---|---|
| `status` | 8 views: `graph`, `coverage`, `belief`, `diagnose`, `plan`, `artifacts`, `cycle`, `trace` |
| `run_test` | runs a declared test, captures its artifact and stamp, records its trials |
| `ingest` | imports external evidence with its source and artifact |
| `amend` | reclassifies or supersedes trials by appending; nothing is edited |
| `note` | qualitative annotation; zero weight |
| `decide` | evaluates a policy; human approver for `ADOPT`/`ROLLBACK`; records the revision |

```
CTR-declarations-gate [unbucketed] supported gate 15/15 passed in RUN-0017 (+30 stale)
CTR-model-honest [unbucketed] supported gate 54/54 passed in RUN-0022 (+136 stale)
CTR-surface-intact [unbucketed] supported gate 31/31 passed in RUN-0023 (+93 stale)
basis: evidence×199 set=196375 · model bb-2 · prior none
```

`set=` is a hash of the exact evidence set; `status(view="trace", set=196375)` expands it to the
records. `+N stale` is evidence still on record that measured code which has since changed.

---

## stamp-monitor: is the evidence still current?

Design in [`docs/stamp_monitor_mcp_design.md`](docs/stamp_monitor_mcp_design.md).

Each belief server sees its own ledger. The monitor sees across them — and writes nothing. It takes
no registrations: stamps are made by the runner that ran the command, because a monitor that
accepted them would be an agent-writable path into the evidence. Freshness is a library
(`component_belief/staleness.py`) both belief servers already import, so "stale" has one definition.

| Tool | Answers |
|---|---|
| `impact(base, worktree)` | changed path → component / test → contract (state at HEAD) → design branch → policy, and which tests to re-run |
| `audit()` | every ledger line parses; ids are unique; amendments and decisions cite records that exist; stamps and artifacts still match their digests; declarations are committed |
| `workflow()` | reclassifications that remove only adverse results; adoptions with no human approver; decisions on dirty-tree evidence; adoptions whose evidence has since gone stale |

```text
src/component_belief/runner.py changed
→ CMP-runner → CTR-surface-intact [stale]
→ BRN-runner-captures (governs CMP-runner, cites CTR-surface-intact)
→ POL-release, POL-consistency-gate
next: run_test TST-server
```

The same reports run from a shell for git hooks, CI, and Claude Code hooks:
`stamp-monitor impact|audit|workflow`, exiting 1 on a `[block]` finding from `audit` or `workflow`.

---

## How the ledgers join

`consistency.yaml` opens with the components its designs govern, and each branch names one of them
and cites the contract that measures it:

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

The `components:` list is an import, not a copy: `belief.yaml` owns each component, and this list
says which of them the designs speak for. consistency-belief reads `belief.yaml` at HEAD — one way,
read-only — and `status(view="coverage")` sorts every component by what each ledger knows:

| | a declared branch | no declared branch |
|---|---|---|
| **has `code:`** | **governed** — built, and the design says why | **undeclared design** — prune the code, or declare the design |
| **no `code:`** | **planned** — design ahead of implementation, which is allowed | a name in `belief.yaml`, nothing more |

Faults are reported separately, because they are different mistakes. All are advisory: whether a
claim follows from its premises has nothing to do with whether anyone built it.

| Code | Means |
|---|---|
| `REMOVED_SUBJECT` (**BROKEN**) | the subject is a `CMP-` id `belief.yaml` no longer declares — repoint, re-declare, or prune |
| `REMOVED_COMPONENT` | a listed component `belief.yaml` no longer declares |
| `UNLISTED_SUBJECT` | a branch's subject is missing from the `components:` list |
| `UNATTACHED_SUBJECT` | the subject is prose, so the design was never bound to a component |
| `UNKNOWN_EVIDENCE` | a derivation rule cites a `CMP-`/`CTR-` id `belief.yaml` does not declare |

The release gate spans both: `POL-consistency-gate` requires each branch **proven** and its cited
contract **supported**. A project with no `belief.yaml` still works — subjects go unchecked, and
the coverage view says so.

---

## The systems-engineering view

Read as a V-model, the three servers cover definition down to component test, joined by
traceability and configuration control.

| Stage | Artifact | Method |
|---|---|---|
| Requirements | axioms and definitions in `consistency.yaml` | inspection, at commit |
| Architecture | components and interfaces in `belief.yaml`; lemmas | analysis by probe; set difference for unbacked assumptions |
| Component design | branches, each with premises and `evidence: CTR-...` | analysis by `verify_step`, from the declarations only |
| Build | `code:` claims per component; `status(view="artifacts")` | inspection |
| Component, integration, system test | contracts and tests by `layer`; `run_test`; `.belief/` | test |
| Traceability | a branch's `subject` and cited contract; `status(view="coverage")` on both sides | mechanical |
| Configuration control | declarations from git HEAD; a content stamp on every run; evidence stale once a file it rests on changes; every decision names its revision | mechanical |
| Change control | `audit_change`, STALE on restatement, `amend`, `decide(approver=)`; `stamp-monitor impact` | mechanical, plus a human approver |
| Configuration audit | `stamp-monitor audit` and `workflow` | mechanical, read-only |
| Independence | the verifier reads `status(view="probe")` and nothing else; the `consistency-verifier` agent cannot open a file | structural |
| Release gate | `POL-consistency-gate`: each branch proven **and** its cited contract supported | both ledgers |

Not represented yet: needs and validation (nothing sits above an axiom), interface-level design
claims (`IFC-` is not an admissible subject), and a failure-mode-to-metric check.

---

## Reference

### Layout

```
consistency.yaml                     axioms, definitions, lemmas, branches, policies (applied to itself)
belief.yaml                          components, interfaces, contracts, tests, policies (applied to itself)
docs/
  consistency_belief_mcp_design_rules.md   8 design rules for deductive consistency
  component_belief_mcp_design_rules.md     11 design rules for empirical belief
  component_belief_mcp_design.md           empirical model and architecture
  stamp_monitor_mcp_design.md              stamps, freshness, and the read-only monitor
src/
  consistency_belief/                deductive server (8 tools)
    declarations.py                  git-HEAD loader, validation, the component join
    graph.py                         proof DAG kernel: acyclicity, grounding, blast radius
    model.py                         verification state (PROVEN, REFUTED, OBLIGATION, STALE)
    probes.py                        falsification probe generators and parsers
    decide.py                        policy evaluation and the human approval gate
    views.py / render.py             proof tree, status and coverage views
    store.py                         append-only JSONL ledger in .consistency/
  component_belief/                  empirical server (6 tools)
    declarations.py                  git-HEAD loader, validation, code claims
    model.py                         belief slices; gate and rate contracts
    staleness.py                     content stamps and freshness (shared with both other servers)
    runner.py / readlog.py           test execution, artifact capture, the read hook
    diagnose.py / planning.py        bottleneck ranking; round test selection
    decide.py                        policy evaluation and the human approval gate
    stamps.py / views.py / render.py the artifacts view; status views
    store.py                         append-only JSONL ledger in .belief/
  stamp_monitor/                     read-only monitor (3 tools)
    impact.py                        a change traced through both ledgers
    audit.py                         stamp, artifact and ledger integrity
    workflow.py                      conformance patterns in recorded history
    server.py / cli.py               MCP server; the same reports from a shell
tools/pytest_trials.py               pytest → trials adapter
tests/                               the suites belief.yaml declares as tests
.claude/
  agents/consistency-verifier.md     verifier subagent: consistency-belief tools only, no file access
  skills/component-belief/SKILL.md   the empirical loop, four rules
  skills/consistency-belief/SKILL.md the deductive loop, six rules, when to delegate
```

### Tests

```bash
PYTHONPATH=src python -m pytest tests -q
```

That is a shell run: no artifact, no provenance. The count the ledger vouches for is `run_test` on
each declared suite, read back through `status(view="coverage")`.

The suites assert the invariants above, not the implementation:

1. Asserted notes cannot move a posterior or close a proof obligation.
2. Uncommitted threshold or axiom edits cannot alter a verdict.
3. The DAG kernel detects and rejects circular dependencies.
4. An upstream restatement invalidates exactly its topological blast radius.
5. A probe that captures a counterexample makes its claim `REFUTED`.
6. An adoption cannot be recorded without a human approver.
7. A component removed from `belief.yaml` leaves its designs reported as broken, not proven.
8. Three probes of one strategy by one actor do not close an obligation; a pass of three strategies does.
9. A gate contract is read from its latest run; evidence measured before a claimed file changed is stale and cannot satisfy an adopt criterion.
10. A falsification argued from a source file is refused before anything is recorded; a decision names the revision it was taken at.
11. Evidence is bound to the content it measured: discarded uncommitted edits, a weakened test, or an edited stamp make it stale; a rewritten history with the same bytes does not.
12. The monitor writes nothing, and reports a damaged ledger line, a changed artifact, and an agent approving its own adoption.
