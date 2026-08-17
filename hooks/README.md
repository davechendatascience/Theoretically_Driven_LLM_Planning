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
