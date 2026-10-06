---
name: consistency-belief
description: Check that a design claim is logically sound before (or while) building it, via the consistency-belief MCP -- axioms, definitions, lemmas and branches in consistency.yaml, verified by falsification probes served by status(view="probe"). Use when proposing a design or rule change, when a design claim is about to be stated as true, when an axiom or lemma is edited, or when asked whether the logic holds.
---

# Consistency belief workflow

`component-belief` measures whether the built thing works. `consistency-belief` asks
whether the reasons for the design follow: given the axioms, does each lemma and branch
hold, and where does it not? A branch is *proven* only by falsification trials that tried
to break it; nothing is proven by being stated.

## The loop

```
status(view="probe")  →  verify_step(target, trials=[...])  →  status(view="tree")
```

`probe` serves every open obligation with all a verifier may use: the claim, each
premise's statement, the derivation rule, the three strategies and the call that records
them. `obligations` is the shorter list; `tree` shows the DAG with badges;
`contradictions` shows what is refuted or ungrounded, with the counterexamples.
`tree` with `subject=<id>` draws one node's lineage alone; on a large ledger the whole tree is
too long to read inline.

## Delegate the probing

Verification belongs in a context that holds declarations and nothing else. Hand the
probe to the `consistency-verifier` subagent this plugin ships (`agents/consistency-verifier.md`):
its tool list has no Read, Grep or Bash, so it cannot open a file even by habit, and its
context is the probe text alone. Run it after `propose_branch`, after a restatement, and
before reporting any node as proven. Read its report; do not re-verify in the main session.

## Six rules

1. **A probe is a search for a counterexample, not a confirmation.** One pass is one
   `verify_step` call carrying three trials: `counterexample` (a scenario where every
   premise holds and the claim fails), `entailment` (an unstated assumption is a `gap`,
   named), `negation` (can NOT(claim) also be derived?). Independence is counted as
   distinct (strategy, actor) pairs: three `sound`s of one strategy are one probe repeated,
   recorded but not progress.

2. **The verifier reads no code.** A trial judges entailment from the premises. A clause
   that cannot be judged without opening a file is the finding: `outcome="gap"` naming the
   premise the claim needs. The server refuses a falsification whose counterexample or
   rationale names a source file. Whether the code matches the design is measured in
   component-belief and cited by the branch (`evidence: CTR-...` in its derivation rule).

