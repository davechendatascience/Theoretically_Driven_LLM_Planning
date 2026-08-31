from __future__ import annotations

import pytest
from conftest import make_project

from plan_auto.models import ConstraintStatus
from plan_auto.services.constraint_service import (
    ConstraintUpdateError,
    apply_constraint_update,
)


def test_hard_sat_requires_evidence():
    project = make_project(compute_status=ConstraintStatus.UNKNOWN)
    with pytest.raises(ConstraintUpdateError, match="record_evidence"):
        apply_constraint_update(
            project, "C-compute", "sat", "profiled fine", [], set()
        )


def test_hard_sat_requires_existing_evidence_ids():
    project = make_project(compute_status=ConstraintStatus.UNKNOWN)
    with pytest.raises(ConstraintUpdateError, match="do not exist"):
        apply_constraint_update(
            project, "C-compute", "sat", "profiled fine", ["EV-9999"], {"EV-0001"}
        )


def test_hard_sat_with_evidence_succeeds():
    project = make_project(compute_status=ConstraintStatus.UNKNOWN)
    constraint, old = apply_constraint_update(
        project,
        "C-compute",
        "sat",
        "Peak allocated VRAM 18.6 GB under target batch size",
        ["EV-0010"],
        {"EV-0010"},
    )
    assert old == ConstraintStatus.UNKNOWN
    assert constraint.status == ConstraintStatus.SAT
    assert "EV-0010" in constraint.evidence_ids


def test_rationale_required():
    project = make_project()
    with pytest.raises(ConstraintUpdateError, match="rationale"):
        apply_constraint_update(project, "C-compute", "unknown", "  ", [], set())


def test_unknown_constraint_id_lists_registered():
    project = make_project()
    with pytest.raises(ConstraintUpdateError, match="C-compute"):
        apply_constraint_update(project, "C-nope", "sat", "x", ["EV-1"], {"EV-1"})


def test_unsat_needs_no_evidence():
    # Reporting a violation must stay low-friction.
    project = make_project()
    constraint, _ = apply_constraint_update(
        project, "C-compute", "unsat", "OOM at batch 8", [], set()
    )
    assert constraint.status == ConstraintStatus.UNSAT
