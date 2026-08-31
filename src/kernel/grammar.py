"""The Expectation grammar and its falsifiability check.

The central rule — *no change without an expectation that could fail* — is
enforceable exactly to the extent "could fail" is decidable. It is decidable
for the six admitted forms and NOT decidable for the universal logic claim
("F never returns null for any input in class X"), which is therefore rejected
at construction and must be reduced to a finite witness set.

That rejection is why the adversarial reviewer is load-bearing rather than
advisory: it is the natural author of the witnesses that make a logic-level
claim checkable at all.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from .models import Expectation

CONTRACT_FIELDS = (
    "form", "metric_id", "lo", "hi", "baseline", "unit_ref",
    "inputs", "golden_ref", "expected_output", "command", "allowed_set",
)


class Unfalsifiable(ValueError):
    """Raised when an Expectation admits no outcome that would count as a miss."""


def can_fail(e: Expectation) -> tuple[bool, str]:
    """Decide whether some constructible Outcome would be recorded as a miss.

    Returns (decidable_and_falsifiable, reason). Never guesses: a form whose
    falsifiability cannot be established returns False with the reason.
    """
    if not e.instrument:
        return False, (
            "no instrument named: nothing can produce an Outcome for this "
            "expectation, so no observation would count as a miss"
        )

    if e.form == "range":
        if e.lo is None or e.hi is None:
            return False, "range expectation with no bounds admits every value"
        if math.isinf(e.lo) and math.isinf(e.hi):
            return False, "unbounded range admits every value"
        if e.lo > e.hi:
            return False, "empty range admits no value, so it cannot be satisfied either"
        return True, "any value outside [lo, hi] is a miss"

    if e.form == "invariance":
        if e.baseline is None:
            return False, (
                "invariance with no recorded baseline is unfalsifiable — this is "
                "v1's live defect (no_change with expected_range: null)"
            )
        return True, "any value differing from the baseline is a miss"

    if e.form == "golden":
        if not e.golden_ref:
            return False, "golden equality with no recorded golden output"
        if not e.inputs:
            return False, "golden equality over an empty input set is vacuous"
        return True, "any differing byte is a miss"

    if e.form == "exit":
        if not e.command:
            return False, "exit expectation names no command"
        return True, "a nonzero exit status is a miss"

    if e.form == "witness":
        if e.expected_output is None:
            return False, "witness with no expected output"
        if not e.inputs:
            return False, "witness names no input"
        return True, "any other output for this input is a miss"

    if e.form == "membership":
        if not e.allowed_set:
            return False, "membership with an empty allowed set cannot be satisfied"
        return True, "any element outside the allowed set is a miss"

    return False, f"unknown expectation form {e.form!r}"


def admit(e: Expectation) -> Expectation:
    """Admit an Expectation, or refuse it. Refusal is the point.

    Also freezes the contract-critical fields as a hash so a later revision is
    visible rather than silent.
    """
    ok, reason = can_fail(e)
    if not ok:
        raise Unfalsifiable(f"{e.id}: {reason}")
    return e.model_copy(update={"frozen_hash": freeze(e)})


def freeze(e: Expectation) -> str:
    payload = {f: getattr(e, f) for f in CONTRACT_FIELDS}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()


def revised(e: Expectation) -> bool:
    """True when contract-critical fields no longer match the frozen hash."""
    return bool(e.frozen_hash) and freeze(e) != e.frozen_hash


def reduce_universal(claim: str, witnesses: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """Turn an inadmissible universal claim into admissible witness expectations.

    `"F never returns null for class X"` is rejected; the same claim over an
    enumerated set of inputs is admitted as one witness expectation each.
    """
    if not witnesses:
        raise Unfalsifiable(
            f"universal claim {claim!r} has no witnesses: it is not decidable and "
            f"cannot be admitted. Enumerate inputs, or the reviewer must supply them."
        )
    return [
        {"form": "witness", "inputs": [inp], "expected_output": out, "rationale": claim}
        for inp, out in witnesses
    ]


def evaluate(e: Expectation, outcome_value: Any) -> str:
    """Derive match/miss. Polarity is computed here, never stored."""
    if e.form == "range":
        if outcome_value is None:
            return "inconclusive"
        return "match" if e.lo <= float(outcome_value) <= e.hi else "miss"
    if e.form == "invariance":
        if outcome_value is None:
            return "inconclusive"
        return "match" if float(outcome_value) == e.baseline else "miss"
    if e.form in ("golden", "witness"):
        if outcome_value is None:
            return "inconclusive"
        expected = e.expected_output if e.form == "witness" else e.golden_ref
        return "match" if str(outcome_value) == str(expected) else "miss"
    if e.form == "exit":
        if outcome_value is None:
            return "inconclusive"
        return "match" if int(outcome_value) == 0 else "miss"
    if e.form == "membership":
        if outcome_value is None:
            return "inconclusive"
        observed = outcome_value if isinstance(outcome_value, (list, set, tuple)) else [outcome_value]
        return "match" if set(map(str, observed)) <= set(e.allowed_set) else "miss"
    return "inconclusive"
