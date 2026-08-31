"""Regression tests from real-world dogfooding (2026-08-17).

A project used purely as a state ledger (constraints resolved before any plan
exists) must still keep gate.json in sync — the stale-gate bug left the hook
citing already-resolved constraints.
"""

from __future__ import annotations

import json

from conftest import make_project

from plan_auto.models import ConstraintStatus, PlanStatus
from plan_auto.server import build_server
from plan_auto.store import JsonStore
from plan_auto.store import events as event_log
from plan_auto.store.gate import write_gate
from plan_auto.workspace import Workspace


def test_constraint_update_refreshes_gate_with_zero_plans(tmp_path):
    ws = Workspace(tmp_path)
    ws.register_project(
        {"name": "ledger", "constraints": [{"id": "C-1", "statement": "x"}]}
    )
    gate = json.loads((tmp_path / "gate.json").read_text())
    assert gate["unresolved_hard_constraints"] == ["C-1"]

    ws.record_evidence({"summary": "measured it"})
    ws.update_constraint_status("C-1", "sat", "measured", ["EV-0001"])

    gate = json.loads((tmp_path / "gate.json").read_text())
    assert gate["unresolved_hard_constraints"] == []


def test_gate_event_logged_only_on_change(tmp_path):
    store = JsonStore(tmp_path)
    project = make_project(compute_status=ConstraintStatus.UNKNOWN)
    write_gate(store, project, [])
    write_gate(store, project, [])
    write_gate(store, project, [])
    gate_events = [
        e for e in event_log.read_events(tmp_path) if e["event"] == "gate_updated"
    ]
    assert len(gate_events) == 1


def test_server_startup_self_heals_stale_gate(tmp_path):
    ws = Workspace(tmp_path)
    ws.register_project(
        {"name": "ledger", "constraints": [{"id": "C-1", "statement": "x"}]}
    )
    # Simulate the pre-fix stale file: constraint resolved but gate not rewritten.
    project = ws.store.load_project()
    project.constraints[0].status = ConstraintStatus.SAT
    ws.store.save_project(project)
    stale = json.loads((tmp_path / "gate.json").read_text())
    assert stale["unresolved_hard_constraints"] == ["C-1"]

    build_server(tmp_path)

    healed = json.loads((tmp_path / "gate.json").read_text())
    assert healed["unresolved_hard_constraints"] == []


def test_terminal_plans_do_not_reopen_gate(tmp_path):
    ws = Workspace(tmp_path)
    ws.register_project(
        {
            "name": "ledger",
            "goals": [{"statement": "g", "metric_name": "m", "target": "t"}],
        }
    )
    evaluation = ws.create_plan(
        {
            "title": "measure once",
            "kind": "measurement",
            "hypothesis": "h",
            "intervention": {"description": "run probe", "allowed_files": ["probe.py"]},
            "validation_steps": ["check"],
            "decision_rule": {"adopt_if": ["ok"], "reject_if": ["bad"]},
        }
    )
    assert evaluation.plan_status == PlanStatus.READY_FOR_REVIEW
    ws.approve_plan(evaluation.plan_id, "Dana")
    ws.record_evidence({"summary": "done"})
    ws.record_plan_outcome(evaluation.plan_id, "validated", "done", ["EV-0001"])
    gate = json.loads((tmp_path / "gate.json").read_text())
    assert gate["gate_open"] is False
