"""P-0003: contract self-consistency decided before data exists.

Every expected verdict here is preregistered in P-0003's intervention.description,
which was fixed and adversarially reviewed before this module was written. A failure
is not an ordinary broken test — it means an observation diverged from what was
preregistered, and P-0003's decision_rule says what to do about it.

The five-fixture corpus is P-0001's recorded artifact, read only. `metric_relations`
strings are supplied HERE and never written into that file: editing it would mutate a
preregistered artifact while changing no posterior verdict, making the mutation
invisible to P-0003's V-0305.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from damped_plan_mcp.services.normalize import _normalize_contract
from damped_plan_mcp.services.predictive import prior_contract_check

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "probe" / "fixtures" / "impossible_contracts.json"

# Transcribed from impossible_contracts.json:7 ("total_ms = parse_ms + emit_ms by
# definition"), not composed for this plan. V-0303 asserts the transcription.
RELATION = "total_ms = parse_ms + emit_ms"

# F5 MARGINAL and F6 SHARED-VARIABLE are preregistered in P-0003's intervention,
# directions included, because unenforceable_invariances_flagged depends on them.
F5_MARGINAL = {
    "context_fixed": ["total_ms = parse_ms + emit_ms by definition"],
    "predictions": [
        {"id": "P-total", "metric_id": "total_ms", "direction": "decrease", "expected_range": [70, 80]},
        {"id": "P-parse", "metric_id": "parse_ms", "direction": "decrease", "expected_range": [38, 42]},
        {"id": "P-emit", "metric_id": "emit_ms", "direction": "no_change", "expected_range": [39, 41]},
    ],
    "disconfirming_patterns": [{"id": "D-001", "description": "marginal-overlap control"}],
    "metric_relations": [RELATION],
}

F6_SHARED = {
    "context_fixed": ["total_ms = parse_ms + emit_ms", "total_ms = parse_ms"],
    "predictions": [
        {"id": "P-total", "metric_id": "total_ms", "direction": "no_change", "expected_range": [0, 10]},
        {"id": "P-parse", "metric_id": "parse_ms", "direction": "no_change", "expected_range": [0, 10]},
        {"id": "P-emit", "metric_id": "emit_ms", "direction": "no_change", "expected_range": [5, 6]},
    ],
    "disconfirming_patterns": [{"id": "D-001", "description": "shared-variable control"}],
    "metric_relations": [RELATION, "total_ms = parse_ms"],
}

PREREGISTERED_VERDICTS = {
    "F1": "unsatisfiable",
    "F2a": "unsatisfiable",
    "F3": "unsatisfiable",
    "F2b": "inconclusive",
    "F4": "satisfiable",
    "F5": "satisfiable",
    # The WRONG answer, preregistered: jointly the two relations force emit_ms = 0,
    # outside [5,6]. Per-relation propagation cannot see it.
    "F6": "satisfiable",
}


@pytest.fixture(scope="module")
def checks() -> dict:
    data = json.loads(FIXTURES.read_text(encoding="utf-8"))
    raw_by_id = {f["id"]: f for f in data["fixtures"]}

    contracts = {}
    for fid, fixture in raw_by_id.items():
        payload = dict(fixture["contract"])
        payload["metric_relations"] = [RELATION]
        contracts[fid] = _normalize_contract(payload)
    contracts["F5"] = _normalize_contract(dict(F5_MARGINAL))
    contracts["F6"] = _normalize_contract(dict(F6_SHARED))

    return {
        "raw": data,
        "contracts": contracts,
        "results": {fid: prior_contract_check(c) for fid, c in contracts.items()},
    }


@pytest.mark.parametrize("fixture_id", sorted(PREREGISTERED_VERDICTS))
def test_verdict_matches_preregistration(checks: dict, fixture_id: str) -> None:
    actual = checks["results"][fixture_id].status
    expected = PREREGISTERED_VERDICTS[fixture_id]
    assert actual == expected, (
        f"{fixture_id} returned {actual!r}, preregistered {expected!r}. "
        f"Route this through P-0003's decision_rule rather than adjusting either side."
    )


def test_f1_induced_interval_is_disjoint(checks: dict) -> None:
    """The arithmetic P-0001 could not see: 60+40 cannot be 75."""
    finding = checks["results"]["F1"].relation_findings[0]
    assert finding.induced_range == (98.0, 102.0)
    assert finding.declared_range == (70.0, 80.0)
    assert finding.status == "unsatisfiable"


def test_f5_overlaps_marginally_and_has_a_witness(checks: dict) -> None:
    """Guards against over-rejection at the boundary. Witness: 38.5 + 39.5 = 78."""
    finding = checks["results"]["F5"].relation_findings[0]
    assert finding.induced_range == (77.0, 83.0)
    assert finding.declared_range == (70.0, 80.0)
    assert finding.status == "satisfiable"
    assert 70 <= 78 <= 80 and 38 <= 38.5 <= 42 and 39 <= 39.5 <= 41


def test_f2b_is_undecidable_not_guessed(checks: dict) -> None:
    """A missing band makes satisfiability undecidable; it must not be defaulted."""
    result = checks["results"]["F2b"]
    assert result.status == "inconclusive"
    assert result.relation_findings[0].status == "inconclusive"
    assert result.relation_findings[0].induced_range is None


def test_f6_is_a_preregistered_false_negative(checks: dict) -> None:
    """Both relations pass individually; jointly they force emit_ms = 0 outside [5,6].

    This asserts the check gets it WRONG, which is what stops P-0003 claiming a
    completeness it does not have.
    """
    result = checks["results"]["F6"]
    assert result.status == "satisfiable"
    assert len(result.relation_findings) == 2
    assert all(f.status == "satisfiable" for f in result.relation_findings)


def test_verdicts_partition_the_corpus(checks: dict) -> None:
    """V-0306: counts are over fixture ENTRIES (F1/F2a/F3 share one contract)."""
    statuses = [r.status for r in checks["results"].values()]
    counts = {
        "unsatisfiable_verdicts": statuses.count("unsatisfiable"),
        "satisfiable_verdicts": statuses.count("satisfiable"),
        "inconclusive_verdicts": statuses.count("inconclusive"),
    }
    assert counts == {
        "unsatisfiable_verdicts": 3,
        "satisfiable_verdicts": 3,
        "inconclusive_verdicts": 1,
    }
    assert sum(counts.values()) == 7


def test_unenforceable_invariances_flagged(checks: dict) -> None:
    """Only F2b's range-less no_change predictions. Everything else carries a band."""
    flagged = {
        fid: r.unenforceable_invariances
        for fid, r in checks["results"].items()
        if r.unenforceable_invariances
    }
    assert flagged == {"F2b": ["P-parse", "P-emit"]}


def test_relation_is_transcribed_not_composed(checks: dict) -> None:
    """V-0303: the relation comes from P-0001's recorded context_fixed."""
    recorded = checks["raw"]["preregistration"]["context_fixed"][0]
    assert recorded.startswith(RELATION), (
        f"relation {RELATION!r} is not a prefix of the recorded {recorded!r}"
    )


def test_malformed_relation_is_reported_not_dropped(checks: dict) -> None:
    """A silently dropped relation would make an impossible contract look satisfiable."""
    payload = dict(F5_MARGINAL)
    payload["metric_relations"] = ["total_ms ~ parse_ms * emit_ms"]
    result = prior_contract_check(_normalize_contract(payload))
    assert result.unparseable_relations == ["total_ms ~ parse_ms * emit_ms"]
    assert result.relation_findings[0].status == "unparseable"
    assert result.status == "inconclusive"


def test_no_relations_is_satisfiable_by_vacuity(checks: dict) -> None:
    payload = dict(F5_MARGINAL)
    payload["metric_relations"] = []
    result = prior_contract_check(_normalize_contract(payload))
    assert result.status == "satisfiable"
    assert result.relation_findings == []
