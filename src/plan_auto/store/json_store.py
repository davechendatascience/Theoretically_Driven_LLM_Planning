"""JSON file store: atomic writes, advisory lock, internal version bumps.

Layout inside the data dir (the target project's `.plan-auto/`):

    project.json        ProjectState
    plans/P-0001.json   one file per Plan
    evidence/EV-0001.json
    events.jsonl        append-only (see events.py)
    gate.json           derived snapshot for the PreToolUse hook (see gate.py)
    .lock               flock target
"""

from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from ..models import EvidenceRecord, Plan, ProjectState


def atomic_write_json(path: Path, data: Any) -> None:
    """Write via temp file + os.replace so readers never see partial JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)


class JsonStore:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        (self.data_dir / "plans").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "evidence").mkdir(parents=True, exist_ok=True)

    # -- locking ------------------------------------------------------------

    @contextmanager
    def locked(self) -> Iterator[None]:
        lock_path = self.data_dir / ".lock"
        with open(lock_path, "w") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    # -- project ------------------------------------------------------------

    @property
    def project_path(self) -> Path:
        return self.data_dir / "project.json"

    def load_project(self) -> ProjectState | None:
        if not self.project_path.exists():
            return None
        return ProjectState.model_validate_json(
            self.project_path.read_text(encoding="utf-8")
        )

    def save_project(self, project: ProjectState, bump_version: bool = True) -> ProjectState:
        if bump_version and self.project_path.exists():
            project = project.model_copy(update={"version": project.version + 1})
        atomic_write_json(self.project_path, project.model_dump(mode="json"))
        return project

    # -- plans --------------------------------------------------------------

    def plan_path(self, plan_id: str) -> Path:
        return self.data_dir / "plans" / f"{plan_id}.json"

    def load_plan(self, plan_id: str) -> Plan | None:
        path = self.plan_path(plan_id)
        if not path.exists():
            return None
        return Plan.model_validate_json(path.read_text(encoding="utf-8"))

    def save_plan(self, plan: Plan) -> None:
        atomic_write_json(self.plan_path(plan.id), plan.model_dump(mode="json"))

    def list_plans(self) -> list[Plan]:
        plans = [
            Plan.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted((self.data_dir / "plans").glob("*.json"))
        ]
        return plans

    # -- evidence -----------------------------------------------------------

    def evidence_path(self, evidence_id: str) -> Path:
        return self.data_dir / "evidence" / f"{evidence_id}.json"

    def load_evidence(self, evidence_id: str) -> EvidenceRecord | None:
        path = self.evidence_path(evidence_id)
        if not path.exists():
            return None
        return EvidenceRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def save_evidence(self, record: EvidenceRecord) -> None:
        atomic_write_json(self.evidence_path(record.id), record.model_dump(mode="json"))

    def list_evidence(self) -> list[EvidenceRecord]:
        return [
            EvidenceRecord.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted((self.data_dir / "evidence").glob("*.json"))
        ]
