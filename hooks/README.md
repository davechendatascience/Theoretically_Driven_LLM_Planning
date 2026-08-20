# damped-plan gate hook (opt-in)

`damped_plan_gate.py` is a stdlib-only Claude Code **PreToolUse** hook that
gives the damped-plan gate real teeth: it denies `Edit`/`Write`/`NotebookEdit`
calls for files not covered by an approved plan's `allowed_files`.

It reads the precomputed `.damped-plan/gate.json` (rewritten by the MCP server
on every mutation) — it never starts the server, so it adds only a few
milliseconds per edit.

## Enable for a target project

Add to the target project's `.claude/settings.json` (or
`settings.local.json`):

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write|NotebookEdit",
        "hooks": [
          {
            "type": "command",
            "command": "python3 /absolute/path/to/damped-plan-mcp/hooks/damped_plan_gate.py"
          }
        ]
      }
    ]
  }
}
```

## Behavior

- Finds `gate.json` by walking up from the edited file (falls back to `cwd`).
  **No gate file → silent allow** — the hook never interferes with projects
  that don't use damped-plan.
- Paths matching `always_allowed` (default: `.damped-plan/**`, `docs/**`,
  `*.md`) are always editable, so notes and the plan store itself stay
  friction-free.
- Otherwise the file must match some approved plan's `allowed_files` globs
  (`src/policy/*.py`, `tests/**`, bare names match any directory).
- Deny messages carry the server's precomputed explanation of what to do
  next (create a measurement plan, extend allowed_files and re-evaluate, ...).

## Modes (`DAMPED_PLAN_HOOK_MODE` env var)

| Mode | Uncovered file | Corrupt/unreadable gate.json |
|---|---|---|
| `enforce` (default) | deny | allow (fail-open) |
| `warn` | escalate to the human for a decision | allow |
| `strict` | deny | deny (fail-closed) |

Set the mode in the same settings entry, e.g.
`"command": "DAMPED_PLAN_HOOK_MODE=warn python3 /path/to/damped_plan_gate.py"`.

---

# damped-plan reviewer gate hook (opt-in)

`damped_plan_reviewer_gate.py` is the second stdlib-only **PreToolUse** hook.
Where `damped_plan_gate.py` stops the *implementer* from editing files no
approved plan covers, this one stops the *reviewer* from executing anything.

The reviewer is an evidence **consumer**: evidence enters the ledger through
`run_validation` (allowlisted argv, immutable artifact, polarity from the exit
code) or the implementing session's `record_evidence`. A reviewer that re-runs
the suite in its own shell produces a number with no `artifact_uri` and no
event — the hand-narrated evidence that `agents/plan-reviewer.md`'s own depth
policy tells reviewers to distrust. This hook makes that ground rule mechanical
instead of merely written down.

Read-only inspection stays open, because the predictive-contract review needs
to compare `context_fixed` against the actual diff.

## Enable for a target project

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "python3 /absolute/path/to/damped-plan-mcp/hooks/damped_plan_reviewer_gate.py"
          }
        ]
      }
    ]
  }
}
```

Both hooks can be registered side by side — they match different tools.

## Behavior

- Fires only when the PreToolUse payload's `agent_type` is a gated reviewer
  agent (default: `plan-reviewer`). **Every other agent — the main session
  included — passes through untouched.**
- Allows read-only inspection: `git diff|status|log|show|rev-parse|ls-files`
  (leading `-C`/`-c` options are skipped), plus `cat`, `head`, `tail`, `ls`,
  `wc`, `grep`, `rg`, `jq`, and `find` without `-exec`/`-delete`-style options.
- Denies everything else, including any command containing `;`, `|`, `&`,
  backticks, `$`, or redirection — those could chain past the argv check.
- The deny reason restates the rule and points at `.damped-plan/artifacts/`,
  so the reviewer learns the ground rule at the moment it tries to break it.

## Configuration

| Env var | Effect |
|---|---|
| `DAMPED_PLAN_REVIEWER_AGENTS` | Comma-separated agent types to gate (default `plan-reviewer`). Empty string makes the hook inert. |
| `DAMPED_PLAN_REVIEWER_HOOK_MODE` | `enforce` (default) denies; `warn` escalates to the human instead. |

## Honest limit

Like `.damped-plan/commands.json`, this is an allowlist by convention — a
discipline boundary with reviewable provenance, not a security sandbox. It
also cannot stop a reviewer from asking the parent session to run a command
and narrate the result back; that failure mode belongs to the evidence layer,
not the capability layer.
