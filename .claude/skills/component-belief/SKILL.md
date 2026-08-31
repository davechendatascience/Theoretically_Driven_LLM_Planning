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
   provenance. Re-run it through `run_test` or do not state it.

3. **`insufficient` is an answer.** Report it as one. A slice below `n_min`
   carries an estimate but no verdict, and no amount of confidence in the
   estimate promotes it. "We don't know yet, n=3, need 5 more" is a complete
   and useful reply.

4. **Escalate for `decide()`.** An `adopt` or `rollback` verdict will not
   record without `approver=`. Present the verdict, get explicit human
   approval, then pass their name. Never supply it yourself.

## Declarations

Components, interfaces, contracts, tests, priors, and policies live in
`belief.yaml` — **not** behind tools. The server reads it from git HEAD, so
your edits to that file do nothing until a human commits them. If you need a
new contract or a changed threshold, edit the file and *tell the user it needs
committing*; do not work around the gate.

`status(view="graph")` will say `PENDING` when the working tree has
uncommitted edits. That is not an error to fix — it is the gate reporting that
your edit is not in effect.

## Citations

Every response ends with a `basis:` line carrying `set=<hash>` — the exact
evidence set behind the numbers above it. When you quote a belief in a summary,
quote the handle with it. `status(view="trace", set=...)` expands it to the
records. A number without its handle is narration.

## What you cannot do, and should not try

- Write a belief directly — no such tool exists.
- Make an assertion count as evidence — `note()` is inert by construction.
- Approve your own contract, threshold, prior, or weight change.
- Pool evidence across incompatible conditions.

These are not obstacles to route around. They are the reason a number from
this server means something.
