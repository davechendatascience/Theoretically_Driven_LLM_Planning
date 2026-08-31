# plan-auto gate hook (opt-in)

`plan_auto_gate.py` is a stdlib-only Claude Code **PreToolUse** hook that
gives the plan-auto gate real teeth: it denies `Edit`/`Write`/`NotebookEdit`
calls for files not covered by an approved plan's `allowed_files`.

It reads the precomputed `.plan-auto/gate.json` (rewritten by the MCP server
on every mutation) — it never starts the server, so it adds only a few
milliseconds per edit.

## Enable for a target project

The reliable way is `scripts/install_integration.py`, which fills in the
absolute paths and picks an interpreter name that exists on this host (see
[Interpreter and shells](#interpreter-and-shells) — Windows has no `python3`,
many Linux distributions have no `python`):

```bash
uv run python scripts/install_integration.py --target /path/to/project
```

To write it by hand instead, add to the target project's
`.claude/settings.json` (or `settings.local.json`):

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write|NotebookEdit",
        "hooks": [
          {
            "type": "command",
            "command": "python3 /absolute/path/to/plan-auto/hooks/plan_auto_gate.py"
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
  that don't use plan-auto.
- Paths matching `always_allowed` (default: `.plan-auto/**`, `docs/**`,
  `*.md`) are always editable, so notes and the plan store itself stay
  friction-free.
- Otherwise the file must match some approved plan's `allowed_files` globs
  (`src/policy/*.py`, `tests/**`, bare names match any directory).
- Deny messages carry the server's precomputed explanation of what to do
  next (create a measurement plan, extend allowed_files and re-evaluate, ...).

## Modes (`PLAN_AUTO_HOOK_MODE` env var)

| Mode | Uncovered file | Corrupt/unreadable gate.json |
|---|---|---|
| `enforce` (default) | deny | allow (fail-open) |
| `warn` | escalate to the human for a decision | allow |
| `strict` | deny | deny (fail-closed) |

Set the mode in the same settings entry, e.g.
`"command": "PLAN_AUTO_HOOK_MODE=warn python3 /path/to/plan_auto_gate.py"`.

---

# plan-auto reviewer gate hook (opt-in)

`plan_auto_reviewer_gate.py` is the second stdlib-only **PreToolUse** hook.
Where `plan_auto_gate.py` stops the *implementer* from editing files no
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
        "matcher": "Bash|PowerShell",
        "hooks": [
          {
            "type": "command",
            "command": "python3 /absolute/path/to/plan-auto/hooks/plan_auto_reviewer_gate.py"
          }
        ]
      }
    ]
  }
}
```

The matcher includes `PowerShell` because Windows hosts expose it as a second
execution tool. Today the reviewer's own frontmatter grants only `Bash`, so
the extra name changes nothing — but it means widening that allowlist later
cannot silently open an ungated execution path.

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
- The deny reason restates the rule and points at `.plan-auto/artifacts/`,
  so the reviewer learns the ground rule at the moment it tries to break it.

## Configuration

| Env var | Effect |
|---|---|
| `PLAN_AUTO_REVIEWER_AGENTS` | Comma-separated agent types to gate (default `plan-reviewer`). Empty string makes the hook inert. |
| `PLAN_AUTO_REVIEWER_HOOK_MODE` | `enforce` (default) denies; `warn` escalates to the human instead. |

## Honest limit

Like `.plan-auto/commands.json`, this is an allowlist by convention — a
discipline boundary with reviewable provenance, not a security sandbox. It
also cannot stop a reviewer from asking the parent session to run a command
and narrate the result back; that failure mode belongs to the evidence layer,
not the capability layer.

---

# Interpreter and shells

Both hooks are stdlib-only and run on any Python 3. Getting them *invoked* is
the part that differs per host.

**Interpreter name.** There is no name that works everywhere: Windows ships no
`python3`, and many Linux distributions ship no `python`. Prefer a bare name
over an absolute path — a bare name needs no quoting, so the same command
string parses identically under `sh`, Git Bash, `cmd.exe`, and PowerShell,
whereas a *quoted* absolute path in command position is a string literal to
PowerShell unless prefixed with `&`. `scripts/install_integration.py` probes
for a working bare name and only falls back to an absolute path (warning when
it does).

**Encoding.** Hook payloads arrive on stdin as UTF-8, except that PowerShell
prepends a UTF-8 BOM when piping to a native executable. Both hooks decode with
`utf-8-sig` for that reason. This matters more than it looks: an unparsable
payload exits 0 (fail-open by design, so unrelated projects are never
bricked), so a BOM the hook could not skip would *silently* disable
enforcement while the hook still appeared installed. Regression tests cover
the BOM case in `tests/unit/test_gate_hook.py` and `test_reviewer_gate.py`.

**Latency.** The claim above that the gate hook adds "only a few milliseconds"
is about the hook's own work, which is a `gate.json` read. Process startup
dominates and is not always small: on a Windows host with real-time antivirus
scanning, bare CPython startup measured ~0.8 s, so each `Edit`/`Write` pays
that. It is the interpreter, not the hook — an empty `python -c pass` costs
the same. Do not route hooks through `uv run` to avoid the interpreter
question: that adds project resolution on top and measured 1.5–3.6 s per call
on the same host.
