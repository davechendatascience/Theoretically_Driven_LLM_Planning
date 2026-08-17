# damped-plan-mcp

A local MCP server that acts as a **constraint-closure gate for LLM planning**.
An LLM may retrieve knowledge and propose candidate actions freely, but it may
not declare a nontrivial plan executable until the plan has an explicit goal
with a metric, a hard-constraint audit, a causal hypothesis, a scoped
intervention, a validation path, adopt/reject criteria, and a rollback story —
and every hard constraint is evidence-backed `SAT`.

Design blueprint: [docs/blueprint.md](docs/blueprint.md). Tool reference:
[docs/tool_contracts.md](docs/tool_contracts.md). Claude Code setup:
[docs/claude_code_integration.md](docs/claude_code_integration.md). Why this
works on qualitative measures — how the critical-damping idea maps to
discrete state: [docs/damping_translation.md](docs/damping_translation.md).

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
- **No silent "fixed".** `validated` outcomes require recorded evidence; every
  state transition lands in an append-only `events.jsonl`.
- **Escalation over repair loops.** After two failed sibling plans with no new
  evidence, the recommendation is `escalate` (change the causal framing), not
  another local patch.

## Quick start

```bash
uv sync
uv run pytest -q                          # 66 tests
uv run python scripts/demo_end_to_end.py  # full blocked->measure->unblock flow
```

## Set up for your project

Three pieces, each opt-in, all configured in the *target* project (the repo
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

**3. Enable the enforcement hook** (optional — turns the gate from advisory
into an actual deny on uncovered edits): add the PreToolUse entry from
[hooks/README.md](hooks/README.md) to the target project's
`.claude/settings.json`.

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

v0 implements the blueprint's Phases 1–3 plus the enforcement hook:
pure-Python kernel (models, closure validator, residuals, decision policy),
JSON store with event log, MCP server (9 tools, 6 resources, 4 prompts), and
the gate hook. Deferred: allowlisted validator execution (Phase 4), dependency
graph and drift analysis (Phase 5), robotics adapters (Phase 6).
