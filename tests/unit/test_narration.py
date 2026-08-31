"""Tests for services/narration.py — the narrated-number detector.

The detector must fire on exactly one situation (a plan-linked record that
states numerals while the contract's ranged predictions go unobserved) and stay
silent everywhere else. A warning that fires on correct behaviour trains the
recorder to ignore all warnings, including true ones.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from plan_auto.models import EvidenceRecord, Plan
from plan_auto.models.enums import EvidencePolarity, PlanKind
from plan_auto.models.predictive import Prediction, PredictiveContract
from plan_auto.services import narration

NOW = datetime(2026, 8, 20, tzinfo=timezone.utc)


def make_plan(predictions: list[Prediction] | None, plan_id: str = "P-1") -> Plan:
    contract = (
        PredictiveContract(predictions=predictions) if predictions is not None else None
    )
    return Plan(
        id=plan_id,
        project_id="proj",
        title="t",
        kind=PlanKind.IMPLEMENTATION,
        predictive_contract=contract,
        schema_version=2,
        created_at=NOW,
        updated_at=NOW,
    )


def make_record(summary: str, plan_id: str | None = "P-1", observations=None):
    return EvidenceRecord(
        id="EV-1",
        project_id="proj",
        source_type="test",
        summary=summary,
        polarity=EvidencePolarity.NEUTRAL,
        linked_plan_id=plan_id,
        observations=observations or [],
        created_at=NOW,
    )


RANGED = [Prediction(id="P-1", metric_id="tests_passing", direction="increase", expected_range=(100, 120))]


# --- the numeral predicate --------------------------------------------------


@pytest.mark.parametrize("text", ["122 passed", "0.043 of records", "rate was 4.3%"])
def test_numeral_detected(text):
    assert narration.contains_numeral(text)


@pytest.mark.parametrize(
    "text",
    ["all tests passed", "plan P-0013 closed", "see EV-0010", "no measurement here"],
)
def test_identifiers_are_not_numerals(text):
    assert not narration.contains_numeral(text)


# --- predicted_metric_ids ---------------------------------------------------


def test_predicted_ids_need_a_range():
    plan = make_plan([Prediction(metric_id="m", direction="increase")])
    assert narration.predicted_metric_ids(plan) == []


def test_predicted_ids_listed_when_ranged():
    assert narration.predicted_metric_ids(make_plan(RANGED)) == ["tests_passing"]


def test_no_contract_means_no_predicted_ids():
    assert narration.predicted_metric_ids(make_plan(None)) == []


def test_none_plan_is_safe():
    assert narration.predicted_metric_ids(None) == []


# --- the one case that must warn --------------------------------------------


def test_warns_on_narrated_number():
    plan, record = make_plan(RANGED), make_record("the suite reported 122 passing")
    assert narration.outstanding_metric_ids(record, plan) == ["tests_passing"]
    warning = narration.narration_warning(record, plan)
    assert warning and "tests_passing" in warning and "record_run_metrics" in warning


# --- everywhere else it must stay silent ------------------------------------


def test_silent_when_observations_present():
    record = make_record(
        "the suite reported 122 passing",
        observations=[{"metric_id": "tests_passing", "value": 122}],
    )
    assert narration.narration_warning(record, make_plan(RANGED)) is None


def test_silent_without_a_linked_plan():
    record = make_record("counted 69 records", plan_id=None)
    assert narration.narration_warning(record, make_plan(RANGED)) is None


def test_silent_when_linked_to_a_different_plan():
    record = make_record("counted 69 records", plan_id="P-other")
    assert narration.narration_warning(record, make_plan(RANGED)) is None


def test_silent_when_plan_has_no_contract():
    record = make_record("the suite reported 122 passing")
    assert narration.narration_warning(record, make_plan(None)) is None


def test_silent_when_contract_has_no_ranges():
    plan = make_plan([Prediction(metric_id="m", direction="increase")])
    assert narration.narration_warning(make_record("saw 122"), plan) is None


def test_silent_on_prose_without_numbers():
    record = make_record("the reviewer found no contradiction")
    assert narration.narration_warning(record, make_plan(RANGED)) is None


def test_silent_when_plan_is_none():
    assert narration.narration_warning(make_record("saw 122"), None) is None
