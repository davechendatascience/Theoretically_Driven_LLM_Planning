# Component Belief-Update MCP

Evidence-grounded belief state for a system modelled as components and
interfaces. Design rules in [`docs/component_belief_mcp_design_rules.md`](docs/component_belief_mcp_design_rules.md),
design in [`docs/component_belief_mcp_design.md`](docs/component_belief_mcp_design.md).

## The commitment

An LLM agent is the primary caller, and an agent is a fluent producer of
*plausible* numbers. So **the agent has no write path to a belief.** There is no
`set_belief`, no free-text field a belief model reads. Beliefs are a pure
function of `(belief-eligible evidence, declared priors, model version)`.

This is enforced by a missing tool, not by a prompt instruction.

| Channel | Tool | Belief-eligible |
|---|---|---|
| Server ran a declared test | `run_test` | yes — artifact + hash captured |
| External import | `ingest` | yes — requires source + artifact |
| Agent or human statement | `note` | **no** — it is testimony |

## Install

```bash
pip install -e .
```

Register with Claude Code via the included `.mcp.json`, or run directly:

```bash
PYTHONPATH=src python -m component_belief.server
```

## Declarations live in git, not in tools

Components, interfaces, contracts, tests, priors, and policies are declared in
`belief.yaml`. The server reads it from **git HEAD, not the working tree** — so
editing the file changes nothing until a human commits it.

That is the entire approval gate for rule 10.5, and it costs zero tools and
zero roundtrips. Uncommitted edits show as `PENDING` in `status`; a threshold
lowered in the working tree cannot flip a verdict.

> Caveat: this is exactly as strong as your commit discipline. If agents can
> commit unattended, add CODEOWNERS on `belief.yaml` or require signed commits.

## The loop

```
status(view="diagnose")  →  run_test(...)  →  status(view="belief")
```

Six tools total — `status`, `run_test`, `ingest`, `note`, `amend`, `decide` —
because tool schemas are standing context in every session, paid whether or not
the server is used.

```
CTR-grasp-reachable [normal, model_revision=v3] supported 0.91 [0.84,0.96] n=34
CTR-grasp-reachable [low, model_revision=v3] insufficient n=3 (need 5 more)
basis: evidence×37 set=a3f9c1 · model bb-1 · prior none
next: run_test TST-grasp-ik conditions={low}  # closes the thin slice
```

`set=` is a hash of the exact evidence set, expandable with
`status(view="trace", set=a3f9c1)`. An id *range* would be cheaper and would
occasionally lie — slices use a non-contiguous subset once invalid trials and
other buckets are dropped.

## What it refuses to do

- **Score an annotation.** `note()` is inert by construction.
- **Issue a verdict from sparse data.** `insufficient_evidence` is checked
  first, so n=2 can never present as a result.
- **Pool incompatible evidence.** Trials differing on a declared
  `compatibility_key` land in separate slices; a hardware swap reports
  `not_comparable`, never "no regression detected".
- **Recommend optimising what it cannot see.** If the leading suspect has no
  test targeting it, `coverage_limited: true` and *no* optimisation
  recommendation is produced. The answer is instrumentation.
- **Score a declared metric off an exit code.** A test that declares
  `ik_success` but emits nothing gets its trial excluded with
  `missing_metrics`, not silently passed.
- **Self-approve.** `adopt` and `rollback` will not record without `approver=`.

## Writing tests

A declared test writes trials to `$OUT` (expanded on every platform):

```yaml
tests:
  - id: TST-grasp-ik
    layer: component          # component | interface | e2e
    targets: [CMP-grasp]
    run: python tools/pytest_trials.py $OUT -- tests/test_grasp.py -q
    metrics: [passed]
    capture: [lighting, model_revision]
```

```json
{"trials": [{"metrics": {"ik_success": true}, "conditions": {"lighting": "low"}}]}
```

`tools/pytest_trials.py` adapts any pytest suite, emitting one trial per test
case — trial-level granularity is rule 3.1, and "the suite passed" throws away
the evidence every later question needs.

A test's version is the hash of its `run` line and metric spec, so editing a
test mints a new version and beliefs stop pooling across the boundary. That is
what stops "we improved the test and the number went up" from reading as
progress.

## Layout

```
belief.yaml                     declarations — human-owned, git-approved
src/component_belief/
  declarations.py               load from git HEAD, validate
  model.py                      belief slices; no writer exists
  diagnose.py                   four status classes, decision-relevance ranking
  decide.py                     policies; the endpoint-disagreement estimator
  planning.py                   round selection, every skip with a reason
  runner.py                     test execution and artifact capture
  views.py / render.py          the seven status views, compact output
  stats.py                      Beta-Binomial (no SciPy dependency)
  expr.py                       whitelisted AST rule evaluator, never eval()
  store.py                      append-only JSONL ledger
tools/pytest_trials.py          pytest -> trials adapter
.belief/                        evidence, artifacts, events, decisions
```

## Tests

```bash
PYTHONPATH=src python -m pytest tests -q
```

73 tests. They assert the invariants above, not the implementation: that
asserted evidence cannot move a posterior, that an uncommitted threshold cannot
flip a verdict, that a hardware swap reports `not_comparable`, and that the
rule language rejects `__import__`.
