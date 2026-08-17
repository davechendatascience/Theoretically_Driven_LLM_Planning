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
from .services import constraint_service, evaluation, normalize
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
            return {
                "evidence": record.model_dump(mode="json"),
                "human_summary": f"Recorded {record.id}. {hint}",
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