3. **Propose before you build.** A design change is a branch: `propose_branch(id, subject,
   premises, claim, rationale)` first. The server rejects cycles and unknown premises, and
   warns when a claim describes a function or class instead of what must hold of any
   implementation. A subject is a component in belief.yaml, an interface (belief.yaml's
   between components, goals.yaml's between goals) or a goal. An axiom names the goal
   whose requirement it states (`goal:`). `status(view="coverage")` shows what is
   governed, planned or built with no design, and which goals no axiom traces to.

4. **Audit before you edit an axiom or lemma.** `audit_change(target_id, ...)` records the
   blast radius: every downstream node that becomes `STALE` and must be re-verified. Tell
   the user before the edit; never re-verify a stale branch by re-recording the old outcome.
   A trial vouches for a node's statement and its premises, not its derivation rule.
   Re-citing a `CTR-` or rewording the argument restates nothing and sets no trial aside.
   Pass the proposal to `audit_change` and it says which kind of change it is. When you
   wrap a folded YAML scalar, never break a line inside an id: the break folds into a
   space, so `CTR-a-` on one line and `b` on the next reads as `CTR-a-`.

5. **Declarations take effect when committed.** Axioms, definitions, lemmas, branches and
   policies live in `consistency.yaml`, read from git HEAD; `PENDING` in `status` means an
   edit is not in effect yet. The design is yours: commit it as you work, after
   `audit_change` for an axiom or lemma. The human's line is `goals.yaml` -- what the design
   is for and how that is measured -- which you never commit (component-belief's skill says
   how to propose a change to it). An axiom added to close a gap is a claim nothing verifies:
   say in the commit which requirement it states.

6. **Escalate for `decide()`.** An `ADOPT` verdict will not record without `approver=`.
   Present it, get the human's explicit approval, then pass their name. A policy criterion
   with `evidence: supported` also requires the cited contract supported in
   component-belief -- a design proven over a refuted measurement is proven of nothing.
   `note()` is inert (zero proof weight) and cannot close an obligation.

## Pinning what a branch cites

A branch's `evidence: CTR-x` says which contract measures it. When you have read that contract's
acceptance rule and tests against the claim, pin the citation: `evidence: CTR-x@<8 hex>`.
`status(view="coverage")` prints the pin to write.

- **Restating the branch, or a premise upstream, leaves its cited measurements unreviewed.** The
  contract may still read supported, but it measured the old claim. Re-read it against the new
  claim; strengthen the test if the claim now says more; then write the new pin. `audit_change`
  lists them before you restate.
- **A pin lives in the derivation rule, which no fingerprint covers,** so writing one restates
  nothing and sets no trial aside.
- **`contracts no branch cites`** in the coverage view lists them by what they measure.
  On a component: declare the design it measures, or keep it as a plain regression
  measure, knowingly. A goal's measure is explained by the goal's outcome. `(no evidence
  yet)` marks one nothing has measured.

## Referencing sources

A declaration may name the works it came from, as a paper cites its references. It is optional,
and most useful on an axiom taken from a paper, a book or a standard.

```yaml
sources:
  - {id: SRC-siciliano2009-robotics, title: "Robotics: Modelling, Planning and Control",
     authors: [Siciliano, Sciavicco, Villani, Oriolo], year: 2009}
axioms:
  - id: AXM-pseudo-inverse-projects-onto-null-space
    references: [{source: SRC-siciliano2009-robotics, at: "sec. 3.5.1"}]
```

- **A reference weighs nothing.** It is not a premise, not part of a fingerprint and never in a
  probe, so adding one restates nothing, and citing a famous result makes no claim count. If a
  lemma rests on a paper's result, declare that result as an axiom and reference the paper from it.
- **Write only what you have seen.** A doi, arXiv id, ISBN, url or `at:` you are not sure of is
  left out, not guessed: nothing checks that a source says what the node states, so a made-up one
  reads exactly like a real one. Quote an `at:` that holds a comma.
- `status(view="sources")` is the reference list. `DANGLING_REFERENCE` and `UNREFERENCED_SOURCE`
  are advisory; fix them like a broken link.

## Linking code to claims

When you write the code that realizes a branch, lemma or definition, tag the region. A tag is
an assertion that you read this code against this claim. It is not a proof, and it moves no
proof state.

```python
# tdlp:begin CODE-runner-exit-code-fallback
# tdlp:implements BRN-runner-captures
...the code...
# tdlp:end CODE-runner-exit-code-fallback
```

1. **Pin before you commit.** `stamp-monitor links` lists your uncommitted regions with the exact
   header lines that align them, the `@xxxxxxxx` pins. Read the region against the claim
   (`status(view="branches", subject=<id>)`), then paste the lines and commit both together.
2. **A stale pin is a review, not a chore.** `BODY_CHANGED` means the code moved since someone
   read it against the claim, and it names the revision to diff against. `CLAIM_RESTATED` means
   the claim or a premise upstream changed, and it names which. Re-read, then re-pin. Never
   re-pin a region you did not re-read.
3. **Cite the theory inside a region that declares it.** A `DEF-`/`BRN-` id in a comment or
   docstring outside such a region is `UNTRACKED_MENTION`, and nothing will notice when it rots.
   One that names nothing is `DANGLING_MENTION`. Fix those first.
4. **Before you restate a node,** `audit_change` lists the regions whose pins it will stale.
5. **The verifier never sees any of this.** Links live in stamp-monitor, not in `status`. Do not
   paste a region into a probe or a trial. Whether code realizes a claim is the implementer's
   judgment, and whether it works is component-belief's measurement.

## Citations

Every response ends with a `basis:` line naming the trial set behind it. Quote it when
you quote a proof state. "BRN-x is proven" without its basis is narration.
