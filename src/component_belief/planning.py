"""Round planning — deliberately not an optimiser.

It reuses the decision-relevance flag from §7 rather than running a knapsack
over an expected-information-gain model. That keeps rule 8.3 honest and cheap:
a test whose policy outcome is the same at both ends of its interval is
redundant confirmation, and gets skipped with that reason on the record.
"""

from __future__ import annotations

from typing import Any

from .declarations import Declarations
from .decide import active_policy, decision_relevant
from .model import Slice

LAYERS = ("component", "interface", "e2e")


def plan_round(
    decl: Declarations,
    slices: list[Slice],
    budget: float | None = None,
    policy_id: str | None = None,
) -> dict[str, Any]:
    policy = active_policy(decl, policy_id)

    mandatory: list[dict[str, Any]] = []
    considered: list[tuple[Any, bool]] = []

    for test in decl.tests.values():
        if test.mandatory:
            # Scheduled regardless of expected information gain (8.5).
            mandatory.append({
                "test_id": test.id, "layer": test.layer, "cost": test.cost,
                "reason": "mandatory_gate",
            })
            continue
        contracts = [c.id for c in decl.contracts.values() if test.id in c.evaluable_by]
        relevant = bool(policy) and any(
            decision_relevant(decl, policy, slices, c) for c in contracts
        )
        considered.append((test, relevant))

    selected: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    spent = sum(item["cost"] for item in mandatory)

    for test, relevant in sorted(considered, key=lambda pair: (not pair[1], pair[0].cost, pair[0].id)):
        contracts = [c.id for c in decl.contracts.values() if test.id in c.evaluable_by]
        if not contracts:
            skipped.append({
                "test_id": test.id, "reason": "no_contract",
                "detail": "no contract lists this test in evaluable_by",
            })
            continue
        if not relevant:
            skipped.append({
                "test_id": test.id, "reason": "not_decision_relevant",
                "detail": "policy verdict is identical at both ends of the interval",
            })
            continue
        if budget is not None and spent + test.cost > budget:
            skipped.append({
                "test_id": test.id, "reason": "over_budget",
                "detail": f"cost {test.cost} exceeds remaining {round(budget - spent, 3)}",
            })
            continue
        selected.append({
            "test_id": test.id, "layer": test.layer, "cost": test.cost,
            "reason": "decision_relevant", "contracts": contracts,
        })
        spent += test.cost

    gaps = [
        cid for cid in decl.active_components()
        if not any(cid in t.targets for t in decl.tests.values())
    ]
    for cid in sorted(gaps):
        skipped.append({
            "test_id": f"(none for {cid})", "reason": "no_instrumentation",
            "detail": f"{cid} has no registered test; it cannot be planned for",
        })

    scheduled_layers = {item["layer"] for item in mandatory + selected}
    missing_layers = [layer for layer in LAYERS if layer not in scheduled_layers]
    declared_layers = {t.layer for t in decl.tests.values()}
    imbalance = [layer for layer in missing_layers if layer in declared_layers]

    return {
        "policy": policy.id if policy else None,
        "budget": budget,
        "spent": round(spent, 3),
        "mandatory": mandatory,
        "selected": selected,
        "skipped": skipped,
        "imbalance": imbalance,
        "instrumentation_gaps": sorted(gaps),
    }
