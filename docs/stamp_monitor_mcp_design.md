# Stamp and Monitoring Design

## Purpose

Evidence freshness, ledger integrity, and workflow conformance across the two belief ledgers.

- `component-belief` decides whether a component's contracts have sufficient current support.
- `consistency-belief` decides whether the declared design graph is sufficiently supported.
- **Stamps** establish what a piece of evidence measured, so it can be told when it no longer applies.
- **`stamp-monitor`** reads both ledgers, their stamps, and git, and reports the joins between them,
  their integrity, and patterns in their history. It writes nothing.

The monitor is an infrastructure boundary: it exposes objective repository- and ledger-state facts
to the belief systems, to agents, and to humans, without taking part in their reasoning or changing
their decisions.

## Core principle: lazy invalidation

> Stamp when durable evidence is produced. Compare the stamp when something wants to rely on the
> evidence again.

A file change does not trigger a test run, a verification pass, or a global traversal. It changes
nothing until a decision needs evidence whose applicability may have changed; then the stamp
comparison says whether it still applies. Nothing reruns tests automatically, mutates belief state,
records adoption, or deletes provenance.

## Architecture as built

```text
              run_test                                   status / decide
   runner ──────────────► stamp.json ──┐        ┌──► component-belief model
   (the only stamper)     + digest in  │        │    (stale slices, plan, policy)
                          every trial  ├─ staleness.py ─┤
                                       │  (a library)   └──► consistency-belief
   git HEAD ───────────────────────────┘                     (via contract states)
                                       │
                                       └──► stamp-monitor  (read-only: impact, audit, workflow)
```

Freshness is computed **in-process by a shared library** (`component_belief/staleness.py`), which
both belief servers already import. The monitor imports the same library. There is one definition
of "stale", and it is never relayed through an agent.

## Stamps

### What a stamp records

Before a declared test's command starts, the runner writes `.belief/artifacts/RUN-*/stamp.json`:

```json
{
  "version": 1,
  "head": "<full HEAD sha>",
  "claimed": ["<every component's code: entries, as declared at run time>"],
  "named": ["<files the test names on its run line or in reads:>"],
  "opened": ["<tracked files the run opened for reading, from the read hook>"],
  "dirty": ["<which of the files below differed from HEAD when the run started>"],
  "files": {"<path>": "<git blob id as the run saw it, or null if absent>"}
}
```

Blob ids are taken from the working tree through git's own filters (`git hash-object
--stdin-paths`), so a CRLF checkout of an LF blob hashes to the committed id. Every trial the run
records carries the stamp's digest; a stamp edited after the fact no longer matches it and is not
trusted.

### When evidence is current

A trial is current while every file it rests on has the same blob at HEAD as in its stamp. The
files it rests on, in its **stale scope**:

| Scope | Source | Why |
|---|---|---|
| Claimed code | the subject component's `code:` entries (file, glob, or directory) | what the contract measures |
| Test-named files | paths on the test's `run:` line and its `reads:` | the test is part of what was measured |
| Declared reads | `reads:` on the test (e.g. `tests/conftest.py`, `uv.lock`) | inputs the run line does not name |

Opened files are **recorded, not scoped**: a run opens far more than it depends on, and the project
rule is *declared, never guessed*. A file a test depends on but does not name is declared in
`reads:`; the monitor can point at candidates.

### Why content and not revision

A revision says which commit was checked out, not what was measured:

| Case | Revision check | Content check |
|---|---|---|
| Run on uncommitted edits, edits later discarded | current (wrong: HEAD was never measured) | stale |
| Same edits later committed as measured | stale (needless re-run) | current |
| Amend / rebase / squash-merge, same bytes | stale: "revision not in history" | current |
| Test file weakened and committed | current (wrong) | stale |

Trials without a stamp (recorded before stamps existed, or imported) fall back to the revision check,
so no existing evidence changed state when stamps were introduced.

### Evidence states

| State | Meaning | Counts as support | Where it comes from |
|---|---|---|---|
| current | every stamped file in scope matches HEAD | yes | staleness |
| stale | a file in scope changed; still on record and cited | no | staleness |
| superseded | replaced by a newer record | no | `amend(supersede_with=)` |
| invalid / quarantined | the trial, rig, or oracle was unreliable; the reason is kept | no | `amend(validity=)` |

Stale and invalid stay distinct: stale evidence was a valid measurement of a state that no longer
exists; invalid evidence was never a valid measurement.

## The monitor: three read-only tools

| Tool | Answers | Severity |
|---|---|---|
| `impact(base, worktree)` | What does a change touch, across both ledgers, and what must be re-run? | report |
| `audit()` | Is the recorded evidence still what was recorded? | block / warn / info |
| `workflow()` | Does the history show the loop being routed around? | block / warn / info |

### `impact`

Follows the declared chain rather than guessing it:

```text
changed path → component that claims it, test that names or declares it
             → contracts on that component or measured by that test   [state at HEAD]
             → design branches whose subject is the component or whose rule cites the contract
             → policies whose criteria name the contract or the branch
