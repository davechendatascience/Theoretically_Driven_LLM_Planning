from __future__ import annotations

import json

from conftest import make_evidence, make_plan, make_project

from damped_plan_mcp.models import ConstraintStatus, PlanStatus
from damped_plan_mcp.store import JsonStore
from damped_plan_mcp.store import events as event_log
from damped_plan_mcp.store.gate import write_gate


def test_project_round_trip_and_version_bump(tmp_path):
    store = JsonStore(tmp_path)
    project = make_project()
    saved = store.save_project(project)
    assert saved.version == 1  # first save does not bump
    saved = store.save_project(saved)
    assert saved.version == 2
    loaded = store.load_project()
    assert loaded == saved


def test_plan_and_evidence_round_trip(tmp_path):
    store = JsonStore(tmp_path)
    plan = make_plan()
    record = make_evidence()
    store.save_plan(plan)
    store.save_evidence(record)
    assert store.load_plan(plan.id) == plan
    assert store.list_plans() == [plan]
    assert store.list_evidence() == [record]


def test_events_monotone_seq(tmp_path):
    for index in range(3):
        event_log.append_event(
            tmp_path, "plan_created", "test", "plan", f"P-{index}", {}
        )
    records = event_log.read_events(tmp_path)
    assert [r["seq"] for r in records] == [1, 2, 3]


def test_atomic_write_leaves_no_tmp(tmp_path):
    store = JsonStore(tmp_path)
    store.save_project(make_project())
    assert not list(tmp_path.glob("*.tmp"))


def test_gate_closed_without_approved_plans(tmp_path):
    store = JsonStore(tmp_path)
    project = make_project(compute_status=ConstraintStatus.UNKNOWN)
    plan = make_plan(status=PlanStatus.BLOCKED)
    snapshot = write_gate(store, project, [plan])
    assert snapshot.gate_open is False
    assert snapshot.unresolved_hard_constraints == ["C-compute"]
    on_disk = json.loads((tmp_path / "gate.json").read_text())
    assert on_disk["gate_open"] is False
    assert "damped-plan" in on_disk["deny_message"]


def test_gate_open_lists_allowed_files(tmp_path):
    store = JsonStore(tmp_path)
    project = make_project()
    plan = make_plan(status=PlanStatus.EXECUTABLE)
    snapshot = write_gate(store, project, [plan])
    assert snapshot.gate_open is True
    assert snapshot.open_plans[0].allowed_files == [
        "src/policy/placement_head.py",
        "tests/test_head.py",
    ]
    # gate updates are event-logged
    assert any(e["event"] == "gate_updated" for e in event_log.read_events(tmp_path))
