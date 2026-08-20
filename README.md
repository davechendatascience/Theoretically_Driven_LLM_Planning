# damped-plan-mcp

A local MCP server that acts as a **constraint-closure gate for LLM planning**.
An LLM may retrieve knowledge and propose candidate actions freely, but it may
not declare a nontrivial plan executable until the plan has an explicit goal
with a metric, a hard-constraint audit, a causal hypothesis, a scoped
intervention, a validation path, adopt/reject criteria, and a rollback story —
and every hard constraint is evidence-backed `SAT`.

Design blueprints: [docs/blueprint.md](docs/blueprint.md) (constraint
closure) and [docs/damped-plan-mcp-bayesian-scope.md](docs/damped-plan-mcp-bayesian-scope.md)
(predictive layer). Tool reference: [docs/tool_contracts.md](docs/tool_contracts.md).
Claude Code setup: [docs/claude_code_integration.md](docs/claude_code_integration.md).
Why this works on qualitative measures:
[docs/damping_translation.md](docs/damping_translation.md). The predictive
contract and posterior checks — the model-checking discipline borrowed from
Gelman et al., *Bayesian Data Analysis* (3rd ed., CRC Press, 2013):
[docs/predictive_layer.md](docs/predictive_layer.md). Which evidence channel to
use, and why the gate warns instead of refusing:
[docs/evidence_discipline.md](docs/evidence_discipline.md). Open design work —
pre-registration, a commitment ladder, the harness as model structure:
[docs/tempering_and_preregistration.md](docs/tempering_and_preregistration.md).

## What it enforces

- **`UNKNOWN` is never treated as `SAT`.** Implementation plans are `BLOCKED`
  while any hard constraint is unresolved; marking one `SAT` requires recorded
  evidence with provenance.
- **Measurement before commitment.** A safe, reversible measurement plan that
  directly targets the unknown is the one thing allowed through a closed gate.
- **Plan drafting is separate from approval.** A plan becomes `EXECUTABLE`
  only when a human approves it; AI self-approval is refused.
- **Scoped execution.** An approved plan authorizes only its
  `intervention.allowed_files` — enforced for real by an opt-in Claude Code
  PreToolUse hook that reads the precomputed `.damped-plan/gate.json`.
- **Review that cannot manufacture evidence.** The optional fresh-context
  `plan-reviewer` agent attacks a plan before approval and holds no mutating
  tools; a second PreToolUse hook denies it execution, so it cites recorded
  artifacts instead of producing unrecorded numbers of its own.
- **No silent "fixed".** `validated` outcomes require recorded evidence; every
  state transition lands in an append-only `events.jsonl`.
- **Numbers are recorded, not narrated.** `record_run_metrics` puts measured
  values where the posterior check can actually read them and returns the
  verdict in the same call; a plan-linked summary that states numerals while
  the contract's metrics go unobserved comes back with a warning naming them.
  It warns and never refuses — a mandatory field is satisfiable by fabricating
  a value, which trades a visible problem for an invisible one.
- **Escalation over repair loops.** After two failed sibling plans with no new
  evidence, the recommendation is `escalate` (change the causal framing), not
  another local patch.
- **Predictive contracts.** New implementation/repair plans must state what
  should move, what must stay invariant, under what fixed context, and which
  observed patterns would refute the causal story — and a posterior predictive
  check compares recorded observations against those predictions, turning
  mismatch into a named model expansion instead of a generic failure.

## Quick start

```bash
uv sync
uv run pytest -q                          # 153 tests
uv run python scripts/demo_end_to_end.py  # full blocked->measure->unblock flow
```

## Set up for your project

Four pieces, each opt-in, all configured in the *target* project (the repo
whose changes you want gated). Full details in
[docs/claude_code_integration.md](docs/claude_code_integration.md).

**1. Register the MCP server** — add `.mcp.json` at the target repo's root
(or use `claude mcp add`, see the integration doc):

```json
{
  "mcpServers": {
    "damped-plan": {
      "command": "uv",
      "args": [
        "--directory", "/absolute/path/to/damped-plan-mcp",
        "run", "damped-plan-mcp"
      ],
      "env": {
        "DAMPED_PLAN_DATA_DIR": "/absolute/path/to/your-project/.damped-plan"
      }
    }
  }
}
```

Add `.damped-plan/` to the target project's `.gitignore` (or commit it if you
want plans and evidence reviewed alongside code).

**2. Install the `/damped-plan` skill** (recommended — teaches Claude the
workflow and auto-triggers on nontrivial changes):

```bash
mkdir -p .claude/skills
cp -r /absolute/path/to/damped-plan-mcp/skills/damped-plan .claude/skills/
```

**3. Enable the enforcement hooks** (optional — turn the gate from advisory
into actual denials): add the PreToolUse entries from
[hooks/README.md](hooks/README.md) to the target project's
`.claude/settings.json`. `damped_plan_gate.py` (matcher
`Edit|Write|NotebookEdit`) denies edits no approved plan covers;
`damped_plan_reviewer_gate.py` (matcher `Bash`) denies *execution* to the
reviewer agent while leaving read-only inspection open. Every other agent,
including the main session, passes through untouched.

**4. Install the adversarial reviewer** (optional): copy
`agents/plan-reviewer.md` into the target project's `.claude/agents/`. It
reviews `ready_for_review` plans with fresh context and returns a verdict; it
never approves anything.

Then restart Claude Code in the target project (MCP servers connect at
session start), approve the server when prompted, and verify with `/mcp`.
First use: ask Claude to register the project's goals, hard constraints, and
failure modes, then propose a change and watch it get gated.

## How state is stored

Everything lives in the target project's `.damped-plan/` directory as plain
JSON — human-diffable, git-friendly:

```text
.damped-plan/
├── project.json      goals, constraints (+statuses), failure modes, facts
├── plans/P-0001.json one file per plan
├── evidence/EV-0001.json
├── events.jsonl      append-only audit log of every transition
└── gate.json         derived snapshot the PreToolUse hook reads
```

## Status

v0 implements the blueprint's Phases 1–4 plus the enforcement hooks:
pure-Python kernel (models, closure validator, residuals, decision policy),
JSON store with event log, MCP server (11 tools, 7 resources, 4 prompts), both
PreToolUse hooks, the allowlisted command runner (`run_validation` +
`.damped-plan/commands.json`) that converts captured command results into
evidence automatically, and the structured-observation channel
(`record_run_metrics` + the narrated-number warning) that feeds the posterior
check.

Deferred: dependency graph and drift analysis (Phase 5, which owns the
still-stubbed `oscillation_risk`), robotics adapters (Phase 6).

Known gaps, with the reasoning recorded in
[docs/tempering_and_preregistration.md](docs/tempering_and_preregistration.md):
there is **no project-level model document** — `ProjectState` records goals,
constraints and failure modes (targets and limits) but no statement of the
mechanism the project believes it is operating on, so each plan's
`predictive_contract` is a local model with no parent to be consistent with and
drift is undetectable; relatedly, `create_plan` auto-links a plan to *all*
unmet goals when `goal_ids` is omitted (`normalize.py:369`), so closure passes
without the author ever choosing a goal. Contract fields are not hashed at
first set, so "was this range fixed before the data existed?" is narrated
rather than checkable. Commitment is binary (approved or not) with no probe
rung, so `alternative_hypothesis_ids` is counted as a penalty and never carried
as a live candidate. And the harness configuration that shapes what the agent
may do appears in no ledger.
