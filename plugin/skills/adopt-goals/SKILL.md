---
name: adopt-goals
description: Set up goals.yaml in a project that already uses TDLP -- draft the human's goals, the interfaces between them and how each is measured, for the human to review and commit. Use when the user asks to set up, add, draft or adopt goals, or when status(view="goals") says no goals are in effect.
---

# Setting up goals in a project that already uses TDLP

`goals.yaml` is the human's: each goal's outcome and the contract that says it is met, each
interface between goals and the contract its hand-over must pass, and the tests those run. You
draft it; the human commits it. Everything below the goals stays yours.

Only step 4 waits on the human. Nothing else in the procedure does.

## 1. Read what exists

- `status(view="goals")`, with no goals in effect, lists the **candidate measures**: contracts an
  end-to-end test already measures, with their current state.
- `status(view="belief")` shows every contract's state; `belief.yaml` shows the components.
- The README and the declarations usually say what the project is for. Ask the human one
  question only if the outcomes are not clear from them: "what should this project do, in a
  sentence per outcome?"

## 2. Draft goals.yaml in the working tree -- never commit it

- **Goals: two to five,** each an outcome the human would say in one sentence, not a component's
  behaviour. Each names one measure.
- **Choose each measure one of two ways:**
  - **Promote** an existing end-to-end contract when it already measures the outcome and its test
    changes rarely. Copy the contract and its test into `goals.yaml` **with the same ids**, the
    contract's `subject` and the test's `targets` changed to the goal. Its evidence carries over:
    trials are keyed by contract id. The test's files become the human's, so promote only a test
    you would not edit in routine work.
  - **Draft an acceptance test** otherwise: a short file in `acceptance/` with its own
    `conftest.py`, driving only the project's public surface, one criterion per test name.
    Keep it out of `tests/` and away from fixtures you edit: every file a goal's test names or
    `reads:` becomes the human's, and the guard refuses your commits to it.
- **Interfaces:** one per hand-over between two goals' systems (`from`, `to`, `hands_over`), each
  measured by a `layer: interface` test.
- **Policy:** `POL-goals`, naming every measure with `require: supported`.
- **Check the draft:** `status(view="goals")` reads a `goals.yaml` in the working tree as a draft,
  lists its goals and any issues (`UNMEASURED_GOAL`, `MEASURE_OUTSIDE_GOALS`, ...), and puts
  nothing in effect. Ids promoted from `belief.yaml` show as carried over, which is expected.
  Run any new acceptance test once in your shell to see it pass; its evidence comes later.

## 3. Install the guard

`uvx --from "git+https://github.com/davechendatascience/Theoretically_Driven_LLM_Planning@tdlp--v<version>" tdlp-guard install`
(the goals view prints the exact command). From here a commit of yours that touches the goal
set is refused, so the draft cannot slip into a commit of yours.

## 4. Hand the draft to the human, and wait

For each goal: the outcome in one line, how it is measured, and -- for a promoted measure -- its
current state. Say which files become theirs. They edit what they like and commit
`goals.yaml` (and `acceptance/`) themselves. **This is the only step that waits on them.**

## 5. After their commit

- Remove from `belief.yaml` every id now declared in `goals.yaml`: the goals view's issues list
  them as `DUPLICATE_ID`.
- Tag each component with the goal it serves (`goal: GOL-...`), so a goal's evidence goes stale
  when that code changes.
- Commit `belief.yaml` (yours), then run each goal's test that has no evidence yet.
- `status(view="goals")`: no issues, and every promoted measure reads the state it had before the
  move.

## 6. From then on

- Propose, never edit: `note(subject="GOL-...", text=...)` with what you would change and the
  evidence ids behind it. The human reads it in the goals view.
- `decide` answers to `POL-goals` and needs no approver while no commit of yours has touched the
  goal set.
