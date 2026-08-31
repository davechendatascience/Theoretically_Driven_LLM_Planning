# Evidence discipline: which channel, and why the gate warns instead of refusing

Evidence enters a plan-auto store through three doors. Choosing the wrong one
is the most common way a project ends up with a ledger full of claims that
nothing can check.

| Door | Use it when | Provenance |
|---|---|---|
| `run_validation` | a registered command produces the result | **Mechanical** — argv, exit code, stdout captured to an immutable artifact; polarity from the exit code |
| `record_run_metrics` | you have numbers the plan's contract predicted | **Structured** — values land in `observations`, where the posterior check reads them |
| `record_evidence` | the observation is not a number | **Narrated** — prose, optionally with `artifact_uri` |

Prefer them in that order. Each step down trades machine-checkability for
expressiveness, and you should only pay that price when the observation
actually requires it.

## The rule for `record_run_metrics`

> Evidence needs structured `observations` when it is **linked to a plan whose
> predictive contract predicts those metrics**. Nothing else does.

The contract is what declares "a number will exist here." Evidence answering
that declaration must supply it structurally, because
`services/predictive.py:58 posterior_check` matches `MetricObservation.metric_id`
against `Prediction.metric_id` and compares the value to `expected_range`. A
number in a `summary` string is invisible to it: the check returns
`inconclusive`, and the plan cannot honestly reach `validated`.

`record_run_metrics` returns the recomputed evaluation in the same call, so the
verdict — `consistent` | `mismatch` | `inconclusive` — is visible at the moment
of recording rather than after a separate `evaluate_plan` round-trip. Its
`notes` field reports two things the values alone do not show: metrics you
recorded that the contract never predicted (nothing scores them), and contract
metrics still unobserved across every record linked to the plan.

## Not every record needs a metric

Requiring metrics everywhere produces invented `metric_id`s on records that
have no natural measurement, and that is **worse than prose**: prose is
honestly unstructured, while a fabricated metric looks scoreable and is not.

These belong in `record_evidence`, unchanged and not weaker for it:

- **Process records.** EV-0007 in this repo documents that the predictive layer
  shipped outside the ledger during an agreed pause. The point is what happened
  and why, not a measurement.
- **Non-numeric source types.** `paper`, `commit`, `manual_review` — a
  citation, "this commit introduced the shim", a code-reading finding.
- **Bad news, cheaply.** The system already made this call: marking a
  constraint `unsat` requires no evidence at all, because reporting a violation
  must stay low-friction. Friction on bad news does not produce better records,
  it produces fewer.
- **Pre-metric exploration.** Early measurement plans where the first look is
  what *tells* you the metric. Forcing quantification first is how you get the
  picked-to-be-easy ranges the reviewer is supposed to catch.

## Why the narrated-number check warns and never refuses

When a record is linked to a contract-carrying plan, states a numeral, and has
empty `observations`, `record_evidence` returns a `warnings` entry naming the
outstanding `metric_id`s. **The record is always still saved.**

Hard constraint `C-advisory-quality` requires it, but the design argument is
stronger than the constraint:

> A refusal is satisfiable without honesty. The cheapest way to clear a
> mandatory-`observations` check is not to record real numbers — it is to
> record `{"metric_id": "x", "value": 1}`. A hard refusal converts a visible
> honesty problem into an invisible compliance one.

A warning plus `predictive_status: inconclusive` is permanently visible to the
human and to the reviewer, and the *outcome* gate already prevents an honest
`validated`. Blocking the intake buys no enforcement that blocking the outcome
does not already provide, and it costs every legitimate case above.

This failure mode recurs, and it is worth stating as a standing design rule:

> **Recurring trap.** Refuse free text → fabricated metrics. Block outcomes →
> constraints argued down. Require invariances → filler invariances. When a
> requirement can be satisfied by writing something meaningless, the
> requirement produces meaningless writing. Prefer a visible warning over an
> evadable block.

## The quality criterion: model-invariance

Provenance answers *where a number came from*. It does not answer *whether the
record is any good*. The criterion for that:

> **Evidence is sufficient when a fresh reader, given only the artifact,
> reaches the conclusion recorded in the summary.**

If you need to know which model produced a piece of evidence in order to
interpret it, the evidence is weak. This is why capturing model identity is
*not* on the roadmap: it would control for a confound that good evidence should
not have.

The system already has this reader. `agents/plan-reviewer.md` runs with fresh
context by construction and checks summaries against artifacts. When a reviewer
cannot reproduce a conclusion from the artifact, the finding is not "the
reviewer disagrees" — it is **the evidence was narration-dependent**, which is
a defect in the record.

Structured `observations` serve this criterion directly: a number in a field
means the same thing to every reader; the same number in prose does not.

## Operational note

MCP servers connect at session start, so **a newly added tool is not reachable
until Claude Code is restarted** in the target project. This is not
hypothetical — `record_run_metrics` could not be called over the live
connection in the session that introduced it, and its first real use went
through `Workspace` directly (`server.py` is a thin decorator layer over it).
After adding a tool, restart and confirm with `/mcp`.

## Where this stands

Measured across all four live stores on 2026-08-20 (EV-0010), before this
change: **3 of 69 evidence records carried `observations`** — 4.3%, while 56 of
69 were linked to a plan. Contracts were collecting ranges that nothing scored.

`P-observations-default` validated that the channel now exists and that
skipping it is detected. It explicitly did **not** validate that adoption
rises: that is a lagging indicator needing a follow-up measurement plan against
the 4.3% baseline. If adoption stays flat, the named expansion (`D-1`) is that
discoverability was never the cause — `metric_id`s are chosen when the contract
is written and forgotten by the time results are recorded — and the fix moves
from offering a channel to surfacing the obligation in every plan-linked
response.
