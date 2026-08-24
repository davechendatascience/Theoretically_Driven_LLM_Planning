#!/usr/bin/env python3
"""P-0001 mechanical impossibility probe: measure the posterior check's detection floor.

Runs five preregistered fixture contracts through the real posterior check and
records, per fixture, the full PredictiveCheck. Answers one question: when a
contract's predictions are jointly unsatisfiable, does anything notice?

Per P-0001's preregistered fixture load path, fixtures reach the checker through
`normalize.py`'s contract normalization — the same path a real plan's
predictive_contract takes — so the silent `expected_range` coercion at
normalize.py:517-521 is a live guard rather than a bypassed one. Constructing
`Prediction` objects directly is explicitly out of scope.

This script writes tests/probe/artifacts/P-0001-probe.json. That path is
deliberately NOT under .damped-plan/artifacts/: this output is agent-produced,
outside `run_validation`, with no exit code and no event, and placing it in the
ledger's captured-evidence namespace would counterfeit the marker that lets a
reviewer cite mechanical output without recomputing it.

Run:
    python scripts/probe_impossibility.py
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from damped_plan_mcp.models import EvidencePolarity, EvidenceRecord, Plan, PlanKind
from damped_plan_mcp.models.predictive import MetricObservation, PredictiveCheck
from damped_plan_mcp.services.normalize import _normalize_contract
from damped_plan_mcp.services.predictive import posterior_check

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "probe" / "fixtures" / "impossible_contracts.json"
ARTIFACT = REPO / "tests" / "probe" / "artifacts" / "P-0001-probe.json"


def load_fixtures() -> dict[str, Any]:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))


def run_fixture(fixture: dict[str, Any]) -> tuple[Any, PredictiveCheck]:
    """Normalize one fixture's contract and run the real posterior check over it."""
    contract = _normalize_contract(fixture["contract"])
    stamp = datetime.now(UTC)
    plan = Plan(
        id=f"PROBE-{fixture['id']}",
        project_id="probe",
        title=fixture["title"],
        kind=PlanKind.IMPLEMENTATION,
        predictive_contract=contract,
        created_at=stamp,
        updated_at=stamp,
    )
    evidence = EvidenceRecord(
        id=f"EV-PROBE-{fixture['id']}",
        project_id="probe",
        source_type="test",
        summary=f"probe fixture {fixture['id']}",
        polarity=EvidencePolarity.NEUTRAL,
        linked_plan_id=plan.id,
        observations=[
            MetricObservation(metric_id=metric, value=float(value))
            for metric, value in fixture["observations"].items()
        ],
        created_at=stamp,
    )
    return contract, posterior_check(plan, [evidence])


def wiring_errors(
    fixture: dict[str, Any], contract: Any, check: PredictiveCheck
) -> list[dict[str, str]]:
    """V-0002: compare the RAW fixture JSON against the normalized Predictions.

    Inspecting only the normalized object cannot work: a malformed band is
    coerced to None by normalize.py:517-521 before any such check could see it,
    which would make the affected prediction indistinguishable from F2b's
    legitimate range-less ones and fabricate divergence.
    """
    seen = (
        set(check.matched_prediction_ids)
        | set(check.violated_prediction_ids)
        | set(check.inconclusive_prediction_ids)
    )
    normalized = {p.id: p for p in (contract.predictions if contract else [])}
    # Exempt by explicit id, never by range-nullity, so the exemption cannot
    # accidentally absorb a silently coerced prediction.
    exempt = set(fixture.get("wiring_exempt_prediction_ids", []))
    errors: list[dict[str, str]] = []

    for raw in fixture["contract"]["predictions"]:
        pid = str(raw.get("id") or "")
        if pid not in seen:
            errors.append({"prediction_id": pid, "clause": "a_silently_dropped"})
            continue
        norm = normalized.get(pid)
        raw_declares_range = raw.get("expected_range") is not None
        if raw_declares_range and (norm is None or norm.expected_range is None):
            errors.append({"prediction_id": pid, "clause": "b_silent_range_coercion"})
        if (
            pid in check.inconclusive_prediction_ids
            and norm is not None
            and norm.expected_range is not None
            and pid not in exempt
        ):
            errors.append(
                {"prediction_id": pid, "clause": "c_inconclusive_despite_band"}
            )

    if check.status == "not_ready":
        errors.append({"prediction_id": "-", "clause": "d_not_ready"})
    return errors


def is_caught(fixture: dict[str, Any], check: PredictiveCheck) -> bool | None:
    """Per-fixture caught-criterion. `inconclusive` and `not_ready` never count."""
    rule = fixture["caught_rule"]
    if rule == "control":
        return None
    if check.status != "mismatch":
        return False
    if rule == "any_mismatch":
        return True
    return fixture["caught_prediction_id"] in check.violated_prediction_ids


def main() -> int:
    data = load_fixtures()
    results: list[dict[str, Any]] = []
    total_wiring_errors = 0

    for fixture in data["fixtures"]:
        contract, check = run_fixture(fixture)
        errs = wiring_errors(fixture, contract, check)
        total_wiring_errors += len(errs)
        caught = is_caught(fixture, check)
        results.append(
            {
                "id": fixture["id"],
                "title": fixture["title"],
                "status": check.status,
                "matched": check.matched_prediction_ids,
                "violated": check.violated_prediction_ids,
                "inconclusive": check.inconclusive_prediction_ids,
                "observed_patterns": check.observed_pattern_ids,
                "discrepancy_summary": check.discrepancy_summary,
                "caught": caught,
                "wiring_errors": errs,
                "expected_status": fixture["expected_status"],
                "expected_violated": fixture["expected_violated"],
                "expected_caught": fixture["expected_caught"],
                "status_matches_preregistration": check.status
                == fixture["expected_status"],
            }
        )

    by_id = {r["id"]: r for r in results}
    f3 = by_id["F3"]
    metrics = {
        "fixture_wiring_errors": total_wiring_errors,
        "f3_anchor_held": int(
            f3["status"] == "mismatch" and "P-total" in f3["violated"]
        ),
        "impossible_fixtures_caught": sum(
            1 for fid in ("F1", "F2a", "F2b", "F3") if by_id[fid]["caught"]
        ),
        "control_fixture_passed": int(by_id["F4"]["status"] == "consistent"),
        "f2a_f2b_divergence": int(by_id["F2a"]["status"] != by_id["F2b"]["status"]),
    }

    payload = {
        "plan_id": "P-0001",
        "generated_at": datetime.now(UTC).isoformat(),
        "provenance": (
            "agent-authored script, not run_validation; no exit code and no event "
            "back this file. Kept outside .damped-plan/artifacts/ deliberately."
        ),
        "fixture_source": str(FIXTURES.relative_to(REPO)).replace("\\", "/"),
        "results": results,
        "metrics": metrics,
        "expected_metrics": data["expected_metrics"],
        "metrics_match_preregistration": metrics == data["expected_metrics"],
    }

    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(f"{'fixture':6} {'status':12} {'violated':22} {'inconclusive':22} caught")
    for r in results:
        print(
            f"{r['id']:6} {r['status']:12} "
            f"{','.join(r['violated']) or '-':22} "
            f"{','.join(r['inconclusive']) or '-':22} {r['caught']}"
        )
    print()
    for key, value in metrics.items():
        expected = data["expected_metrics"][key]
        mark = "OK " if value == expected else "DIFF"
        print(f"  [{mark}] {key} = {value} (preregistered {expected})")
    print(f"\nArtifact: {ARTIFACT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
