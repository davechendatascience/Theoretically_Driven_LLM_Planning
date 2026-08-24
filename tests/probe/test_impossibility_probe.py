"""P-0001: the mechanical impossibility probe, asserted against its preregistration.

Every expected value here comes from P-0001's `intervention.description`, which was
fixed before these fixtures existed and survived three adversarial review rounds. A
failure in this module is therefore NOT a broken test in the ordinary sense — it means
an observation diverged from what was preregistered, and P-0001's decision_rule says
what to do about it. Read the failure message, not just the traceback.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import probe_impossibility as probe  # noqa: E402


@pytest.fixture(scope="module")
def run() -> dict:
    data = probe.load_fixtures()
    results = {}
    for fixture in data["fixtures"]:
        contract, check = probe.run_fixture(fixture)
        results[fixture["id"]] = {
            "fixture": fixture,
            "contract": contract,
            "check": check,
            "wiring": probe.wiring_errors(fixture, contract, check),
            "caught": probe.is_caught(fixture, check),
        }
    return {"data": data, "results": results}


@pytest.mark.parametrize("fixture_id", ["F1", "F2a", "F2b", "F3", "F4"])
def test_status_matches_preregistration(run: dict, fixture_id: str) -> None:
    entry = run["results"][fixture_id]
    expected = entry["fixture"]["expected_status"]
    actual = entry["check"].status
    assert actual == expected, (
        f"{fixture_id} returned {actual!r}, preregistered {expected!r}. "
        f"This refutes the source reading behind H-0001; see P-0001 decision_rule."
    )


@pytest.mark.parametrize("fixture_id", ["F1", "F2a", "F2b", "F3", "F4"])
def test_violated_predictions_match_preregistration(run: dict, fixture_id: str) -> None:
    entry = run["results"][fixture_id]
    expected = entry["fixture"]["expected_violated"]
    actual = entry["check"].violated_prediction_ids
    assert sorted(actual) == sorted(expected), (
        f"{fixture_id} violated {actual}, preregistered {expected}. "
        f"F2a and F3 are separable only by violated ids, so a divergence here "
        f"invalidates the caught-criteria."
    )


def test_f2b_predictions_are_inconclusive_not_violated(run: dict) -> None:
    """The mechanism behind the whole probe: a range-less invariance is skipped.

    predictive.py:89-90 appends any prediction with expected_range None to
    inconclusive and `continue`s before comparison, so it can never reach violated
    no matter how far the observed value drifts. F2b's parse_ms moves 60 -> 35 and
    is still not a violation.
    """
    check = run["results"]["F2b"]["check"]
    assert "P-parse" in check.inconclusive_prediction_ids
    assert "P-emit" in check.inconclusive_prediction_ids
    assert check.violated_prediction_ids == []


def test_f2a_and_f2b_differ_only_by_encoding(run: dict) -> None:
    """Identical observations, identical baseline; only the declared band differs."""
    f2a = run["results"]["F2a"]["fixture"]
    f2b = run["results"]["F2b"]["fixture"]
    assert f2a["observations"] == f2b["observations"]


def test_f4_control_shares_f2a_observations(run: dict) -> None:
    """F2a's mismatch cannot be attributed to the data: F4 carries the same numbers."""
    f2a = run["results"]["F2a"]["fixture"]
    f4 = run["results"]["F4"]["fixture"]
    assert f2a["observations"] == f4["observations"]
    assert run["results"]["F4"]["check"].status == "consistent"


def test_no_fixture_wiring_errors(run: dict) -> None:
    """V-0002 gate: every adopt branch is conditioned on this being zero."""
    all_errors = {
        fid: entry["wiring"] for fid, entry in run["results"].items() if entry["wiring"]
    }
    assert not all_errors, (
        f"fixture_wiring_errors > 0: {all_errors}. The run is uninterpretable "
        f"regardless of every other value (P-0001 reject_if branch 1)."
    )


def test_metrics_match_preregistration(run: dict) -> None:
    """The five recorded metrics, against the values fixed before the fixtures existed."""
    results = run["results"]
    metrics = {
        "fixture_wiring_errors": sum(len(e["wiring"]) for e in results.values()),
        "f3_anchor_held": int(
            results["F3"]["check"].status == "mismatch"
            and "P-total" in results["F3"]["check"].violated_prediction_ids
        ),
        "impossible_fixtures_caught": sum(
            1 for fid in ("F1", "F2a", "F2b", "F3") if results[fid]["caught"]
        ),
        "control_fixture_passed": int(
            results["F4"]["check"].status == "consistent"
        ),
        "f2a_f2b_divergence": int(
            results["F2a"]["check"].status != results["F2b"]["check"].status
        ),
    }
    assert metrics == run["data"]["expected_metrics"], (
        f"observed {metrics}, preregistered {run['data']['expected_metrics']}. "
        f"Route the observed combination through P-0001's decision_rule rather "
        f"than adjusting either side."
    )
