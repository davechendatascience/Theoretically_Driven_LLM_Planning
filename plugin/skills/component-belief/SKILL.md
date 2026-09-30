---
name: component-belief
description: Ground engineering claims in measured evidence via the component-belief MCP. Use before reporting that something works, when diagnosing which component is the bottleneck, when deciding whether a change is ready, or whenever you are about to state a number you did not measure.
---

# Component belief workflow

This project tracks per-component belief state from trial-level evidence. The
server exists because a fluent summary is indistinguishable from a measurement
until something forces the difference — so let it force the difference.

## The loop

```
status(view="diagnose")  →  run_test(...)  →  status(view="belief")
```

Three calls. Do not skip the first: diagnosing before optimising is the whole
point, and the ranking is by *decision relevance*, not by lowest score.

## Four rules

1. **Diagnose before optimising.** If `status(view="diagnose")` returns
   `coverage_limited: true`, the answer is instrumentation, not performance
   work. Do not propose an optimisation it explicitly declined to recommend.

2. **Never report a result you did not obtain through `run_test` or `ingest`.**
   If you ran something in your own shell, that number has no artifact and no
   provenance. Re-run it through `run_test` or do not state it. `ingest` is for
   results a run you could not start produced -- CI, a robot, a GPU box -- and
   it takes the results file itself (`artifact_uri`, a file on this machine)
   and a test the contract lists in `evaluable_by`; the server copies and
   hashes that file. Importing your own shell run is not a shortcut around
   `run_test`: declare the test instead.

3. **`insufficient` is an answer.** Report it as one. A slice below `n_min`
   carries an estimate but no verdict, and no amount of confidence in the
   estimate promotes it. "We don't know yet, n=3, need 5 more" is a complete
   and useful reply.

4. **Decide under the human's goals.** When the project has a `goals.yaml`,
   `decide()` answers to its policy by default, and an `adopt` or `rollback`
   under it records with no approver: the human approved its criteria by
   committing them. Any other `adopt` or `rollback`, or one the server says is
   not covered, needs `approver=`: present the verdict, get explicit human
   approval, then pass their name. Never supply it yourself.

## Declarations

Two files, loaded from git HEAD, never behind tools:

- **`belief.yaml` is yours.** Components (each may name the `goal:` it
  serves), their contracts, tests, thresholds and policies. Edit it and commit
  it as you work, with the evidence that motivated the change; an uncommitted
  edit is `PENDING` and not in effect.
- **`goals.yaml` is the human's.** Goals, the interfaces between them, and the
  contracts, tests and policy that measure them. Never commit it or a file its
  tests name: the commit hook refuses a commit carrying your trailer that does.
  If you believe a goal, a threshold on it or an interface is wrong or out of
  reach, say so with `note(subject="GOL-...", text=...)` -- what you would
  change and the evidence ids behind it -- and carry on with what you can do.
  The human reads it in `status(view="goals")`.

`status(view="goals")` is also your check: every goal met, insufficient,
stale or not met, with the test to run for each.

## Citations

Every response ends with a `basis:` line carrying `set=<hash>` — the exact
evidence set behind the numbers above it. When you quote a belief in a summary,
quote the handle with it. `status(view="trace", set=...)` expands it to the
records. A number without its handle is narration.

## What you cannot do, and should not try

- Write a belief directly — no such tool exists.
- Make an assertion count as evidence — `note()` is inert by construction.
- Change a goal, how it is measured, or the interface between two goals.
- Name an approver the human did not give you.
- Pool evidence across incompatible conditions.

These are not obstacles to route around. They are the reason a number from
this server means something.
