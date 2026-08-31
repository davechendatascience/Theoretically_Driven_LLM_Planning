"""Belief slices — the derived layer.

There is no function here that an agent can reach which writes a belief. Every
number below is recomputed from (evidence, declarations, priors, model version)
on demand, which is what makes the cache deletable and the whole layer
reproducible (4.6, 10.2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from . import MODEL_VERSION
from .declarations import Contract, Declarations
from .expr import ExprError, evaluate_bool, referenced_names
from .ids import content_hash, set_hash
from .stats import beta_mean, credible_interval

BELIEF_ELIGIBLE = ("measured", "imported")

STATE_INSUFFICIENT = "insufficient_evidence"
STATE_SUPPORTED = "supported"
STATE_REFUTED = "refuted"
STATE_CONTESTED = "contested"

UNBUCKETED = "unbucketed"


@dataclass
class Slice:
    contract_id: str
    bucket: str
    compat_group: str
    compat_fields: dict[str, Any]
    state: str
    point: float
    lo: float
    hi: float
    n_valid: int
    n_invalid: int
    n_excluded: int
    passes: int
    fails: int
    alpha: float
    beta: float
    target_rate: float
    evidence_ids: list[str]
    prior_id: str | None
    missing: dict[str, Any] = field(default_factory=dict)
    exclusions: dict[str, int] = field(default_factory=dict)

    @property
    def ci_width(self) -> float:
        return self.hi - self.lo

    @property
    def set_hash(self) -> str:
        return set_hash(self.evidence_ids)

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.contract_id, self.bucket, self.compat_group)

    def condition_label(self) -> str:
        parts = [self.bucket]
        parts += [f"{k}={v}" for k, v in sorted(self.compat_fields.items())]
        return ", ".join(parts)


def _env_for(trial: dict[str, Any]) -> dict[str, Any]:
    """Variables a condition predicate may reference: captured conditions and
    the reproducibility block, with metrics available too."""
    env: dict[str, Any] = {}
    env.update(trial.get("repro") or {})
    env.update((trial.get("conditions") or {}).get("raw") or {})
    env.update(trial.get("metrics") or {})
    return env


def bucket_for(contract: Contract, trial: dict[str, Any]) -> str:
    """Buckets are declared, never inferred (2.4). A trial matching no declared
    predicate is `unbucketed` and contributes only to the unconditioned slice."""
    env = _env_for(trial)
    for condition in contract.conditions:
        when = condition.get("when")
        if not when:
            continue
        try:
            if evaluate_bool(when, env):
                return str(condition.get("id", UNBUCKETED))
        except ExprError:
            continue
    return UNBUCKETED


def compat_for(contract: Contract, trial: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Compatibility group: trials differing on any declared key are never
    pooled (5.6)."""
    if not contract.compatibility_key:
        return "all", {}
    repro = trial.get("repro") or {}
    fields = {k: repro.get(k) for k in contract.compatibility_key}
    return content_hash(fields, 6), fields


def score_trial(contract: Contract, trial: dict[str, Any]) -> tuple[bool | None, str]:
    """Did this trial pass its contract?

    The contract's acceptance rule is authoritative — not the runner's exit
    code. If the declared metrics are absent the trial is *excluded* with a
    reason rather than silently falling back to the outcome field, because a
    quiet fallback is exactly how an unmeasured thing starts looking measured.
    """
    outcome = trial.get("outcome")
    if outcome in ("error", "not_applicable"):
        return None, f"outcome_{outcome}"

    metrics = trial.get("metrics") or {}
    try:
        needed = referenced_names(contract.rule)
    except ExprError:
        return None, "unparsable_rule"

    missing = needed - set(metrics)
    if missing:
        return None, "missing_metrics"

    try:
        return evaluate_bool(contract.rule, dict(metrics)), ""
    except ExprError:
        return None, "unevaluable_rule"


def eligible(trial: dict[str, Any]) -> bool:
    """Only measured and imported evidence can move a posterior (10.4)."""
    return trial.get("provenance") in BELIEF_ELIGIBLE


