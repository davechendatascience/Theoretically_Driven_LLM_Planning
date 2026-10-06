# Theoretically Driven LLM Planning

Four MCP servers that hold an LLM agent's engineering work to account, and show it.

| Server | Asks | Grounded in | Ledger |
|---|---|---|---|
| **consistency-belief** | Do the reasons for a design **follow**? | declared axioms, checked by falsification probes | `.consistency/` |
| **component-belief** | Does the built thing **work**? | declared tests, run by the server itself | `.belief/` |
| **stamp-monitor** | Is the evidence still **current and intact**, was the loop followed, and does the tagged code still match its claims? | both ledgers, their stamps, tagged code, and git | reads only |
| **graph-snapshot** | What does the **whole design** look like at this revision? | the three declaration files at one commit, and the proof states | reads only; writes one page |

The first two are paired: a design branch names the component it governs, and cites the contract
that measures it — so neither a proof about nothing nor code nobody justified can hide. The third
watches the joins between them and writes nothing. The fourth draws the joined graph as one page a
person can read.

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
[graph-snapshot](#graph-snapshot-what-does-the-whole-design-look-like) ·
[How the ledgers join](#how-the-ledgers-join) · [Systems-engineering view](#the-systems-engineering-view) ·
[Reference](#reference) · [Changelog](#changelog)

---

## Quick start

The four servers, the two workflow skills and the `consistency-verifier` subagent ship as one
Claude Code plugin, `tdlp`, pinned to a release tag. Add this repository as a marketplace once per
machine, then enable the plugin in each project that uses it:

```bash
claude plugin marketplace add davechendatascience/Theoretically_Driven_LLM_Planning
cd /path/to/your/project
claude plugin install tdlp@davechendatascience-marketplace --scope project   # writes .claude/settings.json -- commit it
```

Enabling it per project keeps the tools out of every other project's context. On another machine,
add the marketplace once and run the same install; a project that lists the plugin in its settings
does not fetch it on its own.

* **Which project.** Every server reads the project Claude Code reports (`${CLAUDE_PROJECT_DIR}`),
  so all four describe the same repository.
* **Which version.** The servers install with `uvx` from the tag `tdlp--v<version>`, so edits here
  reach a project only when a release is tagged and the plugin updated
  (`claude plugin update tdlp@davechendatascience-marketplace`).
* **The first start after an update is slow.**
  - **Why.** The first time each server starts at a new version, `uvx` clones that tag, builds
    the package and installs its dependencies. That took 50 to 100 seconds here, against the 30
    seconds Claude Code gives an MCP server to connect. Every later start takes about 4 seconds.
    Too short a limit leaves the servers failed with `CONNECT_TIMEOUT` for the session.
  - **The fix.** Raise the limit next to `enabledPlugins` in the project's
    `.claude/settings.json`, and restart Claude Code, which reads it at startup. A plugin cannot
    set this for its own servers.

    ```json
    {"enabledPlugins": {"tdlp@davechendatascience-marketplace": true},
     "env": {"MCP_TIMEOUT": "120000"}}
    ```

  - **If it already failed.** Reconnect the servers from `/mcp`, since the build finishes in the
    background.
* **Which Python a test gets.** A declared test's `run:` line runs in the project's environment:
  its `.venv` if it has one, else the PATH Claude Code inherited, never the plugin's own
  interpreter. For anything else, name the interpreter on the run line (`conda run -n env python ...`).
* **Skills.** They load as `/tdlp:component-belief`, `/tdlp:consistency-belief` and
  `/tdlp:adopt-goals` (setting up goals in a project that already uses the harness).

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
uvx --from "git+https://github.com/davechendatascience/Theoretically_Driven_LLM_Planning@tdlp--v0.7.6" tdlp-guard install
```

Then check in with one call, `status(view="goals")`. It shows each goal and interface as met, not
met, insufficient or stale (with the test to run), the agent's proposals on them, and any agent
commit to your goal set since your last. Your goals policy is the default for `decide`,
`diagnose` and `plan`, and an adoption under it needs no approver.

### Setting up goals in a project that already uses TDLP

Ask the agent to run `/tdlp:adopt-goals`. The procedure is the same in every project, and only
step 4 waits on you:

1. **The agent reads what exists.** With no goals in effect, `status(view="goals")` lists the
   candidate measures: contracts an end-to-end test already measures, with their state.
2. **It drafts `goals.yaml` in the working tree** and never commits it. Each goal's measure is
   one of two kinds:
   - **Promoted:** an existing end-to-end contract, moved with its id and test, so its evidence
     comes along. Use this when its test rarely changes, since the test becomes yours.
   - **An acceptance test:** a new one in `acceptance/`, with its own `conftest.py`, so your
     measures share nothing with the agent's tests.

   The goals view checks the draft as if committed and puts nothing in effect.
3. **It installs the guard** in this clone.
4. **You review the draft and commit it yourself.**
5. **It cleans up after your commit.** It removes the promoted ids from `belief.yaml`, tags each
   component with the goal it serves, and runs any measure without evidence. A promoted measure
   reads the state it had before the move, with no re-run.

This repository's own goals went through it (`680e5da`): four goals and one interface, each
measured by the acceptance suite in `acceptance/`.

### Moving a project that installed `tdlp@tdlp`

The marketplace was named `tdlp` until `956a80e`; it is now `davechendatascience-marketplace`.

1. Once per machine: `claude plugin marketplace remove tdlp`, then
   `claude plugin marketplace add davechendatascience/Theoretically_Driven_LLM_Planning`.
2. In the project: `claude plugin install tdlp@davechendatascience-marketplace --scope project`,
   remove `tdlp@tdlp` from `enabledPlugins` in `.claude/settings.json`, and commit it.

### Moving a project that registered the servers by hand

1. Once per machine: `claude plugin marketplace add davechendatascience/Theoretically_Driven_LLM_Planning`.
2. In the project: `claude plugin install tdlp@davechendatascience-marketplace --scope project`, and commit `.claude/settings.json`.
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
7. Restart the session (or `/reload-plugins`). `claude mcp list` should show four
   `plugin:tdlp:*` servers as connected, and `status(view="belief")` your own contracts.

Nothing in the ledgers moves. `belief.yaml`, `consistency.yaml`, `.belief/` and `.consistency/` are
read as they are, and evidence stays current, because staleness is judged by content, not by which
server recorded it.

To work on the harness itself, install it editable and register the servers by hand, all four at
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
    },
    "graph-snapshot": {
      "command": "uv",
      "args": ["--directory", "/path/to/Theoretically_Driven_LLM_Planning", "run", "graph-snapshot-mcp"],
      "env": {"GRAPH_SNAPSHOT_ROOT": "/path/to/your/project"}
    }
  }
}
```

Or run them directly: `PYTHONPATH=src python -m consistency_belief.server` (likewise
`component_belief.server`, `stamp_monitor.server`, `graph_snapshot.server`).

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
* **Cited measurements are pinned.**
  - A branch's citation can carry a pin: `evidence: CTR-x@<pin>`, the claim's digest when the
    contract's rule and tests were read against it.
  - Restating the branch, or a premise upstream, leaves the citation unreviewed until it is
    re-read and re-pinned. The contract alone would go on reading supported for a claim it never
    measured.
  - A contract no branch cites is listed by what it measures: a component's, an interface's or a
    goal's.
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
* **Content stamps.** Before a test's command starts, the runner records the git blob id of every file the evidence could rest on — the components' claimed `code:`, the files the test names on its `run:` line or in `reads:` — and records beside them what the run opened, which the artifacts view reads and staleness does not. Every trial carries the stamp's digest. Content rather than revision, so evidence from uncommitted edits later discarded is stale, an amend or squash-merge that keeps the bytes keeps the evidence, and weakening the test itself stales what it produced. A declared input git ignores — a checkpoint, a dataset, a directory of demonstrations — has no blob at HEAD, so it is stamped by its content digest instead, and the evidence stays current while the file on disk still has it: retrain the checkpoint and the evidence goes stale, restore the same bytes and it counts again. Trials recorded before stamps fall back to `git diff <sw_revision> HEAD`. Design: [`docs/stamp_monitor_mcp_design.md`](docs/stamp_monitor_mcp_design.md).
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
| `links(subject)` | tagged code regions (`# tdlp:begin CODE-...`) and the claims they relate to: each link aligned, or why not, with the header lines to write once reviewed |

```text
src/component_belief/runner.py changed
→ CMP-runner → CTR-surface-intact [stale]
→ BRN-runner-captures (governs CMP-runner, cites CTR-surface-intact)
→ POL-release, POL-consistency-gate
next: run_test TST-server
```

The same reports run from a shell for git hooks, CI, and Claude Code hooks:
`stamp-monitor impact|audit|workflow|links`, exiting 1 on a `[block]` finding from `audit` or
`workflow`, and from `links --strict` on any tag that is broken or needs review.

### Code linked to claims

A region of code names the claim it realizes, and carries two pins: one of its own body, and one
of the claim as it stood when someone read the two together.

```python
# tdlp:begin CODE-runner-exit-code-fallback@3f9a1c2e      <- the body that was reviewed
# tdlp:implements BRN-runner-captures@7c41d0e2            <- the claim, and everything upstream
...
# tdlp:end CODE-runner-exit-code-fallback
```

* **Code edit.** The body pin ignores comments and formatting, so a code edit stales it and a
  formatter run does not.
* **Claim restated.** The claim pin binds to what a verification trial binds to, so restating the
  claim, or any premise upstream of it, stales the link.
* **Persistent.** A stale link is reported at every revision until someone re-reads the region
  and updates the pin, not only in the commit that broke it.
* **Dangling ids.** A `DEF-`/`BRN-` id in a comment or docstring that names nothing is reported.
  So is one outside any region that declares it, since nothing will notice when it rots.
* **Outside the probe.** None of it reaches the verifier. Links are a stamp-monitor report, not
  a consistency-belief view.

Design and adoption steps: [`docs/code_to_theory_tagging_design.md`](docs/code_to_theory_tagging_design.md).

---

## graph-snapshot: what does the whole design look like?

Design in [`docs/graph_snapshot_mcp_design.md`](docs/graph_snapshot_mcp_design.md); declared as
`DEF-snapshot` and `BRN-snapshot-shows-one-revision`.

The other three answer one question each, in text. None of them shows the graph a person reasons
about: every component, the theory it rests on, each claim's proof tree, and the gaps between
`consistency.yaml`, `belief.yaml` and `goals.yaml`. One tool draws it:

| Tool | Does |
|---|---|
| `snapshot(focus)` | resolves HEAD to one commit, reads the declarations committed there and the proof state consistency-belief computes for each lemma and branch, writes `.graph-snapshot/snapshot.html`, and returns the state counts, the issues and the gaps |

* **A snapshot, not a verdict.** It names its revision and the time it was taken, and it does not
  update. Every proof state on it is the one consistency-belief computes for that commit; it adds
  only the edges between the files and the gaps along them. It reads no evidence: contracts appear
  by name, and whether their evidence holds is component-belief's to say.
* **One revision.** It resolves HEAD once and reads every declaration file at that sha, so a commit
  landing mid-read cannot mix two revisions into one page. Uncommitted edits are named, not shown.
* **The page.** An index (components, claims worst first, foundations, issues), the selected
  node's lineage drawn left to right as "rests on", and an inspector with the claim, why it is in
  its state, and its proof tree down to axioms and definitions. The same file opens in a browser
  and publishes as an Artifact; publishing is the person's call, since the page carries their
  design.
* **Issues and gaps.** The issues the loaders and the build report, under their own codes, and the
  gaps only the join shows: an axiom naming no goal, a goal no axiom names, code with no design, an
  interface or goal no branch governs, ground nothing rests on.
* **Writes nothing else.** Its directory carries its own `.gitignore`, so git never lists the page,
  and where a component claims or a test names that directory it writes nothing at all, because
  rewriting a file evidence rests on would stale that evidence.

```text
graph snapshot: embodied_ai @ a50ed9e (2026-10-06) -- consistency.yaml, belief.yaml, goals.yaml as committed there
uncommitted edits, not shown: consistency.yaml
branches 146: 1 refuted, 8 doubted, 83 stale, 2 obligation, 52 proven · lemmas 22: 2 refuted, 9 doubted, 4 stale, 7 proven
components 24: 15 undeclared design, 9 governed · interfaces 12: 12 no design claim · 82 axioms · 20 definitions · 4 goals
issues: 1 PENDING, 50 MISSING_EVIDENCE, 1 UNKNOWN_EVIDENCE, 3 UNLISTED_SUBJECT, 82 AXIOM_WITHOUT_GOAL, ...
page: .../embodied_ai/.graph-snapshot/snapshot.html
```

The same snapshot runs from a shell: `graph-snapshot [--focus ID]`.

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
| Requirements | axioms and definitions in `consistency.yaml`, each axiom naming the goal whose requirement it states (`goal:`) | inspection, at commit; `status(view="coverage")` traces each goal to its axioms |
| Architecture | components and interfaces in `belief.yaml`; lemmas; design claims over an interface (`subject: IFC-...`) or a goal | analysis by probe; set difference for unbacked assumptions |
| Component design | branches, each with premises and `evidence: CTR-...` | analysis by `verify_step`, from the declarations only |
| Build | `code:` claims per component; `status(view="artifacts")` | inspection |
| Component, integration, system test | contracts and tests by `layer`, an interface's contract on the interface itself; `run_test`; `.belief/` | test |
| Risk register | failure modes in `belief.yaml`, each naming the contract and the case that observe it (`observed_by:`, `case:`) | mechanical: `status(view="graph")` lists the ones nothing observes and checks each named case passed in the ledger |
| Traceability | a branch's `subject` and cited contract; `status(view="coverage")` on both sides; tagged code regions pinned to the claims they realize (`stamp-monitor links`) | mechanical |
| Configuration control | declarations from git HEAD; a content stamp on every run, covering declared inputs git ignores by their content on disk; evidence stale once a file it rests on changes; every decision names its revision | mechanical |
| Change control | `audit_change`, STALE on restatement, `amend`, `decide`; `stamp-monitor impact`; the goal guard | mechanical, plus the human's commit of `goals.yaml` |
| Configuration audit | `stamp-monitor audit` and `workflow` | mechanical, read-only |
| Independence | the verifier reads `status(view="probe")` and nothing else; the `consistency-verifier` agent cannot open a file | structural |
| Release gate | `POL-consistency-gate`: each branch proven **and** its cited contract supported; the goals policy in `goals.yaml` | both ledgers, and the human's goals |

Every stage now has a home. This repository applies each to itself: every axiom names its goal,
the goal interface carries a design claim, each component interface has an integration test,
and each of its 35 failure modes names the case that would catch it.

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
  graph_snapshot_mcp_design.md             the design graph at one revision, drawn as one page
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
    project.py                       which project root all four servers read
    diagnose.py / planning.py        bottleneck ranking; round test selection
    decide.py                        policy evaluation and the human approval gate
    stamps.py / views.py / render.py the artifacts view; status views
    store.py                         append-only JSONL ledger in .belief/
  code_links/                        tagged code regions: parser, revision-pinned index, pins, mentions
  graph_snapshot/                    the design graph at one revision (1 tool)
    snapshot.py                      the join, the revision it pins, the gaps
    page.py / page.html              the one self-contained page, and where it may be written
    server.py / cli.py               MCP server; the same snapshot from a shell
  stamp_monitor/                     read-only monitor (4 tools)
    impact.py                        a change traced through both ledgers
    audit.py                         stamp, artifact and ledger integrity
    workflow.py                      conformance patterns in recorded history
    links.py                         tagged code regions against their claims
    server.py / cli.py               MCP server; the same reports from a shell
tools/pytest_trials.py               pytest → trials adapter
tests/                               the suites belief.yaml declares as tests
.claude-plugin/marketplace.json      this repository as the `davechendatascience-marketplace`, listing `tdlp`
plugin/                              the `tdlp` Claude Code plugin
  .claude-plugin/plugin.json         name and version (one version: plugin, marketplace, package, tag)
  .mcp.json                          the four servers, installed with uvx from tag tdlp--v<version>
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
14. As a plugin, every server reads the project Claude Code reports, installs from its own version's tag, and never lends a test the plugin's own interpreter.
15. An agent-trailered commit to the goal set is refused and one the human types passes; an adoption under the goals policy needs no approver until the agent touches the goal set.
16. A declared input git ignores is judged by its content on disk: changed or missing, its evidence is stale; the same bytes again, current.
17. A measure promoted from `belief.yaml` into `goals.yaml` keeps its evidence, while both files declare it and after; a draft `goals.yaml` is checked without taking effect.
18. A snapshot shows the declarations of the one revision it names and the proof states the consistency server computes over them, lists the join's gaps, reads no evidence, and writes nothing but its page, which git does not see and no declaration names.
19. A tagged code region reads aligned only while its body and its claim, with everything upstream, are as they were pinned; any other link, and any id named in a comment that resolves to nothing, is reported at every revision until fixed; and none of it moves a proof state or reaches the probe.

---

## Changelog

Newest first. Versions are the `tdlp` plugin's, released as git tags `tdlp--v<version>`. Before
0.2.0 the harness was installed by hand at version 0.1.0 and never tagged. The ids point at the
change itself; an `evidence:` commit recording the suites' runs follows each.

### 0.7.6 — 2026-10-07 · status views in seconds, and the cited-measurement report sorted

Reported from embodied_ai on 0.7.5.

- **`status(view="coverage")` and `status(view="goals")` took over 120 seconds there.** Profiling
  disproved the report's guesses: the DAG rebuild, claim pins and the 3,617-slice contract were all
  cheap. The cost was staleness.
  - **Every trial was judged on its own.** Each one matched every claimed `code:` entry against
    every tracked file, about 25 million `fnmatch` calls on this repository. On Windows each of
    those also paid `normcase` twice.
  - **The fixes.** A run's trials share a stamp, so a run is now judged once. The files a set of
    entries claims at HEAD are matched once. `normcase` is remembered, so a glob reads exactly as
    `fnmatch` reads it.
  - **The revision fallback** for trials from before stamps diffed the ledger directories with
    rename detection on. It no longer does.
  - **The result here:** coverage went from 42.5 s to 3.8 s, goals to 3.1 s. Every slice's state,
    count and stale reason is identical: 21 slices, 3,196 stale trials and 154 reasons compared
    before and after.
- **Contracts no branch cites are sorted by what they measure:** a component's first, then an
  interface's, then a goal's measure, which the goal's outcome already explains. One with no
  evidence is marked `(no evidence yet)` rather than listed as measured. There, 27 had sat in one
  list, goal measures and unmeasured contracts among them.
- **graph-snapshot shows the cited measurements.**
  - Each branch's "Cites the measures" gives each contract's review state.
  - The Issues tab lists unreviewed cited measurements in their own group, and every contract no
    design cites, marked by what it measures.
  - The review state is judged from the declarations at the snapshot's commit, so the snapshot
    still reads no evidence. `DEF-snapshot` was restated to say so (`355b0ee`), and
    `BRN-snapshot-shows-one-revision` was re-proven against it.

### 0.7.5 — 2026-10-06 · a cited measurement is reviewed only while its claim stands

- **A citation can carry a pin.** A branch cites the contract that measures it, and nothing held
  the two together. A branch restated to claim more kept citing the contract that measured the old
  claim. That contract read supported, so once the branch was re-proven the release gate passed,
  and no one was asked whether the contract still measured the claim.
  - **The pin.** Write `evidence: CTR-x@<pin>`, where the pin is the branch's claim digest (the
    one a code link's claim pin records) at the moment the contract's rule and tests were read
    against the claim.
  - **What breaks it.** Restating the branch, or anything it rests on, leaves the citation
    unreviewed. The coverage view prints the pin to write, `audit_change` lists the citations a
    restatement will leave unreviewed, and `stamp-monitor audit` warns `MEASUREMENT_NOT_REVIEWED`.
  - **What it costs.** A pin lives in the derivation rule, so writing one restates nothing and
    sets no trial aside.
  - It is reported, not gated: `decide` is unchanged.
- **A contract no branch cites is listed** as "measured, cited by no design" in the coverage view,
  and as `UNCITED_CONTRACT` in `audit`. Here that is the four interface contracts and the four
  goal measures, the same subjects the snapshot lists with no design claim.
- Design first: `AXM-cited-measurements-reviewed`, `DEF-cited-measurement` and
  `BRN-cited-measurements-reviewed-while-the-claim-stands` (`87a7e8a`). "Cited measurement", not
  "citation", because `DEF-premise-graph` already calls a premise a citation.
- Two suggestions from an agent adopting the harness, taken together. They are the two
  directions of one join.

### 0.7.4 — 2026-10-06 · tests in parallel, and "aligned" never read as "works"

- **`run_test` calls made together run at once.** By default, half the cores run at once;
  `BELIEF_MAX_RUNS` sets the number. Until now one lock covered the whole run. Only three things
  need to be one at a time, and only those are now:
  - taking a run id: the run makes its artifact directory with `exist_ok=False`, so two runs never
    share an id, even from two server processes;
  - appending to the ledger, with its evidence ids;
  - installing the read hook, which is written atomically and only when it changed, so a run
    starting mid-write cannot import half a hook and record no reads.

  The digest cache is replaced whole rather than written in place. Two concurrent runs are shown
  to overlap: each waits for the other to start. The suites here use 22 cores.
- **Each link shows the measurement its claim cites:** `evidence: CTR-x [stale]` beside every link
  in `stamp-monitor links`. "Aligned" says code was read against a claim; whether it still works
  is the contract's to say. Two observations follow:
  - `LINKED_EVIDENCE_NOT_SUPPORTED`: a claim whose regions read aligned while its cited evidence
    is not supported.
  - `UNSCOPED_ENVIRONMENT`: a test behind linked code that names no lockfile, so upgrading a
    dependency under unchanged code stales nothing.
- **This repository's suites now read `uv.lock`**, so a dependency bump stales their evidence.
  The acceptance suites' `reads:` are in `goals.yaml`, which is the human's to change.

### 0.7.3 — 2026-10-06 · code links, verified and usable at scale

- **`links(subject=...)` works on the cases an adopting agent hit.** These were reported from
  embodied_ai on 0.7.2 (`dccf26c`).
  - **A scanned file with no region** read as "not a scanned path". It now prints `0 region(s)`
    and its diagnostics.
  - **A region only in the working tree** could not be found by its id. A subject (region id,
    claim, or path) now narrows the uncommitted section too, and that section prints the pins to
    write.
  - **The full report outgrew one tool response** on a large project: 121 KB of 353 untracked
    mentions and 143 unlinked branches, with the pins printed last. The uncommitted section now
    comes first. Past 40 lines, the rest of a severity are counted per file instead of listed.
- **An unpinned `motivated-by` reads `explanatory`, never `aligned`** (`91946d5`). It asserts no
  correspondence, so it is not a code link.
- **The code-links theory was verified.** The verifier refuted the first wording of
  `BRN-links-stale-when-either-side-moves` (TRL-0307..0309). Its claim-pin clause named an event
  where it should have compared states, and it had four entailment gaps. The branch, its axiom
  and its two definitions were restated (`70f9497`) and proven (TRL-0310..0312).
- **`DEF-snapshot` says what a snapshot shows of code links** (`455a196`): each node's regions
  with their link state, and the scan's broken tags and unaligned links.
  `BRN-snapshot-shows-one-revision` was re-verified against it.
- `code_links`' own docstrings named example ids that resolve to nothing, and its own scan
  reported them. They are placeholders now (`da35623`).

### 0.7.2 — 2026-10-06 · code linked to the claims it realizes

- **Tagged code regions** (`code_links`, a library the servers share, not a fifth server).
  - `# tdlp:begin CODE-<name>` / `# tdlp:implements BRN-<id>` / `# tdlp:end CODE-<name>` mark
    a region and the node it realizes (also `uses`, `checks`, `motivated-by`). Targets may be
    branches, lemmas, definitions or axioms.
  - Each tag carries pins. The body pin is set by the code tokens; comments and layout do not
    move it. The claim pin is set by the claim's fingerprint and everything upstream, which is
    what a trial binds to.
  - A link whose pins no longer match is reported at every revision until it is re-read and
    re-pinned, with the revision to diff against or the nodes restated since.
  - Ids named in comments and docstrings are checked: one that names nothing is an error, and
    one no region tracks is listed.
- **stamp-monitor gets `links`**, its fourth tool, plus `stamp-monitor links [--strict]`.
  `audit` reports broken and stale links as warnings, never blocks. `impact` lists what the range
  did to tagged regions beside the chain, never on it. consistency-belief gets no view: the
  verifier holds `status`. `audit_change` names, by id only, the regions a restatement unpins.
- **graph-snapshot lists each claim's regions** with their link state at the snapshot's commit,
  and broken or stale links in its Issues tab. Regions are never nodes or edges.
- **Tag and pin in one commit.** `stamp-monitor links` prints the pins an uncommitted region
  would need, so an untagged region goes to aligned in a single reviewed commit.
- **The servers no longer time out after an update.** On 0.7.0 three of the four failed with
  `CONNECT_TIMEOUT`. The first start at a new tag clones, builds and installs, which took 50 to 100
  seconds here, against Claude Code's 30-second connect limit; graph-snapshot connected only on a
  retry, once the build had finished. A plugin cannot raise the limit, so this project sets
  `MCP_TIMEOUT` to 120 seconds in `.claude/settings.json`, and the quick start says to do the
  same.
- **Fixed, from a review of the harness:**
  - **Compatibility groups.** A refuted compatibility group in a bucket no longer hides behind a
    supported one: the policy read one state per bucket, and the last slice overwrote the rest.
  - **Unknown policy id.** consistency-belief `decide` refuses a policy id it does not declare,
    instead of deciding under the first one.
  - **Goals policy.** It is no longer approved by the human's commit when it reads something the
    agent declares: a prior on a goal measure, or `mandatory:` flags through `safety_gates`.
  - **Goal guard and record.** A file renamed out of a goal test's directory is refused by the
    guard and found by the record.
  - **Malformed entries.** One stray entry in `belief.yaml`, `goals.yaml` or `consistency.yaml`
    (a bare id, a mapping with no id, a string criterion) is reported as `MALFORMED`. It no
    longer raises in every tool.
  - **Design-ledger audit.** `audit` checks `.consistency/` for duplicate trial ids and for
    amendments and decisions citing trials that do not exist.
  - **Policy ids in both files.** `impact` keeps what each ledger's policy gates when
    `belief.yaml` and `consistency.yaml` declare the same policy id.
  - **Unstamped evidence.** It reads a `code:` directory as a directory.
  - **Test version check.** A changed test stales its evidence even when no staleness reader is
    passed.

### 0.7.0 — 2026-10-06 · the whole design, drawn at one revision

- **graph-snapshot, a fourth server** (`5878314`), with one tool, `snapshot(focus)`. It joins
  `consistency.yaml`, `belief.yaml` and `goals.yaml` at one commit, with the proof state
  consistency-belief computes for each lemma and branch, and writes one self-contained page
  (`.graph-snapshot/snapshot.html`). The page has:
  - an index of components, claims worst first, foundations and issues;
  - the selected node's lineage, drawn left to right as "rests on";
  - an inspector with the full claim, why it is in its state, and its proof tree down to axioms
    and definitions.

  The same file opens in a browser or publishes as an Artifact. Design:
  [`docs/graph_snapshot_mcp_design.md`](docs/graph_snapshot_mcp_design.md).
- **It reads no evidence, so it is fast.** It takes 1.2 s on embodied_ai's 310-node graph.
  Contracts appear by name only. A first prototype that also read contract states took 12½ minutes
  there; see [Measured cost](docs/graph_snapshot_mcp_design.md#measured-cost) for the
  component-belief cost behind that.
- **One revision.** Both declaration loaders and `Context.build` take a `revision`, `HEAD` by
  default, so the servers are unchanged. A snapshot resolves HEAD once and reads every file at
  that sha. During the prototype's slow run, embodied_ai's HEAD moved mid-read, which is what
  showed this was needed.
- **Issues and gaps.** The page lists the issues both loaders and the premise-graph build already
  report, under their own codes. It also lists the gaps only the join shows: an axiom naming no
  goal, a goal no axiom names, code with no declared design, an interface or goal no branch
  governs, and an axiom or definition nothing rests on. In embodied_ai none of the 82 axioms names
  a goal.
- **The theory came first.** `DEF-snapshot` and `BRN-snapshot-shows-one-revision` were committed
  (`321906d`) before the code, as a new definition rather than a widened `DEF-report`, so nothing
  already proven went stale. The first verifier pass refuted the branch: the definition limited
  which declarations a snapshot shows but not which proposals. Both were restated (`745b545`)
  before the code was committed, and a second pass proved the branch with no gaps (17 of 17
  claims proven). That proof rests on one actor's judgement, so treat it as provisional.
- **Your goal set.** `acceptance/test_any_project.py` expects three servers, so
  `CTR-runs-in-any-project` reads refuted until you decide whether a fourth belongs there. The
  agent proposed the one-line change in a note on `GOL-any-project` and did not make it.

### 0.6.2 — 2026-10-03 · the marketplace has its own name

- **The marketplace is `davechendatascience-marketplace`** (`956a80e`). It was named `tdlp`, the
  same as the plugin, so the install read `tdlp@tdlp`. It now reads
  `tdlp@davechendatascience-marketplace`. To move a project that installed `tdlp@tdlp`, follow
  [Moving a project that installed `tdlp@tdlp`](#moving-a-project-that-installed-tdlptdlp)
  (`037ebe9`). The servers, skills and verifier have not changed since 0.6.1.
- `uv.lock` now records the package's version. It read 0.1.0 through 0.6.1.

### 0.6.1 — 2026-10-01 · the audit sees what was set aside

- **An audit finding on evidence nothing counts any more stops blocking.** The remedy for an
  artifact that cannot be audited is to set its records aside with `amend`. The audit read raw
  trials and never folded amendments, so it went on blocking after every record was quarantined.
  A missing or mismatched artifact, or an untrusted stamp, now blocks while any record resting on
  it still counts. Once none does, it is reported as information naming the amendment's reason;
  it is never dropped. An unhashed import whose records are all set aside moves from a warning to
  one information line. In embodied_ai: four blocks became information, and 157 warnings became
  112 plus one line for 45 runs set aside.
- The design came first: `AXM-damage-blocks-while-it-counts`, `DEF-set-aside` (which states what
  the model already did -- a set-aside record moves no belief) and `BRN-audit-blocks-what-counts`.

### 0.6.0 — 2026-10-01 · every stage of the V has a home

- **Row 9 of the systems-engineering mapping.**
  - A design claim may govern an interface (`subject: IFC-...`, from `belief.yaml` or
    `goals.yaml`) or a goal, as well as a component.
  - An axiom names the goal whose requirement it states (`goal:`). `goal:` is not part of the
    fingerprint, so tracing an axiom restates nothing.
  - `status(view="coverage")` lists interfaces and goals with and without a design claim, and
    traces each goal to its axioms.
  - A failure mode names the contract and the case that observe it (`observed_by:`, `case:`).
    `status(view="graph")` lists those nothing observes and checks each named case passed in its
    latest trial.
- **A trial made before fingerprints is judged by the build it was made against.** Until now it
  stayed current through any restatement upstream, which `AXM-blast-radius-invalidation` forbids.
  It now counts as having recorded the fingerprints its nodes had then: `consistency.yaml` at the
  last commit before it, plus the proposals staged by then. In a project with such trials (three
  on this machine hold 104), a node whose premises were restated since goes STALE and needs
  re-verifying.
- **The configuration audit stops reporting present artifacts.** A run recorded on Windows wrote
  its artifact path with backslashes and hashed CRLF bytes, which git stores, and Linux checks
  out, as LF. 43 artifacts here read as missing, then as tampered. Both separators and both
  line-ending directions now audit as what they are, and the runner records POSIX paths.
- **A long `run_test` stays alive.** A stdio tool call that sends nothing for 30 minutes is
  aborted by the client's idle timeout, and the server sent nothing while a test ran. The test
  now runs in a worker thread, and the tool reports progress every minute: a progress
  notification when the client sent a progress token, and a log message either way. Runs are
  still one at a time (until 0.7.4). How long a test may run is its own `timeout_s` (default 900 seconds),
  declared with the test.
- **Evidence from an earlier version of its test is stale** (design rule 3.5). A test's version
  is its run line and metrics. It was recorded on every trial and read by nothing, so a changed
  run line pooled old and new procedures, and a gate read its latest run whatever the version.
  An edit that left the procedure the same is mapped explicitly with `same_as: [<version>]` on the
  test. An import that names only the test id records the declared version.
- **A value cut at an unquoted comma is reported (`SPLIT_VALUE`).** `{id: FM-x, observable: a, b}`
  reads as "a" plus a stray key. Four failure modes and three component notes here had been cut
  that way.
- **The design graph was re-verified until it held.** Eight verifier passes, each judged from the
  served probes alone, found:
  - one stale doubt (`LMA-blast-radius-propagation`);
  - two refuted new designs (the goal guard and the plugin);
  - claims wider than their premises;
  - "when" where "exactly when" was meant;
  - three places where the theory and the code disagreed. `AXM-no-belief-write-path` is now
    scoped to the declarations in effect. `BRN-runner-captures` says the runner takes `passed`
    from the exit code. `DEF-belief-eligible` agrees with that.

  Each fix was audited before it was committed. The code commit followed the declarations.
- This repository applies all of it to itself:
  - an integration test for each of its four component interfaces;
  - every failure mode traced to the case that catches it, with five new tests where none did;
  - every axiom traced to a goal;
  - design claims for the goal guard, the plugin and the goal interface.

### 0.5.2 — 2026-10-01 · what an adopting agent tripped on

- **`run_test` no longer crashes on a directory at `$OUT`.** It hashed `$OUT` as a file, so a
  measure in several parts that made it a directory recorded nothing. Each way `$OUT` can be
  wrong falls back to one trial built from the exit code, and the reply names which it was:
  absent, a directory, not JSON, or a shape it does not accept.
- **The goals view names a guard from an earlier release.** Upgrading the plugin leaves the
  commit-msg hook on the release that installed it, and the view said "installed" either way.
  Running the install command again replaces it; `--force` is only for a hook that is not the
  guard.
- **`audit_change` says whether anything restates.** A trial vouches for a node's statement and
  premises, not its derivation rule. Given the proposal, the audit says whether the node's own
  trials are kept and whether its dependents go stale. Without one, it says what a restatement
  would cost, and that a change only to a citation costs nothing.
- **`ingest` says why it refuses an artifact:** a URL, a missing path, a directory, or several
  paths in one string. It has refused all four since 0.2.0, but only as "not a file".
- **Skills.**
  - component-belief has a new section, *Declaring contracts and tests*: what clears a target,
    gates, compatibility keys, the `$OUT` format, what evidence is bound to, and keeping the
    read hook through a wrapper script.
  - adopt-goals adds what shapes a draft: a goal reads its worst slice, and which files become
    the human's.
  - consistency-belief: re-citing a contract restates nothing.
- The staleness docs no longer say that a file the run opened makes its evidence stale. The stamp
  records it, but nothing watches it.

### 0.5.1 — 2026-10-01 · the artifacts view reads a run line the way staleness does

- **`status(view="artifacts")`** looked for a run line's files only under the top-level
  directories some component's `code:` mentions. Staleness matches every token against every
  tracked file. So a script elsewhere, such as `bash acceptance/replay_labels.sh $OUT`, carried
  live evidence while the view gave it no `named`, `invoked` or `supports` stamp. Bash runs it, so
  the read hook never saw it opened either, and the view listed it as a prune candidate. Both now
  use one extractor, `named_paths`, so they cannot disagree.
- A run line that starts `cd dir && …` names everything under `dir`. Staleness always read it
  that way; the view now keeps those files too.

### 0.5.0 — 2026-10-01 · setting up goals in any project that uses TDLP

- **`/tdlp:adopt-goals`**, a plugin skill, walks the agent through putting goals into a project
  that already uses the harness. It drafts, checks and installs the guard; the human commits;
  then the agent cleans up. Only the human's commit waits on the human.
- **The goals view**, with no goals in effect, lists the candidate measures: contracts an
  end-to-end test already measures. It also checks a `goals.yaml` in the working tree as a draft
  and puts nothing in effect, so the agent can validate what it will hand over without
  committing it.
- **A measure promoted** from `belief.yaml` into `goals.yaml`, with its id and test, is shown to
  keep its evidence ids and state before, during and after the move, with no re-run.
- **This repository adopted its own goals** (`680e5da`, committed by the human): honest evidence,
  sound designs, goals that stay the human's, and running in any project, plus the interface
  from evidence to designs. Each is measured by the acceptance suite in `acceptance/`.

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
