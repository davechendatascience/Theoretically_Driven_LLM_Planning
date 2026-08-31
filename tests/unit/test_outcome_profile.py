"""P-0007: the outcome profile — the number the gate can be falsified by.

The live-store tests read six plans that TERMINATED BEFORE this plan existed and
that `create_plan` refuses to edit (P-0002 proved that refusal). Their numbers
cannot be fixtured by whoever writes this file, which makes them the strongest
evidential footing any plan in this project has had.
"""

from __future__ import annotations

import glob
import json
from pathlib import Path

from plan_auto.services.outcomes import outcome_profile
from plan_auto.config import resolve_data_dir

REPO = Path(__file__).resolve().parents[2]


def live_plans() -> list[dict]:
    return [
        json.loads(Path(f).read_text(encoding="utf-8"))
        for f in sorted(glob.glob(str(resolve_data_dir(REPO) / "plans" / "*.json")))
    ]


# --- fixture arithmetic, independent of the live store ----------------------


def test_fixture_rate_is_correct() -> None:
    plans = [{"status": "validated"}] * 3 + [{"status": "rejected"}] * 7
    p = outcome_profile(plans)
    assert p.terminal_plans == 10
    assert p.validated == 3
    assert p.validated_rate_pct == 30
    assert p.reading == "below_band"


def test_in_flight_plans_are_excluded() -> None:
    """Counting drafts would let the rate move by drafting rather than finishing."""
    plans = [
        {"status": "validated"}, {"status": "rejected"},
        {"status": "draft"}, {"status": "executable"}, {"status": "ready_for_review"},
    ]
    p = outcome_profile(plans)
    assert p.terminal_plans == 2
    assert p.excluded_nonterminal == 3
    assert p.validated_rate_pct == 50


def test_no_terminal_plans_leaves_the_rate_undefined() -> None:
    """Undefined, not zero — an empty numerator over an empty denominator."""
    p = outcome_profile([{"status": "draft"}, {"status": "executable"}])
    assert p.terminal_plans == 0
    assert p.validated_rate_pct is None
    assert p.reading == "no_terminal_plans"


def test_theatre_signature_is_named() -> None:
    p = outcome_profile([{"status": "validated"}] * 19 + [{"status": "rejected"}])
    assert p.validated_rate_pct == 95
    assert p.reading == "theatre_signature"


def test_band_readings() -> None:
    assert outcome_profile([{"status": "validated"}] * 5 +
                           [{"status": "rejected"}] * 5).reading == "in_band"
    assert outcome_profile([{"status": "validated"}] * 7 +
                           [{"status": "rejected"}] * 3).reading == "above_band"


def test_rolled_back_and_superseded_are_terminal_but_not_validated() -> None:
    p = outcome_profile([
        {"status": "validated"}, {"status": "rolled_back"}, {"status": "superseded"},
    ])
    assert p.terminal_plans == 3
    assert p.rolled_back == 1 and p.superseded == 1
    assert p.validated_rate_pct == 33


# --- the live store: unfixturable AND time-independent ----------------------
#
# P-0007 pinned terminal==6, validated==4, rate==67. Those broke the moment
# P-0007 itself validated and P-0008 was created. Unfixturable live data cannot
# be fabricated by an implementer AND cannot be pinned by one — the same
# property gives both. So these assert PROPERTIES that hold for whatever the
# store contains, and are re-checked below against a synthetic future ledger.


def counts_on_disk(plans: list[dict]) -> dict[str, int]:
    """Ground truth read from the same files the profile reads."""
    terminal = {"validated", "rejected", "rolled_back", "superseded"}
    out = {k: 0 for k in terminal}
    out["_nonterminal"] = 0
    for p in plans:
        status = p.get("status")
        if status in terminal:
            out[status] += 1
        else:
            out["_nonterminal"] += 1
    return out


def assert_profile_is_self_consistent(plans: list[dict]) -> None:
    """Every invariant the profile must satisfy for ANY ledger state."""
    p = outcome_profile(plans)
    truth = counts_on_disk(plans)

    # counts match the store
    assert p.validated == truth["validated"]
    assert p.rejected == truth["rejected"]
    assert p.rolled_back == truth["rolled_back"]
    assert p.superseded == truth["superseded"]
    assert p.excluded_nonterminal == truth["_nonterminal"]

    # the counts partition, and nothing is dropped or double-counted
    assert p.terminal_plans == (
        p.validated + p.rejected + p.rolled_back + p.superseded
    )
    assert p.terminal_plans + p.excluded_nonterminal == len(plans)

    # the rate is arithmetically correct, and the reading matches the band
    if p.terminal_plans == 0:
        assert p.validated_rate_pct is None
        assert p.reading == "no_terminal_plans"
        return
    assert p.validated_rate_pct == round(100 * p.validated / p.terminal_plans)
    rate = p.validated_rate_pct
    expected = (
        "theatre_signature" if rate >= 90
        else "above_band" if rate > 60
        else "below_band" if rate < 40
        else "in_band"
    )
    assert p.reading == expected


def test_live_store_profile_is_self_consistent() -> None:
    """Reads the real ledger — unauthorable by the implementer, and undated."""
    plans = live_plans()
    assert plans, "the live store should hold plans by now"
    assert_profile_is_self_consistent(plans)


def test_live_store_excludes_whatever_is_in_flight() -> None:
    """However many plans are open, exactly those are excluded."""
    plans = live_plans()
    p = outcome_profile(plans)
    in_flight = counts_on_disk(plans)["_nonterminal"]
    assert p.excluded_nonterminal == in_flight
    assert p.terminal_plans == len(plans) - in_flight


def test_the_same_properties_hold_on_a_future_ledger() -> None:
    """What separates a property from a disguised snapshot.

    If these only held for today's store they would be pins with extra steps.
    """
    future = (
        [{"status": "validated"}] * 9
        + [{"status": "rejected"}] * 2
        + [{"status": "rolled_back"}] * 1
        + [{"status": "executable"}, {"status": "draft"}, {"status": "blocked"}]
    )
    assert_profile_is_self_consistent(future)
    p = outcome_profile(future)
    assert p.terminal_plans == 12 and p.validated == 9 and p.excluded_nonterminal == 3

    # and on an empty one
    assert_profile_is_self_consistent([])
