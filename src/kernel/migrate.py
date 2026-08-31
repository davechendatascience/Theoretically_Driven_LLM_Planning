"""v1 (.damped-plan) -> v2, per docs/migration_map.md.

Two kinds exist so migration stays lossless without admitting an expectation
that cannot fail:

  Intent  a stated direction with no check  (v1 predictions with no range and
          no pattern — seven of them live, one on a plan recorded `validated`)
  Given   an observation no intervention produced (v1 Facts, and every evidence
          record with no paired expectation)

Unplaceable fields are reported by name, never dropped into a catch-all.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import Change, Constraint, Expectation, FailureMode, Given, Goal, Intent, Outcome

# Fields with no home in the v2 model. Derivable or unread — see the map.
KNOWN_UNPLACEABLE = {
    "Goal.met": "derived from baseline/target and the latest Outcome",
    "Goal.evaluation_protocol": "carried",
    "EvidenceRecord.polarity": "derived by comparing Outcome to its Expectation",
    "Fact.confidence": "free numeric parameter with no calibration path",
    # Fact.truth_status is NOT unplaceable: it maps to Given.provenance,
    # a separate epistemic lattice. Collapsing it into Constraint.status
    # would have been lossy — live stores carry "assumed" and "observed".
    "Intervention.estimated_cost": "no reader",
    "Plan.outcome_summary": "prose superseded by Outcomes",
    "EvidenceClaim.credibility_score": "carried as deprecated, read by nothing",
    "EvidenceClaim.coverage_ratio": "carried as deprecated, read by nothing",
}


@dataclass
class MigrationReport:
    store: str
    goals: int = 0
    constraints: int = 0
    givens: int = 0
    failure_modes: int = 0
    changes: int = 0
    expectations: int = 0
    intents: int = 0
    outcomes: int = 0
    unplaceable: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def lossless(self) -> bool:
        return not self.errors


_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def _split_target(raw: str) -> tuple[float | None, str]:
    """v1 target is prose with the current value inlined. Extract the first
    number as the typed target; preserve the whole string so nothing is lost."""
    if not raw:
        return None, ""
    m = _NUM.search(raw)
    return (float(m.group()) if m else None), raw


def migrate(v1_dir: Path) -> tuple[dict[str, list[Any]], MigrationReport]:
    v1_dir = Path(v1_dir)
    rep = MigrationReport(store=str(v1_dir))
    out: dict[str, list[Any]] = {
        "goals": [], "constraints": [], "givens": [], "failure_modes": [],
        "changes": [], "expectations": [], "intents": [], "outcomes": [],
    }

    pj = v1_dir / "project.json"
    if pj.exists():
        proj = json.loads(pj.read_text())
        for g in proj.get("goals", []):
            target, note = _split_target(g.get("target", ""))
            out["goals"].append(Goal(
                id=g["id"], statement=g.get("statement", ""),
                metric_name=g.get("metric_name", ""),
                baseline=None, target=target, target_note=note,
                evaluation_protocol=g.get("evaluation_protocol"),
                priority=int(g.get("priority", 1)),
            ))
        for c in proj.get("constraints", []):
            out["constraints"].append(Constraint(
                id=c["id"], statement=c.get("statement", ""),
                severity=c.get("severity", "high"), status=c.get("status", "unknown"),
                citations=list(c.get("evidence_ids", [])), rationale=c.get("rationale"),
            ))
        for f in proj.get("facts", []):
            out["givens"].append(Given(
                id=f["id"], statement=f.get("statement", ""),
                provenance=f.get("truth_status", "unknown"),
                citations=list(f.get("evidence_ids", [])), verified=False,
            ))
        for fm in proj.get("failure_modes", []):
            out["failure_modes"].append(FailureMode(
                id=fm["id"], symptom=fm.get("symptom", ""),
                severity=fm.get("severity", "medium"), subsystem=fm.get("subsystem"),
                citations=list(fm.get("evidence_ids", [])),
            ))

    for pf in sorted((v1_dir / "plans").glob("*.json")) if (v1_dir / "plans").exists() else []:
        try:
            p = json.loads(pf.read_text())
        except Exception as exc:                       # pragma: no cover
            rep.errors.append(f"{pf.name}: {exc}")
            continue
        iv = p.get("intervention") or {}
        dr = p.get("decision_rule") or {}
        out["changes"].append(Change(
            id=p["id"], title=p.get("title", ""),
            status={"validated": "adopted", "rejected": "rejected",
                    "rolled_back": "rolled_back", "executable": "authorised",
                    "executing": "executing"}.get(p.get("status", ""), "draft"),
            allowed_files=list(iv.get("allowed_files", [])),
            reversible=bool(iv.get("reversible", True)),
            references=[a["constraint_id"] for a in p.get("constraint_audit", [])],
            goal_ids=list(p.get("goal_ids", [])),
            failure_ids=list(p.get("addresses_failure_ids", [])),
            adopt_if=" ".join(dr.get("adopt_if", []) or []),
            reject_if=" ".join(dr.get("reject_if", []) or []),
            rollback=p.get("rollback_description") or "",
            approved_by=p.get("approved_by"),
            parent_change_id=p.get("parent_plan_id"),
        ))
        # An expectation nobody can produce an Outcome for cannot fail, so the
        # plan's registered validation command becomes the instrument. v1 plans
        # whose steps carry command=null have none, and their predictions
        # degrade to Intent rather than being admitted unfalsifiably.
        instrument = next(
            (vs.get("command") for vs in p.get("validation_steps", []) if vs.get("command")),
            "",
        )
        pc = p.get("predictive_contract") or {}
        for pred in pc.get("predictions", []):
            rng = pred.get("expected_range")
            pattern = pred.get("expected_pattern") or ""
            if rng and len(rng) == 2 and instrument:
                form = "invariance" if pred.get("direction") == "no_change" else "range"
                out["expectations"].append(Expectation(
                    id=f"{p['id']}::{pred.get('id', pred.get('metric_id',''))}",
                    change_id=p["id"], form=form,
                    metric_id=pred.get("metric_id", ""),
                    lo=float(rng[0]), hi=float(rng[1]),
                    baseline=float(rng[0]) if form == "invariance" else None,
                    instrument=instrument,
                    rationale=pred.get("rationale", ""),
                ))
            elif not pattern or not instrument:
                # Unfailable in v1: preserved as Intent rather than admitted.
                out["intents"].append(Intent(
                    id=f"{p['id']}::{pred.get('id', pred.get('metric_id',''))}",
                    change_id=p["id"], metric_id=pred.get("metric_id", ""),
                    direction=pred.get("direction", ""),
                    note=("migrated: no instrument, nothing could produce an outcome"
                          if not instrument else
                          "migrated: no range and no pattern, cannot fail"),
                ))

    ev_dir = v1_dir / "evidence"
    for ef in sorted(ev_dir.glob("*.json")) if ev_dir.exists() else []:
        try:
            e = json.loads(ef.read_text())
        except Exception as exc:                       # pragma: no cover
            rep.errors.append(f"{ef.name}: {exc}")
            continue
        obs = e.get("observations") or []
        plan_id = e.get("linked_plan_id")
        if obs and plan_id:
            for o in obs:
                out["outcomes"].append(Outcome(
                    id=f"{e['id']}::{o.get('metric_id','')}",
                    expectation_id=f"{plan_id}::{o.get('metric_id','')}",
                    change_id=plan_id, value=o.get("value"),
                    payload={"unit": o.get("unit")}, artifact_uri=e.get("artifact_uri"),
                ))
        else:
            # No paired Expectation: state, not evidence. Polarity preserved
            # but marked unverified rather than laundered.
            out["givens"].append(Given(
                id=e["id"], statement=e.get("summary", "")[:500],
                provenance="observed", citations=[e["id"]],
                asserted_polarity=e.get("polarity"), verified=False,
            ))

    rep.goals, rep.constraints = len(out["goals"]), len(out["constraints"])
    rep.givens, rep.failure_modes = len(out["givens"]), len(out["failure_modes"])
    rep.changes, rep.expectations = len(out["changes"]), len(out["expectations"])
    rep.intents, rep.outcomes = len(out["intents"]), len(out["outcomes"])
    rep.unplaceable = sorted(KNOWN_UNPLACEABLE)
    return out, rep
