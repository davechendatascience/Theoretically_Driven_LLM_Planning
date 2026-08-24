"""Application service: every tool call goes through here.

Each mutating operation runs under the store lock, appends events, and
rewrites gate.json, so the PreToolUse hook and the event log can never
drift from state.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import (
    ConstraintStatus,
    GATE_OPEN_STATUSES,
    NextAction,
    Plan,
    PlanEvaluation,
    PlanIndexEntry,
    PlanStatus,
    ProjectSnapshot,
    ProjectSummary,
    ConstraintView,
    TERMINAL_PLAN_STATUSES,
)
from .render import reports
from .services import (
    command_runner,
    constraint_service,
    evaluation,
    micro_damping,
    narration,
    normalize,
)
from .store import JsonStore
from .store import events as event_log
from .store import gate as gate_store

# Approver names that look like the model approving its own plan.
SELF_APPROVAL_NAMES = {"claude", "assistant", "ai", "agent", "model", "llm", "bot", ""}

VALID_OUTCOMES = {
    "validated": PlanStatus.VALIDATED,
    "rejected": PlanStatus.REJECTED,
    "rolled_back": PlanStatus.ROLLED_BACK,
}


class WorkspaceError(ValueError):
    """Operation refused; the message tells the caller how to proceed."""


class Workspace:
    def __init__(self, data_dir: Path):
        self.store = JsonStore(data_dir)

    # -- helpers ------------------------------------------------------------

    def _require_project(self):
        project = self.store.load_project()
        if project is None:
            raise WorkspaceError(
                "No project is registered yet. Call register_project with at least "
                '{"name": "...", "goals": [...], "constraints": [...]} first.'
            )
        return project

    def _require_plan(self, plan_id: str) -> Plan:
        plan = self.store.load_plan(plan_id)
        if plan is None:
            known = [p.id for p in self.store.list_plans()]
            raise WorkspaceError(
                f"No plan {plan_id!r} exists. Known plans: {known or 'none'}. "
                f"Create one with create_plan."
            )
        return plan

    def _evaluate(self, plan: Plan) -> PlanEvaluation:
        project = self._require_project()
        return evaluation.evaluate_plan(
            plan, project, self.store.list_plans(), self.store.list_evidence()
        )

    def _persist_evaluation(
        self, plan: Plan, result: PlanEvaluation, actor: str
    ) -> Plan:
        """Apply the derived status to the stored plan, log, and re-gate."""
        project = self._require_project()
        if result.plan_status != plan.status:
            event_log.append_event(
                self.store.data_dir,
                event="plan_status_changed",
                actor=actor,
                entity_type="plan",
                entity_id=plan.id,
                data={
                    "from": plan.status.value,
                    "to": result.plan_status.value,
                    "reason": [b.code for b in result.blockers] or ["closure_ok"],
                },
                project_version=project.version,
            )
            plan = plan.model_copy(update={"status": result.plan_status})
            self.store.save_plan(plan)
        gate_store.write_gate(self.store, project, self.store.list_plans())
        return plan

    # -- tools --------------------------------------------------------------

    def register_project(self, payload: Any) -> ProjectSummary:
        with self.store.locked():
            existing = self.store.load_project()
            project, warnings = normalize.normalize_project(payload, existing)
            project = self.store.save_project(project)
            event_log.append_event(
                self.store.data_dir,
                event="project_registered" if existing is None else "project_updated",
                actor="mcp:register_project",
                entity_type="project",
                entity_id=project.project_id,
                data={"warnings": warnings},
                project_version=project.version,
            )
            plans = self.store.list_plans()
            gate_store.write_gate(self.store, project, plans)
            summary = ProjectSummary(
                project_id=project.project_id,
                name=project.name,
                goal_count=len(project.goals),
                constraint_count=len(project.constraints),
                failure_mode_count=len(project.failure_modes),
                plan_count=len(plans),
                human_summary=reports.render_project_summary(project, len(plans)),
            )
            if warnings:
                summary.human_summary += " Warnings: " + " ".join(warnings)
            return summary

    def snapshot(self) -> ProjectSnapshot:
        project = self._require_project()
        plans = self.store.list_plans()
        evidence = self.store.list_evidence()
        top_blockers = []
        recommended = NextAction.STOP
        for plan in plans:
            if plan.status in TERMINAL_PLAN_STATUSES:
                continue
            result = evaluation.evaluate_plan(plan, project, plans, evidence)
            top_blockers.extend(result.blockers)
            recommended = result.recommended_next_action
        gate_snapshot = gate_store.compute_gate(project, plans)
        if not any(p.status not in TERMINAL_PLAN_STATUSES for p in plans):
            recommended = gate_snapshot.recommended_next_action
        return ProjectSnapshot(
            project_id=project.project_id,
            name=project.name,
            goals=[g.model_dump(mode="json") for g in project.goals],
            constraints=[
                ConstraintView(
                    id=c.id,
                    statement=c.statement,
                    kind=c.kind.value,
                    severity=c.severity.value,
                    status=c.status,
                    evidence_ids=c.evidence_ids,
                )
                for c in project.constraints
            ],
            failure_modes=[f.model_dump(mode="json") for f in project.failure_modes],
            plans=[
                PlanIndexEntry(
                    plan_id=p.id, title=p.title, kind=p.kind, status=p.status
                )
                for p in plans
            ],
            open_unknowns=gate_snapshot.unresolved_hard_constraints,
            top_blockers=top_blockers[:5],
            recommended_next_action=recommended,
            gate_open=gate_snapshot.gate_open,
            current_baseline=project.current_baseline,
            human_summary=reports.render_project_summary(project, len(plans)),
        )

    def get_plan(self, plan_id: str) -> dict[str, Any]:
        plan = self._require_plan(plan_id)
        result = self._evaluate(plan)
        return {
            "plan": plan.model_dump(mode="json"),
            "evaluation": result.model_dump(mode="json"),
        }

    def create_plan(self, payload: Any) -> PlanEvaluation:
        with self.store.locked():
            project = self._require_project()
            data = normalize._as_dict(payload, "plan")
            requested_id = str(data.get("id") or data.get("plan_id") or "")
            existing = self.store.load_plan(requested_id) if requested_id else None
            if existing is not None and existing.status in TERMINAL_PLAN_STATUSES:
                raise WorkspaceError(
                    f"Plan {requested_id} is terminal ({existing.status.value}) and "
                    f"cannot be edited. Create a new plan (optionally with "
                    f'parent_plan_id="{requested_id}").'
                )
            if existing is not None and existing.status in (
                PlanStatus.APPROVED,
                PlanStatus.EXECUTABLE,
                PlanStatus.EXECUTING,
            ):
                raise WorkspaceError(
                    f"Plan {requested_id} is already approved "
                    f"({existing.status.value}); editing it would bypass the human "
                    f"approval gate. Create a new plan with "
                    f'parent_plan_id="{requested_id}" and get it re-approved.'
                )
            taken = {p.id for p in self.store.list_plans()}
            plan, warnings = normalize.normalize_plan(
                payload, project, taken, existing_plan=existing
            )
            self.store.save_plan(plan)
            event_log.append_event(
                self.store.data_dir,
                event="plan_created" if existing is None else "plan_updated",
                actor="mcp:create_plan",
                entity_type="plan",
                entity_id=plan.id,
                data={"title": plan.title, "kind": plan.kind.value,
                      "version": plan.version},
                project_version=project.version,
            )
            result = self._evaluate(plan)
            self._persist_evaluation(plan, result, actor="mcp:create_plan")
            result.warnings = warnings + result.warnings
            return result

    def evaluate_plan(self, plan_id: str) -> PlanEvaluation:
        with self.store.locked():
            plan = self._require_plan(plan_id)
            result = self._evaluate(plan)
            self._persist_evaluation(plan, result, actor="mcp:evaluate_plan")
            return result

    def approve_plan(
        self, plan_id: str, approver: str, approval_note: str = ""
    ) -> dict[str, Any]:
        if approver.strip().lower() in SELF_APPROVAL_NAMES:
            raise WorkspaceError(
                "approver must identify the human who approved this plan (their "
                "name or handle, as stated by them). An AI assistant must not "
                "approve plans on its own; ask the user."
            )
        with self.store.locked():
            plan = self._require_plan(plan_id)
            result = self._evaluate(plan)
            plan = self._persist_evaluation(plan, result, actor="mcp:approve_plan")
            if plan.status != PlanStatus.READY_FOR_REVIEW:
                raise WorkspaceError(
                    f"Plan {plan_id} is {plan.status.value}, not ready_for_review. "
                    f"{result.human_summary}"
                )
            project = self._require_project()
            plan = plan.model_copy(
                update={
                    "status": PlanStatus.EXECUTABLE,
                    "approved_by": approver.strip(),
                    "approval_note": approval_note,
                }
            )
            self.store.save_plan(plan)
            event_log.append_event(
                self.store.data_dir,
                event="plan_approved",
                actor="mcp:approve_plan",
                entity_type="plan",
                entity_id=plan.id,
                data={"approver": approver.strip(), "note": approval_note,
                      "from": "ready_for_review", "to": "executable"},
                project_version=project.version,
            )
            gate_snapshot = gate_store.write_gate(
                self.store, project, self.store.list_plans()
            )
            return {
                "plan": plan.model_dump(mode="json"),
                "gate_open": gate_snapshot.gate_open,
                "human_summary": (
                    f"Plan {plan.id} approved by {approver.strip()} and is now "
                    f"EXECUTABLE. Implement only: "
                    f"{plan.intervention.allowed_files if plan.intervention else '[]'}"
                ),
            }

    def record_evidence(self, payload: Any) -> dict[str, Any]:
        with self.store.locked():
            project = self._require_project()
            record = normalize.normalize_evidence(
                payload, project, {e.id for e in self.store.list_evidence()}
            )
            self.store.save_evidence(record)
            event_log.append_event(
                self.store.data_dir,
                event="evidence_recorded",
                actor="mcp:record_evidence",
                entity_type="evidence",
                entity_id=record.id,
                data={"summary": record.summary, "polarity": record.polarity.value},
                project_version=project.version,
            )
            unknown = [
                c.id
                for c in project.hard_constraints()
                if c.status == ConstraintStatus.UNKNOWN
            ]
            hint = (
                f"If this evidence resolves any of the UNKNOWN hard constraints "
                f"{unknown}, call update_constraint_status with evidence_ids="
                f'["{record.id}"].'
                if unknown
                else "No hard constraints are currently UNKNOWN."
            )
            linked_plan = (
                self.store.load_plan(record.linked_plan_id)
                if record.linked_plan_id
                else None
            )
            warning = narration.narration_warning(record, linked_plan)
            summary = f"Recorded {record.id}. {hint}"
            if warning:
                summary = f"Recorded {record.id}. {warning} {hint}"
            return {
                "evidence": record.model_dump(mode="json"),
                "warnings": [warning] if warning else [],
                "human_summary": summary,
            }

    def record_run_metrics(
        self,
        plan_id: str,
        metrics: dict[str, float],
        summary: str = "",
        source_type: str = "test",
        artifact_uri: str | None = None,
        polarity: str = "neutral",
        observed_pattern_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Record measured values structurally and return the scored evaluation.

        The inverse of record_evidence: metrics first, prose optional. Values
        land in `observations`, where posterior_check can actually read them,
        and the recomputed PlanEvaluation comes back in the same call so the
        posterior verdict is visible at the moment of recording rather than
        after a separate evaluate_plan round-trip.
        """
        with self.store.locked():
            plan = self._require_plan(plan_id)
            if not metrics:
                raise WorkspaceError(
                    "record_run_metrics needs at least one {metric_id: value} "
                    "pair. For an observation with no measurement — a process "
                    "record, a paper, a code reading — use record_evidence: "
                    "evidence without a metric is not weaker, it is a "
                    "different kind of record."
                )
            bad = sorted(k for k, v in metrics.items() if not isinstance(v, (int, float)) or isinstance(v, bool))
            if bad:
                raise WorkspaceError(
                    f"record_run_metrics values must be numbers; {bad} are not. "
                    f"A value that cannot be compared to an expected_range "
                    f"cannot be scored."
                )

            predicted = narration.predicted_metric_ids(plan)
            unpredicted = sorted(set(metrics) - set(predicted))

            evidence_payload: dict[str, Any] = {
                "summary": summary.strip()
                or (
                    f"Measured values for {plan_id}: "
                    + ", ".join(f"{k}={v}" for k, v in sorted(metrics.items()))
                ),
                "source_type": source_type,
                "polarity": polarity,
                "linked_plan_id": plan_id,
                "artifact_uri": artifact_uri,
                "observations": [
                    {"metric_id": k, "value": float(v)} for k, v in metrics.items()
                ],
                "observed_pattern_ids": observed_pattern_ids or [],
            }
            project = self._require_project()
            record = normalize.normalize_evidence(
                evidence_payload, project, {e.id for e in self.store.list_evidence()}
            )
            self.store.save_evidence(record)
            event_log.append_event(
                self.store.data_dir,
                event="run_metrics_recorded",
                actor="mcp:record_run_metrics",
                entity_type="evidence",
                entity_id=record.id,
                data={"plan_id": plan_id, "metrics": dict(metrics)},
                project_version=project.version,
            )

            result = self._evaluate(plan)
            self._persist_evaluation(plan, result, actor="mcp:record_run_metrics")

            notes = []
            if unpredicted:
                notes.append(
                    f"Recorded but unpredicted (nothing to score them against): "
                    f"{unpredicted}."
                )
            outstanding = sorted(
                set(predicted)
                - {
                    obs.metric_id
                    for e in self.store.list_evidence()
                    if e.linked_plan_id == plan_id
                    for obs in e.observations
                }
            )
            if outstanding:
                notes.append(f"Still unobserved from the contract: {outstanding}.")
            return {
                "evidence": record.model_dump(mode="json"),
                "evaluation": result.model_dump(mode="json"),
                "predictive_status": result.predictive_status,
                "notes": notes,
                "human_summary": (
                    f"Recorded {record.id} with {len(metrics)} observation(s) on "
                    f"{plan_id}. Predictive check: {result.predictive_status}. "
                    + " ".join(notes)
                ).strip(),
            }

    def record_evidence_bundle(
        self,
        subtask_id: str,
        claims: list[dict[str, Any]],
        linked_plan_id: str | None = None,
        summary: str = "",
        required_attributes: list[str] | None = None,
        max_steps: int = 10,
        tau_evidence: float = 0.85,
        epsilon_threshold: float = 0.05,
    ) -> dict[str, Any]:
        """Record an aggregated micro-query subtask evidence bundle with damping verification."""
        with self.store.locked():
            project = self._require_project()
            parsed_claims = []
            for c in claims:
                norm = normalize.normalize_evidence(
                    {"summary": c.get("assertion_statement", "claim"), "claims": [c]},
                    project,
                    set(),
                )
                if norm.claims:
                    parsed_claims.append(norm.claims[0])

            bundle = micro_damping.build_subtask_bundle(
                subtask_id=subtask_id,
                claims=parsed_claims,
                required_attributes=required_attributes,
                max_steps=max_steps,
                tau_evidence=tau_evidence,
                epsilon_threshold=epsilon_threshold,
            )
            evidence_payload = {
                "summary": summary.strip()
                or (
                    f"Micro-damping bundle for {subtask_id}: {len(claims)} claim(s), "
                    f"coverage={bundle.total_coverage:.2f}, "
                    f"credibility={bundle.aggregate_credibility:.2f}, "
                    f"status={bundle.damping_status}"
                ),
                "source_type": (
                    "simulation"
                    if any("sim" in c.source_provenance for c in bundle.claims)
                    else "test"
                ),
                "polarity": (
                    "supports" if bundle.damping_status == "converged" else "neutral"
                ),
                "linked_plan_id": linked_plan_id,
                "claims": [c.model_dump(mode="json") for c in bundle.claims],
                "subtask_bundle": bundle.model_dump(mode="json"),
            }
            record = normalize.normalize_evidence(
                evidence_payload, project, {e.id for e in self.store.list_evidence()}
            )
            self.store.save_evidence(record)
            event_log.append_event(
                self.store.data_dir,
                event="evidence_bundle_recorded",
                actor="mcp:record_evidence_bundle",
                entity_type="evidence",
                entity_id=record.id,
                data={
                    "subtask_id": subtask_id,
                    "damping_status": bundle.damping_status,
                    "aggregate_credibility": bundle.aggregate_credibility,
                    "total_coverage": bundle.total_coverage,
                },
                project_version=project.version,
            )
            return {
                "evidence": record.model_dump(mode="json"),
                "subtask_bundle": bundle.model_dump(mode="json"),
                "human_summary": (
                    f"Recorded micro-damping bundle {record.id} for {subtask_id}: "
                    f"{bundle.damping_status} (coverage={bundle.total_coverage:.2f}, "
                    f"credibility={bundle.aggregate_credibility:.2f})."
                ),
            }

    def update_constraint_status(
        self,
        constraint_id: str,
        status: str,
        rationale: str,
        evidence_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        with self.store.locked():
            project = self._require_project()
            known_evidence = {e.id for e in self.store.list_evidence()}
            constraint, old_status = constraint_service.apply_constraint_update(
                project,
                constraint_id,
                status,
                rationale,
                evidence_ids or [],
                known_evidence,
            )
            project = self.store.save_project(project)
            event_log.append_event(
                self.store.data_dir,
                event="constraint_status_changed",
                actor="mcp:update_constraint_status",
                entity_type="constraint",
                entity_id=constraint_id,
                data={
                    "from": old_status.value,
                    "to": constraint.status.value,
                    "evidence_ids": evidence_ids or [],
                    "rationale": rationale,
                },
                project_version=project.version,
            )
            # Re-evaluate every non-terminal plan so BLOCKED plans can unblock.
            transitions: list[dict[str, str]] = []
            evidence = self.store.list_evidence()
            plans = self.store.list_plans()
            for plan in plans:
                if plan.status in TERMINAL_PLAN_STATUSES:
                    continue
                result = evaluation.evaluate_plan(plan, project, plans, evidence)
                if result.plan_status != plan.status:
                    transitions.append(
                        {"plan_id": plan.id, "from": plan.status.value,
                         "to": result.plan_status.value}
                    )
                self._persist_evaluation(
                    plan, result, actor="mcp:update_constraint_status"
                )
            # Refresh the gate even when no plans exist (state-ledger usage):
            # unresolved_hard_constraints and deny_message must track statuses.
            gate_store.write_gate(self.store, project, self.store.list_plans())
            summary = (
                f"Constraint {constraint_id}: {old_status.value} -> "
                f"{constraint.status.value}."
            )
            if transitions:
                summary += " Plan status changes: " + ", ".join(
                    f"{t['plan_id']} {t['from']}->{t['to']}" for t in transitions
                )
            return {
                "constraint": constraint.model_dump(mode="json"),
                "plan_transitions": transitions,
                "human_summary": summary,
            }

    def run_validation(self, plan_id: str, validation_step_id: str) -> dict[str, Any]:
        with self.store.locked():
            plan = self._require_plan(plan_id)
            if plan.status not in GATE_OPEN_STATUSES:
                raise WorkspaceError(
                    f"Plan {plan_id} is {plan.status.value}; validations run through "
                    f"the MCP only for approved plans (approved/executable/"
                    f"executing). Get the plan approved first — or run the command "
                    f"yourself and record_evidence manually."
                )
            step = next(
                (s for s in plan.validation_steps if s.id == validation_step_id), None
            )
            if step is None:
                known = [s.id for s in plan.validation_steps]
                raise WorkspaceError(
                    f"Plan {plan_id} has no validation step {validation_step_id!r}. "
                    f"Steps: {known}."
                )
            if not step.command:
                raise WorkspaceError(
                    f"Validation step {step.id} has no command id (kind="
                    f"{step.kind.value}). Reference a registered command id in the "
                    f"step's 'command' field before approval, or perform it "
                    f"manually and record_evidence."
                )

            try:
                result = command_runner.run_command(self.store.data_dir, step.command)
            except command_runner.CommandRunnerError as exc:
                raise WorkspaceError(str(exc)) from exc

            project = self._require_project()
            passed = result["exit_code"] == 0 and not result["timed_out"]
            outcome_word = (
                "TIMED OUT"
                if result["timed_out"]
                else f"exit {result['exit_code']}"
            )
            summary = (
                f"run_validation {plan.id}/{step.id}: command {step.command} "
                f"({' '.join(result['argv'])}) {outcome_word} in "
                f"{result['duration_s']}s. Expected: "
                f"{step.expected_result or 'unspecified'}. "
                f"stdout tail: {result['stdout_tail'][-1500:] or '(empty)'}"
            )
            if result["stderr_tail"].strip():
                summary += f" | stderr tail: {result['stderr_tail'][-500:]}"
            record = normalize.normalize_evidence(
                {
                    "summary": summary,
                    "source_type": result["source_type"],
                    "polarity": "supports" if passed else "refutes",
                    "artifact_uri": result["artifact_uri"],
                    "linked_plan_id": plan.id,
                },
                project,
                {e.id for e in self.store.list_evidence()},
            )
            self.store.save_evidence(record)
            event_log.append_event(
                self.store.data_dir,
                event="validation_run",
                actor="mcp:run_validation",
                entity_type="plan",
                entity_id=plan.id,
                data={
                    "validation_step_id": step.id,
                    "command_id": step.command,
                    "exit_code": result["exit_code"],
                    "timed_out": result["timed_out"],
                    "duration_s": result["duration_s"],
                    "evidence_id": record.id,
                    "artifact_uri": result["artifact_uri"],
                },
                project_version=project.version,
            )

            if plan.status == PlanStatus.EXECUTABLE:
                event_log.append_event(
                    self.store.data_dir,
                    event="plan_status_changed",
                    actor="mcp:run_validation",
                    entity_type="plan",
                    entity_id=plan.id,
                    data={"from": "executable", "to": "executing",
                          "reason": ["validation_started"]},
                    project_version=project.version,
                )
                plan = plan.model_copy(update={"status": PlanStatus.EXECUTING})
                self.store.save_plan(plan)
                gate_store.write_gate(self.store, project, self.store.list_plans())

            verdict = "passed" if passed else "FAILED"
            # Key is "run", not "result" — MCP hosts unwrap a top-level "result"
            # key when tools return primitives, so that name is ambiguous.
            return {
                "run": {
                    k: result[k]
                    for k in ("command_id", "argv", "exit_code", "timed_out",
                              "duration_s", "stdout_tail", "stderr_tail",
                              "artifact_uri")
                },
                "passed": passed,
                "evidence": record.model_dump(mode="json"),
                "human_summary": (
                    f"Validation {step.id} {verdict} ({outcome_word}, "
                    f"{result['duration_s']}s). Evidence {record.id} recorded with "
                    f"artifact {result['artifact_uri']}. "
                    + (
                        "Compare against the plan's decision_rule before recording "
                        "the outcome."
                        if passed
                        else "A failing required validation means repair or reject "
                        "— do not record 'validated'."
                    )
                ),
            }

    def record_plan_outcome(
        self,
        plan_id: str,
        outcome: str,
        summary: str,
        evidence_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        with self.store.locked():
            plan = self._require_plan(plan_id)
            key = str(outcome).strip().lower()
            if key not in VALID_OUTCOMES:
                raise WorkspaceError(
                    f"outcome must be one of {sorted(VALID_OUTCOMES)}, got {outcome!r}."
                )
            if not summary or not summary.strip():
                raise WorkspaceError(
                    "Provide a summary of what happened: which validation ran, what "
                    "it showed, and why that justifies this outcome."
                )
            if plan.status in TERMINAL_PLAN_STATUSES:
                raise WorkspaceError(
                    f"Plan {plan_id} already has terminal status {plan.status.value}."
                )
            known_evidence = {e.id for e in self.store.list_evidence()}
            missing = [e for e in (evidence_ids or []) if e not in known_evidence]
            if missing:
                raise WorkspaceError(
                    f"Evidence id(s) {missing} do not exist; call record_evidence "
                    f"first so the outcome is backed by recorded evidence."
                )
            if key == "validated" and not evidence_ids:
                raise WorkspaceError(
                    "Marking a plan validated requires evidence_ids: record the "
                    "validation result via record_evidence first (never report "
                    "'validated' without a completed validation record)."
                )
            project = self._require_project()
            old_status = plan.status
            plan = plan.model_copy(
                update={
                    "status": VALID_OUTCOMES[key],
                    "outcome_summary": summary.strip(),
                }
            )
            self.store.save_plan(plan)
            event_log.append_event(
                self.store.data_dir,
                event="plan_outcome_recorded",
                actor="mcp:record_plan_outcome",
                entity_type="plan",
                entity_id=plan.id,
                data={"from": old_status.value, "to": plan.status.value,
                      "summary": summary.strip(),
                      "evidence_ids": evidence_ids or []},
                project_version=project.version,
            )
            gate_snapshot = gate_store.write_gate(
                self.store, project, self.store.list_plans()
            )
            return {
                "plan": plan.model_dump(mode="json"),
                "gate_open": gate_snapshot.gate_open,
                "recommended_next_action": gate_snapshot.recommended_next_action.value,
                "human_summary": (
                    f"Plan {plan.id}: {old_status.value} -> {plan.status.value}. "
                    f"Gate is now {'open' if gate_snapshot.gate_open else 'closed'}."
                ),
            }
