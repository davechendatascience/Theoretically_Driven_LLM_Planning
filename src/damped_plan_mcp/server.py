"""MCP server: thin decorator layer over Workspace.

Single-project server — bound to one target project's `.damped-plan/`
directory via DAMPED_PLAN_DATA_DIR, so no tool takes a project_id.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from . import config, prompts
from .store import events as event_log
from .store import gate as gate_store
from .workspace import Workspace

INSTRUCTIONS = """\
damped-plan is a constraint-closure gate for nontrivial changes. Workflow:
1. register_project once (goals with metrics, hard constraints, failure modes).
2. Before implementing anything nontrivial, create_plan; the returned
   evaluation says exactly what is missing or blocking.
3. UNKNOWN hard constraints block implementation plans. Resolve them with a
   safe measurement plan (kind="measurement"), record_evidence, then
   update_constraint_status.
4. A plan becomes EXECUTABLE only after the human approves it (approve_plan
   with the human's name). Implement only the plan's allowed_files.
5. Afterwards: record_evidence, then record_plan_outcome (validated needs
   evidence). Never report "fixed" or "validated" without a validation record.
"""


def build_server(data_dir: Path | None = None) -> MCPServer:
    root = config.ensure_data_dir(data_dir)
    workspace = Workspace(root)

    # Self-heal on startup: gate.json is derived state, so recompute it in case
    # an older server version (or a crash) left it stale. Logs an event only if
    # the content actually changed.
    existing_project = workspace.store.load_project()
    if existing_project is not None:
        with workspace.store.locked():
            gate_store.write_gate(
                workspace.store, existing_project, workspace.store.list_plans()
            )

    server = MCPServer("damped-plan", instructions=INSTRUCTIONS)

    # -- tools ---------------------------------------------------------------

    @server.tool(
        description=(
            "Create or update the project state: goals (with metric_name/target), "
            "constraints (strings become hard+unknown), failure_modes, facts. "
            "Idempotent merge; never deletes. Minimal call: {'project': {'name': 'x'}}"
        )
    )
    def register_project(project: dict[str, Any]) -> dict[str, Any]:
        return workspace.register_project(project).model_dump(mode="json")

    @server.tool(
        description=(
            "Read the current project: goals, constraint statuses, plans, open "
            "unknowns, top blockers, and the recommended next action."
        )
    )
    def get_project_snapshot() -> dict[str, Any]:
        return workspace.snapshot().model_dump(mode="json")

    @server.tool(description="Fetch a stored plan plus its current evaluation.")
    def get_plan(plan_id: str) -> dict[str, Any]:
        return workspace.get_plan(plan_id)

    @server.tool(
        description=(
            "Create or repair a plan (same id updates a draft). Partial plans are "
            "accepted and evaluated immediately: the result lists concrete repair "
            "instructions. Minimal call: {'plan': {'title': '...', 'kind': "
            "'measurement|implementation|repair|rollback'}}. A full plan adds "
            "goal_ids, addresses_failure_ids, hypothesis, intervention "
            "(allowed_files!), validation_steps, decision_rule, rollback_description."
        )
    )
    def create_plan(plan: dict[str, Any]) -> dict[str, Any]:
        return workspace.create_plan(plan).model_dump(mode="json")

    @server.tool(
        description=(
            "Re-evaluate a plan: closure, blockers, residuals, recommended next "
            "action. Deterministic; safe to call any time."
        )
    )
    def evaluate_plan(plan_id: str) -> dict[str, Any]:
        return workspace.evaluate_plan(plan_id).model_dump(mode="json")

    @server.tool(
        description=(
            "Record the human's approval of a ready_for_review plan, making it "
            "EXECUTABLE. approver must be the human's name/handle as stated by "
            "them — an AI must not approve plans itself."
        )
    )
    def approve_plan(
        plan_id: str, approver: str, approval_note: str = ""
    ) -> dict[str, Any]:
        return workspace.approve_plan(plan_id, approver, approval_note)

    @server.tool(
        description=(
            "Record an observation with provenance: {'evidence': {'summary': '...', "
            "'source_type': 'test|benchmark|simulation|log|manual_review|paper|"
            "commit|profiling|solver', 'polarity': 'supports|refutes|neutral', "
            "'artifact_uri': ..., 'linked_constraint_ids': [...], "
            "'linked_plan_id': ...}}"
        )
    )
    def record_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
        return workspace.record_evidence(evidence)

    @server.tool(
        description=(
            "Change a constraint's status with a rationale. Marking a hard "
            "constraint 'sat' requires evidence_ids from record_evidence. "
            "Automatically re-evaluates all open plans (BLOCKED plans may unblock)."
        )
    )
    def update_constraint_status(
        constraint_id: str,
        status: str,
        rationale: str,
        evidence_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        return workspace.update_constraint_status(
            constraint_id, status, rationale, evidence_ids
        )

    @server.tool(
        description=(
            "Close out a plan: outcome 'validated' (requires evidence_ids), "
            "'rejected', or 'rolled_back', with a summary tied to its "
            "decision_rule."
        )
    )
    def record_plan_outcome(
        plan_id: str,
        outcome: str,
        summary: str,
        evidence_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        return workspace.record_plan_outcome(plan_id, outcome, summary, evidence_ids)

    # -- resources -----------------------------------------------------------

    def _dump(data: Any) -> str:
        return json.dumps(data, indent=2, default=str)

    @server.resource("damped://project/current/state")
    def project_state() -> str:
        return _dump(workspace.snapshot().model_dump(mode="json"))

    @server.resource("damped://project/current/constraints")
    def project_constraints() -> str:
        project = workspace.store.load_project()
        if project is None:
            return _dump({"error": "no project registered"})
        return _dump([c.model_dump(mode="json") for c in project.constraints])

    @server.resource("damped://project/current/plans")
    def plan_index() -> str:
        return _dump(
            [
                {"plan_id": p.id, "title": p.title, "kind": p.kind.value,
                 "status": p.status.value}
                for p in workspace.store.list_plans()
            ]
        )

    @server.resource("damped://project/current/plans/{plan_id}")
    def plan_detail(plan_id: str) -> str:
        return _dump(workspace.get_plan(plan_id))

    @server.resource("damped://project/current/gate")
    def gate_state() -> str:
        project = workspace.store.load_project()
        if project is None:
            return _dump({"gate_open": False, "error": "no project registered"})
        snapshot = gate_store.compute_gate(project, workspace.store.list_plans())
        return _dump(snapshot.model_dump(mode="json"))

    @server.resource("damped://project/current/decision-log")
    def decision_log() -> str:
        return _dump(event_log.read_events(workspace.store.data_dir, limit=200))

    # -- prompts -------------------------------------------------------------

    @server.prompt(description="Extract goals/constraints/failures; no method yet.")
    def compile_project_state() -> str:
        return prompts.COMPILE_PROJECT_STATE

    @server.prompt(description="Draft exactly one structured candidate plan.")
    def draft_feasible_plan() -> str:
        return prompts.DRAFT_FEASIBLE_PLAN

    @server.prompt(description="Explain closure failures; request minimal repairs.")
    def review_plan_blockers() -> str:
        return prompts.REVIEW_PLAN_BLOCKERS

    @server.prompt(description="Convert results into evidence and update state.")
    def postmortem_update() -> str:
        return prompts.POSTMORTEM_UPDATE

    return server


def main() -> None:
    build_server().run("stdio")


if __name__ == "__main__":
    main()