```

Contract states are measured (stale is a fact at HEAD); everything else on the chain is *possibly*
affected. Uncommitted edits are listed and stale nothing, but name the tests that will need a re-run
once they are committed. Paths no component claims and no test names are listed as such, which is
how an untested file becomes visible.

### `audit`

- Every ledger line parses (the stores skip unparsable lines silently), and evidence ids are unique.
- Every amendment and every decision cites records that exist.
- Every stamp a trial cites exists and matches the trial's digest.
- Every measured trial's artifact exists and still hashes to the recorded value (LF-normalised
  content counts as the same artifact, so a cross-platform checkout is not tampering).
- The declarations in effect are the committed ones.
- Unstamped evidence is counted, since its staleness is judged by the weaker revision check.

### `workflow`

Patterns in recorded history, not verdicts on intent; each finding names the records.

- Reclassifications that remove only adverse results (fails, falsifications, gaps). Three or more,
  all one way: warn. Fewer: reported with the recorded reason.
- An adoption or rollback with no approver, or approved by the agent or the actor that requested it.
- A decision resting on evidence measured with uncommitted edits.
- An adoption whose evidence has gone stale since: the decision stands as recorded but no longer
  describes HEAD.

### Surfaces

- MCP server `stamp-monitor` (`stamp-monitor-mcp`), registered in `.mcp.json`.
- CLI `stamp-monitor impact|audit|workflow`, exiting 1 on a `[block]` finding from `audit` or
  `workflow`, for git hooks, CI, and Claude Code hooks.

## Decisions against the first draft

| Draft | Built | Why |
|---|---|---|
| `register_artifact`: agents or wrappers submit manifests | no registration; the runner stamps what it ran | a submitted manifest is an agent-writable path into evidence, and whoever submits it chooses the scope that keeps it fresh |
| monitor is the single source of freshness; belief servers query it | freshness is a shared library both servers import | MCP servers cannot call each other; routing freshness through the agent makes the untrusted party the relay |
| seven tools | three | tool schemas are standing context in every session; `explain_gate` is `impact` plus `decide`, `prune_candidates` is `status(view="artifacts")` |
| subject paths declared in the manifest | scope from committed `belief.yaml` (`code:`, `reads:`) and the run line | changing what evidence depends on is a declaration change, gated by a human commit |
| `CLM-`, `TST-diagnose-202` ids | the ledgers' own `CTR-`, `TST-`, `RUN-`, `EV-`, `BRN-` ids | one vocabulary |

## Event model

The monitor is triggered, not continuously running. Useful triggers, none installed by default:

| Event | Call |
|---|---|
| after a commit | `stamp-monitor impact` |
| before `decide` | `stamp-monitor audit` and `stamp-monitor workflow` |
| end of an agent session (Claude Code `Stop` hook) | `stamp-monitor workflow` |
| CI on a pull request | all three; fail on exit 1 |

## Safety and authority

- Reads repository contents, git state, and both ledgers. Writes nothing, anywhere.
- Never modifies source, declarations, branches, pull requests, issues, or releases.
- Never repairs a finding: amend, re-run, or restore is a decision for someone accountable for it.
- Never claims semantic proof or authorizes adoption.

## Not yet

- **Environment and data scopes** are declared, not built in: `reads: [uv.lock, pyproject.toml]` on
  a test makes a dependency bump stale its evidence today. No interpreter, platform, or hardware
  fingerprint is stamped.
- **API and behavioral scopes** (surviving an internal refactor) are not attempted; a wrong
  fine-grained scope is worse than a conservative path-level one.
- **Unversioned evidence**: a trial with neither stamp nor revision is treated as current, not
  unknown. Strict gates may want it excluded.
- **Ledger tamper-evidence** is limited to stamps and artifacts: `evidence.jsonl` itself is
  appendable and editable. A hash chain over ledger records would let `audit` detect an edited line.
- **Undeclared dependencies**: `impact` lists changed files nothing claims; it does not yet list
  files a test opens but does not declare.

## Success criteria

1. Which evidence currently supports this contract? `status(view="belief")`, `status(view="trace")`.
2. Did a code, test, or declared-input change stale any of it? `impact`.
3. What is the smallest set of re-runs that restores support? `impact`'s `next:`.
4. Why is a gate blocked? `decide` for the verdict, `impact` for the chain behind it.
5. Which old artifacts are safe to stop keeping? `status(view="artifacts")`.

A typical answer:

```text
src/component_belief/runner.py changed
→ CMP-runner → CTR-surface-intact [stale]
→ BRN-runner-captures (governs CMP-runner, cites CTR-surface-intact)
→ POL-release, POL-consistency-gate
next: run_test TST-server
```
