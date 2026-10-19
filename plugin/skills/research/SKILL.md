---
name: research
description: Run research directions for a goal on the research-board MCP -- send research-scout subagents to find papers and the tweaks they suggest, approve the directions worth trying, spend points before building and testing for one, and reflect after each result to continue, halt or pivot. Use when the user asks to research approaches to a goal, to set up or run the research loop, when a goal is not met and nothing open addresses it, or while test results are pending and scouts could be working.
---

# Research loop

The research board keeps research directions for the human's goals: the papers behind each, the
tweak each suggests to a component, what was spent testing it and what came of it. You are the
**director**. You approve directions and trails, spend points, build and test, and reflect.
**Scouts** are `research-scout` subagents. They read the board, the ledgers and the web, never the
code, and record what they find.

## The loop

```
board() → scouts (background) → approve → spend → build, run_test → board() → reflect
```

1. **`board()`** lists every direction in the order to act on it: those needing a reflection, those
   with a result pending, those ready, those still earning, the proposals, and the closed ones. Its
   `next:` lines name the moves waiting on you.
2. **Send scouts in the background**, up to the `scouts` the rules allow. Send one per open
   direction to deepen it, and one per goal to look for a new direction. Give each the id it
   works on. Scouts cost nothing, so send them whenever results are pending.
3. **Approve or reject** with `approve(target, approved, why, rank=)`. A direction must be approved
   before anything is spent on it; `rank` sets the order to try them (1 first). Reject a trail
   that adds nothing, with the reason: its points stop counting, and the reason reaches the next
   scout.
4. **Spend before you work for a direction:** `spend(direction, action, target, expect)`. Then
   build, and run the target's tests with `run_test`. Only results recorded after the spend count
   for the direction. Work without spending is always allowed, but its results belong to no
   direction. Spend on a **test** (`TST-...`) rather than its contract when several arms share a
   contract: a spend on a test counts that test's runs only.
   **Spend right before you launch, and launch long runs in the background:**
   `run_test(test_id, wait=False)` answers at once with the RUN id and records the trials when the
   run ends; `status(view="runs")` shows it until then. Give a run of hours its `timeout_s`.
   **Keep scouts out while a test you paid for waits on its result.** Every hour with no research
   recorded on the board costs the waiting direction a point. Research is an earning trail, a new
   direction, a measured finding, a scout's question or an answer -- not a note. Each keeps research
   running for `running_minutes`. Send scouts when you spend, and send the next one when one
   returns. The board's `next:` line says when the clock is running and when the next point goes.
   The clock stops when the result is in, or when you halt the direction.
5. **Reflect when a result settles:** `reflect(direction, continue|halt|pivot, why)`. Nothing more
   is spent on that direction until you do. A pivot halts it; open the next one with
   `open_direction(..., pivot_from=...)`.

## Keeping briefs readable

A scout reads `board(direction=...)`: a head that always fits -- the human's standing rules for the
goal, your digest, open questions, the latest feedback, the papers already cited and an index --
and then pages through `section=` or fetches one record with `item=`. Two moves keep the head
useful as a direction grows:

- **`digest(direction, text)`** -- the facts so far, in at most 4000 characters, which every brief
  on the direction leads with. Rewrite it after each result and each scout round that changed the
  picture. Scouts propose edits in feedback; the digest is yours.
- **`evidence(direction, artifact, summary)`** -- attach a measured finding you made outside a
  declared test (a failure map, the table of a free check): a `.json`, `.csv`, `.md`, `.txt` or
  `.log` file no component claims and no test runs. The board keeps a copy and its digest, scouts
  read it with `ledger(evidence=...)`, and it counts as research. It earns `earn.evidence` (0 by
  default) and is never a spend's result.
- **Notes on a goal** -- `feedback("GOL-...", text)` reaches every brief on that goal: what has been
  measured before any direction holds it.

The human's standing rules ("actions are executed exactly, with no noise") belong in `goals.yaml`
under the goal as `constraints:`, which every brief carries. They are the human's: draft them and
leave them for the human to commit, as you would a goal.

## Answering scouts

- Open questions are listed on the board. Answer with
  `feedback(about, text, kind="answer", reply_to="FBK-...")`.
- An answer carries no weight: it is context, not a result.
- A question only you could answer means the evidence ledger dropped something the research
  needs. Answer it, then add that metric to the contract, so the next run records it and the next
  scout reads it from `ledger(run=...)` itself.

## The rules are yours to tune

`research.yaml` holds `focus` (the goal being pursued), `costs` (points per action), `earn` (what a
trail earns, `trail`, and a measured finding, `evidence`), `idle` (`per_hour`: points an idle hour costs, 0 for none; `running_minutes`: how long
a research record keeps research running) and `scouts`. It takes effect when committed, and the
board names the commit that last changed it, so a cost lowered to get a spend through is visible to
the human. A spend keeps the idle terms in effect when it was made, so changing them later reprices
no hour already waited. Change the rules when a reflection shows they are wrong, and say so in the
commit.

## Rules

1. **Research never counts as a result.** A trail is a reason to test. Goals are met by their
   measures, and designs are proven by their verifiers, as before.
2. **Scouts read no code.** Do not paste code into feedback or a brief. If a tweak cannot be judged
   without the code, that judgement is yours, made when you approve and build.
3. **Commit `.research/`** with your work, as you commit `.belief/` and `.consistency/`. If the
   board says `IGNORED .research/ledger.jsonl`, the repository's `.gitignore` drops the ledger:
   add the exception it names.
4. **The goals stay the human's.** A direction serves a goal in `goals.yaml`. If research shows a
   goal is wrong or out of reach, say so with component-belief's `note(subject="GOL-...")`.
