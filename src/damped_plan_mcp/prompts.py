"""MCP prompts (blueprint §16.2): reusable planning-discipline instructions."""

COMPILE_PROJECT_STATE = """\
Compile the current project into structured state for the damped-plan MCP.
Do NOT propose a method or solution yet.

Extract and register via register_project:
1. Goals: each with a measurable metric_name and target.
2. Hard constraints (must hold: compute, data, interfaces, safety, evaluation
   protocol) and soft constraints (preferences). If you cannot show evidence a
   hard constraint holds, leave its status UNKNOWN — UNKNOWN is a useful,
   first-class answer, not a failure.
3. Failure modes actually observed (symptom, subsystem), with evidence if any.
4. Facts, labeled observed / inferred / assumed.
5. Available resources and forbidden actions.

Then call get_project_snapshot and report the open unknowns.
"""

DRAFT_FEASIBLE_PLAN = """\
Draft exactly ONE structured candidate plan via create_plan. Requirements:

- kind: "measurement" if any hard constraint the plan depends on is UNKNOWN
  (the smallest safe experiment that resolves it); otherwise "implementation".
- Link goal_ids and, if one exists, the failure mode it addresses.
- State a causal hypothesis: why the failure happens, or why this change
  reaches the goal. Name alternatives if there are competing explanations.
- Scope the intervention: exact allowed_files, reversible if possible.
- Validation steps that could REFUTE the hypothesis, at least one required.
- decision_rule with both adopt_if and reject_if.
- rollback_description unless the intervention is reversible.

Then act on the returned evaluation: repair blockers with another create_plan
call (same id), or present the plan for approval. Do not edit source files
until the plan is EXECUTABLE (or the user approves a safe measurement plan).
"""

REVIEW_PLAN_BLOCKERS = """\
Call evaluate_plan for the active plan. For each blocker, apply the minimal
repair it describes — do not expand scope while repairing. If the blocker is
an UNRESOLVED_HARD_CONSTRAINT, prefer the smallest safe measurement plan that
resolves it over arguing the constraint is probably fine. Re-evaluate after
repairs and report the new status honestly.
"""

POSTMORTEM_UPDATE = """\
Convert what just happened into recorded state:

1. record_evidence for each artifact (test run, benchmark, profile, log),
   with polarity supports/refutes and links to the plan and constraints.
2. update_constraint_status for any constraint the evidence resolves
   (SAT needs evidence ids; UNSAT should be reported immediately).
3. record_plan_outcome: validated (requires evidence), rejected, or
   rolled_back, with a summary tied to the decision_rule.
4. Report the recommended_next_action to the user. Never report "fixed" or
   "validated" without the completed validation record.
"""
