# plan-auto

A local MCP server that gates nontrivial changes behind one rule:

> **No change without an expectation that could fail, and no evidence without a change.**

An agent may retrieve knowledge and propose freely. It may not declare a change
executable until the change has a scoped intervention, adopt/reject criteria
fixed in advance, a rollback story, and every hard constraint evidence-backed —
and it may not call anything *validated* without a recorded observation that
could have come out otherwise.

## Why the rule is shaped that way

The code already exists. Observing it tells you **what it is** — a fact you
could have got by reading. It cannot tell you whether your model of it is
right. Only intervening can do that:

| | |
|---|---|
| **The model** | the developed repository itself |
| **The belief** | what the code is expected to produce |
| **The evidence** | what it actually produces |
| **Effectiveness** | the agreement between them |

A test run against unchanged code is therefore *state*, not evidence. It could
not have come out otherwise.

This is the interventionist view rather than the observational one, and it fits
a codebase — which you can manipulate — better than a workflow designed for
data you cannot.

## What it enforces

- **`unknown` is never coerced.** A proposition leaves `unknown` only with a
  citation — `not_applicable` included, which in the previous design was the
  one uncited escape.
- **Measurement before commitment.** A safe, reversible measurement is the one
  thing allowed through a closed gate.
- **Drafting is separate from approval.** Only a human authorises a change.
  Self-approval is refused, and an approved plan cannot be edited — moving a
  band after signature requires a successor plan and a fresh signature.
- **Scoped execution.** An authorised change may write only its declared files,
  enforced by an opt-in PreToolUse hook reading a precomputed `gate.json`.
- **Review that cannot manufacture evidence.** The fresh-context `plan-reviewer`
  agent attacks a change before approval and holds no mutating tools, so it
  cites recorded artifacts instead of producing numbers of its own.
- **Expectations must be falsifiable.** Six admissible forms; an expectation
  naming no instrument, or admitting no failing outcome, is refused at
  construction rather than warned about.
- **Nothing computed that no reader consumes.** Shipped as a test, not a
  principle. See `kernel/invariants.py::i5_every_field_has_a_reader`.

## The expectation grammar

Full detail in [docs/expectation_grammar.md](docs/expectation_grammar.md).

| Form | Falsifiable when |
|---|---|
| `range` | bounds are present and finite |
| `invariance` | a baseline is recorded |
| `golden` | a golden output exists and the input set is non-empty |
| `exit` | a command is named |
| `witness` | an input and its expected output are both given |
| `membership` | the allowed set is non-empty |

The universal logic claim — *"F never returns null for any input in class X"* —
is **not** mechanically decidable and is refused. It is admitted only after
reduction to a finite witness set.

That makes the adversarial reviewer load-bearing rather than advisory: it is
the natural author of the witnesses that make a logic-level claim checkable at
all. A reviewer objection becomes a runnable counterexample, added to the
golden set before either arm runs.

## Architecture

Three **layers**, which update by different rules. A hard constraint is a
normative gate, not a causal claim — collapsing the two is what broke the
previous design.

```
A  Commitments   Objective / Goal / Constraint / Given / FailureMode
                 change only by human edit; evidence never moves them
B  The loop      Change / Expectation / Outcome / Intent
                 the only place belief updates
C  Enforcement   PreToolUse scope hook, human approval, append-only log
                 mechanism; holds no data
```

`Change` **references** the commitments it depends on rather than auditing them,
so an unreferenced constraint simply does not bind — which removes the uncited
`not_applicable` escape by construction rather than by adding a check.
`polarity` and `Goal.met` are derived, never stored.

## Quick start

```bash
uv sync
uv run pytest -q
uv run python scripts/demo_end_to_end.py   # blocked -> measure -> unblock
```

**Known-failing:** 17 tests in `tests/unit/test_research_trigger.py` (11) and
`test_research_join.py` (6) fail with `ModuleNotFoundError: No module named
'tests'` — a test-packaging defect, pre-existing and unrelated to the kernel.
They are listed here rather than omitted; the previous README advertised a test
count without disclosing them.

## Set up for your project

Four pieces, each opt-in, all configured in the *target* project.

```bash
uv run python scripts/install_integration.py --target /path/to/project
uv run python scripts/install_integration.py --target /path/to/project --dry-run
```

Idempotent; `--no-hooks` / `--no-skill` / `--no-reviewer` skip individual
pieces. Manually:

**1. Register the server** — `.mcp.json` at the target repo root:

```json
{
  "mcpServers": {
    "plan-auto": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/plan-auto", "run", "plan-auto"],
      "env": { "PLAN_AUTO_DATA_DIR": "/absolute/path/to/your-project/.plan-auto" }
    }
  }
}
```

**2. Install the skill**: `cp -r /path/to/plan-auto/skills/plan-auto .claude/skills/`

**3. Enable the hooks** (turns the gate from advisory into real denials): add the
PreToolUse entries from [hooks/README.md](hooks/README.md).
`plan_auto_gate.py` (`Edit|Write|NotebookEdit`) denies edits no authorised
change covers; `plan_auto_reviewer_gate.py` (`Bash|PowerShell`) denies
*execution* to the reviewer while leaving read-only inspection open.

**4. Install the reviewer**: copy `agents/plan-reviewer.md` into
`.claude/agents/`.

Then restart Claude Code in the target project — **MCP servers connect at
session start**, so a rename or a fresh install is not live until you do.

## State on disk

```text
.plan-auto/
├── project.json      goals, constraints (+statuses), failure modes
├── plans/P-0001.json one file per plan
├── evidence/EV-0001.json
├── events.jsonl      append-only audit log
└── gate.json         derived snapshot the PreToolUse hook reads
```

**Legacy stores.** This project was previously named `damped-plan` and wrote to
`.damped-plan/`. That name is still honoured everywhere — `resolve_data_dir`
prefers `.plan-auto/` and falls back, `DAMPED_PLAN_DATA_DIR` is still read, and
the gate hook searches both. Existing projects need no change. A rename that
orphans a ledger is not a rename.

## Status

Two trees, deliberately:

- **`src/plan_auto/`** — the shipping server. 12 MCP tools, 7 resources, 4
  prompts, both PreToolUse hooks, the allowlisted command runner
  (`run_validation`) that turns captured command results into evidence
  mechanically, and the structured-observation channel that feeds the
  posterior check.
- **`src/kernel/`** — the intervention-centred rebuild: three layers, the
  expectation grammar, executable invariants I1–I5, a total deterministic
  order, and a lossless v1 migrator. **Library code plus tests only** — wired
  to no MCP tool or hook yet, so the server above keeps running untouched.

### Measured, not claimed

Migrating every live store through `kernel.migrate` yields:

```
admissible expectations =  40
degraded to Intent      = 191
```

**83% of every prediction ever written across five real projects cannot be
admitted** — almost entirely because no instrument was ever named, so nothing
was positioned to produce the outcome. One store had zero admissible
expectations across 38 changes. Nothing is lost: each is preserved as an
`Intent`, flagged, and never counted as evidence.

That number is the honest argument for the rebuild, and it is the kind of
number the previous design could not produce about itself.

### Known gaps

- The kernel is not wired to the MCP surface or the hooks.
- The command registry has no sanctioned author: no MCP tool writes
  `commands.json`, so an agent told to prefer `run_validation` can only comply
  by writing its own allowlist. That should be human-authored.
- No project-level model document, and no human-only terminal objective — so
  each change's expectations are local, with no parent to be consistent with.
- `services/corpus.py` still names a removed module in a docstring.