def compute_slices(
    decl: Declarations,
    trials: Iterable[dict[str, Any]],
    contract_ids: Iterable[str] | None = None,
) -> list[Slice]:
    wanted = set(contract_ids) if contract_ids is not None else None
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}

    for trial in trials:
        contract_id = trial.get("contract_id", "")
        if wanted is not None and contract_id not in wanted:
            continue
        contract = decl.contracts.get(contract_id)
        if contract is None or not decl.is_scorable(contract_id):
            continue
        if not eligible(trial):
            continue

        bucket = bucket_for(contract, trial)
        compat_group, compat_fields = compat_for(contract, trial)
        key = (contract_id, bucket, compat_group)
        bundle = grouped.setdefault(key, {
            "contract": contract,
            "compat_fields": compat_fields,
            "passes": 0, "fails": 0,
            "n_invalid": 0, "n_excluded": 0,
            "ids": [], "exclusions": {},
        })

        if trial.get("validity") != "valid":
            bundle["n_invalid"] += 1
            continue

        verdict, reason = score_trial(contract, trial)
        if verdict is None:
            bundle["n_excluded"] += 1
            bundle["exclusions"][reason] = bundle["exclusions"].get(reason, 0) + 1
            continue

        bundle["ids"].append(trial["id"])
        if verdict:
            bundle["passes"] += 1
        else:
            bundle["fails"] += 1

    slices: list[Slice] = []
    for (contract_id, bucket, compat_group), bundle in grouped.items():
        contract: Contract = bundle["contract"]
        prior = decl.priors.get(contract_id)
        a0 = prior.alpha if prior else 1.0
        b0 = prior.beta if prior else 1.0

        passes, fails = bundle["passes"], bundle["fails"]
        n_valid = passes + fails
        alpha, beta = a0 + passes, b0 + fails
        point = beta_mean(alpha, beta)
        lo, hi = credible_interval(alpha, beta)

        state, missing = _classify(contract, n_valid, lo, hi)
        slices.append(Slice(
            contract_id=contract_id,
            bucket=bucket,
            compat_group=compat_group,
            compat_fields=bundle["compat_fields"],
            state=state,
            point=point, lo=lo, hi=hi,
            n_valid=n_valid,
            n_invalid=bundle["n_invalid"],
            n_excluded=bundle["n_excluded"],
            passes=passes, fails=fails,
            alpha=alpha, beta=beta,
            target_rate=contract.target_rate,
            evidence_ids=sorted(bundle["ids"]),
            prior_id=prior.id if prior else None,
            missing=missing,
            exclusions=bundle["exclusions"],
        ))

    slices.sort(key=lambda s: (s.contract_id, s.bucket, s.compat_group))
    return slices


def _classify(contract: Contract, n_valid: int, lo: float, hi: float) -> tuple[str, dict[str, Any]]:
    """`insufficient_evidence` is a state, not a low number (5.7).

    It is checked *first*, so sparse data can never present as a verdict — the
    likeliest failure of an agent-driven loop is declaring victory on n=2.
    """
    width = hi - lo
    if n_valid < contract.n_min or width > contract.max_ci_width:
        missing: dict[str, Any] = {}
        if n_valid < contract.n_min:
            missing["trials_needed"] = contract.n_min - n_valid
        if width > contract.max_ci_width:
            missing["ci_width"] = round(width, 3)
            missing["max_ci_width"] = contract.max_ci_width
        return STATE_INSUFFICIENT, missing
    if lo > contract.target_rate:
        return STATE_SUPPORTED, {}
    if hi < contract.target_rate:
        return STATE_REFUTED, {}
    return STATE_CONTESTED, {}


def unobserved_contracts(decl: Declarations, slices: list[Slice]) -> list[str]:
    """Declared, scorable contracts with no belief-eligible evidence at all."""
    seen = {s.contract_id for s in slices}
    return sorted(
        cid for cid in decl.contracts
        if decl.is_scorable(cid) and cid not in seen
    )


def compare(before: list[Slice], after: list[Slice]) -> dict[str, list[dict[str, Any]]]:
    """Regressions across compatible slices only (5.5).

    Slices whose compat groups differ come back as `not_comparable` with the
    differing fields named — never as "no regression detected", which is the
    reading that lets a genuine regression hide behind a hardware swap.
    """
    index_after = {s.key: s for s in after}
    index_before = {s.key: s for s in before}
    regressions, improvements, not_comparable = [], [], []

    for key, new in index_after.items():
        old = index_before.get(key)
        if old is None:
            partial = [
                s for s in before
                if s.contract_id == new.contract_id and s.bucket == new.bucket
            ]
            for candidate in partial:
                differing = sorted(
                    k for k in set(candidate.compat_fields) | set(new.compat_fields)
                    if candidate.compat_fields.get(k) != new.compat_fields.get(k)
                )
                not_comparable.append({
                    "contract": new.contract_id,
                    "bucket": new.bucket,
                    "differing_fields": differing,
                    "reason": "compatibility group changed; pooling would require a reviewed decision",
                })
            continue
        delta = new.point - old.point
        entry = {
            "contract": new.contract_id,
            "bucket": new.bucket,
            "from": round(old.point, 4),
            "to": round(new.point, 4),
            "delta": round(delta, 4),
            "from_state": old.state,
            "to_state": new.state,
        }
        if new.hi < old.lo:
            regressions.append(entry)
        elif new.lo > old.hi:
            improvements.append(entry)

    return {
        "regressions": regressions,
        "improvements": improvements,
        "not_comparable": not_comparable,
    }


def model_version() -> str:
    return MODEL_VERSION
