# Claude Code integration

Three pieces, each opt-in per target project:

1. **MCP server** — the tools/resources/prompts (required).
2. **`/damped-plan` skill** — teaches Claude the workflow (recommended).
3. **PreToolUse hooks** — hard enforcement, on the implementer and on the
   reviewer (optional).

## 1. Register the MCP server

In the *target* project (the repo whose changes you want gated), add
`.mcp.json` at the repo root:

```json
{
  "mcpServers": {
    "damped-plan": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/damped-plan-mcp",
        "run",
        "damped-plan-mcp"
      ],
      "env": {
        "DAMPED_PLAN_DATA_DIR": "/absolute/path/to/your-project/.damped-plan"
      }
    }
  }
}
```

Or via CLI from inside the target project:

```bash
claude mcp add damped-plan \
  --env DAMPED_PLAN_DATA_DIR="$(pwd)/.damped-plan" \
  -- uv --directory /absolute/path/to/damped-plan-mcp run damped-plan-mcp
```

The server is single-project: one `.damped-plan/` data dir per registration.
Add `.damped-plan/` to the target project's `.gitignore` — or commit it, if
you want plans and evidence reviewed alongside code (it is plain JSON and
diffs well; `events.jsonl` is append-only).

## 2. Install the skill

Copy (or symlink) the packaged skill into the target project:

```bash
mkdir -p .claude/skills
cp -r /absolute/path/to/damped-plan-mcp/skills/damped-plan .claude/skills/
```

Claude will auto-load it for nontrivial changes (its `description` covers
multi-file edits, new modules/dependencies, evaluation changes, repeated
failed fixes), and you can invoke it explicitly with `/damped-plan`.

Alternatively — or additionally — put the short policy in the target
project's `CLAUDE.md`:

```markdown
# Damped Plan Policy

For any nontrivial change (multi-file edit, new algorithm/model/dependency,
data or evaluation change):

1. get_project_snapshot; register_project if empty.
2. create_plan; repair blockers until ready_for_review (or blocked-with-
   measurement, then propose the measurement).
3. Do not edit source files until the plan is EXECUTABLE, or the user has
   explicitly approved a safe measurement plan.
4. Implement only files in the approved plan's allowed_files.
5. Afterwards: record_run_metrics for every number the plan's contract
   predicted (a number narrated into an evidence summary scores nothing),
   record_evidence for observations that are not numbers,
   update_constraint_status for anything resolved, then record_plan_outcome.
6. Never report "fixed" or "validated" without a recorded validation.
```

## 2b. Install the adversarial plan reviewer (optional)

`agents/plan-reviewer.md` is a fresh-context reviewer agent that tries to
refute a `ready_for_review` plan (checks evidence artifacts against their
summaries, attacks closure quality, reads the diff against the predictive
contract's `context_fixed`) and returns a structured verdict before the human
decides. It is advisory only: the human stays the approver.

Its tool allowlist is the enforcement, not the prompt. `approve_plan`,
`create_plan`, `record_evidence`, and `run_validation` are absent, and so is
`evaluate_plan` — despite reading as a query, it persists status transitions,
appends an event, and rewrites `gate.json` (`workspace.py:228-233`), so a
reviewer holding it could move the gate before the human decided. `get_plan`
returns the same evaluation without writing. The reviewer also does not execute
the project's checks: it cites artifacts captured by `run_validation` rather
than re-running commands, because a number produced in a reviewer's shell has
no `artifact_uri` and no event. Pair the agent with the reviewer gate hook
(step 3) to make that mechanical rather than merely instructed.

```bash
mkdir -p .claude/agents
cp /absolute/path/to/damped-plan-mcp/agents/plan-reviewer.md .claude/agents/
```

Control: the reviewer runs when the session delegates to it (its
`description` triggers on plans reaching ready_for_review) or when you invoke
it explicitly. To skip it for one plan, say so ("approve without review"); to
disable it entirely, delete or move the agent file. Approval always requires
the human regardless of whether the reviewer ran.

## 3. Enable the enforcement hooks (optional)

See [hooks/README.md](../hooks/README.md). Two independent PreToolUse hooks,
each opt-in:

- `damped_plan_gate.py` (matcher `Edit|Write|NotebookEdit`) gates the
  **implementer**. Without it the gate is advisory (the model is instructed to
  respect it); with it, uncovered edits are denied with the server's
  explanation of what to do instead.
- `damped_plan_reviewer_gate.py` (matcher `Bash`) gates the **reviewer**,
  denying execution for the `plan-reviewer` agent while leaving read-only
  inspection (`git diff`, `cat`, `grep`, ...) open. Every other agent,
  including the main session, passes through untouched.

Together they express the same rule from both sides: the implementer may not
change what no approved plan covers, and the reviewer may not manufacture
evidence outside the ledger.

## 4. Verify

Inside the target project, ask Claude:

> Use /damped-plan and register this project: goal = <your goal + metric>,
> hard constraints = <your constraints>, failures = <what's broken>.

Then propose a change and watch the flow: plan → blockers → (measurement) →
approval → scoped implementation → evidence → outcome. Inspect
`.damped-plan/events.jsonl` for the audit trail, or the MCP resources
(`damped://project/current/state`, `.../gate`).

For a scripted proof of the whole loop, run in this repo:

```bash
uv run python scripts/demo_end_to_end.py
```

## Notes on the approval semantics

`approve_plan` records who approved; it cannot verify a human typed it. The
guard refuses obvious self-approval names ("claude", "assistant", ...), and
the honest workflow is: Claude presents the ready_for_review plan, the user
says "approved", Claude calls `approve_plan` with the user's name. The
append-only event log preserves exactly what was claimed and when.
