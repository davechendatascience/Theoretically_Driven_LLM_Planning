"""Compact rendering.

The response format is a cost decision as much as a presentation one: an agent
reads these lines on every loop iteration, so the belief read is one line per
slice and the citation is a set hash rather than an id list. Full chains live
in the cycle report, which is where rule 10.1 actually applies.
"""

from __future__ import annotations

from typing import Any, Iterable

from . import MODEL_VERSION
from .ids import set_hash
from .model import STATE_INSUFFICIENT, Slice


def basis_line(
    slices: Iterable[Slice],
    derived_from: str = "evidence",
    prior_ids: Iterable[str] | None = None,
    assumptions: Iterable[str] | None = None,
) -> str:
    """The `basis:` line required on every response (10.3).

    `set=` is a hash of the exact evidence-id set, expandable with
    `status(view="trace", set=...)`. An id range would be cheaper and would
    occasionally be a lie — slices routinely use a non-contiguous subset once
    invalid trials and other buckets are dropped.
    """
    ids = sorted({e for s in slices for e in s.evidence_ids})
    priors = sorted({p for p in (prior_ids or []) if p})
    parts = [f"basis: {derived_from}×{len(ids)} set={set_hash(ids)}", f"model {MODEL_VERSION}"]
    parts.append(f"prior {','.join(priors) if priors else 'none'}")
    extra = list(assumptions or [])
    if extra:
        parts.append("assumes " + "; ".join(extra))
    return " · ".join(parts)


def slice_line(sl: Slice) -> str:
    label = sl.condition_label()
    if sl.state == STATE_INSUFFICIENT:
        need = sl.missing.get("trials_needed")
        detail = f"n={sl.n_valid}"
        if need:
            detail += f" (need {need} more)"
        elif "ci_width" in sl.missing:
            detail += f" (interval {sl.missing['ci_width']} > {sl.missing['max_ci_width']})"
        return f"{sl.contract_id} [{label}] insufficient {detail}"
    return (
        f"{sl.contract_id} [{label}] {sl.state} "
        f"{sl.point:.2f} [{sl.lo:.2f},{sl.hi:.2f}] n={sl.n_valid}"
    )


def slice_dict(sl: Slice) -> dict[str, Any]:
    """Full form — used by the cycle report, where the chain must be complete."""
    return {
        "contract": sl.contract_id,
        "bucket": sl.bucket,
        "compat_group": sl.compat_group,
        "applicable_conditions": sl.compat_fields | {"bucket": sl.bucket},
        "state": sl.state,
        "estimate": {
            "point": round(sl.point, 4),
            "ci_low": round(sl.lo, 4),
            "ci_high": round(sl.hi, 4),
            "ci_width": round(sl.ci_width, 4),
        },
        "target_rate": sl.target_rate,
        "n_valid": sl.n_valid,
        "n_invalid": sl.n_invalid,
        "n_excluded": sl.n_excluded,
        "passes": sl.passes,
        "fails": sl.fails,
        "missing": sl.missing,
        "exclusions": sl.exclusions,
        "evidence_ids": sl.evidence_ids,
        "set": sl.set_hash,
        "prior_id": sl.prior_id,
        "model_version": MODEL_VERSION,
    }


def envelope(body: str, basis: str, next_action: str | None = None) -> str:
    """One response shape: content, basis, and at most one next action."""
    lines = [body.rstrip(), basis]
    if next_action:
        lines.append(f"next: {next_action}")
    return "\n".join(line for line in lines if line)


def bullet(items: Iterable[str], empty: str = "(none)") -> str:
    rendered = [f"  - {item}" for item in items]
    return "\n".join(rendered) if rendered else f"  {empty}"
