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

## Declaring contracts and tests

Six facts decide whether a declaration measures what you meant.

1. **A target is cleared by an interval, not a point estimate.** A rate
   slice is `supported` when the lower end of its 94% credible interval
   (Beta(1+passes, 1+fails), or the declared prior) is above `target_rate`
   (default 0.9), `refuted` when the upper end is below it, and `contested`
   in between. `insufficient` is checked first: fewer than `n_min` trials
   (default 8), or an interval wider than `max_ci_width` (default 0.35). At
   n = 500, 0.90 needs 463 passes and 0.87 needs 450. The widest interval is
   at a 50% pass rate: about 0.33 at n = 30, 0.19 at n = 100 and 0.084 at
   n = 500. Set `max_ci_width` above it for your run size, or a full run can
   come back insufficient.
2. **A deterministic check is a gate.** Declare a bit-identical replay or a
   test suite `kind: gate`: its latest run decides it. As a rate it stays
   contested: 33 of 33 against 0.99 has a lower bound of 0.90.
3. **Every `compatibility_key` field splits the evidence.** Trials that
   differ on any key are never pooled, and `n_min` counts each slice alone.
   Keying on something that changes every run, such as a revision or a seed,
   leaves many slices too small to decide. Key on what makes trials
   incomparable. For a version that staleness already binds (fact 5), let
   staleness retire the old runs instead of keying on it.
4. **`$OUT` is one JSON file:** `{"trials": [...]}`, a list of trials, or
   one `{"metrics": ...}`. Anything else falls back to one trial built from
   the exit code, and the reply says what was wrong with `$OUT`. A contract
   whose rule reads a real metric then excludes that trial. A measure in
   several parts writes them elsewhere (e.g. `${OUT%.json}.d/`) and merges
   them into `$OUT`.
5. **Evidence goes stale when any of these change:**
   - the code its components claim;
   - every tracked file a run-line token or a `reads:` entry names;
   - ignored inputs (a checkpoint, a dataset) named in `reads:` or on the
     run line. These are judged by the sha256 of their bytes.

   Run-line tokens are shell-split, and those containing `$` or starting
   with `-` are skipped. A token matches an exact path, a glob or a
   directory prefix, so `cd dir && ...` names everything in `dir`. A script
   the run line names is bound; the files it calls are not. The read hook
   records what the run opened, but that record does not make evidence
   stale. To bind a file a script calls, claim it or list it in `reads:`.

   To measure "the current checkpoint", put a symlink to the file in
   `reads:`: moving the link changes the bytes and retires the old runs. A
   symlink to a directory binds nothing; name a file.
6. **The read hook rides `PYTHONPATH`.** The runner adds its hook to
   `PYTHONPATH=` assignments on the run line only. A wrapper script that sets
   `PYTHONPATH` must prepend to it, as in
   `PYTHONPATH=x${PYTHONPATH:+:$PYTHONPATH}`. Otherwise its Python children
   record no reads.

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
