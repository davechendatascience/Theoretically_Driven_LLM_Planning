"""Lenient input coercion — the ergonomics layer.

Tool payloads arrive as loose dicts (or JSON strings). Missing optional
structure never raises: the plan is stored anyway and the closure validator
turns each gap into a repair instruction. Only truly unusable input raises
InputError, and its message is itself an instruction for the caller.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from .. import ids
from ..models import (
    PLAN_SCHEMA_VERSION,
    CausalHypothesis,
    DisconfirmingPattern,
    MetricObservation,
    Prediction,
    PredictiveContract,
    Constraint,
    ConstraintKind,
    ConstraintStatus,
    DecisionRule,
    EvidenceClaim,
    EvidencePolarity,
    EvidenceRecord,
    Fact,
    FailureMode,
    Goal,
    Intervention,
    Plan,
    PlanConstraintAudit,
    PlanKind,
    PlanStatus,
    ProjectState,
    Severity,
    SubtaskEvidenceBundle,
    TruthStatus,
    ValidationStep,
    ValidatorKind,
)


class InputError(ValueError):
    """Unusable input; the message tells the caller how to fix the call."""


def now() -> datetime:
    return datetime.now(UTC)


def _as_dict(payload: Any, what: str) -> dict[str, Any]:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise InputError(
                f"The {what} argument was a string that is not valid JSON: {exc}. "
                f"Pass a JSON object."
            ) from exc
    if not isinstance(payload, dict):
        raise InputError(
            f"The {what} argument must be a JSON object, got {type(payload).__name__}."
        )
    return payload


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _str_list(value: Any) -> list[str]:
    return [str(item) for item in _as_list(value) if item is not None]


def _coerce_enum(enum_cls: type, value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    try:
        return enum_cls(text)
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------


def normalize_project(
    payload: Any, existing: ProjectState | None = None
) -> tuple[ProjectState, list[str]]:
    """Build/merge a ProjectState from a loose payload.

    Merge semantics: re-registering adds and updates items by id/statement,
    never deletes.
    """
    data = _as_dict(payload, "project")
    warnings: list[str] = []

    name = str(data.get("name") or (existing.name if existing else "") or "").strip()
    if not name:
        raise InputError(
            'Provide at least {"name": "<project name>"}. Goals, constraints and '
            "failure_modes may be added now or in a later register_project call."
        )

    project_id = (
        existing.project_id
        if existing
        else str(data.get("project_id") or "").strip()
        or re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-")
    )

    goals = list(existing.goals) if existing else []
    constraints = list(existing.constraints) if existing else []
    facts = list(existing.facts) if existing else []
    failure_modes = list(existing.failure_modes) if existing else []

    goal_ids = {g.id for g in goals}
    for raw in _as_list(data.get("goals")):
        goal = _normalize_goal(raw, goal_ids, warnings)
        _upsert(goals, goal)
        goal_ids.add(goal.id)

    constraint_ids = {c.id for c in constraints}
    for raw in _as_list(data.get("constraints")):
        constraint = _normalize_constraint(raw, constraint_ids, existing_by_id={c.id: c for c in constraints})
        _upsert(constraints, constraint)
        constraint_ids.add(constraint.id)

    failure_ids = {f.id for f in failure_modes}
    for raw in _as_list(data.get("failure_modes")):
        failure = _normalize_failure(raw, failure_ids)
        _upsert(failure_modes, failure)
        failure_ids.add(failure.id)

    fact_ids = {f.id for f in facts}
    facts_without_truth_status: list[str] = []
    for raw in _as_list(data.get("facts")):
        fact = _normalize_fact(raw, fact_ids)
        if isinstance(raw, dict) and not raw.get("truth_status"):
            facts_without_truth_status.append(fact.id)
        _upsert(facts, fact)
        fact_ids.add(fact.id)

    state = ProjectState(
        project_id=project_id,
        name=name,
        goals=goals,
        constraints=constraints,
        facts=facts,
        failure_modes=failure_modes,
        available_resources=_str_list(data.get("available_resources"))
        or (existing.available_resources if existing else []),
        forbidden_actions=_str_list(data.get("forbidden_actions"))
        or (existing.forbidden_actions if existing else []),
        current_baseline=data.get("current_baseline")
        or (existing.current_baseline if existing else None),
        version=existing.version if existing else 1,
    )

    for goal in state.goals:
        if not goal.metric_name or not goal.target:
            warnings.append(
                f"Goal {goal.id} has no metric/target yet; plans linked to it will be "
                f"UNDER_SPECIFIED until you re-register it with metric_name and target."
            )

    # Hollow-entity warnings: ids alone don't preserve meaning in the audit
    # trail. Advisory only — never blocks, so existing stores keep working.
    hollow_goals = [g.id for g in state.goals if not g.statement.strip()]
    if hollow_goals:
        warnings.append(
            f"Goal(s) {hollow_goals} have an empty statement; re-register them with "
            f'"statement" (aliases: title/description) saying what success means.'
        )
    hollow_constraints = [c.id for c in state.constraints if not c.statement.strip()]
    if hollow_constraints:
        warnings.append(
            f"Constraint(s) {hollow_constraints} have an empty statement; re-register "
            f'them with "statement" (aliases: description/text) saying what must hold.'
        )
    hollow_failures = [f.id for f in state.failure_modes if not f.symptom.strip()]
    if hollow_failures:
        warnings.append(
            f"Failure mode(s) {hollow_failures} have an empty symptom; re-register "
            f'them with "symptom" (aliases: statement/description) describing what '
            f"was observed."
        )
    if facts_without_truth_status:
        warnings.append(
            f"Fact(s) {facts_without_truth_status} defaulted to truth_status "
            f'"assumed"; pass observed|inferred|assumed|unknown to preserve the '
            f"distinction between measured and assumed knowledge."
        )
    return state, warnings


def _upsert(items: list, item) -> None:
    for i, current in enumerate(items):
        if current.id == item.id:
            items[i] = item
            return
    items.append(item)


def _normalize_goal(raw: Any, taken: set[str], warnings: list[str]) -> Goal:
    if isinstance(raw, str):
        return Goal(id=ids.next_id(ids.GOAL_PREFIX, taken), statement=raw)
    data = _as_dict(raw, "goal")
    return Goal(
        id=str(data.get("id") or ids.next_id(ids.GOAL_PREFIX, taken)),
        statement=str(
            data.get("statement")
            or data.get("title")
            or data.get("description")
            or data.get("name")
            or ""
        ),
        metric_name=str(data.get("metric_name") or data.get("metric") or ""),
        target=str(data.get("target") or ""),
        evaluation_protocol=data.get("evaluation_protocol"),
        priority=int(data.get("priority") or 1),
        met=bool(data.get("met", False)),
    )


def _normalize_constraint(
    raw: Any, taken: set[str], existing_by_id: dict[str, Constraint]
) -> Constraint:
    if isinstance(raw, str):
        return Constraint(
            id=ids.next_id(ids.CONSTRAINT_PREFIX, taken),
            statement=raw,
            kind=ConstraintKind.HARD,
            status=ConstraintStatus.UNKNOWN,
        )
    data = _as_dict(raw, "constraint")
    constraint_id = str(data.get("id") or ids.next_id(ids.CONSTRAINT_PREFIX, taken))
    prior = existing_by_id.get(constraint_id)
    # Status changes must go through update_constraint_status (evidence-gated),
    # so re-registration preserves the recorded status of a known constraint.
    if prior is not None:
        status = prior.status
        evidence_ids = prior.evidence_ids
        rationale = prior.rationale
    else:
        status = _coerce_enum(ConstraintStatus, data.get("status"), ConstraintStatus.UNKNOWN)
        evidence_ids = _str_list(data.get("evidence_ids"))
        rationale = data.get("rationale")
        if (
            status == ConstraintStatus.SAT
            and _coerce_enum(ConstraintKind, data.get("kind"), ConstraintKind.HARD)
            == ConstraintKind.HARD
            and not evidence_ids
        ):
            # No unaudited SAT hard constraints at registration time (§10.3).
            status = ConstraintStatus.UNKNOWN
    return Constraint(
        id=constraint_id,
        statement=str(
            data.get("statement") or data.get("description") or data.get("text") or ""
        ),
        kind=_coerce_enum(ConstraintKind, data.get("kind"), ConstraintKind.HARD),
        severity=_coerce_enum(Severity, data.get("severity"), Severity.HIGH),
        status=status,
        evidence_ids=evidence_ids,
        validator_ids=_str_list(data.get("validator_ids")),
        rationale=rationale,
    )


def _normalize_failure(raw: Any, taken: set[str]) -> FailureMode:
    if isinstance(raw, str):
        return FailureMode(
            id=ids.next_id(ids.FAILURE_PREFIX, taken),
            symptom=raw,
            severity=Severity.HIGH,
        )
    data = _as_dict(raw, "failure_mode")
    return FailureMode(
        id=str(data.get("id") or ids.next_id(ids.FAILURE_PREFIX, taken)),
        symptom=str(
            data.get("symptom")
            or data.get("statement")
            or data.get("description")
            or data.get("name")
            or ""
        ),
        severity=_coerce_enum(Severity, data.get("severity"), Severity.HIGH),
        subsystem=data.get("subsystem"),
        evidence_ids=_str_list(data.get("evidence_ids")),
    )


def _normalize_fact(raw: Any, taken: set[str]) -> Fact:
    if isinstance(raw, str):
        return Fact(
            id=ids.next_id(ids.FACT_PREFIX, taken),
            statement=raw,
            truth_status=TruthStatus.ASSUMED,
        )
    data = _as_dict(raw, "fact")
    return Fact(
        id=str(data.get("id") or ids.next_id(ids.FACT_PREFIX, taken)),
        statement=str(
            data.get("statement") or data.get("description") or data.get("text") or ""
        ),
        truth_status=_coerce_enum(
            TruthStatus, data.get("truth_status"), TruthStatus.ASSUMED
        ),
        evidence_ids=_str_list(data.get("evidence_ids")),
        confidence=data.get("confidence"),
    )


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------


def normalize_plan(
    payload: Any,
    project: ProjectState,
    existing_plan_ids: set[str],
    existing_plan: Plan | None = None,
) -> tuple[Plan, list[str]]:
    data = _as_dict(payload, "plan")
    warnings: list[str] = []

    title = str(
        data.get("title") or (existing_plan.title if existing_plan else "")
    ).strip()
    if not title:
        raise InputError(
            'Provide at least {"title": "<what this plan does>", "kind": '
            '"measurement|implementation|repair|rollback"}. Everything else — goals, '
            "hypothesis, intervention, validation, decision_rule — may be added later "
            "by calling create_plan again with the same plan id."
        )

    kind_raw = data.get("kind") or (existing_plan.kind if existing_plan else None)
    kind = _coerce_enum(PlanKind, kind_raw, None)
    if kind is None:
        raise InputError(
            'Set "kind" to one of: measurement (safe diagnostic that resolves an '
            "unknown), implementation (changes production behavior), repair, rollback. "
            "The kind decides which gate rules apply, so it cannot be defaulted."
        )

    plan_id = str(
        data.get("id")
        or data.get("plan_id")
        or (existing_plan.id if existing_plan else "")
        or ids.next_id(ids.PLAN_PREFIX, existing_plan_ids)
    )

    goal_ids = _str_list(data.get("goal_ids")) or (
        existing_plan.goal_ids if existing_plan else []
    )
    if not goal_ids:
        goal_ids = [g.id for g in project.goals if not g.met]
        if goal_ids:
            warnings.append(
                f"goal_ids not given; linked to all open goals: {goal_ids}."
            )

    hypothesis = _normalize_hypothesis(data.get("hypothesis"), plan_id) or (
        existing_plan.hypothesis if existing_plan else None
    )
    intervention = _normalize_intervention(data.get("intervention"), plan_id, kind) or (
        existing_plan.intervention if existing_plan else None
    )
    validation_steps = [
        _normalize_validation_step(raw, index)
        for index, raw in enumerate(_as_list(data.get("validation_steps")), start=1)
    ] or (existing_plan.validation_steps if existing_plan else [])
    decision_rule = _normalize_decision_rule(data.get("decision_rule")) or (
        existing_plan.decision_rule if existing_plan else None
    )
    contract = _normalize_contract(data.get("predictive_contract")) or (
        existing_plan.predictive_contract if existing_plan else None
    )

    audit = _normalize_audit(
        data.get("constraint_audit"), project, existing_plan, warnings
    )

    steps_without_expectation = [
        s.id for s in validation_steps if s.required and not s.expected_result.strip()
    ]
    if steps_without_expectation:
        warnings.append(
            f"Required validation step(s) {steps_without_expectation} have no "
            f"expected_result; state what outcome counts as a pass so the "
            f"decision_rule can be applied without judgment calls."
        )

    timestamp = now()
    plan = Plan(
        id=plan_id,
        project_id=project.project_id,
        title=title,
        status=existing_plan.status if existing_plan else PlanStatus.DRAFT,
        kind=kind,
        goal_ids=goal_ids,
        addresses_failure_ids=_str_list(data.get("addresses_failure_ids"))
        or (existing_plan.addresses_failure_ids if existing_plan else []),
        hypothesis=hypothesis,
        intervention=intervention,
        constraint_audit=audit,
        assumptions=_str_list(data.get("assumptions"))
        or (existing_plan.assumptions if existing_plan else []),
        unknowns=_str_list(data.get("unknowns"))
        or (existing_plan.unknowns if existing_plan else []),
        validation_steps=validation_steps,
        decision_rule=decision_rule,
        predictive_contract=contract,
        # New plans get the current schema; edited plans keep the version they
        # were created under (grandfathered closure rules).
        schema_version=(
            existing_plan.schema_version if existing_plan else PLAN_SCHEMA_VERSION
        ),
        rollback_description=data.get("rollback_description")
        or (existing_plan.rollback_description if existing_plan else None),
        parent_plan_id=data.get("parent_plan_id")
        or (existing_plan.parent_plan_id if existing_plan else None),
        approved_by=existing_plan.approved_by if existing_plan else None,
        approval_note=existing_plan.approval_note if existing_plan else None,
        version=(existing_plan.version + 1) if existing_plan else 1,
        created_at=existing_plan.created_at if existing_plan else timestamp,
        updated_at=timestamp,
    )
    return plan, warnings


def _normalize_hypothesis(raw: Any, plan_id: str) -> CausalHypothesis | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        return CausalHypothesis(id=f"H-{plan_id}", statement=raw)
    data = _as_dict(raw, "hypothesis")
    statement = str(data.get("statement") or "")
    if not statement:
        return None
    return CausalHypothesis(
        id=str(data.get("id") or f"H-{plan_id}"),
        statement=statement,
        linked_failure_ids=_str_list(data.get("linked_failure_ids")),
        alternative_hypothesis_ids=_str_list(data.get("alternative_hypothesis_ids")),
    )


def _normalize_intervention(raw: Any, plan_id: str, kind: PlanKind) -> Intervention | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        return Intervention(id=f"I-{plan_id}", description=raw, kind=kind)
    data = _as_dict(raw, "intervention")
    description = str(data.get("description") or "")
    if not description:
        return None
    return Intervention(
        id=str(data.get("id") or f"I-{plan_id}"),
        description=description,
        kind=_coerce_enum(PlanKind, data.get("kind"), kind),
        allowed_files=_str_list(data.get("allowed_files")),
        expected_api_changes=_str_list(data.get("expected_api_changes")),
        reversible=bool(data.get("reversible", True)),
        estimated_cost=data.get("estimated_cost"),
    )


def _normalize_validation_step(raw: Any, index: int) -> ValidationStep:
    if isinstance(raw, str):
        return ValidationStep(
            id=f"V-{index:03d}",
            description=raw,
            kind=ValidatorKind.MANUAL,
        )
    data = _as_dict(raw, "validation_step")
    phase = str(data.get("phase") or "posterior").strip().lower()
    return ValidationStep(
        id=str(data.get("id") or f"V-{index:03d}"),
        description=str(data.get("description") or ""),
        kind=_coerce_enum(ValidatorKind, data.get("kind"), ValidatorKind.MANUAL),
        command=data.get("command"),
        expected_result=str(data.get("expected_result") or ""),
        required=bool(data.get("required", True)),
        phase=phase if phase in ("prior", "posterior") else "posterior",
    )


def _normalize_contract(raw: Any) -> PredictiveContract | None:
    if raw is None:
        return None
    data = _as_dict(raw, "predictive_contract")

    predictions: list[Prediction] = []
    for index, entry in enumerate(_as_list(data.get("predictions")), start=1):
        p = _as_dict(entry, "prediction")
        metric_id = str(p.get("metric_id") or p.get("metric") or "").strip()
        if not metric_id:
            continue
        expected_range = None
        raw_range = p.get("expected_range")
        if isinstance(raw_range, (list, tuple)) and len(raw_range) == 2:
            try:
                expected_range = (float(raw_range[0]), float(raw_range[1]))
            except (TypeError, ValueError):
                expected_range = None
        direction = str(p.get("direction") or "no_change").strip().lower()
        if direction not in ("increase", "decrease", "no_change", "non_monotonic"):
            direction = "no_change"
        confidence = str(p.get("confidence") or "medium").strip().lower()
        if confidence not in ("low", "medium", "high"):
            confidence = "medium"
        predictions.append(
            Prediction(
                id=str(p.get("id") or f"PR-{index:03d}"),
                metric_id=metric_id,
                direction=direction,
                expected_range=expected_range,
                expected_pattern=str(p.get("expected_pattern") or p.get("prediction") or ""),
                confidence=confidence,
                rationale=str(p.get("rationale") or ""),
            )
        )

    patterns: list[DisconfirmingPattern] = []
    for index, entry in enumerate(_as_list(data.get("disconfirming_patterns")), start=1):
        if isinstance(entry, str):
            patterns.append(
                DisconfirmingPattern(id=f"D-{index:03d}", description=entry)
            )
            continue
        d = _as_dict(entry, "disconfirming_pattern")
        description = str(d.get("description") or d.get("pattern") or "").strip()
        if not description:
            continue
        patterns.append(
            DisconfirmingPattern(
                id=str(d.get("id") or f"D-{index:03d}"),
                description=description,
                implication=str(d.get("implication") or ""),
                suggested_model_expansion=d.get("suggested_model_expansion")
                or d.get("expansion"),
            )
        )

    contract = PredictiveContract(
        context_fixed=_str_list(data.get("context_fixed")),
        context_varied=_str_list(data.get("context_varied")),
        predictions=predictions,
        disconfirming_patterns=patterns,
        next_expansions=_str_list(
            data.get("next_expansions") or data.get("next_model_expansion_if_failed")
        ),
    )
    if (
        not contract.predictions
        and not contract.disconfirming_patterns
        and not contract.context_fixed
    ):
        return None
    return contract


def _normalize_decision_rule(raw: Any) -> DecisionRule | None:
    if raw is None:
        return None
    data = _as_dict(raw, "decision_rule")
    rule = DecisionRule(
        adopt_if=_str_list(data.get("adopt_if")),
        reject_if=_str_list(data.get("reject_if")),
    )
    if not rule.adopt_if and not rule.reject_if:
        return None
    return rule


def _normalize_audit(
    raw: Any,
    project: ProjectState,
    existing_plan: Plan | None,
    warnings: list[str],
) -> list[PlanConstraintAudit]:
    """Auto-populate one audit entry per registered constraint, seeded from the
    project's evidence-gated status, then overlay caller-provided entries.

    A caller entry may only claim NOT_APPLICABLE or UNSAT/UNKNOWN on its own;
    claiming SAT for a hard constraint the project has not recorded as SAT is
    downgraded to the project status (self-certification guard, §10.3).
    """
    provided: dict[str, PlanConstraintAudit] = {}
    if existing_plan:
        provided.update(existing_plan.audit_by_constraint())
    for entry_raw in _as_list(raw):
        if isinstance(entry_raw, str):
            continue
        data = _as_dict(entry_raw, "constraint_audit entry")
        constraint_id = str(data.get("constraint_id") or data.get("id") or "")
        if not constraint_id:
            continue
        provided[constraint_id] = PlanConstraintAudit(
            constraint_id=constraint_id,
            status=_coerce_enum(
                ConstraintStatus, data.get("status"), ConstraintStatus.UNKNOWN
            ),
            evidence=data.get("evidence"),
            blocker=data.get("blocker"),
        )

    audit: list[PlanConstraintAudit] = []
    for constraint in project.constraints:
        entry = provided.pop(constraint.id, None)
        if entry is None:
            audit.append(
                PlanConstraintAudit(
                    constraint_id=constraint.id,
                    status=constraint.status,
                    evidence=constraint.rationale,
                )
            )
            continue
        if (
            entry.status == ConstraintStatus.SAT
            and constraint.kind == ConstraintKind.HARD
            and constraint.status != ConstraintStatus.SAT
        ):
            warnings.append(
                f"Audit claims {constraint.id} is SAT but the project records it as "
                f"{constraint.status}. Using {constraint.status}: record evidence and "
                f"call update_constraint_status to mark it SAT."
            )
            entry = entry.model_copy(update={"status": constraint.status})
        audit.append(entry)

    for orphan_id, entry in provided.items():
        warnings.append(
            f"Audit entry for unregistered constraint {orphan_id!r} kept as-is; "
            f"register it via register_project to have it gate-checked."
        )
        audit.append(entry)
    return audit


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


def normalize_evidence(
    payload: Any, project: ProjectState, existing_evidence_ids: set[str]
) -> EvidenceRecord:
    data = _as_dict(payload, "evidence")
    summary = str(data.get("summary") or data.get("statement") or "").strip()
    if not summary:
        raise InputError(
            'Provide at least {"summary": "<what was observed>"}. Optional: '
            'source_type (test|benchmark|simulation|log|manual_review|paper|commit|'
            'profiling|solver), polarity (supports|refutes|neutral), artifact_uri, '
            "linked_constraint_ids, linked_hypothesis_ids, linked_plan_id."
        )
    source_type = str(data.get("source_type") or "manual_review").strip().lower()
    valid_sources = {
        "test", "benchmark", "simulation", "log", "manual_review",
        "paper", "commit", "profiling", "solver",
    }
    if source_type not in valid_sources:
        source_type = "manual_review"
    observations: list[MetricObservation] = []
    for entry in _as_list(data.get("observations")):
        o = _as_dict(entry, "observation")
        metric_id = str(o.get("metric_id") or o.get("metric") or "").strip()
        if not metric_id or o.get("value") is None:
            continue
        try:
            value = float(o.get("value"))
        except (TypeError, ValueError):
            continue
        seeds = []
        for s in _as_list(o.get("seed_values")):
            try:
                seeds.append(float(s))
            except (TypeError, ValueError):
                continue
        observations.append(
            MetricObservation(
                metric_id=metric_id, value=value, unit=o.get("unit"),
                seed_values=seeds,
            )
        )

    claims: list[EvidenceClaim] = []
    for entry in _as_list(data.get("claims")):
        c = _as_dict(entry, "claim")
        stmt = str(c.get("assertion_statement") or c.get("statement") or "").strip()
        if not stmt:
            continue
        try:
            cred_score = float(c.get("credibility_score", 1.0))
        except (TypeError, ValueError):
            cred_score = 1.0
        try:
            cov_ratio = float(c.get("coverage_ratio", 1.0))
        except (TypeError, ValueError):
            cov_ratio = 1.0
        try:
            step_idx = int(c.get("step_index", 0))
        except (TypeError, ValueError):
            step_idx = 0
        claims.append(
            EvidenceClaim(
                claim_id=str(c.get("claim_id") or ids.generate_id(ids.CLAIM_PREFIX)),
                target_subtask_id=str(c.get("target_subtask_id") or "subtask-0"),
                assertion_statement=stmt,
                observed_payload=_as_dict(c.get("observed_payload") or {}, "observed_payload"),
                source_provenance=str(c.get("source_provenance") or "tool:unknown"),
                credibility_score=max(0.0, min(1.0, cred_score)),
                coverage_ratio=max(0.0, min(1.0, cov_ratio)),
                step_index=step_idx,
                is_terminal=bool(c.get("is_terminal", False)),
            )
        )

    bundle: SubtaskEvidenceBundle | None = None
    if data.get("subtask_bundle"):
        b_data = _as_dict(data.get("subtask_bundle"), "subtask_bundle")
        b_claims: list[EvidenceClaim] = []
        for entry in _as_list(b_data.get("claims")):
            c = _as_dict(entry, "claim")
            stmt = str(c.get("assertion_statement") or c.get("statement") or "").strip()
            if not stmt:
                continue
            try:
                cred_score = float(c.get("credibility_score", 1.0))
            except (TypeError, ValueError):
                cred_score = 1.0
            try:
                cov_ratio = float(c.get("coverage_ratio", 1.0))
            except (TypeError, ValueError):
                cov_ratio = 1.0
            try:
                step_idx = int(c.get("step_index", 0))
            except (TypeError, ValueError):
                step_idx = 0
            b_claims.append(
                EvidenceClaim(
                    claim_id=str(c.get("claim_id") or ids.generate_id(ids.CLAIM_PREFIX)),
                    target_subtask_id=str(c.get("target_subtask_id") or "subtask-0"),
                    assertion_statement=stmt,
                    observed_payload=_as_dict(c.get("observed_payload") or {}, "observed_payload"),
                    source_provenance=str(c.get("source_provenance") or "tool:unknown"),
                    credibility_score=max(0.0, min(1.0, cred_score)),
                    coverage_ratio=max(0.0, min(1.0, cov_ratio)),
                    step_index=step_idx,
                    is_terminal=bool(c.get("is_terminal", False)),
                )
            )
        d_status = str(b_data.get("damping_status") or "converged")
        valid_statuses = {"converged", "exhausted_budget", "diminishing_returns"}
        if d_status not in valid_statuses:
            d_status = "converged"
        bundle = SubtaskEvidenceBundle(
            subtask_id=str(b_data.get("subtask_id") or "subtask-0"),
            claims=b_claims or claims,
            aggregate_credibility=max(0.0, min(1.0, float(b_data.get("aggregate_credibility", 1.0)))),
            total_coverage=max(0.0, min(1.0, float(b_data.get("total_coverage", 0.0)))),
            damping_status=d_status,  # type: ignore[arg-type]
            residual_variance=float(b_data.get("residual_variance", 0.0)),
        )

    return EvidenceRecord(
        id=str(data.get("id") or ids.next_id(ids.EVIDENCE_PREFIX, existing_evidence_ids)),
        project_id=project.project_id,
        source_type=source_type,  # type: ignore[arg-type]
        artifact_uri=data.get("artifact_uri"),
        summary=summary,
        polarity=_coerce_enum(
            EvidencePolarity, data.get("polarity"), EvidencePolarity.NEUTRAL
        ),
        linked_hypothesis_ids=_str_list(data.get("linked_hypothesis_ids")),
        linked_constraint_ids=_str_list(data.get("linked_constraint_ids")),
        linked_plan_id=data.get("linked_plan_id"),
        observations=observations,
        observed_pattern_ids=_str_list(data.get("observed_pattern_ids")),
        claims=claims,
        subtask_bundle=bundle,
        created_at=now(),
    )
