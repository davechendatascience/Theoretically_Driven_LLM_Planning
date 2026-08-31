# The Expectation grammar

Status: **design draft.** Published *before* kernel code exists, deliberately —
otherwise the implementer defines the set they are measured on, and
`expectations_that_cannot_fail == 0` passes by construction.

An `Expectation` is admitted only if it matches one of the forms below. The
central rule — *no change without an expectation that could fail* — is
enforceable exactly to the extent that "could fail" is decidable per form.

## The forms

| # | Form | Statement | Is "could fail" decidable? |
|---|---|---|---|
| **E1** | Range | metric `M` lands in `[lo, hi]` | **Yes.** Fails iff the range is bounded and `lo <= hi`. Reject unbounded ranges at construction |
| **E2** | Invariance | metric `M` is unchanged from baseline `b` | **Yes, but only with a recorded baseline.** This is v1's live bug: `no_change` with `expected_range: null` is unfailable. Baseline becomes required |
| **E3** | Golden equality | unit `U` on input set `I` produces output byte-identical to recorded golden `G` | **Yes.** Fails iff any byte differs. Requires `G` recorded and `I` non-empty |
| **E4** | Exit status | command `C` exits 0 | **Yes** |
| **E5** | Witness | for input `z`, unit `U` produces `y` | **Yes.** This is E3 with `|I| = 1` |
| **E6** | Set membership | no file outside `S` is modified; symbol `X` is absent from module `M` | **Yes**, if `S` and the predicate are computable |
| **E7** | Universal logic claim | "`F` cannot return null for **any** input in class `X`" | **NO — not decidable in general** |

## The result that changes the design

`docs/redesign.md` §6.1 asked whether a logic-level claim is mechanically
checkable. **It is not.** E7 is the form the design wanted, and it fails: `X` is
typically infinite or unspecified, so no procedure decides whether some Outcome
would count as a miss.

E7 is therefore **admitted only after reduction to a finite, enumerated witness
set** — that is, rewritten as a conjunction of E5 or a single E3.

```
"F never returns null for class X"        -> REJECTED at construction
"F does not return null for z1..z12"      -> ADMITTED as 12 x E5
```

This has a consequence worth stating plainly:

> **The reviewer's counterexamples are not a review nicety. They are the
> mechanism by which a logic-level claim becomes checkable at all.**

An implementer proposing an E7 claim must have it reduced to witnesses, and the
adversarial reviewer is the natural author of those witnesses — it is trying to
find the `z` where the claim breaks. The review step moves from advisory into
the formalism.

## Two kinds that are not Expectations

Migration turns up records that cannot be Expectations without either lying or
losing them. Each gets its own kind rather than being forced or dropped.

- **`Intent`** — a stated direction with no check attached (`direction` set,
  `expected_range: null`, `expected_pattern: ""`). Seven live predictions are
  of this shape, one on a plan recorded `validated`. Preserved, flagged, never
  counted as evidence. This is why `expectations_that_cannot_fail == 0` is
  scoped to Expectations: Intents are a different kind, not a violation.
- **`Given`** — a recorded observation no intervention produced. State, not
  evidence. It cannot corroborate or refute, because it could not have come out
  otherwise.

## Construction rules

1. Every Expectation names the instrument that will produce its Outcome, and
   that instrument must be registered — a step with `kind: "command"` and
   `command: null` is rejected, not warned about.
2. E2 requires a recorded baseline. No baseline, no invariance claim.
3. E7 is rejected; its witness reduction is admitted.
4. An Expectation is frozen at first set and hashed. Later revision is recorded
   with both hashes and the timestamp relative to first Outcome, never blocked.
