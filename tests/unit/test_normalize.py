from __future__ import annotations

import pytest
from conftest import make_project
from hypothesis import given, settings
from hypothesis import strategies as st

from plan_auto.models import (
    ConstraintKind,
    ConstraintStatus,
    PlanKind,
    PlanStatus,
)
from plan_auto.services.normalize import (
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


def test_alias_fields_accepted():
    # Real-world sessions passed description/name instead of statement/symptom;
    # aliases must capture the content instead of storing hollow entities.
    state, warnings = normalize_project(
        {
            "name": "demo",
            "goals": [{"id": "G1", "description": "reach the target"}],
            "constraints": [{"id": "C1", "description": "must hold"}],
            "failure_modes": [{"id": "F1", "description": "it breaks"}],
            "facts": [{"id": "FA1", "text": "observed thing", "truth_status": "observed"}],
        }
    )
    assert state.goals[0].statement == "reach the target"
    assert state.constraints[0].statement == "must hold"
    assert state.failure_modes[0].symptom == "it breaks"
    assert state.facts[0].statement == "observed thing"
    assert not any("empty" in w for w in warnings)


def test_hollow_entities_warned_not_blocked():
    state, warnings = normalize_project(
        {
            "name": "demo",
            "goals": [{"id": "G1", "metric_name": "m", "target": "t"}],
            "failure_modes": [{"id": "F-cryptic"}],
            "facts": [{"id": "FA1", "statement": "measured X"}],
        }
    )
    # Stored anyway (existing users keep working)...
    assert state.goals[0].statement == ""
    assert state.failure_modes[0].symptom == ""
    # ...but each hollow field and the defaulted truth_status get a warning.
    assert any("G1" in w and "empty statement" in w for w in warnings)
    assert any("F-cryptic" in w and "empty symptom" in w for w in warnings)
    assert any("FA1" in w and "assumed" in w for w in warnings)


def test_project_id_slug_strips_punctuation():
    state, _ = normalize_project({"name": "embodied_ai: grounding a VLA!"})
    assert state.project_id == "embodied_ai-grounding-a-vla"


def test_required_validation_without_expected_result_warned():
    project = make_project()
    _, warnings = normalize_plan(
        {
            "title": "x",
            "kind": "measurement",
            "validation_steps": [{"description": "run it", "required": True}],
        },
        project,
        set(),
    )
    assert any("expected_result" in w for w in warnings)


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
