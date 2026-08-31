"""I1-I5 as executable predicates, not principles.

Every one of these returns a list of violations. I5 in particular is the
anti-v0 guard: v1 shipped three components that computed values nothing read,
and no check existed that could have said so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel

from . import grammar
from .models import Change, Constraint, Expectation, Given, Objective, Outcome


@dataclass(frozen=True)
class Violation:
    invariant: str
    subject: str
    detail: str


def i1_citation_required(
    constraints: Iterable[Constraint] = (), givens: Iterable[Given] = ()
) -> list[Violation]:
    """A proposition leaves `unknown` only with a citation — `not_applicable`
    included. v1 read the evidence string only for `unknown`, so N/A was the
    one uncited escape.

    Givens are judged on provenance, not status: a claim to have *observed*
    something must point at where.
    """
    out = []
    for c in constraints:
        if c.status != "unknown" and not c.citations:
            out.append(Violation("I1", c.id, f"status={c.status} with no citation"))
    for g in givens:
        if g.provenance == "observed" and not g.citations:
            out.append(Violation("I1", g.id, "claims observation with no citation"))
    return out


def i2_objective_has_a_human_owner(objectives: Iterable[Objective]) -> list[Violation]:
    """The terminal goal is human-only. An unowned objective is one no agent
    can be refused for amending."""
    return [
        Violation("I2", o.id, "objective names no human owner")
        for o in objectives
        if not o.owner.strip()
    ]


def i2_human_authorised(changes: Iterable[Change]) -> list[Violation]:
    """Only a human authorises a change, and only over its declared scope."""
    out = []
    for c in changes:
        if c.status in ("authorised", "executing", "adopted") and not c.approved_by:
            out.append(Violation("I2", c.id, f"status={c.status} with no approver"))
        if c.status in ("authorised", "executing") and not c.allowed_files:
            out.append(Violation("I2", c.id, "authorised with an empty file scope"))
    return out


def i3_no_coerced_unknown(expectations: Iterable[Expectation]) -> list[Violation]:
    """No admitted Expectation may be unfalsifiable."""
    out = []
    for e in expectations:
        ok, reason = grammar.can_fail(e)
        if not ok:
            out.append(Violation("I3", e.id, reason))
    return out


def i4_append_only(seqs: list[int]) -> list[Violation]:
    """The log is strictly increasing; a rewrite shows as a break."""
    out = []
    for prev, cur in zip(seqs, seqs[1:]):
        if cur <= prev:
            out.append(Violation("I4", f"seq {cur}", f"not greater than {prev}"))
    return out


def i5_every_field_has_a_reader(
    package_dir: Path, models_module: str = "models.py"
) -> list[Violation]:
    """Nothing is computed that no reader consumes.

    For every field declared on a model, require its name to appear somewhere
    in the package outside the module that declares it. This is what would
    have caught residual_variance, aggregate_credibility, oscillation_risk and
    dependency_gap on the day they were written.
    """
    from . import models as _models

    sources = {
        p.name: p.read_text()
        for p in package_dir.glob("*.py")
        if p.name not in (models_module, "__init__.py")
    }
    out = []
    for name in dir(_models):
        cls = getattr(_models, name)
        if not (isinstance(cls, type) and issubclass(cls, BaseModel) and cls is not BaseModel):
            continue
        for field in cls.model_fields:
            if field in ("id", "created_at", "captured_at"):
                continue
            pattern = re.compile(rf"\b{re.escape(field)}\b")
            if not any(pattern.search(src) for src in sources.values()):
                out.append(
                    Violation("I5", f"{cls.__name__}.{field}", "computed or stored, read by nothing")
                )
    return out


def check_all(
    constraints: Iterable[Constraint],
    givens: Iterable[Given],
    changes: Iterable[Change],
    expectations: Iterable[Expectation],
    seqs: list[int],
    objectives: Iterable[Objective] = (),
    package_dir: Path | None = None,
) -> list[Violation]:
    out: list[Violation] = []
    out += i1_citation_required(constraints, givens)
    out += i2_objective_has_a_human_owner(objectives)
    out += i2_human_authorised(changes)
    out += i3_no_coerced_unknown(expectations)
    out += i4_append_only(seqs)
    if package_dir is not None:
        out += i5_every_field_has_a_reader(package_dir)
    return out
