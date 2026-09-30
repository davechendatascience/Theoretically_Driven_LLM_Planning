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
[Reference](#reference) · [Changelog](#changelog)

---

## Quick start

The three servers, the two workflow skills and the `consistency-verifier` subagent ship as one
Claude Code plugin, `tdlp`, pinned to a release tag. Add this repository as a marketplace once per
machine, then enable the plugin in each project that uses it:

```bash
claude plugin marketplace add davechendatascience/Theoretically_Driven_LLM_Planning
cd /path/to/your/project
claude plugin install tdlp@tdlp --scope project   # writes .claude/settings.json -- commit it
```

Enabling it per project keeps the tools out of every other project's context. On another machine,
add the marketplace once and run the same install; a project that lists the plugin in its settings
does not fetch it on its own.

* **Which project.** Every server reads the project Claude Code reports (`${CLAUDE_PROJECT_DIR}`),
  so all three describe the same repository.
* **Which version.** The servers install with `uvx` from the tag `tdlp--v<version>`, so edits here
  reach a project only when a release is tagged and the plugin updated
  (`claude plugin update tdlp@tdlp`).
* **Which Python a test gets.** A declared test's `run:` line runs in the project's environment:
  its `.venv` if it has one, else the PATH Claude Code inherited, never the plugin's own
  interpreter. For anything else, name the interpreter on the run line (`conda run -n env python ...`).
* **Skills.** They load as `/tdlp:component-belief` and `/tdlp:consistency-belief`.

### Your goals

Write `goals.yaml` at the project root and commit it yourself. It holds your goals, the interfaces
between them, and the contracts, tests and policy that measure them, in `belief.yaml`'s schema:

```yaml
goals:
  - {id: GOL-teacher, outcome: The teacher's demonstrations succeed in sim, measure: CTR-demos-succeed}
  - {id: GOL-vla, outcome: The VLA performs the skill from a language instruction, measure: CTR-vla-success}
interfaces:
  - {id: IFC-teacher__vla, from: GOL-teacher, to: GOL-vla,
     hands_over: "demonstrations: format, frame, rate", measure: CTR-demos-fit-vla}
contracts:   # the three measures above, and only those
  - {id: CTR-demos-succeed, subject: GOL-teacher, kind: rate, metrics: [{id: success, unit: bool}],
     acceptance: {rule: "success == true", target_rate: 0.9}, sufficiency: {n_min: 30},
     evaluable_by: [TST-teacher-eval]}
  - {id: CTR-vla-success, subject: GOL-vla, kind: rate, metrics: [{id: success, unit: bool}],
     acceptance: {rule: "success == true", target_rate: 0.8}, sufficiency: {n_min: 30},
     evaluable_by: [TST-vla-eval]}
  - {id: CTR-demos-fit-vla, subject: IFC-teacher__vla, kind: gate, metrics: [{id: passed, unit: bool}],
     acceptance: {rule: "passed == true"}, evaluable_by: [TST-demos-fit]}
tests:
  - {id: TST-teacher-eval, layer: e2e, targets: [GOL-teacher], run: python eval/teacher.py $OUT, metrics: [success]}
  - {id: TST-vla-eval, layer: e2e, targets: [GOL-vla], run: python eval/vla.py $OUT, metrics: [success]}
  - {id: TST-demos-fit, layer: interface, targets: [IFC-teacher__vla], run: python eval/demos_fit.py $OUT, metrics: [passed]}
policies:
  - id: POL-goals
    criteria:
      - {slice: CTR-demos-succeed, require: supported}
      - {slice: CTR-vla-success, require: supported}
      - {slice: CTR-demos-fit-vla, require: supported}
```

The agent tags each component in `belief.yaml` with the `goal:` it serves, so a goal's evidence
goes stale when that code changes. Once per clone, install the guard that keeps the agent's
commits off your goal set:

```bash
uvx --from "git+https://github.com/davechendatascience/Theoretically_Driven_LLM_Planning@tdlp--v0.4.0" tdlp-guard install
```

Then check in with one call, `status(view="goals")`. It shows each goal and interface as met, not
met, insufficient or stale (with the test to run), the agent's proposals on them, and any agent
commit to your goal set since your last. Your goals policy is the default for `decide`,
`diagnose` and `plan`, and an adoption under it needs no approver.

### Moving a project that registered the servers by hand

1. Once per machine: `claude plugin marketplace add davechendatascience/Theoretically_Driven_LLM_Planning`.
2. In the project: `claude plugin install tdlp@tdlp --scope project`, and commit `.claude/settings.json`.
3. Remove the hand registrations, **every scope at once**: the three entries in the project's
   `.mcp.json`, and on each machine `claude mcp remove <name> -s local` for `component-belief`,
   `consistency-belief` and `stamp-monitor`. Removing one scope and not the other leaves the other
   in charge, such as a Linux path on a Windows machine.
4. Delete any copies of the two skills or the verifier under the project's `.claude/`. The plugin
   ships them as `/tdlp:component-belief`, `/tdlp:consistency-belief` and `consistency-verifier`;
   a copy is a second, unversioned rulebook.
5. Rename tool ids wherever they are written, such as permission allowlists, hooks, `CLAUDE.md`
   and your own agents: `mcp__component-belief__run_test` becomes
   `mcp__plugin_tdlp_component-belief__run_test`, and likewise for the other two servers.
6. Check each `run:` line's interpreter. A plain `python` now resolves to the project's `.venv`
   when it has one; a conda environment needs naming (`conda run -n env python ...`).
7. Restart the session (or `/reload-plugins`). `claude mcp list` should show three
   `plugin:tdlp:*` servers as connected, and `status(view="belief")` your own contracts.

Nothing in the ledgers moves. `belief.yaml`, `consistency.yaml`, `.belief/` and `.consistency/` are
read as they are, and evidence stays current, because staleness is judged by content, not by which
server recorded it.

To work on the harness itself, install it editable and register the servers by hand, all three at
the **same** project root: the joins exist only when the ledgers describe one repository.

```bash
pip install -e .          # or: uv sync
```

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
| External import | `component_belief.ingest` | imported evidence (a declared test, and a local artifact the server copies and hashes) |
| Agent or human statement | `note` (both servers) | **zero** — recorded as `provenance=asserted` |

### 2. Declarations live in git, not in tools

`consistency.yaml`, `belief.yaml` and `goals.yaml` load from **git HEAD, not the working tree**:

* Editing a declaration changes nothing until it is committed; uncommitted edits show as `PENDING`.
* A lowered threshold or weakened axiom in the working tree cannot flip a verdict.
* A staged proposal (consistency-belief) can be verified and cited before that commit, but cannot support a decision until it is declared and committed.

The files have different owners. `belief.yaml` and `consistency.yaml` are the agent's engineering:
components, contracts, thresholds and designs, which it commits as it works. **`goals.yaml` is the
human's**: each goal's outcome and the contract that says it is met, each interface between goals
and the contract its hand-over must pass, and the tests and policy those use. The agent may change
anything below the goals; only the human changes what a goal is and how it is measured.

* **Refused.** `tdlp-guard install` puts a `commit-msg` hook in a clone. It refuses a commit that
  changes `goals.yaml` or a file its tests name when the commit carries the agent's trailer
  (`Co-Authored-By: Claude`). A commit you type yourself has no trailer and passes.
* **Recorded.** Any agent commit to the goal set that got through (hook not installed,
  `--no-verify`) shows in `status(view="goals")` and `stamp-monitor workflow`
  (`GOAL_SET_CHANGED_BY_AGENT`) until your next commit to the goal set.
* **Proposed.** An agent that thinks a goal is wrong writes `note(subject="GOL-...")`; the goals
  view lists it.

> The trailer is a convention the agent keeps, not a credential. This guards against drift, an
> agent relaxing a measure while sincerely reporting progress, not against an agent working
> around you on purpose. For that, the agent needs its own account and a remote it cannot
> administer.

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
never a pass. `decide` will not record an adoption or rollback without a human `approver=` --
except under a policy in `goals.yaml`, whose criteria (and every contract and test they name) the
human approved by committing them, and only while no agent commit to the goal set has come since.
The record names the `goals.yaml` blob it rests on.

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
recorded but does not close an obligation. `plugin/agents/consistency-verifier.md` runs this loop
in a context that cannot open a file; `plugin/skills/consistency-belief/SKILL.md` says when to
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
* **Content stamps.** Before a test's command starts, the runner records the git blob id of every file the evidence could rest on — the components' claimed `code:`, the files the test names on its `run:` line or in `reads:` — plus what the run opened. Every trial carries the stamp's digest. Content rather than revision, so evidence from uncommitted edits later discarded is stale, an amend or squash-merge that keeps the bytes keeps the evidence, and weakening the test itself stales what it produced. A declared input git ignores — a checkpoint, a dataset, a directory of demonstrations — has no blob at HEAD, so it is stamped by its content digest instead, and the evidence stays current while the file on disk still has it: retrain the checkpoint and the evidence goes stale, restore the same bytes and it counts again. Trials recorded before stamps fall back to `git diff <sw_revision> HEAD`. Design: [`docs/stamp_monitor_mcp_design.md`](docs/stamp_monitor_mcp_design.md).
* **Runs record what they read.** Each `run_test` installs an audit hook through `sitecustomize` (chaining to any the environment already had), so the run reports each project file it opened for reading — an import from cached bytecode counts as reading its source. Files a non-Python child opens are declared with `reads:`.
* **Every file carries a verdict.** `status(view="artifacts")` joins git history, the run ledger, the declarations and the filesystem. A file nothing claims, nothing ran, and no live evidence rests on is a prune candidate; a generated artifact is *kept*, *prunable*, or *undecidable* — with the source of each fact named, because "RUN-0140 opened it" is a fact and "its mtime is three weeks old" is a hint.

### The loop

```
status(view="diagnose")  →  run_test(...)  →  status(view="belief")
```

### Tools (six)

| Tool | Does |
|---|---|
| `status` | 9 views: `graph`, `coverage`, `belief`, `diagnose`, `plan`, `artifacts`, `cycle`, `trace`, `goals` |
| `run_test` | runs a declared test, captures its artifact and stamp, records its trials |
| `ingest` | imports external evidence: each record names a test its contract lists, and the server copies and hashes the results file itself |
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

Read as a V-model, the three servers cover stakeholder needs down to component test, joined by
traceability and configuration control. The human owns the top of the V; the agent owns the rest.

| Stage | Artifact | Method |
|---|---|---|
| Needs and validation | goals and the interfaces between them in `goals.yaml`, each with the contract that says it is met; `status(view="goals")` | test (typically `layer: e2e`), criteria committed by the human |
| Requirements | axioms and definitions in `consistency.yaml` | inspection, at commit |
| Architecture | components and interfaces in `belief.yaml`; lemmas | analysis by probe; set difference for unbacked assumptions |
| Component design | branches, each with premises and `evidence: CTR-...` | analysis by `verify_step`, from the declarations only |
| Build | `code:` claims per component; `status(view="artifacts")` | inspection |
| Component, integration, system test | contracts and tests by `layer`; `run_test`; `.belief/` | test |
| Traceability | a branch's `subject` and cited contract; `status(view="coverage")` on both sides | mechanical |
| Configuration control | declarations from git HEAD; a content stamp on every run, covering declared inputs git ignores by their content on disk; evidence stale once a file it rests on changes; every decision names its revision | mechanical |
| Change control | `audit_change`, STALE on restatement, `amend`, `decide`; `stamp-monitor impact`; the goal guard | mechanical, plus the human's commit of `goals.yaml` |
| Configuration audit | `stamp-monitor audit` and `workflow` | mechanical, read-only |
| Independence | the verifier reads `status(view="probe")` and nothing else; the `consistency-verifier` agent cannot open a file | structural |
| Release gate | `POL-consistency-gate`: each branch proven **and** its cited contract supported; the goals policy in `goals.yaml` | both ledgers, and the human's goals |

Not represented yet: a trace from a goal into the design ledger (an axiom naming the goal it
serves), interface-level design claims (`IFC-` is not an admissible subject), and a
failure-mode-to-metric check.

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
    runner.py / readlog.py           test execution in the project's environment, artifact capture, the read hook
    project.py                       which project root all three servers read
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
.claude-plugin/marketplace.json      this repository as a plugin marketplace, listing `tdlp`
plugin/                              the `tdlp` Claude Code plugin
  .claude-plugin/plugin.json         name and version (one version: plugin, marketplace, package, tag)
  .mcp.json                          the three servers, installed with uvx from tag tdlp--v<version>
  agents/consistency-verifier.md     verifier subagent: consistency-belief tools only, no file access
  skills/component-belief/SKILL.md   the empirical loop, four rules
  skills/consistency-belief/SKILL.md the deductive loop, six rules, when to delegate
```

A release: bump `version` in `pyproject.toml`, `plugin/.claude-plugin/plugin.json`, the marketplace
entry and the tag in `plugin/.mcp.json` together (`TST-plugin` fails if any disagree), commit, then
`claude plugin tag plugin --push`.

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
13. An import rests on a local artifact the server copied and hashed, from a test its contract lists; a fabricated import cannot move a gate or reach an adoption.
14. As a plugin, all three servers read the project Claude Code reports, install from their own version's tag, and never lend a test the plugin's own interpreter.
15. An agent-trailered commit to the goal set is refused and one the human types passes; an adoption under the goals policy needs no approver until the agent touches the goal set.
16. A declared input git ignores is judged by its content on disk: changed or missing, its evidence is stale; the same bytes again, current.

---

## Changelog

Newest first. Versions are the `tdlp` plugin's, released as git tags `tdlp--v<version>`. Before
0.2.0 the harness was installed by hand at version 0.1.0 and never tagged. The ids point at the
change itself; an `evidence:` commit recording the suites' runs follows each.

### 0.4.0 — 2026-10-01 · evidence on files git does not track

- A declared input git ignores is stamped by its content digest and judged against the file on
  disk. This covers a checkpoint, a dataset or a directory of demonstrations, whether in `reads:`
  or named as a file on the run line. Retrain the checkpoint and its evidence goes stale; restore
  the same bytes and it counts again; delete it and the reason says so. Before, a gitignored
  checkpoint never entered the stamp, so retraining it staled nothing, and an untracked dataset
  left its evidence stale forever.
- A file git neither tracks nor ignores stays stale until it is committed or ignored, and the
  reason now says exactly that instead of calling it an uncommitted edit.
- Digests are cached by size and modification time, so a large file is hashed once per change.

### 0.3.0 — 2026-10-01 · goals the human owns

- **`goals.yaml`** (`746dc2a`) holds the goals, the interfaces between them, and the contracts,
  tests and policy that measure them. Only the human commits it. The agent owns `belief.yaml` and
  `consistency.yaml` and commits them as it works. A component names the goal it serves, so a
  goal's evidence goes stale with that code.
- **The guard, `tdlp-guard install`,** is a commit-msg hook. It refuses a commit that carries the
  agent's trailer and changes the goal set.
- **`status(view="goals")`** is the one view to check in with. `note(subject="GOL-…")` is how the
  agent proposes a goal change.
- **`decide`** records an adoption under the goals policy without an approver, since the human's
  commit approved it. That holds until the agent touches the goal set; `workflow` reports any
  such commit.
- **`impact`** now reaches a contract through every component its subject rests on. Goals and
  interfaces were missed before.
- The PYTHONPATH read-hook test runs end to end only where `env` exists (`6491778`). The last
  hand-registered servers gave way to the plugin (`3bc2f68`).

### 0.2.0 — 2026-09-30 · one plugin, and imports that hold to their definition

- **`ingest`** (`b2cabd2`) requires a test the contract lists and a local artifact, which it copies
  and hashes itself, and `audit` checks imported artifacts. Before, one call naming a made-up test
  and a missing file could turn a gate supported and let `decide` record an adoption, with `audit`
  and `workflow` both clean.
- **The plugin `tdlp`** (`d733b29`) ships the three servers, both skills and the verifier as one
  Claude Code plugin. The servers install with `uvx` from a release tag and read the project
  Claude Code reports. A declared test runs in the project's environment, not the plugin's.
  `UV_LINK_MODE=copy` avoids broken installs under OneDrive.
- `a3812c2` enables the plugin for this project and adds the migration steps for a project that
  registered the servers by hand.

### 0.1.0 — 2026-08-31 to 2026-09-23 · three ledgers, applied to themselves

- **component-belief** (`edf8945`, 2026-08-31) holds evidence-grounded belief per contract slice.
  Beta-Binomial rates keep "insufficient" as an answer, and diagnosis comes before optimising.
  Its first self-hosted run is `41f48ee`.
- **consistency-belief** (`bbdacd5`, 2026-09-21) builds axioms → lemmas → branches, verified by
  falsification probes. Staged proposals persist and trials bind to the statement they verified
  (`243250b`), and only a falsified probe refutes (`627dde7`).
- **The join** (2026-09-23): a branch names the component it governs (`41fd0b1`) and the contract
  that measures it (`1677af7`), and `POL-consistency-gate` needs both. The verifier reasons from
  declarations only (`c3dbae9`), is served its probe, and has independence counted (`3782055`).
  It runs in a context that cannot open a file (`81c35fb`).
- **Evidence and its currency**: gate contracts read their latest run (`6822fc9`); a run records
  what it opened (`5e16d92`) and every file carries a stamp (`e138229`). Evidence is bound to the
  content it measured, not the revision (`105e434`).
- **stamp-monitor** (`2a3dea5`) is a read-only view across both ledgers: impact, audit, workflow.
- **Self-application**: both ledgers declare this repository (`81c35fb`). Eight verifier passes
  narrowed the design to convergence (`d54e2a5` to `cd0dbd6`), and the identity model was stated
  once (`f2f9fab` to `a69b43e`).

### damped-plan — 2026-08-17 to 2026-08-31 · the predecessor, retired

This was a planning MCP (`6d8cb13`) whose own version numbers are unrelated to the ones above.

- It had a PreToolUse gate hook, an allowlisted command runner with evidence capture (`96ffa28`)
  and a plan-reviewer agent.
- It had a predictive layer of contracts, posterior checks and the dominant residual (`1c9303d`),
  and a research loop with a human-supervised gate (`cda5b4e`).
- It recorded its own gaps, among them "the missing human-only ultimate goal" (`5cdfb8b`,
  2026-08-21), which `goals.yaml` answers in 0.3.0.
- Retired (`3deaca3`) on 2026-08-31, the day component-belief (`edf8945`) replaced it.
