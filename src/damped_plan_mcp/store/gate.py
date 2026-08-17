"""Gate snapshot: the machine-readable file the PreToolUse hook reads.

Rewritten after every mutation so the hook never needs to start the server.
`deny_message` is precomputed here; the hook only glob-matches paths.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from ..models import (
    ConstraintStatus,
    GATE_OPEN_STATUSES,
    GatePlanEntry,
    GateSnapshot,
    NextAction,
    Plan,
    ProjectState,
)
from . import events
from .json_store import JsonStore, atomic_write_json


def compute_gate(project: ProjectState, plans: list[Plan]) -> GateSnapshot:
    open_plans = [
        GatePlanEntry(
            plan_id=p.id,
            kind=p.kind,
            status=p.status,
            allowed_files=(p.intervention.allowed_files if p.intervention else []),
        )
        for p in plans
        if p.status in GATE_OPEN_STATUSES
    ]
    unresolved = [
        c.id
        for c in project.hard_constraints()
        if c.status not in (ConstraintStatus.SAT, ConstraintStatus.NOT_APPLICABLE)
    ]

    if open_plans:
        recommended = NextAction.IMPLEMENT
        if all(p.kind.value == "measurement" for p in open_plans):
            recommended = NextAction.MEASURE
        deny = (
            "No approved plan covers this file. Approved plan(s) "
            f"{[p.plan_id for p in open_plans]} only cover their allowed_files. "
            "Either add this file to a plan's intervention.allowed_files and "
            "re-evaluate, or create a new plan via the damped-plan MCP."
        )
    else:
        recommended = NextAction.MEASURE if unresolved else NextAction.STOP
        reason = (
            f"Hard constraint(s) {unresolved} are unresolved; create a measurement "
            f"plan via the damped-plan MCP to resolve them, or record evidence and "
            f"update their status."
            if unresolved
            else "Create a plan via the damped-plan MCP (create_plan), get it to "
            "READY_FOR_REVIEW, and have the human approve it."
        )
        deny = f"No plan is approved for execution. {reason}"

    return GateSnapshot(
        generated_at=datetime.now(UTC).isoformat(),
        project_id=project.project_id,
        gate_open=bool(open_plans),
        open_plans=open_plans,
        unresolved_hard_constraints=unresolved,
        recommended_next_action=recommended,
        deny_message=deny,
    )


def write_gate(store: JsonStore, project: ProjectState, plans: list[Plan]) -> GateSnapshot:
    snapshot = compute_gate(project, plans)
    path = store.data_dir / "gate.json"
    payload = snapshot.model_dump(mode="json")

    changed = True
    if path.exists():
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
            previous.pop("generated_at", None)
            current = dict(payload)
            current.pop("generated_at", None)
            changed = previous != current
        except (OSError, ValueError):
            changed = True

    atomic_write_json(path, payload)
    # Event-log only substantive changes, not timestamp refreshes.
    if changed:
        events.append_event(
            store.data_dir,
            event="gate_updated",
            actor="mcp:gate",
            entity_type="gate",
            entity_id=project.project_id,
            data={"gate_open": snapshot.gate_open,
                  "open_plans": [p.plan_id for p in snapshot.open_plans]},
            project_version=project.version,
        )
    return snapshot
