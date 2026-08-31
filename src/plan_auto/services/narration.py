"""Detect numbers narrated into evidence prose instead of recorded structurally.

The posterior predictive check (`services.predictive.posterior_check`) scores
`MetricObservation`s against a contract's `expected_range`. It has always
worked; what fails is upstream. Across four live stores on 2026-08-20, 3 of 69
evidence records carried `observations` at all (EV-0010) — numbers were being
written into `summary` prose while the structured field stayed empty, so
contracts collected ranges that nothing scored.

Skipping the structured channel produced no signal: the check returned
`inconclusive`, which reads like "nothing to say" rather than "you narrated a
number I was waiting for". This module supplies the missing signal.

It **warns and never blocks** (hard constraint C-advisory-quality). The design
argument is not only that constraint: a refusal is satisfiable by fabricating a
metric value, which converts a visible honesty problem into an invisible
compliance one. A warning plus `predictive_status=inconclusive` already
prevents an honest `validated` outcome, so blocking the intake buys no
enforcement that the outcome gate does not already provide.
"""

from __future__ import annotations

import re

from ..models import EvidenceRecord, Plan

# A decimal numeral: 122, 0.043, 4.3. Deliberately not matching bare years or
# identifiers like "P-0013" / "EV-0010", which carry no measurement.
_NUMERAL = re.compile(r"(?<![\w.-])\d+(?:\.\d+)?(?![\w-])")


def contains_numeral(text: str) -> bool:
    """True when the text states a number that could have been an observation."""
    return _NUMERAL.search(text or "") is not None


def predicted_metric_ids(plan: Plan | None) -> list[str]:
    """Metric ids the plan's contract promises a scoreable number for."""
    if plan is None or plan.predictive_contract is None:
        return []
    return [
        prediction.metric_id
        for prediction in plan.predictive_contract.predictions
        if prediction.expected_range is not None and prediction.metric_id
    ]


def outstanding_metric_ids(record: EvidenceRecord, plan: Plan | None) -> list[str]:
    """Metric ids this record could have supplied structurally and did not.

    Empty (no warning) unless all four hold: the record is linked to a plan,
    that plan carries a contract with at least one ranged prediction, the
    record's `observations` are empty, and its summary states a numeral.
    """
    if plan is None or record.linked_plan_id != plan.id:
        return []
    if record.observations:
        return []
    if not contains_numeral(record.summary):
        return []
    return predicted_metric_ids(plan)


def narration_warning(record: EvidenceRecord, plan: Plan | None) -> str | None:
    """The warning text for a narrated-number record, or None when clean."""
    outstanding = outstanding_metric_ids(record, plan)
    if not outstanding:
        return None
    return (
        f"{record.id} states numbers in prose but records no structured "
        f"observations, while plan {plan.id}'s predictive contract is waiting "
        f"on {outstanding}. Nothing can score a number written in a summary: "
        f"the posterior check will return inconclusive, and this plan cannot "
        f"honestly reach 'validated'. Record the values with "
        f"record_run_metrics(plan_id='{plan.id}', metrics={{'"
        + "': ..., '".join(outstanding)
        + "': ...}}) — or, if these numbers genuinely are not the contract's "
        f"metrics, this record needs no change."
    )
