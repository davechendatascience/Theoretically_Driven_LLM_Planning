"""Outcome profile — the one number the gate can be falsified by (P-0007).

`research_trails.md` §3.1: if the gate does discriminative work, a project using
it should show a **low** rate of plans reaching `validated`. A high rate is
evidence of theatre, not of good engineering.

The band is transposed from metascience, where the experiment has been run on
humans twice. Scheel, Schijen & Lakens (2021) measured first-hypothesis
confirmation at 96.05% in standard psychology reports against 43.66% in
Registered Reports. Kaplan & Irvin (2015) measured large NHLBI trials showing
significant primary-outcome benefit falling from 57% to 8% once prospective
registration was required. Both are priors about *other* systems and neither is
an observation about this one — they set an expectation, they do not score it.

Only TERMINAL plans count. A plan still in flight is excluded deliberately:
counting drafts would let the rate be moved by *drafting* rather than by
*finishing*, which would make the metric reward activity over completion.
"""

from __future__ import annotations

from typing import Any, Iterable

from pydantic import BaseModel

from ..models.enums import TERMINAL_PLAN_STATUSES

# §3.1's transposed band. Priors, not thresholds: nothing gates on these.
BAND_LOW_PCT = 40
BAND_HIGH_PCT = 60
THEATRE_PCT = 90


class OutcomeProfile(BaseModel):
    terminal_plans: int = 0
    validated: int = 0
    rejected: int = 0
    rolled_back: int = 0
    superseded: int = 0
    excluded_nonterminal: int = 0
    validated_rate_pct: int | None = None
    band_low_pct: int = BAND_LOW_PCT
    band_high_pct: int = BAND_HIGH_PCT
    reading: str = "no_terminal_plans"
    detail: str = ""


def _status_of(plan: Any) -> str:
    status = getattr(plan, "status", None)
    if status is None and isinstance(plan, dict):
        status = plan.get("status")
    return getattr(status, "value", status) or ""


def outcome_profile(plans: Iterable[Any]) -> OutcomeProfile:
    """Terminal-plan outcome counts and the validated rate, with a band reading.

    Accepts Plan objects or raw dicts, so it can run against the live store or a
    fixture without either being privileged.
    """
    terminal_values = {getattr(s, "value", s) for s in TERMINAL_PLAN_STATUSES}
    counts = {"validated": 0, "rejected": 0, "rolled_back": 0, "superseded": 0}
    excluded = 0

    for plan in plans:
        status = _status_of(plan)
        if status in terminal_values:
            counts[status] = counts.get(status, 0) + 1
        else:
            excluded += 1

    terminal = sum(counts.values())
    if terminal == 0:
        return OutcomeProfile(
            excluded_nonterminal=excluded,
            reading="no_terminal_plans",
            detail=(
                f"{excluded} plan(s) in flight, none terminal yet; "
                f"the rate is undefined rather than zero"
            ),
        )

    rate = round(100 * counts["validated"] / terminal)
    if rate >= THEATRE_PCT:
        reading = "theatre_signature"
        note = (
            f"at or above {THEATRE_PCT}% the gate is not discriminating - trails 3.1 "
            f"reads this as theatre rather than as good engineering"
        )
    elif rate > BAND_HIGH_PCT:
        reading = "above_band"
        note = f"above trails 3.1's {BAND_LOW_PCT}-{BAND_HIGH_PCT}% band for pre-committed work"
    elif rate < BAND_LOW_PCT:
        reading = "below_band"
        note = (
            f"below trails 3.1's {BAND_LOW_PCT}-{BAND_HIGH_PCT}% band - plans are failing "
            f"more often than pre-registered human work does"
        )
    else:
        reading = "in_band"
        note = f"inside trails 3.1's {BAND_LOW_PCT}-{BAND_HIGH_PCT}% band"

    small = " Sample is small; indicative only." if terminal < 10 else ""
    return OutcomeProfile(
        terminal_plans=terminal,
        validated=counts["validated"],
        rejected=counts["rejected"],
        rolled_back=counts["rolled_back"],
        superseded=counts["superseded"],
        excluded_nonterminal=excluded,
        validated_rate_pct=rate,
        reading=reading,
        detail=(
            f"{counts['validated']}/{terminal} terminal plans validated "
            f"({rate}%) - {note}.{small} "
            f"{excluded} in-flight plan(s) excluded."
        ),
    )
