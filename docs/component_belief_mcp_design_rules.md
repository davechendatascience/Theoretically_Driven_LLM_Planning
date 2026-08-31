# Component Belief-Update MCP: Design Rules

## 1. Model the System Explicitly

1. Represent the target system as a directed graph of components and interfaces.
2. Treat each component as a bounded unit with declared inputs, outputs, dependencies, and downstream consumers.
3. Treat each interface as a first-class object with a schema, semantic assumptions, units, coordinate conventions, timing assumptions, and compatibility checks.
4. Do not create nodes for trivial implementation details. Create a node only when it has an independently testable capability, a meaningful failure mode, and an actionable remediation path.
5. Maintain stable component and interface identifiers across versions.

## 2. Require Testable Contracts

1. Every component must declare a contract before its evidence can contribute to belief updates.
2. A contract must specify accepted input conditions, expected output properties, measurable metrics, pass/fail or graded acceptance rules, and known exclusions.
3. Contracts must distinguish capability claims from implementation details.
4. Contracts must state the operating distribution or conditions under which their claims are intended to hold.
5. Interface contracts must state what the producer guarantees and what the consumer assumes.
6. Reject contracts that cannot be evaluated by a registered test or observable telemetry.

## 3. Preserve Evidence Provenance

1. Store trial-level evidence; do not store aggregates as the only source of truth.
2. Every evidence record must include component or interface ID, test ID, timestamp, system version, configuration, input-condition metadata, result, and metric values.
3. Evidence records must be immutable after ingestion. Corrections must create superseding records with an audit trail.
4. Record enough metadata to distinguish non-comparable trials, including software revision, model/checkpoint revision, hardware identity, calibration state, environment, dataset revision, and random seed when applicable.
5. Keep test definitions versioned. A changed test is not evidence from the same measurement process unless explicitly mapped.
6. Mark evidence quality and validity separately from test outcome.

## 4. Separate Measurements, Beliefs, and Decisions

1. Measurements are observed facts; beliefs are inferred uncertainty estimates; decisions are policy outputs. Never overwrite one layer with another.
2. Maintain belief state per component-contract-condition slice, not only per component globally.
3. Report uncertainty, evidence volume, and applicability conditions with every belief estimate.
4. Do not interpret a posterior or pass rate as proof of universal correctness.
5. Allow qualitative engineering judgment only as explicit priors, utility weights, contract definitions, or annotations; never disguise it as measured evidence.
6. Keep raw measurements available so belief models can be replaced or recomputed.

## 5. Update Beliefs Incrementally

1. Update beliefs whenever valid evidence is ingested.
2. Support simple pass/fail updates as the minimum viable model.
3. Preserve sufficient statistics and raw evidence so more expressive models can be added later.
4. Partition or condition belief updates when operating conditions materially affect performance.
5. Detect and surface regressions by comparing belief states across compatible system versions.
6. Do not pool evidence across incompatible conditions without an explicit modeling or normalization decision.
7. Support an “insufficient evidence” state; do not force a strong verdict from sparse data.

## 6. Use Three Test Layers

1. Require component tests for local capability contracts.
2. Require interface tests for compatibility between connected components.
3. Require end-to-end tests for task-level success and interaction effects.
4. Do not infer component health solely from end-to-end outcomes when component-level evidence is available.
5. Do not treat passing component tests as proof of end-to-end correctness.
6. Link each end-to-end outcome to the relevant component and interface observations from that run whenever possible.

## 7. Diagnose Before Optimizing

1. When an end-to-end test fails, rank likely bottlenecks using current component, interface, and contextual evidence.
2. Distinguish confirmed failures, suspected failures, unobserved components, and blocked downstream components.
3. Recommend investigation of the most decision-relevant uncertainty, not automatically the lowest measured score.
4. Prefer a focused discriminating test when the likely causes remain ambiguous.
5. Do not recommend optimization when instrumentation or test coverage is the limiting factor.
6. Attach a reason, evidence references, and confidence level to every diagnostic recommendation.

## 8. Plan Each Evaluation Round

1. Accept a development goal, candidate changes, available budget, risk constraints, and current belief state.
2. Select tests that maximize expected decision value under time, compute, hardware, and safety constraints.
3. Prefer tests that can change the next engineering decision over tests that merely add redundant evidence.
4. Balance regression coverage, uncertain high-impact components, interfaces, and end-to-end validation.
5. Schedule required safety or release-gate tests regardless of expected information gain.
6. Make the rationale for every selected and skipped test inspectable.

## 9. Make Decisions Explicit

1. Separate acceptance criteria from observed metrics.
2. Define adoption, rejection, hold, rollback, conditional deployment, and further-testing policies explicitly.
3. Allow decisions to depend on capability, uncertainty, safety constraints, resource cost, and task impact.
4. Do not collapse all criteria into a single score unless the utility function and weights are visible and editable.
5. Return conditional recommendations when a component performs differently across conditions.
6. Record each decision, its policy version, supporting evidence, assumptions, and unresolved risks.

## 10. Design for Auditing and Iteration

1. Every report must trace conclusions back to contracts, tests, evidence records, and model versions.
2. Every belief estimate must be reproducible from versioned inputs.
3. Every agent-generated summary or recommendation must identify whether it is derived from evidence, a declared prior, or an assumption.
4. Never permit an LLM to silently invent measurements, test results, causal links, or confidence levels.
5. Require human approval for changes to contracts, acceptance thresholds, priors with material impact, utility weights, and release decisions.
6. Design the MCP as an append-only learning system: new feedback updates knowledge while preserving prior states and the reasons they changed.
7. Optimize for clarity of diagnosis and actionability over theoretical model complexity.

## 11. Minimum Required Outputs

For each evaluation cycle, the MCP must produce:

1. Current system graph and changed components/interfaces.
2. Test coverage and evidence validity summary.
3. Updated belief state, uncertainty, and applicable conditions for each relevant contract.
4. End-to-end outcomes and their relation to local evidence.
5. Ranked bottlenecks, regressions, and unresolved uncertainties.
6. Recommended next tests and/or engineering actions, with rationale.
7. Explicit decision status and remaining release or safety blockers.
