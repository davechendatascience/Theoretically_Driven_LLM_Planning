# TDLP guide

The full manual: installing and moving projects, the principles, every tool of every server, how
the ledgers join, and the systems-engineering mapping. The [README](../README.md) is the short
version; release notes are in [CHANGELOG.md](../CHANGELOG.md).

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
[Reference](#reference)

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
uvx --from "git+https://github.com/davechendatascience/Theoretically_Driven_LLM_Planning@tdlp--v0.9.0" tdlp-guard install
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
| `consistency.yaml` | axioms, definitions, lemmas, branches, policies, and the sources they reference | `status(view="probe")` → `verify_step(...)` → `status(view="tree")` |
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
| Lean service checked a theorem | `consistency_belief.certify` | **none on a proof state** — served to the verifier beside the statements |
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

* A **proof trial** records its target's fingerprint (statement and premises) and the statement of
  each premise it cites: what its probe showed. Restating a node sets its trials aside, and so does
  restating the statement of a premise it cites. Nothing further upstream does, because the step
  never read it.
* A **test run** writes a content stamp: the git blob id of every file its evidence rests on, as the
  working tree actually stood. Once one of those files differs at HEAD, its trials are `stale`.

* A **review** is bound to what was reviewed. `review()` records, in the ledger, that someone
  read a code region against the claim it realizes, or a branch's cited contract against the
  claim, at one commit, with the digests of both there. No pin is written into the source. When
  either side moves, the region or citation reads unreviewed, at every revision, until someone
  re-reads it and records a new review.

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

Rules in [`docs/consistency_belief_mcp_design_rules.md`](consistency_belief_mcp_design_rules.md);
declarations in [`consistency.yaml`](../consistency.yaml).

### Concepts

* **Axiomatic grounding.** Lemmas and branches must trace back to declared axioms (`AXM-`) and definitions; anything else is `UNGROUNDED`.
* **Mechanical DAG kernel.** Acyclicity is enforced before any semantic reasoning; a cycle ($A \implies B \implies A$) is rejected with its trace.
* **Open obligations (`sorry`).** A lemma or branch with fewer than $n_{\min}$ independent trials is an open `OBLIGATION`.
* **Only a counterexample refutes.** A probe with outcome `falsified` makes a node `REFUTED`. A `gap` — a missing premise, an unproven step — leaves it unproven, counts against consensus (so the node reads `DOUBTED` once it has enough trials), and is listed under *Entailment Gaps* in `status(view="contradictions")`.
* **A proof rests on its steps, like Lean's `sorry`.**
  - A trial vouches for one step: a claim from the statements of the premises it cites.
  - A lemma or branch is `PROVEN` only when its own step and every step beneath it are verified.
    One whose own step is verified over a step that is not reads `CONDITIONAL`. It keeps its
    trials, names what it waits on (`[CONDITIONAL 3/3 · rests on REFUTED BRN-x]`), and no policy
    requiring `proven` passes it.
  - Restating a node sets aside only the steps that read it: the node, and the nodes citing it
    when its statement changed. Everything further down waits, `CONDITIONAL`, and is proven again
    with no new trial once those steps are. A premise restated in its premises alone, with its
    statement kept, leaves the steps citing it untouched.
  - A premise proven again at a *new* statement discharges nothing: the steps verified against
    the old one are `STALE` until re-verified. `audit_change` says which steps need a verifier
    pass and which only wait.
  - A revised claim keeps its id rather than needing a new one to escape old verdicts.
* **Staged proposals.** `propose_branch` stages a branch that persists, can be verified, and can be cited at once; it shows as `· STAGED`. It supports `decide()` only once declared at HEAD, and trials recorded while staged carry over if the declared statement is the same.
* **Cited measurements are reviewed.**
  - After reading a contract's rule and tests against the branch that cites it, record
    `review("BRN-x", target="CTR-y", note=...)`. It names the commit and the claim's digest there.
  - Restating the branch, or a premise upstream, leaves the citation unreviewed until it is
    re-read and reviewed again. The contract alone would go on reading supported for a claim it
    never measured.
  - A pin written in the derivation rule before reviews were records, `evidence: CTR-x@<pin>`,
    still counts as its review.
  - A contract no branch cites is listed by what it measures: a component's, an interface's or a
    goal's.
* **Sources are referenced, never relied on.**
  - Any declaration may name the works it came from, the way a paper cites its references:
    list each under `sources:` and name it in the node's `references:`.

    ```yaml
    sources:
      - id: SRC-lipman2023-flow-matching
        title: Flow Matching for Generative Modeling
        authors: [Lipman, Chen, Ben-Hamu, Nickel, Le]
        year: 2023
        arxiv: "2210.02747"            # or doi, isbn, url
    axioms:
      - id: AXM-flow-matching-recovers-the-conditional-law
        references: [{source: SRC-lipman2023-flow-matching, at: "<theorem, section or page>"}]
    ```
  - Referencing is optional. A reference is for the reader: it is not a premise, not part of a
    fingerprint, and never in a probe, so citing a famous result makes no claim count and adding
    one restates nothing.
  - Nothing checks that a source says what the node states.
  - `status(view="sources")` is the reference list. A reference naming no declared source, and a
    source nothing references, are reported.
* **A Lean certificate is evidence beside the statements (optional).**
  - Before a verifier pass, the author may prove a lemma or branch in Lean:
    `certify("LMA-x", declaration=..., expected_statement=..., files=[...], url=...)` sends the
    committed Lean source to a Lean service, which checks it once, and keeps the answer whole in
    the ledger. Services: `lean-prover` (a Lean prover server, the default) and `axle` (Axiom's
    AXLE).
  - The verifier still reads the statements. The probe adds, beside them, the Lean statement that
    was checked and what each axiom standing for a premise states (`premise_axioms`) — never the
    proof or the file. Whether the Lean statement says what the claim says is the verifier's to
    judge; a stand-in axiom that says more than its premise is a gap.
  - A certificate moves no proof state. Like a trial it is bound to its node's fingerprint and the
    statements of the premises it cites, so a restatement sets it aside. A policy criterion may
    require one: `{target: BRN-x, require: proven, formal: certified}`.
  - The service's address is given per call or in the environment, and keys stay in
    `LEAN_PROVER_API_KEY` / `AXLE_API_KEY` or an untracked `.lean-services.yaml`; the ledger
    records neither. `status(view="certificates")` lists every certificate and what it reads as now.
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

### Tools (ten)

| Tool | Does |
|---|---|
| `status` | 12 views: `tree`, `branches`, `axioms`, `sources`, `obligations`, `probe`, `contradictions`, `coverage`, `audit`, `reviews`, `certificates`, `cycle`. `coverage` also gives each cited measurement's review state and the review to record, and lists the contracts no branch cites by what they measure; `sources` is the reference list, each source with the nodes that reference it |
| `propose_branch` | stages a branch or lemma; checks acyclicity and premises; warns when a claim names a file, class or call instead of what must hold of any implementation |
| `verify_step` | records one pass of falsification trials, each bound to the statement it verified |
| `amend` | reclassifies a mis-recorded trial (`invalid`, `quarantined`, `superseded`) by appending; the original and the reason stay |
| `withdraw` | retires a staged proposal; refused for a declaration or anything a declared node cites |
| `audit_change` | computes the blast radius of changing an axiom or lemma -- the steps citing it, which need a verifier pass, apart from those further down, which only wait -- and records the audit so impact, approval and re-verification form one chain. It also names, by id, the tagged code regions and cited measurements the change would leave unreviewed |
| `note` | qualitative annotation; zero weight |
| `certify` | optional, before a verifier pass: sends a lemma's or branch's committed Lean proof to a Lean service (`lean-prover` or `axle`) and keeps the answer whole as a certificate, which the probe serves beside the statements while it certifies the node; moves no proof state |
| `review` | records that you read a code region, or a cited contract, against its claim at HEAD: the commit, the digests there, aligned or not aligned, and a note. Refused for uncommitted code or claims; a ledger record, never a line in the source |
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

Rules in [`docs/component_belief_mcp_design_rules.md`](component_belief_mcp_design_rules.md),
design in [`docs/component_belief_mcp_design.md`](component_belief_mcp_design.md);
declarations in [`belief.yaml`](../belief.yaml).

### Concepts

* **Declared contracts.** A contract states what a component or interface must do, sliced by operating condition and compatibility key; trials differing on a compatibility key are never pooled.
* **Trial-level evidence.** Each test case is a trial (`tools/pytest_trials.py` adapts any pytest suite), stored in `.belief/` with its artifact and hash.
* **Gates and rates.** A deterministic procedure — a pytest suite — is `kind: gate`: read from its latest run, every case passing is `supported`, any failing is `refuted`, with no interval and no `n_min` for reruns to climb. A stochastic process is a rate contract with a Beta-Binomial interval, and sparse data is `insufficient_evidence`.
* **Diagnosis before optimisation.** Bottlenecks are ranked by decision relevance, never by lowest score, and a component no test observes is reported as a coverage limit rather than blamed.
* **Components claim their code.** `code:` lists the files a component owns. A file no component claims is unowned; a claimed path that no longer exists is `MISSING_CODE_PATH`; a component with no `code:` is *planned*.
* **Content stamps.** Before a test's command starts, the runner records the git blob id of every file the evidence could rest on — the components' claimed `code:`, the files the test names on its `run:` line or in `reads:` — and records beside them what the run opened, which the artifacts view reads and staleness does not. Every trial carries the stamp's digest. Content rather than revision, so evidence from uncommitted edits later discarded is stale, an amend or squash-merge that keeps the bytes keeps the evidence, and weakening the test itself stales what it produced. A declared input git ignores — a checkpoint, a dataset, a directory of demonstrations — has no blob at HEAD, so it is stamped by its content digest instead, and the evidence stays current while the file on disk still has it: retrain the checkpoint and the evidence goes stale, restore the same bytes and it counts again. Trials recorded before stamps fall back to `git diff <sw_revision> HEAD`. Design: [`docs/stamp_monitor_mcp_design.md`](stamp_monitor_mcp_design.md).
* **Runs in parallel.** `run_test` calls made together run at once, up to `BELIEF_MAX_RUNS`
  (by default half the cores). Each run reserves its own id and artifact directory, and only
  appends to the ledger one at a time. To run independent suites side by side, make the calls in
  one turn.
* **Environment scope.** A dependency upgrade under unchanged code stales evidence only if the
  test declares the lockfile, so list `uv.lock` (or your requirements file) in `reads:`. This
  repository's suites do. `stamp-monitor links` names a test behind linked code that does not
  (`UNSCOPED_ENVIRONMENT`).
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
| `run_test` | runs a declared test, captures its artifact and stamp, records its trials; calls made together run at once |
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

Design in [`docs/stamp_monitor_mcp_design.md`](stamp_monitor_mcp_design.md).

Each belief server sees its own ledger. The monitor sees across them — and writes nothing. It takes
no registrations: stamps are made by the runner that ran the command, because a monitor that
accepted them would be an agent-writable path into the evidence. Freshness is a library
(`component_belief/staleness.py`) both belief servers already import, so "stale" has one definition.

| Tool | Answers |
|---|---|
| `impact(base, worktree)` | changed path → component / test → contract (state at HEAD) → design branch → policy, and which tests to re-run. What the range did to tagged code regions is listed beside the chain, never on it |
| `audit()` | every ledger line in both ledgers parses; ids are unique; amendments and decisions cite records that exist; stamps and artifacts still match their digests; declarations are committed. It also warns on code links that are broken or need review (`LINK_*`) and on cited measurements not reviewed, and lists the contracts no branch cites |
| `workflow()` | reclassifications that remove only adverse results; adoptions with no human approver; decisions on dirty-tree evidence; adoptions whose evidence has since gone stale |
| `links(subject)` | tagged code regions (`# tdlp:begin CODE-...`) and the claims they relate to: each link aligned, or why not, beside the state of the evidence its claim cites, with the header lines to write once reviewed. `subject` narrows to a region, a claim or a path, uncommitted regions included |

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

A region of code names the claim it realizes, usually in the docstring it already has. A
review, recorded in the ledger, says someone read the two together at one commit.

```python
def load_grid(path):
    """The map's free cells.

    Implements: BRN-clearance-grid-clears-the-footprint
    Uses: AXM-behavior-trav-maps
    """
```

The docstring makes the function a region (classes and modules too; they nest). A stretch that
isn't a whole function can still be marked with `# tdlp:begin CODE-<name>` / `# tdlp:implements
BRN-<id>` / `# tdlp:end CODE-<name>`. After committing the code, read it against its claim and
record `review("CODE-<id>", note="what you checked")` in consistency-belief.

* **Code edit.** A review records the body's digest, which ignores comments, docstrings and
  formatting, so a code edit stales it and documenting the code does not.
* **Claim restated.** A review records the claim's digest: its statement and the statements of
  the premises it cites, which is what a verification trial binds to. Restating either stales the
  link; a restatement further upstream does not.
* **Reviews travel with the code.** They live in `.consistency/reviews.yaml`, one per line,
  append-only. Commit it even where the event ledgers stay local; `review()` and `links` say when
  git ignores it, and give the `.gitignore` line to add. `status(view="reviews")` lists every review.
* **Moved code keeps its review.** A reviewed function moved to another file, unchanged, carries
  its review to its new region (`carried from`).
* **Which review decides.** `links` says, per link, whether its ledger review or its header pin
  sets its state, and shows a header pin beside the old-grammar digest it is compared with.
* **Persistent.** A stale link is reported at every revision until someone re-reads the region
  and records a new review, not only in the commit that broke it.
* **The review bundle.** For each link to review, `stamp-monitor links` shows the claim as it
  stands, a word diff of what moved in it since the last review, the code diff since (the
  region's lines only), and the last reviewer's note.
* **A failed review is a finding.** `review(..., outcome="not_aligned", note=...)` makes the link
  read `review failed` until the code or the claim changes and someone reviews it again.
* **Old pins still count.** Header pins written before reviews were records, `# tdlp:begin
  CODE-x@3f9a1c2e`, align a link that has no review in the ledger, under the old body digest,
  which kept docstrings. So upgrading stales nothing.
* **Dangling ids.** A `DEF-`/`BRN-` id in a comment or docstring that names nothing is reported.
  So is one outside any region that declares it, since nothing will notice when it rots.
* **Aligned is not "works".** Each link is printed beside the state of the contract its claim
  cites. A region reads aligned while its evidence is stale, and that combination is flagged
  (`LINKED_EVIDENCE_NOT_SUPPORTED`).
* **Commit, then review.** A review names the commit it read, so it is refused while the region's
  file or its claim has uncommitted edits. `links --strict` exits 1 on any broken tag or link
  needing review, for CI or a hook.
* **Outside the probe.** None of it reaches the verifier. Links are a stamp-monitor report, not
  a consistency-belief view.

Design and adoption steps: [`docs/code_to_theory_tagging_design.md`](code_to_theory_tagging_design.md).

---

## graph-snapshot: what does the whole design look like?

Design in [`docs/graph_snapshot_mcp_design.md`](graph_snapshot_mcp_design.md); declared as
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
* **Issues and gaps.** It lists the issues the loaders and the build report, under their own
  codes, and the gaps only the join shows:
  - an axiom naming no goal, or a goal no axiom names;
  - code with no design, or an interface or goal no branch governs;
  - ground nothing rests on;
  - a cited measurement not reviewed against its claim;
  - a contract no branch cites, marked by what it measures.

  Broken code tags and unaligned links appear too.
* **Beside each node.** Each branch shows its cited measurements with their review state. Each
  claim, axiom and definition shows its tagged code regions with their link state. Both are judged
  from the declarations and the code at that commit, so the snapshot still reads no evidence.
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

A contract can read supported for a claim it never measured: the claim was restated after its
test was written. So a citation is reviewed: `review("BRN-x", target="CTR-motion-clear")` records
the claim's digest when the contract's rule and tests were read against it. The coverage view
reports each cited measurement as `reviewed`, `unreviewed`, `review failed` or `not reviewed`, and
names the review to record. It also
lists every contract no branch cites, sorted by what it measures: a component's (decide why it is
measured), an interface's, or a goal's (its outcome says why). One with no evidence yet is marked.

The release gate spans both: `POL-consistency-gate` requires each branch **proven** and its cited
contract **supported**. A project with no `belief.yaml` still works — subjects go unchecked, and
the coverage view says so.

---

## The systems-engineering view

Read as a V-model, the four servers cover stakeholder needs down to component test, joined by
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
| Traceability | a branch's `subject` and cited contract, the citation reviewed against the claim it was read against; `status(view="coverage")` on both sides; code regions reviewed against the claims they realize (`stamp-monitor links`) | mechanical |
| Configuration control | declarations from git HEAD; a content stamp on every run, covering declared inputs git ignores by their content on disk; evidence stale once a file it rests on changes; every decision names its revision | mechanical |
| Change control | `audit_change` (with the code links and cited measurements a change leaves unreviewed), STALE on restatement, `amend`, `decide`; `stamp-monitor impact`; the goal guard | mechanical, plus the human's commit of `goals.yaml` |
| Configuration audit | `stamp-monitor audit`, `workflow` and `links`; `graph-snapshot` for the whole design at one revision | mechanical, read-only |
| Independence | the verifier reads `status(view="probe")` and nothing else; the `consistency-verifier` agent cannot open a file | structural |
| Release gate | `POL-consistency-gate`: each branch proven **and** its cited contract supported; the goals policy in `goals.yaml` | both ledgers, and the human's goals |

Every stage now has a home. This repository applies each to itself: every axiom names its goal,
the goal interface carries a design claim, each component interface has an integration test,
and each of its 61 failure modes names the case that would catch it.

---

## Reference

### Layout

```
consistency.yaml                     axioms, definitions, lemmas, branches, policies (applied to itself)
belief.yaml                          components, interfaces, contracts, tests, policies (applied to itself)
README.md                            the short version: what TDLP is, a tour, the vocabulary
CHANGELOG.md                         release notes, newest first
docs/
  guide.md                           this manual
  assets/                            the README's goal snapshot, light and dark
  consistency_belief_mcp_design_rules.md   8 design rules for deductive consistency
  component_belief_mcp_design_rules.md     11 design rules for empirical belief
  component_belief_mcp_design.md           empirical model and architecture
  stamp_monitor_mcp_design.md              stamps, freshness, and the read-only monitor
  graph_snapshot_mcp_design.md             the design graph at one revision, drawn as one page
  code_to_theory_tagging_design.md         tagged code regions: pins, alignment, adoption
src/
  consistency_belief/                deductive server (10 tools)
    declarations.py                  git-HEAD loader, validation, the component join
    graph.py                         proof DAG kernel: acyclicity, grounding, blast radius
    model.py                         verification state (PROVEN, CONDITIONAL, REFUTED, OBLIGATION, STALE)
    probes.py                        falsification probe generators and parsers
    decide.py                        policy evaluation and the human approval gate
    views.py / render.py             proof tree, status and coverage views
    measurements.py                  cited measurements: reviews, review state, contracts no branch cites
    lean.py                          Lean certificates: the services (lean-prover, axle), binding, what the probe serves
    links.py                         the theory side of code links: claim digests, reviews, what moved
    store.py                         append-only JSONL ledger in .consistency/
  component_belief/                  empirical server (6 tools)
    declarations.py                  git-HEAD loader, validation, code claims
    model.py                         belief slices; gate and rate contracts
    staleness.py                     content stamps and freshness (shared with the other servers); a run judged once
    runner.py / readlog.py           test execution in the project's environment, artifact capture, the read hook
    project.py                       which project root all four servers read
    diagnose.py / planning.py        bottleneck ranking; round test selection
    decide.py                        policy evaluation and the human approval gate
    stamps.py / views.py / render.py the artifacts view; status views
    store.py                         append-only JSONL ledger in .belief/
  code_links/                        code regions: parser (markers, docstrings), revision-pinned index, reviews, mentions
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
  skills/consistency-belief/SKILL.md the deductive loop, six rules, when to delegate, reviewing what a branch cites, linking code
  skills/adopt-goals/SKILL.md        setting up goals.yaml in a project that already uses TDLP
```

A release: bump `version` in `pyproject.toml`, `__version__` in `src/component_belief/__init__.py`, `plugin/.claude-plugin/plugin.json`, the marketplace
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
4. A restatement sets aside exactly the trials of the steps that read it, and a node over an unverified step reads conditional, never proven.
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
19. A code region reads aligned only while its body and its claim, with everything upstream, are as its latest review recorded them; any other link, and any id named in a comment that resolves to nothing, is reported at every revision until fixed; and none of it moves a proof state or reaches the probe.
20. Runs made together take distinct run ids and evidence ids and overlap in time; a rejected import leaves no run behind.
21. A cited measurement reads reviewed only while its branch, and everything the branch rests on in the declared graph, is as it was when its latest review was recorded; recording a review restates nothing and sets no trial aside; a contract no branch cites is reported.
22. Staleness gives every trial the verdict it would get alone, judged once per run.
23. A source reference changes no premise graph, fingerprint, proof state or probe, whatever its source's id; a dangling reference and an unreferenced source are reported.
24. The tree for one node draws its lineage alone, and a parameter a status view ignores is named.
25. The order trials were recorded in decides no proof state, and no policy requiring proven passes a conditional branch.
26. A Lean certificate is served to the verifier beside the statements, never in place of them, only while it certifies its node, and moves no proof state; no service address or key reaches the ledger.
