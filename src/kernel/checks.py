"""Interval arithmetic over declared relations — ported from v1's
`prior_contract_check` and, unlike the original, wired to a caller.

A jointly unsatisfiable set of bands returns `consistent` posteriorly: once
data exists every value sits inside its own band, so no posterior check can
catch it. This decides it beforehand. Sound, not complete: it misses
contradictions that only appear when relations share a variable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Expectation


@dataclass
class RelationFinding:
    relation: str
    status: str
    detail: str = ""


@dataclass
class PriorCheck:
    status: str
    findings: list[RelationFinding] = field(default_factory=list)
    summary: str = ""


def _parse(text: str) -> tuple[str, list[str]] | None:
    """`X = Y + Z` or `X = Y`. Anything else is unparseable, never guessed."""
    if text.count("=") != 1:
        return None
    lhs, rhs = text.split("=")
    target = lhs.strip()
    operands = [p.strip() for p in rhs.split("+")]
    if not target or len(operands) > 2 or not all(operands):
        return None
    return target, operands


def prior_check(expectations: list[Expectation], relations: list[str]) -> PriorCheck:
    bands = {
        e.metric_id: (e.lo, e.hi)
        for e in expectations
        if e.form == "range" and e.lo is not None and e.hi is not None
    }
    findings: list[RelationFinding] = []

    for raw in relations:
        parsed = _parse(raw)
        if parsed is None:
            findings.append(RelationFinding(raw, "unparseable", "grammar is 'X = Y + Z' or 'X = Y'"))
            continue
        target, operands = parsed
        missing = [m for m in [target, *operands] if m not in bands]
        if missing:
            findings.append(
                RelationFinding(raw, "inconclusive", f"no band for {', '.join(sorted(set(missing)))}")
            )
            continue
        lo = sum(bands[m][0] for m in operands)
        hi = sum(bands[m][1] for m in operands)
        dlo, dhi = bands[target]
        overlaps = lo <= dhi and dlo <= hi
        findings.append(
            RelationFinding(
                raw,
                "satisfiable" if overlaps else "unsatisfiable",
                f"induced [{lo}, {hi}] {'overlaps' if overlaps else 'is disjoint from'} declared [{dlo}, {dhi}]",
            )
        )

    statuses = {f.status for f in findings}
    if "unsatisfiable" in statuses:
        status = "unsatisfiable"
    elif statuses & {"inconclusive", "unparseable"}:
        status = "inconclusive"
    else:
        status = "satisfiable"
    notes = [f.detail for f in findings if f.detail]
    if not relations:
        notes.append("no relations declared: satisfiable by vacuity")
    return PriorCheck(status=status, findings=findings, summary="; ".join(notes))
