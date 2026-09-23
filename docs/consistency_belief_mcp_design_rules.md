# Consistency Belief-Update MCP: Design Rules

## 1. Ground Every Node Axiomatically
1. Represent the target system, architecture, and design decisions as a Directed Acyclic Graph (Proof DAG) rooted in declared Axioms.
2. An Axiom is a non-negotiable physical invariant, formal requirement, environmental constraint, or foundational assumption.
3. Every component specification, contract, or architecture change must be a branch that traces transitively back to declared axioms.
4. Ungrounded branches (floating claims with no path to axioms) are rejected or marked `UNGROUNDED`.

## 2. Enforce Mechanical Acyclicity Prior to Semantic Reasoning
1. The proof graph kernel must strictly forbid circular dependencies ($A \implies B \implies A$).
2. Acyclicity is checked deterministically upon node insertion, never delegated to an LLM.
3. Any circular proposal is rejected immediately with the exact cycle trace.

## 3. Treat Consistency as Falsifiable Measurement, Not Narration
1. An LLM agent has no direct write-path to mark a branch as proven or consistent. There is no `set_consistency` tool.
2. Consistency is measured via structured, falsifiable verification trials (adversarial counterexample search, entailment gap detection, and negation symmetry checks).
3. The prompt, model metadata, temperature, and raw probe responses are captured, hashed, and committed to an immutable append-only ledger (`.consistency/evidence.jsonl`).

## 4. Distinguish Proven, Refuted, and Open Obligations
1. An unverified or under-tested branch is an open proof obligation (`OBLIGATION`, analogous to Lean's `sorry`).
2. A single valid, realizable counterexample transitions a branch into `REFUTED`.
3. A branch is `PROVEN` only when:
   - All transitive ancestors are grounded in declared axioms.
   - It has completed at least $n_{\min}$ independent verification trials.
   - Its consensus pass rate meets or exceeds the declared threshold.
   - Zero unresolved counterexamples or active contradictions exist.

## 5. Calculate Topological Blast Radii on Mutation
1. When an upstream axiom, definition, or lemma is modified, amended, or refuted, the kernel computes its topological blast radius.
2. All downstream derived branches and contracts are immediately marked `STALE` and their proven status revoked until re-verified against the new premise.

## 6. Preserve Trial-Level Evidence and Provenance
1. Store individual verification trials; never collapse raw probe outputs into un-auditable aggregates.
2. Support non-destructive corrections via amendments that fold over prior trials, preserving the historical trail of why a verification was reclassified.
3. Mark qualitative commentary and hunches with `provenance=asserted` (via `note()`), which carries zero proof weight and cannot satisfy proof obligations.

## 7. Separate Measurements, Proof State, and Adoption Decisions
1. Probes measure semantic properties of a single derivation step; the Proof DAG tracks global deductive consistency; policies govern release and adoption.
2. Acceptance policies explicitly declare required verification thresholds and safety criteria.
3. Adoption of a design branch requires an explicit human approver; an agent cannot approve its own design.

## 8. Expose Clear, Inspectable Status Views
1. Provide an ASCII proof tree (`status(view="tree")`) visualizing the path from root axioms down to terminal branches with verification badges.
2. Surface open proof obligations explicitly (`status(view="obligations")`), indicating exactly how many verification trials remain.
3. Surface active contradictions and discovered counterexamples (`status(view="contradictions")`).

## 9. Name the Components a Design Governs

`consistency.yaml` opens with the components its designs speak for, and every branch's `subject`
names one of them:

```yaml
components:
  - {id: CMP-proof-dag, note: the DAG kernel and the verification state over it}
  - CMP-trial-ledger
```

The list is an import, not a copy. `belief.yaml` (component-belief) owns each component — its
purpose, `code:` paths, contracts and measured evidence — and consistency-belief reads that file
at git HEAD, one way and read-only, to check both ends of the join:

- a listed id `belief.yaml` no longer declares is `REMOVED_COMPONENT`;
- a branch whose subject is a declared component missing from the list is `UNLISTED_SUBJECT`;
- a subject that is a `CMP-` id `belief.yaml` no longer declares is `REMOVED_SUBJECT` — the
  component was deleted or renamed, so that design governs nothing;
- a subject in prose is `UNATTACHED_SUBJECT`, and a `CMP-`/`CTR-` id cited in a
  `derivation_rule` that `belief.yaml` does not declare is `UNKNOWN_EVIDENCE`.

All of them are advisory: whether a claim follows from its premises does not depend on whether
anyone built it, so a node keeps its place in the proof DAG either way. They exist because the
opposite failure is silent — a design left behind by a component that was deleted reads exactly
like a design that is still true.

`status(view="coverage")` reads both files and sorts every component into **governed** (code and a
declared branch), **undeclared design** (code nobody justified — prune it or declare the design),
**planned** (a design declared before anything is built, which is allowed) and **broken**. The list
is optional: a project without one is still checked branch by branch, and a project with no
`belief.yaml` at all keeps working with subjects unchecked.
