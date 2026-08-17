from __future__ import annotations

import pytest
from conftest import make_project
from hypothesis import given, settings
from hypothesis import strategies as st

from damped_plan_mcp.models import (
    ConstraintKind,
    ConstraintStatus,
    PlanKind,
    PlanStatus,
)
from damped_plan_mcp.services.normalize import (
    InputError,
    normalize_evidence,
    normalize_plan,
    normalize_project,
)


def test_minimal_project():
    state, _ = normalize_project({"name": "demo"})
    assert state.name == "demo"
    assert state.project_id == "demo"


def test_project_requires_name():
    with pytest.raises(InputError, match="name"):
        normalize_project({})


def test_string_constraints_become_hard_unknown():
    state, _ = normalize_project(
        {"name": "demo", "constraints": ["No new real-world labels"]}
    )
    constraint = state.constraints[0]
    assert constraint.kind == ConstraintKind.HARD
    assert constraint.status == ConstraintStatus.UNKNOWN
    assert constraint.id == "C-0001"


def test_unaudited_sat_hard_constraint_downgraded_at_registration():
    state, _ = normalize_project(
        {"name": "demo", "constraints": [{"statement": "x", "status": "sat"}]}
    )
    assert state.constraints[0].status == ConstraintStatus.UNKNOWN


def test_reregistration_merges_and_preserves_status():
    state, _ = normalize_project(
        {"name": "demo", "constraints": [{"id": "C-1", "statement": "x"}]}
    )
    state.constraints[0].status = ConstraintStatus.SAT
    merged, _ = normalize_project(
        {
            "name": "demo",
            "constraints": [{"id": "C-1", "statement": "x updated", "status": "unknown"}],
            "goals": ["reach the moon"],
        },
        existing=state,
    )
    # Status survives re-registration; statement updates; goal added.
    assert merged.constraints[0].status == ConstraintStatus.SAT
    assert merged.constraints[0].statement == "x updated"
    assert len(merged.goals) == 1


def test_partial_plan_accepted_and_draft():
    project = make_project()
    plan, _ = normalize_plan(
        {"title": "try something", "kind": "implementation"}, project, set()
    )
    assert plan.id == "P-0001"
    assert plan.status == PlanStatus.DRAFT
    assert plan.hypothesis is None


def test_plan_requires_title_and_kind():
    project = make_project()
    with pytest.raises(InputError, match="title"):
        normalize_plan({}, project, set())
    with pytest.raises(InputError, match="kind"):
        normalize_plan({"title": "x"}, project, set())


def test_plan_accepts_json_string_payload():
    project = make_project()
    plan, _ = normalize_plan(
        '{"title": "as string", "kind": "measurement"}', project, set()
    )
    assert plan.kind == PlanKind.MEASUREMENT


def test_enum_coercion_is_forgiving():
    project = make_project()
    plan, _ = normalize_plan(
        {"title": "x", "kind": "Implementation "}, project, set()
    )
    assert plan.kind == PlanKind.IMPLEMENTATION


def test_goal_ids_default_to_open_goals():
    project = make_project()
    plan, warnings = normalize_plan({"title": "x", "kind": "repair"}, project, set())
    assert plan.goal_ids == ["G-0001"]
    assert any("open goals" in w for w in warnings)


def test_audit_skeleton_auto_populated():
    project = make_project(compute_status=ConstraintStatus.UNKNOWN)
    plan, _ = normalize_plan({"title": "x", "kind": "implementation"}, project, set())
    by_id = plan.audit_by_constraint()
    assert set(by_id) == {"C-compute", "C-safety"}
    assert by_id["C-compute"].status == ConstraintStatus.UNKNOWN
    assert by_id["C-safety"].status == ConstraintStatus.SAT


def test_audit_sat_claim_downgraded_to_project_status():
    project = make_project(compute_status=ConstraintStatus.UNKNOWN)
    plan, warnings = normalize_plan(
        {
            "title": "x",
            "kind": "implementation",
            "constraint_audit": [{"constraint_id": "C-compute", "status": "sat"}],
        },
        project,
        set(),
    )
    assert plan.audit_by_constraint()["C-compute"].status == ConstraintStatus.UNKNOWN
    assert any("update_constraint_status" in w for w in warnings)


def test_plan_upsert_preserves_created_at_and_bumps_version():
    project = make_project()
    first, _ = normalize_plan({"title": "x", "kind": "repair"}, project, set())
    second, _ = normalize_plan(
        {"id": first.id, "title": "x", "kind": "repair", "hypothesis": "because y"},
        project,
        {first.id},
        existing_plan=first,
    )
    assert second.created_at == first.created_at
    assert second.version == first.version + 1
    assert second.hypothesis is not None


def test_evidence_minimal():
    project = make_project()
    record = normalize_evidence({"summary": "saw a thing"}, project, set())
    assert record.id == "EV-0001"
    assert record.source_type == "manual_review"


def test_evidence_requires_summary():
    project = make_project()
    with pytest.raises(InputError, match="summary"):
        normalize_evidence({"polarity": "supports"}, project, set())


@settings(max_examples=25, deadline=None)
@given(
    title=st.text(min_size=1, max_size=40).filter(str.strip),
    kind=st.sampled_from(["measurement", "implementation", "repair", "rollback"]),
)
def test_normalize_plan_idempotent(title: str, kind: str):
    """Re-normalizing a normalized plan changes nothing but version/updated_at."""
    project = make_project()
    first, _ = normalize_plan({"title": title, "kind": kind}, project, set())
    again, _ = normalize_plan(
        first.model_dump(mode="json"), project, {first.id}, existing_plan=first
    )
    exclude = {"version", "updated_at"}
    assert first.model_dump(exclude=exclude) == again.model_dump(exclude=exclude)
