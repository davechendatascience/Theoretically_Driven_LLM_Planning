"""Human-readable rendering of evaluations and snapshots."""

from __future__ import annotations

from ..models import Plan, PlanEvaluation, PlanStatus, ProjectState


def render_evaluation_summary(plan: Plan, evaluation: PlanEvaluation) -> str:
    lines: list[str] = []
    verdict = evaluation.plan_status.value.upper()
    lines.append(f"Plan {plan.id} ({plan.kind.value}) — {plan.title}: {verdict}.")

    if evaluation.plan_status == PlanStatus.READY_FOR_REVIEW and evaluation.executable:
        lines.append(
            "All gate conditions hold. Ask the human to approve_plan; it becomes "
            "EXECUTABLE on approval."
        )
    elif evaluation.plan_status in (PlanStatus.EXECUTABLE, PlanStatus.APPROVED):
        lines.append("Approved and executable: implement only the allowed files.")

    if evaluation.blockers:
        lines.append("Blockers:")
        for blocker in evaluation.blockers:
            lines.append(f"  - [{blocker.code}] {blocker.message}")
    if evaluation.warnings:
        lines.append("Warnings:")
        for warning in evaluation.warnings:
            lines.append(f"  - {warning}")

    lines.append(
        f"Recommended next action: {evaluation.recommended_next_action.value}."
    )
    for reason in evaluation.residuals.rationale:
        lines.append(f"  {reason}")
    return "\n".join(lines)


def render_project_summary(project: ProjectState, plan_count: int) -> str:
    hard = project.hard_constraints()
    unresolved = [c.id for c in hard if c.status.value not in ("sat", "not_applicable")]
    parts = [
        f"Project {project.name!r}: {len(project.goals)} goal(s), "
        f"{len(project.constraints)} constraint(s) ({len(hard)} hard, "
        f"{len(unresolved)} unresolved), {len(project.failure_modes)} failure "
        f"mode(s), {plan_count} plan(s)."
    ]
    if unresolved:
        parts.append(
            f"Unresolved hard constraints {unresolved} will block implementation "
            f"plans until measured or evidenced."
        )
    return " ".join(parts)
